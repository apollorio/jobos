"""Candidaturas: transições validadas com origem. Mesmo serviço para CLI e API.

Nenhuma transição para enviada ocorre por sugestão, e-mail, abertura de vaga, CV gerado ou tempo (DEC-005).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import sqlite3

from jobos.domain.states import (PREP_LABELS, SUBMITTED, TransitionError, application_tag, check_prep_transition,
                                 check_stage)
from jobos.storage import repo
from jobos.storage.db import tx
from jobos.timeutil import brt_date, iso


class NotFound(LookupError):
    pass


def resolve_job_id(con: sqlite3.Connection, ref: str) -> str:
    ref = (ref or "").strip()
    if len(ref) < 8:
        raise NotFound("informe o job_id completo ou um prefixo de pelo menos 8 caracteres")
    rows = con.execute("SELECT job_id FROM job_records WHERE job_id LIKE ? LIMIT 2", (ref + "%",)).fetchall()
    if not rows:
        raise NotFound(f"vaga não encontrada: {ref}")
    if len(rows) > 1:
        raise NotFound(f"prefixo ambíguo: {ref}")
    return rows[0][0]


def _ensure_application(con: sqlite3.Connection, job_id: str) -> sqlite3.Row:
    row = con.execute("SELECT * FROM applications WHERE job_id=?", (job_id,)).fetchone()
    if row:
        return row
    app_id = repo.new_id("app-")
    now = iso()
    con.execute("""INSERT INTO applications (application_id, job_id, prep_state, selection_stage, provenance, created_at,
                     updated_at) VALUES (?,?,?,?,?,?,?)""", (app_id, job_id, "discovered", "none", "system", now, now))
    return con.execute("SELECT * FROM applications WHERE application_id=?", (app_id,)).fetchone()


def _has_cv_artifact(con: sqlite3.Connection, job_id: str) -> bool:
    return con.execute("""SELECT 1 FROM artifacts WHERE job_id=? AND kind IN ('cv_html','cv_data') LIMIT 1""",
                       (job_id,)).fetchone() is not None


def _proof_payload(proof: str | None, artifact_sha256: str | None) -> dict | None:
    payload: dict = {}
    if artifact_sha256:
        payload["artifact_sha256"] = artifact_sha256
    if proof:
        payload["confirmation_sha256"] = hashlib.sha256(proof.encode("utf-8")).hexdigest()
    return payload or None


def transition(con: sqlite3.Connection, job_ref: str, target: str, *, origin: str, reason: str | None = None,
               occurred_at: str | None = None, proof: str | None = None, idempotency_key: str | None = None,
               artifact_sha256: str | None = None) -> dict:
    job_id = resolve_job_id(con, job_ref)
    with tx(con):
        app = _ensure_application(con, job_id)
        if idempotency_key and con.execute("SELECT 1 FROM application_events WHERE dedupe_key=?",
                                           (idempotency_key,)).fetchone():
            return {"application_id": app["application_id"], "prep_state": app["prep_state"], "duplicate": True}
        check_prep_transition(app["prep_state"], target, origin)
        if target in ("cv_ready", "awaiting_review") and not _has_cv_artifact(con, job_id):
            raise TransitionError("cv_ready e awaiting_review exigem um currículo gerado desta vaga (jobos cv build)")
        if target == "submitted_verified" and not proof:
            raise TransitionError("submitted_verified exige uma prova (código ou texto de confirmação da plataforma)")
        now = iso()
        sets = ["prep_state=?", "updated_at=?"]
        vals: list = [target, now]
        if target in ("submitted_manual", "submitted_verified"):
            sets += ["provenance=?", "submitted_at=?", "submitted_precision=?"]
            vals += [origin, occurred_at or now[:10], "date_only" if occurred_at and len(occurred_at) == 10 else "timestamp"]
        con.execute(f"UPDATE applications SET {', '.join(sets)} WHERE application_id=?", (*vals, app["application_id"]))
        payload = _proof_payload(proof, artifact_sha256) if target in SUBMITTED else None
        repo.add_application_event(con, app["application_id"], axis="prep", from_state=app["prep_state"], to_state=target,
                                   origin=origin, occurred_at=occurred_at or now, reason=reason, proof=proof,
                                   payload=payload, dedupe_key=idempotency_key)
        if artifact_sha256 and target in SUBMITTED:
            con.execute("""UPDATE artifacts SET application_id=? WHERE job_id=? AND sha256=? AND application_id IS NULL""",
                        (app["application_id"], job_id, artifact_sha256))
    return {"application_id": app["application_id"], "job_id": job_id, "from": app["prep_state"], "to": target,
            "proof_recorded": bool(payload)}


def duplicate_submitted_warning(con: sqlite3.Connection, job_id: str) -> str | None:
    """Avisa se uma possível repetição desta vaga já tem envio registrado. Não bloqueia o registro."""
    row = con.execute("""SELECT j.company_name, j.title, a.prep_state FROM job_relations r
                         JOIN job_records j ON j.job_id = CASE WHEN r.a_job_id=? THEN r.b_job_id ELSE r.a_job_id END
                         JOIN applications a ON a.job_id=j.job_id
                         WHERE (r.a_job_id=? OR r.b_job_id=?) AND r.kind IN ('possible_duplicate','possible_repost')
                           AND r.status!='rejected' AND a.prep_state IN ('submitted_manual','submitted_verified')
                         LIMIT 1""", (job_id, job_id, job_id)).fetchone()
    if not row:
        return None
    return (f"possível repetição já enviada: {row['company_name']} | {row['title']} ({row['prep_state']}). "
            "Confira antes de enviar de novo.")


def confirm_manual(con: sqlite3.Connection, job_ref: str, date: str, note: str | None = None,
                   artifact_sha256: str | None = None, confirmation: str | None = None) -> dict:
    """Registro manual: origem `user_asserted`; não é prova de plataforma."""
    try:
        d = dt.date.fromisoformat(date)
    except ValueError as e:
        raise ValueError("data no formato AAAA-MM-DD") from e
    if d > brt_date() + dt.timedelta(days=1):
        raise ValueError("data de envio no futuro")
    job_id = resolve_job_id(con, job_ref)
    warning = duplicate_submitted_warning(con, job_id)
    out = transition(con, job_ref, "submitted_manual", origin="user_asserted", occurred_at=d.isoformat(),
                     reason=note or "confirmado pelo usuário", idempotency_key=f"confirm:{job_ref}:{d.isoformat()}",
                     proof=confirmation, artifact_sha256=artifact_sha256)
    if warning:
        out["duplicate_warning"] = warning
    return out


def set_stage(con: sqlite3.Connection, job_ref: str, stage: str, *, origin: str = "user_asserted",
              reason: str | None = None) -> dict:
    check_stage(stage)
    job_id = resolve_job_id(con, job_ref)
    with tx(con):
        app = _ensure_application(con, job_id)
        con.execute("UPDATE applications SET selection_stage=?, updated_at=? WHERE application_id=?",
                    (stage, iso(), app["application_id"]))
        repo.add_application_event(con, app["application_id"], axis="stage", from_state=app["selection_stage"],
                                   to_state=stage, origin=origin, reason=reason)
    return {"application_id": app["application_id"], "from": app["selection_stage"], "to": stage}


def add_note(con: sqlite3.Connection, job_ref: str, note: str) -> dict:
    job_id = resolve_job_id(con, job_ref)
    with tx(con):
        app = _ensure_application(con, job_id)
        repo.add_application_event(con, app["application_id"], axis="note", from_state=None, to_state=None,
                                   origin="user_asserted", reason=note[:2000])
    return {"application_id": app["application_id"]}


def pendencias(con: sqlite3.Connection) -> dict:
    """Fila de trabalho humano: boa aderência sem envio, CV parado e legado por revisar."""
    rows = con.execute("""SELECT j.job_id, j.company_name, j.title, COALESCE(a.priority, -999) AS priority
                          FROM job_records j
                          JOIN analyses a ON a.analysis_id = (
                            SELECT a2.analysis_id FROM analyses a2 WHERE a2.job_version_id=j.current_version_id
                            ORDER BY a2.created_at DESC LIMIT 1)
                          LEFT JOIN applications ap ON ap.job_id=j.job_id
                          WHERE j.is_fixture=0 AND j.listing_state='active' AND a.decision='good_fit'
                            AND (ap.prep_state IS NULL OR ap.prep_state NOT IN
                                 ('submitted_manual','submitted_verified','dismissed'))
                          ORDER BY priority DESC, j.company_name
                          LIMIT 12""").fetchall()
    total = con.execute("""SELECT COUNT(*) FROM job_records j
                           JOIN analyses a ON a.analysis_id = (
                             SELECT a2.analysis_id FROM analyses a2 WHERE a2.job_version_id=j.current_version_id
                             ORDER BY a2.created_at DESC LIMIT 1)
                           LEFT JOIN applications ap ON ap.job_id=j.job_id
                           WHERE j.is_fixture=0 AND j.listing_state='active' AND a.decision='good_fit'
                             AND (ap.prep_state IS NULL OR ap.prep_state NOT IN
                                  ('submitted_manual','submitted_verified','dismissed'))""").fetchone()[0]
    cv_wait = con.execute("""SELECT COUNT(*) FROM applications WHERE prep_state IN ('cv_ready','awaiting_review')""").fetchone()[0]
    legacy = con.execute("""SELECT COUNT(*) FROM applications WHERE prep_state='legacy_needs_review'""").fetchone()[0]
    return {"good_fit_without_application_count": total, "cv_awaiting_review": cv_wait, "legacy_to_review": legacy,
            "good_fit_without_application": [{"job_id": r["job_id"], "company_name": r["company_name"],
                                              "title": r["title"]} for r in rows]}


def list_applications(con: sqlite3.Connection) -> list[dict]:
    rows = con.execute("""SELECT a.*, j.title, j.company_name, j.listing_state, j.location,
                            (SELECT url FROM source_postings p WHERE p.job_id=j.job_id ORDER BY p.last_seen_at DESC LIMIT 1) AS url
                          FROM applications a JOIN job_records j ON j.job_id=a.job_id
                          ORDER BY CASE a.prep_state WHEN 'legacy_needs_review' THEN 0 ELSE 1 END, a.updated_at DESC""").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["prep_label"] = PREP_LABELS.get(d["prep_state"], d["prep_state"])
        d["tag"] = application_tag(d)
        d["counts_as_submitted"] = d["tag"]["counts_as_applied"]
        d["events"] = [dict(e) for e in con.execute(
            "SELECT axis, from_state, to_state, occurred_at, origin, reason, payload_json FROM application_events "
            "WHERE application_id=? ORDER BY occurred_at, event_id", (d["application_id"],))]
        out.append(d)
    return out


def confirm_legacy_manual_marks(con: sqlite3.Connection, *, apply: bool, confirmed_on: str) -> dict:
    """Marcações MANUAIS originais do sistema antigo ("marcado manualmente a pedido do usuário") viram "Aplicado"
    (`submitted_manual`, origem user_asserted) por confirmação explícita do usuário. "Auto aplicado" não muda."""
    rows = con.execute("""SELECT a.application_id, a.job_id, a.legacy_date, j.company_name, j.title FROM applications a
                          JOIN job_records j ON j.job_id=a.job_id
                          WHERE a.prep_state='legacy_needs_review' AND a.legacy_hint LIKE '%legacy_manual_mark_event%'
                          AND COALESCE(a.legacy_source,'') != 'auto_sugerida'""").fetchall()
    out = {"apply": apply, "count": len(rows), "items": [f"{r['company_name']} | {r['title']}" for r in rows]}
    if not apply:
        return out
    for r in rows:
        transition(con, r["job_id"], "submitted_manual", origin="user_asserted",
                   occurred_at=r["legacy_date"] or None,
                   reason=f"marcação manual original no sistema antigo; confirmada pelo usuário em {confirmed_on} "
                          "(pedido de etiqueta 'Aplicado (manual original)')",
                   idempotency_key=f"legacy_manual_confirm:{r['application_id']}")
    out["applied"] = len(rows)
    return out
