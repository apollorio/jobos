"""Única camada que aplica um SourceBatch ao estado canônico (DEC-003/007).

- Mesmo ID com conteúdo novo → nova versão + evento (T07/T08).
- Observação sem descrição não apaga descrição boa (T09).
- Ausência só com lote completo, mesmo escopo, sem queda anômala, 2 leituras separadas (T10-T16).
- Encerramento nunca toca candidatura.
"""
from __future__ import annotations

import datetime as dt
import sqlite3

from jobos.collectors.base import JobObservation, SourceBatch
from jobos.domain.identity import content_hash, fold, is_talent_pool, semantic_text
from jobos.settings import Settings, SourceConfig
from jobos.storage import repo
from jobos.storage.db import tx
from jobos.timeutil import iso, parse_instant, parse_published, utcnow

ANOMALY_MIN_BASE = 10
ANOMALY_RATIO = 0.5
MIN_MISSING_INTERVAL = dt.timedelta(hours=6)
CLOSE_AFTER_COMPLETE_MISSES = 2


def known_lookup(con: sqlite3.Connection, source_id: str):
    def known(external_id: str | None, url: str | None) -> dict | None:
        row = None
        if external_id:
            row = con.execute("""SELECT p.listing_signature, p.detail_fetched_at, v.description_length
                                 FROM source_postings p JOIN job_records j ON j.job_id=p.job_id
                                 LEFT JOIN job_versions v ON v.version_id=j.current_version_id
                                 WHERE p.source_id=? AND p.external_id=?""", (source_id, external_id)).fetchone()
        if row is None and url:
            row = con.execute("""SELECT p.listing_signature, p.detail_fetched_at, v.description_length
                                 FROM source_postings p JOIN job_records j ON j.job_id=p.job_id
                                 LEFT JOIN job_versions v ON v.version_id=j.current_version_id
                                 WHERE p.source_id=? AND p.url=?""", (source_id, url)).fetchone()
        if row is None:
            return None
        return {"listing_signature": row["listing_signature"], "detail_fetched_at": row["detail_fetched_at"],
                "has_description": bool(row["description_length"])}
    return known


def _is_baseline(con: sqlite3.Connection, batch: SourceBatch) -> bool:
    prev = con.execute("""SELECT COUNT(*) FROM source_runs WHERE source_id=? AND scope_id=? AND status IN ('complete','partial')
                          AND run_id != ?""", (batch.source_id, batch.scope_id, batch.run_id)).fetchone()[0]
    return prev == 0


def _merge_fields(obs: JobObservation, cur: sqlite3.Row | None) -> tuple[dict, list[str]]:
    fields = obs.content_fields()
    notes = []
    if cur is None:
        return fields, notes
    if cur["description"] and (obs.description_status == "missing" or
                               (obs.description_status == "partial" and cur["description_status"] == "full")):
        fields.update(description=cur["description"], description_status=cur["description_status"],
                      original_length=cur["original_length"], truncation_note=cur["truncation_note"])
        notes.append("descrição anterior preservada (observação sem descrição completa)")
    for k in ("location", "workplace", "department", "salary"):
        if not fields.get(k) and cur[k]:
            fields[k] = cur[k]
    return fields, notes


def _changed_fields(cur: sqlite3.Row | None, fields: dict) -> list[str]:
    if cur is None:
        return []
    return [k for k in ("title", "description", "location", "workplace", "salary", "department")
            if semantic_text(cur[k]) != semantic_text(fields.get(k))]


def _recompute_job_state(con: sqlite3.Connection, job_id: str, now: str, run_id: str) -> str:
    states = [r[0] for r in con.execute("SELECT posting_state FROM source_postings WHERE job_id=?", (job_id,))]
    if "active" in states:
        new = "active"
    elif "missing_unconfirmed" in states:
        new = "missing_unconfirmed"
    elif states and all(s == "closed_confirmed" for s in states):
        new = "closed_confirmed"
    else:
        new = "unknown"
    old = con.execute("SELECT listing_state FROM job_records WHERE job_id=?", (job_id,)).fetchone()[0]
    if new != old:
        if new == "closed_confirmed":
            con.execute("""UPDATE job_records SET listing_state=?, closed_at=?, close_reason=?, updated_at=? WHERE job_id=?""",
                        (new, now, "ausente em leituras completas consecutivas da fonte", now, job_id))
            repo.add_job_event(con, job_id, "job.closed", occurred_at=now, origin="collector", run_id=run_id,
                               payload={"previous_state": old, "note": "candidatura e estágio não são alterados"},
                               dedupe_key=f"job_closed:{job_id}:{run_id}")
        else:
            con.execute("UPDATE job_records SET listing_state=?, closed_at=CASE WHEN ?='active' THEN NULL ELSE closed_at END,"
                        " updated_at=? WHERE job_id=?", (new, new, now, job_id))
    return new


