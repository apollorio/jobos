"""Importação idempotente do histórico legado (SQLite do Artifact e snapshot `jobs.json` do portal).

Regras (DEC-002/005/006/007):
- Origem aberta só em leitura (`immutable=1`); cópia identificada por hash em data/imports/<import_id>/.
- Mesmo `source_id` legado = mesma vaga canônica (identidade forte). Título parecido sem ID não funde.
- `applied` legado vira `legacy_needs_review`; nenhuma candidatura nova é criada.
- `~AAAA-MM-DD` não vira publicação; vagas importadas ficam `unknown` (não verificadas) e `is_baseline=1`.
"""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit

from jobos.domain.identity import (canonical_url, fold, host_label, is_talent_pool, j2w_id, slugify, totvs_number,
                                   workday_req_id)
from jobos.settings import Registry, Settings
from jobos.storage import repo
from jobos.storage.db import sha256_file, tx
from jobos.timeutil import iso, parse_instant, parse_published

ORIGIN_SQLITE = "legacy_sqlite:Artifact/jobs.db"
ORIGIN_PORTAL = "legacy_portal_json:jobs.json"

_PRECISION_RANK = {"timestamp": 3, "date_only": 2, "relative_estimate": 1, "unknown": 0}


class ImportErrorJobos(RuntimeError):
    pass


# --------------------------------------------------------------------------- identidade

def legacy_identity(source_id: str, url: str) -> tuple[str, str, str | None, str]:
    """Converte o `source_id` do legado em (platform, tenant, external_id, regra)."""
    sid = source_id or ""
    host = urlsplit(url or "").netloc.lower()
    if sid.startswith("gupy:"):
        return "gupy", "", sid.split(":", 1)[1], "legacy_source_id:gupy"
    if sid.startswith("web:j2w:"):
        return "successfactors_j2w", host, j2w_id(url) or sid.rsplit(":", 1)[-1], "legacy_source_id:j2w"
    if sid.startswith("workday:"):
        _, tenant, path = sid.split(":", 2)
        return "workday", tenant, workday_req_id(path), "legacy_source_id:workday"
    if sid.startswith("web:workday:"):
        return "workday", host_label(url), workday_req_id(sid.rsplit(":", 1)[-1]), "legacy_source_id:web_workday"
    if sid.startswith("web:inhire:"):
        return "inhire", host_label(url), sid.rsplit(":", 1)[-1], "legacy_source_id:inhire"
    if sid.startswith("web:webflow_dof:"):
        return "webflow", "dof.com", sid.rsplit(":", 1)[-1], "legacy_source_id:dof"
    if sid.startswith("web:greenhouse:"):
        board = urlsplit(url or "").path.strip("/").split("/")[0] or "capco"
        return "greenhouse", board, sid.rsplit(":", 1)[-1], "legacy_source_id:greenhouse"
    if sid.startswith("totvs:"):
        tenant = urlsplit(url or "").path.strip("/").split("/")[0]
        return "totvs", tenant, totvs_number(url) or sid.rsplit(":", 1)[-1], "legacy_source_id:totvs_number"
    # Sem regra conhecida: fallback de URL (sem inventar ID).
    return "unknown_legacy", "", None, "legacy_url_fallback"


def portal_identity(company: dict, job: dict) -> tuple[str, str, str | None]:
    kind = company.get("kind")
    jid = str(job.get("id") or "")
    url = job.get("url") or ""
    if kind == "gupy":
        return "gupy", "", jid
    if kind == "sf":
        return "successfactors_j2w", urlsplit(url).netloc.lower() or urlsplit(company.get("host") or "").netloc.lower(), \
            j2w_id(jid) or j2w_id(url)
    if kind == "workday":
        return "workday", company.get("tenant") or host_label(company.get("host")), workday_req_id(jid)
    if kind == "inhire":
        return "inhire", company.get("host") or host_label(url), jid
    if kind == "dof":
        return "webflow", "dof.com", jid
    if kind == "bram":
        return "totvs", "bramoffshore", totvs_number(url) or jid
    if kind == "greenhouse":
        return "greenhouse", company.get("host") or "capco", jid
    if kind == "smart":
        return "smartrecruiters", company.get("host") or "", jid
    return f"portal_{kind}", company.get("id", ""), jid or None


