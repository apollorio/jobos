"""Projeção `Book` (contrato do portal antigo `companies[].jobs[]`) gerada do SQLite.

Não é base editável. Sem dados de candidatura, notas ou score pessoal. IDs do snapshot antigo são preservados
para não quebrar marcações `companyId:jobId` do localStorage do portal.
"""
from __future__ import annotations

import json

from jobos.timeutil import iso

PLATFORM_LABEL = {"gupy": "Gupy", "successfactors_j2w": "SuccessFactors", "workday": "Workday",
                  "smartrecruiters": "SmartRecruiters"}
KIND = {"gupy": "gupy", "successfactors_j2w": "sf", "workday": "workday", "smartrecruiters": "smart", "inhire": "inhire",
        "webflow": "dof", "totvs": "bram", "greenhouse": "greenhouse", "oracle_ce": "oracle"}
OPEN_STATES = ("active", "missing_unconfirmed")


def build_book(ctx) -> dict:
    con = ctx.con
    portal_ids = {r["canonical_job_id"]: r["legacy_id"].split(":", 1)[1] for r in con.execute(
        "SELECT canonical_job_id, legacy_id FROM legacy_id_map WHERE origin LIKE 'legacy_portal_json%'")}
    logos = {}
    for r in con.execute("SELECT payload_json FROM legacy_payloads WHERE origin LIKE 'legacy_portal_json%'"):
        comp = json.loads(r["payload_json"]).get("company") or {}
        if comp.get("id") and comp.get("logo"):
            logos[comp["id"]] = comp["logo"]
    companies = []
    seen_company = set()
    updated = con.execute("SELECT MAX(occurred_at) FROM job_events WHERE kind IN ('job.discovered','job.changed','job.closed')"
                          ).fetchone()[0]
    checked = con.execute("SELECT MAX(finished_at) FROM runs WHERE mode='normal'").fetchone()[0]
    for s in ctx.registry.sources:
        if s.company_id in seen_company or not s.enabled:
            continue
        if s.platform == "gupy_portal" or (not s.adapter and s.source_id not in ("abs-oracle",)):
            continue
        seen_company.add(s.company_id)
        last = con.execute("""SELECT * FROM source_runs WHERE source_id=? ORDER BY finished_at DESC LIMIT 1""",
                           (s.source_id,)).fetchone()
        jobs = []
        for j in con.execute(
                """SELECT j.*, (SELECT p.url FROM source_postings p WHERE p.job_id=j.job_id ORDER BY p.last_seen_at DESC LIMIT 1) url,
                          (SELECT p.external_id FROM source_postings p WHERE p.job_id=j.job_id LIMIT 1) ext,
                          (SELECT department FROM job_versions v WHERE v.version_id=j.current_version_id) dept
                   FROM job_records j WHERE j.company_id=? AND j.is_fixture=0
                   AND (j.listing_state IN ('active','missing_unconfirmed')
                        OR (j.listing_state='unknown' AND j.job_id IN (SELECT canonical_job_id FROM legacy_id_map
                                                                        WHERE origin LIKE 'legacy_portal_json%'))
                        OR (j.listing_state='closed_confirmed' AND j.closed_at >= date('now','-30 day')))
                   ORDER BY COALESCE(j.published_at, j.first_seen_at) DESC""", (s.company_id,)):
            closed = j["listing_state"] == "closed_confirmed"
            jobs.append({
                "id": portal_ids.get(j["job_id"]) or j["ext"] or j["job_id"],
                "title": j["title"], "location": j["location"] or "", "url": j["url"] or "",
                "date": j["published_at"] or "", "department": j["dept"] or "", "workplace": j["workplace"] or "",
                "status": "Finalizado" if closed else "", "finishedAt": (j["closed_at"] or "") if closed else "",
                "seenAt": j["first_seen_at"] or "",
            })
        companies.append({
            "id": s.company_id, "name": s.company_name, "platform": PLATFORM_LABEL.get(s.platform, "Outras"),
            "kind": KIND.get(s.platform, s.platform), "boardUrl": s.board_url or "", "note": s.note or "",
            "logo": logos.get(s.company_id, ""),
            "scanned": last["raw_count"] if last else 0,
            "error": "" if not last or last["status"] in ("complete",) else f"{last['status']}: {last['error_message'] or ''}"[:200],
            "lastError": (last["error_message"] or "") if last else "",
            "fetchedAt": last["finished_at"] if last else "", "jobs": jobs})
    return {"updatedAt": updated or iso(), "checkedAt": checked or "",
            "platforms": ["Gupy", "SuccessFactors", "Workday", "SmartRecruiters", "Outras"],
            "companies": companies, "generatedBy": "jobos-local (projeção do SQLite; não editar)"}


def write_workspace_files(ctx) -> dict:
    """Mantém `__VAGAS/jobs.json` e `assets/jobs-data.js` iguais ao SQLite (o portal aberto direto do arquivo lia um
    snapshot de 08/10). Somente campos públicos do Book; originais guardados uma vez em data/backups."""
    import os
    import shutil
    ws = ctx.paths.workspace
    targets = {"jobs.json": ws / "jobs.json", "jobs-data.js": ws / "assets" / "jobs-data.js"}
    keep = ctx.paths.backups / "portal-files-original"
    if not keep.exists():
        keep.mkdir(parents=True)
        for name, path in targets.items():
            if path.is_file():
                shutil.copy2(path, keep / name)
    book = build_book(ctx)
    payload = json.dumps(book, ensure_ascii=False, indent=1)
    js = "window.JOBOS_BOOK = " + json.dumps(book, ensure_ascii=False).replace("</", "<\\/") + ";\n"
    for name, content in (("jobs.json", payload), ("jobs-data.js", js)):
        path = targets[name]
        if not path.parent.is_dir():
            continue
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, path)
    return {"companies": len(book["companies"]), "jobs": sum(len(c["jobs"]) for c in book["companies"]),
            "files": [str(p) for p in targets.values()], "backup": str(keep)}