def apply_batch(con: sqlite3.Connection, batch: SourceBatch, source: SourceConfig, settings: Settings, *,
                is_fixture: bool = False) -> dict:
    now = iso()
    pool_terms = settings.preferences.get("talent_pool_terms") or []
    out = {"new": 0, "changed": 0, "reappeared": 0, "missing": 0, "closed": 0, "absence_applied": False,
           "absence_note": None, "baseline": False}
    with tx(con):
        repo.ensure_company(con, source.company_id, source.company_name)
        baseline = _is_baseline(con, batch) if batch.status in ("complete", "partial") else False
        batch.is_baseline = baseline
        out["baseline"] = baseline
        seen_postings: set[int] = set()
        touched: set[str] = set()
        for obs in batch.jobs:
            pid, job_id, kind = _apply_observation(con, obs, batch, source, now, baseline, pool_terms, is_fixture)
            seen_postings.add(pid)
            touched.add(job_id)
            if kind:
                out[kind] += 1

        if batch.status == "complete" and batch.can_infer_absence:
            note = _absence_guard(con, batch)
            if note:
                out["absence_note"] = note
                batch.warnings.append(note)
            else:
                out["absence_applied"] = True
                m, c, jobs = _apply_absence(con, batch, seen_postings, now)
                out["missing"], out["closed"] = m, c
                touched |= jobs
        elif batch.status in ("complete", "partial"):
            out["absence_note"] = ("lote parcial: ausência não avaliada" if batch.status == "partial"
                                   else f"escopo {batch.coverage_kind}: não autoriza inferir ausência")

        for job_id in touched:
            _recompute_job_state(con, job_id, now, batch.run_id)

        con.execute(
            """INSERT OR REPLACE INTO source_runs (run_id, source_id, adapter, adapter_version, status, complete, coverage_kind,
                 scope_id, can_infer_absence, is_baseline, absence_applied, pages_expected, pages_received, raw_count,
                 normalized_count, new_count, changed_count, missing_count, closed_count, details_fetched, error_code,
                 error_message, warnings_json, started_at, finished_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (batch.run_id, batch.source_id, batch.adapter, batch.adapter_version, batch.status, int(batch.complete),
             batch.coverage_kind, batch.scope_id, int(batch.can_infer_absence), int(baseline), int(out["absence_applied"]),
             batch.pages_expected, batch.pages_received, batch.raw_count, batch.normalized_count, out["new"], out["changed"],
             out["missing"], out["closed"], batch.details_fetched, batch.error_code, batch.error_message,
             repo.dumps(batch.warnings), batch.started_at, batch.finished_at or now))
    return out


def _apply_observation(con, obs: JobObservation, batch: SourceBatch, source: SourceConfig, now: str, baseline: bool,
                       pool_terms: list[str], is_fixture: bool) -> tuple[int, str, str | None]:
    posting = repo.find_posting(con, obs.platform, obs.tenant, obs.external_id, obs.url)
    pub = parse_published(obs.published_raw, obs.published_source or f"{obs.platform}:published").as_dict()
    detail_now = now if obs.description_status in ("full", "truncated") and obs.description else None
    kind = None
    if posting is None:
        talent = obs.talent_pool if obs.talent_pool is not None else is_talent_pool(obs.title, pool_terms)
        job_id = repo.create_job(
            con, company_id=source.company_id, company_name=source.company_name, title=obs.title or "(sem título)",
            location=obs.location, workplace=obs.workplace, origin="fixture" if is_fixture else "observed",
            is_baseline=baseline, is_fixture=is_fixture, talent_pool=talent, listing_state="active",
            first_seen_at=now, first_seen_precision="timestamp", first_seen_source=f"run:{batch.run_id}",
            last_seen_at=now, imported_at=None, published=pub)
        pid = repo.add_posting(con, job_id=job_id, source_id=source.source_id, platform=obs.platform, tenant=obs.tenant,
                               external_id=obs.external_id, url=obs.url, posting_state="active", first_seen_at=now,
                               last_seen_at=now, origin="fixture" if is_fixture else "observed", run_id=batch.run_id,
                               scope_id=batch.scope_id, is_fixture=is_fixture)
        con.execute("UPDATE source_postings SET listing_signature=?, detail_fetched_at=? WHERE posting_id=?",
                    (obs.listing_signature, detail_now, pid))
        repo.add_version(con, job_id=job_id, fields=obs.content_fields(), observed_at=now, origin="observed",
                         run_id=batch.run_id, source_id=source.source_id, payload=obs.raw)
        repo.add_job_event(con, job_id, "job.discovered", occurred_at=now, origin="collector", run_id=batch.run_id,
                           alertable=not baseline and not talent and not is_fixture,
                           payload={"source_id": source.source_id, "baseline": baseline, "talent_pool": talent},
                           dedupe_key=f"discovered:{job_id}")
        _suggest_relations(con, job_id, source.company_id, obs.title, now)
        return pid, job_id, "new"

    job_id = posting["job_id"]
    cur = repo.current_version(con, job_id)
    fields, notes = _merge_fields(obs, cur)
    changed = _changed_fields(cur, fields)
    same_content = cur is not None and content_hash({k: cur[k] for k in cur.keys()}) == content_hash(fields)
    created = False
    if not same_content:  # recalcula com a normalização atual: só formatação diferente não gera versão
        _, created = repo.add_version(con, job_id=job_id, fields=fields, observed_at=now, origin="observed",
                                      run_id=batch.run_id, source_id=source.source_id, payload=obs.raw)
    if created and cur is not None and changed:
        # Descrição que só chegou agora (limite de detalhes) ou primeira leitura sobre texto legado: enriquecimento,
        # não mudança do anúncio. Não alerta.
        enrichment = (changed == ["description"] and not (cur["description"] or "").strip()) or \
            (cur["origin"] != "observed" and "title" not in changed)
        if enrichment:
            repo.add_job_event(con, job_id, "job.enriched", occurred_at=now, origin="collector", run_id=batch.run_id,
                               payload={"fields": changed, "previous_origin": cur["origin"], "source_id": source.source_id},
                               dedupe_key=f"enriched:{job_id}:{batch.run_id}")
        else:
            con.execute("UPDATE job_records SET content_changed_at=? WHERE job_id=?", (now, job_id))
            repo.add_job_event(con, job_id, "job.changed", occurred_at=now, origin="collector", run_id=batch.run_id,
                               alertable=not baseline and not is_fixture,
                               payload={"fields": changed, "notes": notes, "source_id": source.source_id},
                               dedupe_key=f"changed:{job_id}:{batch.run_id}")
            kind = "changed"
    prev_state = posting["posting_state"]
    if prev_state == "missing_unconfirmed":
        repo.add_job_event(con, job_id, "job.reappeared", occurred_at=now, origin="collector", run_id=batch.run_id,
                           payload={"source_id": source.source_id}, dedupe_key=f"reappeared:{job_id}:{batch.run_id}")
        kind = kind or "reappeared"
    elif prev_state == "closed_confirmed":
        repo.add_job_event(con, job_id, "job.reopened", occurred_at=now, origin="collector", run_id=batch.run_id,
                           alertable=not is_fixture, payload={"source_id": source.source_id},
                           dedupe_key=f"reopened:{job_id}:{batch.run_id}")
        kind = kind or "reappeared"
    elif prev_state == "unknown":
        repo.add_job_event(con, job_id, "job.confirmed_active", occurred_at=now, origin="collector", run_id=batch.run_id,
                           payload={"source_id": source.source_id, "note": "primeira observação após importação"},
                           dedupe_key=f"confirmed:{job_id}")
    if posting["source_id"] != source.source_id and posting["source_id"].startswith(("legacy:", "portal:")):
        con.execute("UPDATE source_postings SET source_id=? WHERE posting_id=?", (source.source_id, posting["posting_id"]))
    con.execute("""UPDATE source_postings SET posting_state='active', last_seen_at=?, last_run_id=?, last_scope_id=?,
                     missing_count=0, missing_since=NULL, url=COALESCE(?, url), listing_signature=COALESCE(?, listing_signature),
                     detail_fetched_at=COALESCE(?, detail_fetched_at),
                     first_seen_at=COALESCE(first_seen_at, ?) WHERE posting_id=?""",
                (now, batch.run_id, batch.scope_id, obs.url, obs.listing_signature, detail_now, now, posting["posting_id"]))
    con.execute("""UPDATE job_records SET last_seen_at=?, updated_at=?,
                     first_seen_at=COALESCE(first_seen_at, ?),
                     first_seen_precision=CASE WHEN first_seen_at IS NULL THEN 'timestamp' ELSE first_seen_precision END,
                     first_seen_source=CASE WHEN first_seen_at IS NULL THEN ? ELSE first_seen_source END
                   WHERE job_id=?""", (now, now, now, f"run:{batch.run_id}", job_id))
    repo.maybe_upgrade_published(con, job_id, pub)
    if obs.talent_pool is not None:  # a plataforma informou o tipo: corrige a heurística por título feita antes
        con.execute("UPDATE job_records SET talent_pool=? WHERE job_id=? AND talent_pool != ?",
                    (int(obs.talent_pool), job_id, int(obs.talent_pool)))
    return posting["posting_id"], job_id, kind


def _suggest_relations(con, job_id: str, company_id: str, title: str, now: str) -> None:
    """Novo ID com mesmo título na mesma empresa: relação candidata, nunca fusão (T06)."""
    key = fold(title)
    if not key:
        return
    for r in con.execute("""SELECT job_id, title FROM job_records WHERE company_id=? AND job_id != ?
                            AND listing_state IN ('active','missing_unconfirmed','unknown')""", (company_id, job_id)):
        if fold(r["title"]) == key:
            a, b = sorted((job_id, r["job_id"]))
            con.execute("""INSERT OR IGNORE INTO job_relations (a_job_id, b_job_id, kind, reason, created_at)
                           VALUES (?,?,?,?,?)""", (a, b, "possible_repost", "mesmo título na mesma empresa, ID externo diferente", now))


def _absence_guard(con, batch: SourceBatch) -> str | None:
    prev = con.execute("""SELECT normalized_count FROM source_runs WHERE source_id=? AND scope_id=? AND status='complete'
                          AND run_id != ? ORDER BY finished_at DESC LIMIT 1""",
                       (batch.source_id, batch.scope_id, batch.run_id)).fetchone()
    if prev and prev[0] >= ANOMALY_MIN_BASE and batch.normalized_count < prev[0] * ANOMALY_RATIO:
        return (f"queda anômala ({prev[0]} → {batch.normalized_count}): ausência não aplicada; "
                "verificar formato da fonte")
    return None


def _apply_absence(con, batch: SourceBatch, seen: set[int], now: str) -> tuple[int, int, set[str]]:
    full = batch.coverage_kind == "full_board"
    rows = con.execute("""SELECT * FROM source_postings WHERE source_id=?
                          AND posting_state IN ('active','missing_unconfirmed','unknown')""", (batch.source_id,)).fetchall()
    missing = closed = 0
    jobs: set[str] = set()
    tnow = parse_instant(now) or utcnow()
    for p in rows:
        if p["posting_id"] in seen:
            continue
        same_scope = p["last_scope_id"] == batch.scope_id
        if not (same_scope or (full and p["last_scope_id"] is None)):
            continue  # escopo diferente/desconhecido: não compara (T15/T16)
        if p["last_missing_run"] == batch.run_id:
            continue
        count = p["missing_count"] + 1
        since = p["missing_since"] or now
        state = "missing_unconfirmed"
        since_t = parse_instant(since) or tnow
        if count >= CLOSE_AFTER_COMPLETE_MISSES and tnow - since_t >= MIN_MISSING_INTERVAL:
            state = "closed_confirmed"
        con.execute("""UPDATE source_postings SET posting_state=?, missing_count=?, missing_since=?, last_missing_run=?
                       WHERE posting_id=?""", (state, count, since, batch.run_id, p["posting_id"]))
        if state == "closed_confirmed" and p["posting_state"] != "closed_confirmed":
            closed += 1
            repo.add_job_event(con, p["job_id"], "posting.closed", occurred_at=now, origin="collector", run_id=batch.run_id,
                               payload={"source_id": batch.source_id, "complete_misses": count, "missing_since": since},
                               dedupe_key=f"closed:{p['posting_id']}:{batch.run_id}")
        elif p["posting_state"] != "missing_unconfirmed":
            missing += 1
            repo.add_job_event(con, p["job_id"], "posting.missing", occurred_at=now, origin="collector", run_id=batch.run_id,
                               payload={"source_id": batch.source_id, "complete_misses": count},
                               dedupe_key=f"missing:{p['posting_id']}:{batch.run_id}")
        jobs.add(p["job_id"])
    return missing, closed, jobs


def retire_source(con: sqlite3.Connection, source_id: str, reason: str, *, apply: bool) -> dict:
    """Fonte trocada/desativada: seus anúncios deixam de contar como ativos (viram 'não verificados'), com evento.
    Nada é apagado; se o mesmo anúncio aparecer por outra fonte, ele volta a ficar ativo por lá."""
    rows = con.execute("""SELECT posting_id, job_id FROM source_postings WHERE source_id=?
                          AND posting_state IN ('active','missing_unconfirmed')""", (source_id,)).fetchall()
    out = {"source_id": source_id, "postings": len(rows), "apply": apply}
    if not apply:
        return out
    now = iso()
    with tx(con):
        for r in rows:
            con.execute("UPDATE source_postings SET posting_state='unknown' WHERE posting_id=?", (r["posting_id"],))
            repo.add_job_event(con, r["job_id"], "source.retired", occurred_at=now, origin="user_asserted",
                               payload={"source_id": source_id, "reason": reason},
                               dedupe_key=f"retired:{source_id}:{r['posting_id']}")
        for job_id in {r["job_id"] for r in rows}:
            _recompute_job_state(con, job_id, now, f"retire:{source_id}")
    return out


PROBE_INTERVAL = dt.timedelta(hours=20)


def probe_candidates(con: sqlite3.Connection, source_id: str, run_id: str, limit: int) -> list[sqlite3.Row]:
    """Anúncios 'não verificados'/'sumidos' desta fonte que a listagem atual não viu, mais antigos de probe primeiro.
    Prioriza os que aparecem no portal (importados do jobs.json) e os 'sumidos' (fechamento pendente)."""
    cutoff = (utcnow() - PROBE_INTERVAL).isoformat()
    return con.execute("""SELECT p.* FROM source_postings p JOIN job_records j ON j.job_id=p.job_id
                          WHERE p.source_id=? AND p.posting_state IN ('unknown','missing_unconfirmed')
                          AND COALESCE(p.last_run_id,'') != ? AND (p.last_probe_at IS NULL OR p.last_probe_at < ?)
                          AND j.is_fixture=0
                          ORDER BY CASE p.posting_state WHEN 'missing_unconfirmed' THEN 0 ELSE 1 END,
                                   CASE p.origin WHEN 'legacy_portal_json' THEN 0 ELSE 1 END, p.last_probe_at
                          LIMIT ?""", (source_id, run_id, cutoff, limit)).fetchall()


def apply_probe(con: sqlite3.Connection, posting: sqlite3.Row, result: str, run_id: str) -> str:
    """'gone' conta como leitura de ausência (2 evidências separadas por 6 h fecham); 'alive' zera a contagem."""
    now = iso()
    with tx(con):
        con.execute("UPDATE source_postings SET last_probe_at=?, last_probe_result=? WHERE posting_id=?",
                    (now, result, posting["posting_id"]))
        state = posting["posting_state"]
        if result == "gone":
            count = posting["missing_count"] + 1
            since = posting["missing_since"] or now
            since_t = parse_instant(since) or utcnow()
            state = ("closed_confirmed" if count >= CLOSE_AFTER_COMPLETE_MISSES and utcnow() - since_t >= MIN_MISSING_INTERVAL
                     else "missing_unconfirmed")
            con.execute("""UPDATE source_postings SET posting_state=?, missing_count=?, missing_since=?, last_missing_run=?
                           WHERE posting_id=?""", (state, count, since, run_id, posting["posting_id"]))
            repo.add_job_event(con, posting["job_id"], "posting.probe_gone", occurred_at=now, origin="collector",
                               run_id=run_id, payload={"source_id": posting["source_id"], "evidence_count": count,
                                                       "state": state}, dedupe_key=f"probe:{posting['posting_id']}:{run_id}")
        elif result == "alive" and posting["missing_count"]:
            con.execute("UPDATE source_postings SET missing_count=0, missing_since=NULL WHERE posting_id=?",
                        (posting["posting_id"],))
        _recompute_job_state(con, posting["job_id"], now, run_id)
    return state