def _source_index(registry: Registry) -> dict[tuple[str, str], str]:
    idx: dict[tuple[str, str], str] = {}
    for s in registry.sources:
        p = s.params
        if s.platform == "gupy" and p.get("tenant"):
            idx[("gupy", p["tenant"])] = s.source_id
        elif s.platform == "successfactors_j2w":
            idx[(s.platform, urlsplit(p.get("base", "")).netloc.lower())] = s.source_id
        elif s.platform == "workday":
            idx[(s.platform, p.get("tenant", ""))] = s.source_id
        elif s.platform == "inhire":
            idx[(s.platform, p.get("tenant", ""))] = s.source_id
        elif s.platform == "webflow":
            idx[(s.platform, "dof.com")] = s.source_id
        elif s.platform == "totvs":
            idx[(s.platform, p.get("tenant", ""))] = s.source_id
        elif s.platform == "greenhouse":
            idx[(s.platform, p.get("board", ""))] = s.source_id
        elif s.platform == "smartrecruiters":
            idx[(s.platform, p.get("company_id", ""))] = s.source_id
    return idx


class CompanyResolver:
    """Nome legado → company_id do cadastro. Desconhecida vira `legacy-<slug>` (sem fundir por palpite)."""

    EXTRA = {"modec-br": "modec", "bravaenergia": "brava", "brava energia": "brava", "andrade gutierrez": None}

    def __init__(self, registry: Registry):
        self.map: dict[str, str] = {}
        self.names: dict[str, str] = {}
        for s in registry.sources:
            self.names[s.company_id] = s.company_name
            for alias in (s.company_name, s.company_id, s.params.get("tenant"), s.params.get("board")):
                if alias:
                    self.map[fold(str(alias))] = s.company_id
        for k, v in self.EXTRA.items():
            if v:
                self.map[k] = v

    def resolve(self, name: str) -> tuple[str, str]:
        key = fold(name)
        cid = self.map.get(key)
        if cid:
            return cid, self.names[cid]
        cid = "legacy-" + slugify(name)
        return cid, (name or "").strip() or cid


# --------------------------------------------------------------------------- leitura da origem

