"""Importa marcações do portal exportadas do localStorage pelo PRÓPRIO usuário (A17/T45).

Python não lê o navegador. O arquivo vem de uma exportação manual (snippet no README) com as chaves
`jobos-saved`, `jobos-muted` e `jobos-lifted`. Procedência: `browser_export` (afirmação do usuário, não prova).
- `jobos-saved` ("Aplicadas" no portal) → `legacy_needs_review` com dica `browser_saved_mark`.
- `jobos-muted` → evento de nota "oculta no portal"; não descarta automaticamente.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from jobos.storage import repo
from jobos.storage.db import tx
from jobos.timeutil import iso


def _parse(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("exportação precisa ser um objeto JSON com as chaves do localStorage")
    out = {}
    for key in ("jobos-saved", "jobos-muted", "jobos-lifted"):
        v = data.get(key)
        if isinstance(v, str):
            v = json.loads(v)
        out[key] = v or []
    return out


def _resolve(con, company_id: str, job_id: str) -> str | None:
    r = con.execute("SELECT canonical_job_id FROM legacy_id_map WHERE origin LIKE 'legacy_portal_json%' AND legacy_id=?",
                    (f"{company_id}:{job_id}",)).fetchone()
    if r:
        return r[0]
    r = con.execute("""SELECT p.job_id FROM source_postings p JOIN job_records j ON j.job_id=p.job_id
                       WHERE j.company_id=? AND p.external_id=?""", (company_id, str(job_id))).fetchone()
    return r[0] if r else None


def import_export(ctx, path: Path, *, apply: bool) -> dict:
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    data = _parse(path)
    plan = {"saved": [], "muted": [], "unresolved": []}
    for item in data["jobos-saved"]:
        cid, jid = item.get("companyId"), str((item.get("job") or {}).get("id", ""))
        target = _resolve(ctx.con, cid, jid)
        (plan["saved"] if target else plan["unresolved"]).append({"key": f"{cid}:{jid}", "job_id": target,
                                                                  "title": (item.get("job") or {}).get("title")})
    for key in data["jobos-muted"]:
        cid, _, jid = str(key).partition(":")
        target = _resolve(ctx.con, cid, jid)
        (plan["muted"] if target else plan["unresolved"]).append({"key": key, "job_id": target})
    result = {"file_sha256": sha, "apply": apply, "saved": len(plan["saved"]), "muted": len(plan["muted"]),
              "unresolved": plan["unresolved"]}
    if not apply:
        result["note"] = "somente relatório; use --apply para gravar"
        return result
    import_id = f"imp-browser-{sha[:12]}"
    with tx(ctx.con):
        if ctx.con.execute("SELECT 1 FROM imports WHERE import_id=?", (import_id,)).fetchone():
            return {**result, "status": "already_imported", "import_id": import_id}
        ctx.con.execute("INSERT INTO imports (import_id, kind, origin_path, sha256, started_at, status) VALUES (?,?,?,?,?,?)",
                        (import_id, "browser_export", str(path), sha, iso(), "running"))
        for s in plan["saved"]:
            app = ctx.con.execute("SELECT * FROM applications WHERE job_id=?", (s["job_id"],)).fetchone()
            if app is None:
                app_id = repo.new_id("app-")
                ctx.con.execute("""INSERT INTO applications (application_id, job_id, prep_state, selection_stage, provenance,
                                     legacy_hint, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)""",
                                (app_id, s["job_id"], "legacy_needs_review", "none", "browser_export",
                                 "browser_saved_mark", iso(), iso()))
            else:
                app_id = app["application_id"]
            repo.add_application_event(ctx.con, app_id, axis="note", from_state=None, to_state=None,
                                       origin="browser_export", reason="marcada como 'Aplicada' no portal (localStorage)",
                                       payload={"key": s["key"], "file_sha256": sha},
                                       dedupe_key=f"browser_saved:{sha}:{s['key']}")
        for m in plan["muted"]:
            repo.add_job_event(ctx.con, m["job_id"], "browser.muted_mark", origin="browser_export",
                               payload={"key": m["key"]}, dedupe_key=f"browser_muted:{sha}:{m['key']}")
        ctx.con.execute("UPDATE imports SET status='complete', finished_at=?, counts_json=? WHERE import_id=?",
                        (iso(), repo.dumps({"saved": len(plan["saved"]), "muted": len(plan["muted"]),
                                            "unresolved": len(plan["unresolved"])}), import_id))
    return {**result, "status": "imported", "import_id": import_id}