def _open_ro(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise ImportErrorJobos(f"banco legado não encontrado: {path}")
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro&immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _read_legacy(path: Path) -> dict:
    src = _open_ro(path)
    try:
        ic = src.execute("PRAGMA integrity_check").fetchone()[0]
        if ic != "ok":
            raise ImportErrorJobos(f"integrity_check do legado: {ic}")
        jobs = [dict(r) for r in src.execute("SELECT * FROM jobs ORDER BY rowid")]
        events = [dict(r) for r in src.execute("SELECT * FROM events ORDER BY id")]
        runs = [dict(r) for r in src.execute("SELECT * FROM runs ORDER BY id")]
        data = src.serialize()
    finally:
        src.close()
    return {"jobs": jobs, "events": events, "runs": runs, "snapshot": data, "integrity": ic}


def _group_legacy(jobs: list[dict]) -> dict[tuple, list[dict]]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in jobs:
        platform, tenant, ext, rule = legacy_identity(r.get("source_id") or "", r.get("url") or "")
        key = (platform, tenant, ext) if ext else ("url", canonical_url(r.get("url")) or r["job_id"], None)
        r["_identity"] = (platform, tenant, ext, rule)
        groups[key].append(r)
    return groups


def plan_sqlite(path: Path) -> dict:
    data = _read_legacy(path)
    jobs = data["jobs"]
    groups = _group_legacy(jobs)
    applied = [j for j in jobs if j.get("application_status") == "applied"]
    by_src = defaultdict(int)
    for j in applied:
        by_src[j.get("application_source") or "null"] += 1
    dates = defaultdict(int)
    for j in jobs:
        dates[parse_published(j.get("date_posted"), "legacy").precision] += 1
    return {
        "origin": str(path), "sha256": sha256_file(path), "integrity_check": data["integrity"],
        "counts": {"jobs": len(jobs), "events": len(data["events"]), "runs": len(data["runs"])},
        "canonical_jobs_planned": len(groups),
        "rows_merged_by_strong_identity": len(jobs) - len(groups),
        "applied_rows": len(applied), "applied_by_source": dict(by_src),
        "applications_planned_as_legacy_needs_review": len({_gkey(j) for j in applied}),
        "published_precision": dict(dates),
        "orphan_events": sum(1 for e in data["events"] if e["job_id"] not in {j["job_id"] for j in jobs}),
    }


def _gkey(r: dict) -> tuple:
    platform, tenant, ext, _ = r["_identity"]
    return (platform, tenant, ext) if ext else ("url", canonical_url(r.get("url")) or r["job_id"], None)


# --------------------------------------------------------------------------- aplicação SQLite

def apply_sqlite(con: sqlite3.Connection, settings: Settings, registry: Registry, path: Path) -> dict:
    sha = sha256_file(path)
    prev = con.execute("SELECT * FROM imports WHERE kind='legacy_sqlite' AND sha256=? AND status='complete'",
                       (sha,)).fetchone()
    if prev:
        return {"status": "already_imported", "import_id": prev["import_id"], "counts": json.loads(prev["counts_json"])}

    data = _read_legacy(path)
    import_id = f"imp-sqlite-{sha[:12]}"
    out_dir = settings.paths.imports / import_id
    out_dir.mkdir(parents=True, exist_ok=True)
    snap = out_dir / "legacy-jobs.sqlite3"
    snap.write_bytes(data["snapshot"])
    resolver = CompanyResolver(registry)
    src_index = _source_index(registry)
    pool_terms = settings.preferences.get("talent_pool_terms") or []
    now = iso()
    counts = defaultdict(int)

    found_ts: dict[str, list[str]] = defaultdict(list)
    applied_events: dict[str, list[dict]] = defaultdict(list)
    for e in data["events"]:
        if e["kind"] == "found" and e["ts"]:
            found_ts[e["job_id"]].append(e["ts"])
        if e["kind"] == "applied":
            applied_events[e["job_id"]].append(e)

    groups = _group_legacy(data["jobs"])
    legacy_to_job: dict[str, str] = {}

    with tx(con):
        con.execute("INSERT INTO imports (import_id, kind, origin_path, sha256, started_at, status) VALUES (?,?,?,?,?,?)",
                    (import_id, "legacy_sqlite", str(path), sha, now, "running"))
        repo.sync_registry(con, registry)
        for key, rows in groups.items():
            rows.sort(key=lambda r: (r.get("last_seen") or "", r.get("date_found") or ""))
            latest = rows[-1]
            platform, tenant, ext, rule = latest["_identity"]
            company_id, company_name = resolver.resolve(latest.get("company") or "")
            repo.ensure_company(con, company_id, company_name, [r.get("company") for r in rows if r.get("company")])

            # Já importado antes (origem com hash diferente): reaproveita pelo mapa legado.
            job_id = None
            for r in rows:
                m = con.execute("SELECT canonical_job_id FROM legacy_id_map WHERE origin=? AND legacy_id=?",
                                (ORIGIN_SQLITE, r["job_id"])).fetchone()
                if m:
                    job_id = m["canonical_job_id"]
                    break
            posting = repo.find_posting(con, platform, tenant, ext, latest.get("url")) if not job_id else None
            if posting:
                job_id = posting["job_id"]

            pubs = [parse_published(r.get("date_posted"), "legacy_db:date_posted") for r in rows]
            best_pub = max(pubs, key=lambda p: _PRECISION_RANK[p.precision])
            ts_candidates = sorted(t for r in rows for t in found_ts.get(r["job_id"], []))
            if ts_candidates:
                first_seen, fs_prec, fs_src = ts_candidates[0], "timestamp", "legacy_event:found"
            else:
                df = sorted(r["date_found"] for r in rows if r.get("date_found"))
                first_seen, fs_prec, fs_src = (df[0], "date_only", "legacy_db:date_found") if df else (None, None, None)
            last_seen = max((r.get("last_seen") or "" for r in rows), default="") or None

            if not job_id:
                job_id = repo.create_job(
                    con, company_id=company_id, company_name=company_name, title=latest.get("title") or "(sem título)",
                    location=latest.get("location"), workplace=latest.get("remote_status"), origin="legacy_sqlite",
                    is_baseline=True, is_fixture=False,
                    talent_pool=is_talent_pool(latest.get("title") or "", pool_terms), listing_state="unknown",
                    first_seen_at=first_seen, first_seen_precision=fs_prec, first_seen_source=fs_src,
                    last_seen_at=last_seen, imported_at=now, published=best_pub.as_dict())
                counts["jobs_created"] += 1
            else:
                repo.maybe_upgrade_published(con, job_id, best_pub.as_dict())
                counts["jobs_reused"] += 1

            if not repo.find_posting(con, platform, tenant, ext, latest.get("url")):
                repo.add_posting(con, job_id=job_id, source_id=src_index.get((platform, tenant), f"legacy:{latest.get('source')}"),
                                 platform=platform, tenant=tenant, external_id=ext, url=latest.get("url"),
                                 posting_state="unknown", first_seen_at=first_seen, last_seen_at=last_seen,
                                 origin="legacy_sqlite")
                counts["postings_created"] += 1

            for r in rows:
                desc = r.get("description") or ""
                fields = {"title": r.get("title") or "", "description": desc, "location": r.get("location"),
                          "workplace": r.get("remote_status"), "salary": r.get("salary"),
                          "description_status": "partial" if len(desc) >= 19990 else ("full" if desc else "missing"),
                          "truncation_note": "legado cortava em 20.000 caracteres" if len(desc) >= 19990 else None}
                _, created = repo.add_version(con, job_id=job_id, fields=fields,
                                              observed_at=r.get("last_seen") or r.get("date_found") or now,
                                              origin="legacy_sqlite", source_id=r.get("source"),
                                              make_current=(r is latest))
                counts["versions_created"] += int(created)
                payload = {k: v for k, v in r.items() if not k.startswith("_") and k != "description"}
                con.execute("""INSERT INTO legacy_payloads (origin, legacy_id, import_id, payload_json) VALUES (?,?,?,?)
                               ON CONFLICT(origin, legacy_id) DO UPDATE SET import_id=excluded.import_id,
                               payload_json=excluded.payload_json""",
                            (ORIGIN_SQLITE, r["job_id"], import_id, repo.dumps(payload)))
                con.execute("""INSERT INTO legacy_id_map (origin, legacy_id, canonical_job_id, rule, import_id)
                               VALUES (?,?,?,?,?) ON CONFLICT(origin, legacy_id) DO NOTHING""",
                            (ORIGIN_SQLITE, r["job_id"], job_id, rule if len(rows) == 1 else f"{rule}+merged_same_source_id",
                             import_id))
                legacy_to_job[r["job_id"]] = job_id
                if r.get("closed"):
                    repo.add_job_event(con, job_id, "legacy.closed_mark", occurred_at=r.get("removed_at") or now,
                                       origin="legacy_import",
                                       payload={"removed_at": r.get("removed_at"), "rule": "mark_closed por last_seen (A04)",
                                                "note": "não é confirmação de encerramento"},
                                       dedupe_key=f"legacy_closed:{r['job_id']}")
            repo.add_job_event(con, job_id, "job.imported", occurred_at=now, origin="legacy_import",
                               payload={"import_id": import_id, "legacy_ids": [r["job_id"] for r in rows]},
                               dedupe_key=f"imported:{ORIGIN_SQLITE}:{key}")

            applied_rows = [r for r in rows if r.get("application_status") == "applied"]
            if applied_rows:
                counts["applications_legacy_review"] += _import_application(con, job_id, applied_rows, applied_events)

        for e in data["events"]:
            cur = con.execute("""INSERT OR IGNORE INTO legacy_events (origin, legacy_event_id, legacy_job_id, job_id, ts, kind,
                                   detail, import_id) VALUES (?,?,?,?,?,?,?,?)""",
                              (ORIGIN_SQLITE, e["id"], e["job_id"], legacy_to_job.get(e["job_id"]), e["ts"], e["kind"],
                               e["detail"], import_id))
            counts["legacy_events"] += cur.rowcount
        for r in data["runs"]:
            cur = con.execute("""INSERT OR IGNORE INTO legacy_runs (origin, legacy_run_id, ts, source, fetched, new_jobs, errors,
                                   import_id) VALUES (?,?,?,?,?,?,?,?)""",
                              (ORIGIN_SQLITE, r["id"], r["ts"], r["source"], r["fetched"], r["new_jobs"], r["errors"],
                               import_id))
            counts["legacy_runs"] += cur.rowcount
        counts.update({"source_jobs": len(data["jobs"]), "source_events": len(data["events"]),
                       "source_runs": len(data["runs"]), "canonical_groups": len(groups)})
        con.execute("UPDATE imports SET status='complete', finished_at=?, counts_json=? WHERE import_id=?",
                    (iso(), repo.dumps(dict(counts)), import_id))

    manifest = {"import_id": import_id, "kind": "legacy_sqlite", "origin_path": str(path), "sha256": sha,
                "snapshot": {"file": snap.name, "sha256": sha256_file(snap), "method": "serialize() de origem immutable"},
                "integrity_check": data["integrity"], "counts": dict(counts), "finished_at": iso()}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "imported", "import_id": import_id, "counts": dict(counts)}


def _import_application(con: sqlite3.Connection, job_id: str, rows: list[dict], applied_events: dict) -> int:
    existing = con.execute("SELECT application_id FROM applications WHERE job_id=?", (job_id,)).fetchone()
    first = rows[0]
    hints = []
    for r in rows:
        evs = applied_events.get(r["job_id"], [])
        if r.get("application_source") == "auto_sugerida":
            hints.append("auto_consolidation_by_bulletin")
        elif any("manualmente" in (e.get("detail") or "") for e in evs):
            hints.append("legacy_manual_mark_event")
        else:
            hints.append("no_provenance")
    hint = ",".join(sorted(set(hints)))
    created = 0
    if existing:
        app_id = existing["application_id"]
    else:
        app_id = repo.new_id("app-")
        now = iso()
        con.execute("""INSERT INTO applications (application_id, job_id, prep_state, selection_stage, provenance, legacy_status,
                         legacy_source, legacy_date, legacy_hint, created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (app_id, job_id, "legacy_needs_review", "none", "legacy_import", first.get("application_status"),
                     first.get("application_source"), first.get("application_date"), hint, now, now))
        created = 1
    for r in rows:
        evs = applied_events.get(r["job_id"], [])
        repo.add_application_event(
            con, app_id, axis="prep", from_state=None, to_state="legacy_needs_review", origin="legacy_import",
            occurred_at=r.get("application_date") or iso(),
            reason="registro 'applied' do legado sem prova de envio; revisar procedência",
            payload={"legacy_job_id": r["job_id"], "application_status": r.get("application_status"),
                     "application_source": r.get("application_source"), "application_date": r.get("application_date"),
                     "suggested_at": r.get("suggested_at"), "suggested_run": r.get("suggested_run"),
                     "follow_up_date": r.get("follow_up_date"), "cv_version": r.get("cv_version"),
                     "legacy_applied_events": [{"ts": e["ts"], "detail": e["detail"]} for e in evs]},
            dedupe_key=f"legacy_app:{ORIGIN_SQLITE}:{r['job_id']}")
    return created


# --------------------------------------------------------------------------- snapshot do portal

def plan_portal(path: Path) -> dict:
    book = json.loads(path.read_text(encoding="utf-8"))
    companies = book.get("companies") or []
    return {"origin": str(path), "sha256": sha256_file(path), "updatedAt": book.get("updatedAt"),
            "checkedAt": book.get("checkedAt"), "companies": len(companies),
            "jobs": sum(len(c.get("jobs") or []) for c in companies)}


def apply_portal(con: sqlite3.Connection, settings: Settings, registry: Registry, path: Path) -> dict:
    sha = sha256_file(path)
    prev = con.execute("SELECT * FROM imports WHERE kind='legacy_portal_json' AND sha256=? AND status='complete'",
                       (sha,)).fetchone()
    if prev:
        return {"status": "already_imported", "import_id": prev["import_id"], "counts": json.loads(prev["counts_json"])}
    raw = path.read_bytes()
    book = json.loads(raw.decode("utf-8"))
    import_id = f"imp-portal-{sha[:12]}"
    out_dir = settings.paths.imports / import_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "jobs.json").write_bytes(raw)
    resolver = CompanyResolver(registry)
    src_index = _source_index(registry)
    pool_terms = settings.preferences.get("talent_pool_terms") or []
    now = iso()
    counts = defaultdict(int)
    with tx(con):
        con.execute("INSERT INTO imports (import_id, kind, origin_path, sha256, started_at, status) VALUES (?,?,?,?,?,?)",
                    (import_id, "legacy_portal_json", str(path), sha, now, "running"))
        repo.sync_registry(con, registry)
        for c in book.get("companies") or []:
            company_id, company_name = resolver.resolve(c.get("id") or c.get("name") or "")
            repo.ensure_company(con, company_id, company_name, [c.get("name")])
            seen_at = c.get("fetchedAt")
            for j in c.get("jobs") or []:
                platform, tenant, ext = portal_identity(c, j)
                legacy_id = f"{c.get('id')}:{j.get('id')}"
                pub = parse_published(j.get("date"), "legacy_portal_json:date").as_dict()
                mapped = con.execute("SELECT canonical_job_id FROM legacy_id_map WHERE origin=? AND legacy_id=?",
                                     (ORIGIN_PORTAL, legacy_id)).fetchone()
                posting = repo.find_posting(con, platform, tenant, ext, j.get("url"))
                job_id = mapped["canonical_job_id"] if mapped else (posting["job_id"] if posting else None)
                if job_id:
                    repo.maybe_upgrade_published(con, job_id, pub)
                    counts["jobs_linked_existing"] += 1
                else:
                    job_id = repo.create_job(
                        con, company_id=company_id, company_name=company_name, title=j.get("title") or "(sem título)",
                        location=j.get("location"), workplace=j.get("workplace") or None, origin="legacy_portal_json",
                        is_baseline=True, is_fixture=False, talent_pool=is_talent_pool(j.get("title") or "", pool_terms),
                        listing_state="unknown", first_seen_at=None, first_seen_precision=None, first_seen_source=None,
                        last_seen_at=seen_at, imported_at=now, published=pub)
                    repo.add_version(con, job_id=job_id, fields={
                        "title": j.get("title") or "", "description": "", "location": j.get("location"),
                        "workplace": j.get("workplace") or None, "department": j.get("department") or None,
                        "description_status": "missing"}, observed_at=seen_at or now, origin="legacy_portal_json")
                    counts["jobs_created"] += 1
                if not posting:
                    repo.add_posting(con, job_id=job_id, source_id=src_index.get((platform, tenant), f"portal:{c.get('id')}"),
                                     platform=platform, tenant=tenant, external_id=ext, url=j.get("url"),
                                     posting_state="unknown", first_seen_at=None, last_seen_at=seen_at,
                                     origin="legacy_portal_json")
                    counts["postings_created"] += 1
                con.execute("""INSERT INTO legacy_id_map (origin, legacy_id, canonical_job_id, rule, import_id)
                               VALUES (?,?,?,?,?) ON CONFLICT(origin, legacy_id) DO NOTHING""",
                            (ORIGIN_PORTAL, legacy_id, job_id, f"portal_id:{c.get('kind')}", import_id))
                con.execute("""INSERT INTO legacy_payloads (origin, legacy_id, import_id, payload_json) VALUES (?,?,?,?)
                               ON CONFLICT(origin, legacy_id) DO UPDATE SET import_id=excluded.import_id,
                               payload_json=excluded.payload_json""",
                            (ORIGIN_PORTAL, legacy_id, import_id, repo.dumps({"company": {k: v for k, v in c.items() if k != "jobs"},
                                                                              "job": j})))
                repo.add_job_event(con, job_id, "job.imported", occurred_at=now, origin="legacy_import",
                                   payload={"import_id": import_id, "portal_id": legacy_id},
                                   dedupe_key=f"imported:{ORIGIN_PORTAL}:{legacy_id}")
        counts.update({"source_companies": len(book.get("companies") or []),
                       "source_jobs": sum(len(c.get("jobs") or []) for c in book.get("companies") or [])})
        con.execute("UPDATE imports SET status='complete', finished_at=?, counts_json=? WHERE import_id=?",
                    (iso(), repo.dumps(dict(counts)), import_id))
    manifest = {"import_id": import_id, "kind": "legacy_portal_json", "origin_path": str(path), "sha256": sha,
                "updatedAt": book.get("updatedAt"), "checkedAt": book.get("checkedAt"), "counts": dict(counts),
                "finished_at": iso()}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "imported", "import_id": import_id, "counts": dict(counts)}


def first_seen_from_events(ts_list: list[str]) -> str | None:
    vals = sorted(t for t in ts_list if parse_instant(t))
    return vals[0] if vals else None
