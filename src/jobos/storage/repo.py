"""Operações de escrita compartilhadas por importador e persistência. Chamar dentro de `tx()`."""
from __future__ import annotations

import json
import sqlite3
import uuid

from jobos.domain.identity import NORMALIZATION_VERSION, canonical_url, content_hash, norm_text
from jobos.settings import Registry
from jobos.timeutil import iso

_PRECISION_RANK = {"timestamp": 3, "date_only": 2, "relative_estimate": 1, "unknown": 0}


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4()}"


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)


def ensure_company(con: sqlite3.Connection, company_id: str, name: str, aliases: list[str] | None = None) -> None:
    row = con.execute("SELECT aliases_json FROM companies WHERE company_id=?", (company_id,)).fetchone()
    if row is None:
        con.execute("INSERT INTO companies (company_id, name, aliases_json, created_at) VALUES (?,?,?,?)",
                    (company_id, name, dumps(sorted(set(aliases or []))), iso()))
    elif aliases:
        merged = sorted(set(json.loads(row["aliases_json"])) | set(aliases))
        con.execute("UPDATE companies SET aliases_json=? WHERE company_id=?", (dumps(merged), company_id))


def sync_registry(con: sqlite3.Connection, registry: Registry) -> None:
    con.execute("INSERT OR IGNORE INTO source_registry_versions (sha256, content, loaded_at) VALUES (?,?,?)",
                (registry.sha256, registry.content, iso()))
    for s in registry.sources:
        ensure_company(con, s.company_id, s.company_name)
        con.execute(
            """INSERT INTO sources (source_id, company_id, platform, adapter, enabled, config_json, registry_sha, updated_at)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(source_id) DO UPDATE SET company_id=excluded.company_id, platform=excluded.platform,
                 adapter=excluded.adapter, enabled=excluded.enabled, config_json=excluded.config_json,
                 registry_sha=excluded.registry_sha, updated_at=excluded.updated_at""",
            (s.source_id, s.company_id, s.platform, s.adapter, int(s.enabled), dumps(s.as_dict()), registry.sha256, iso()))


def relink_postings(con: sqlite3.Connection, registry: Registry) -> int:
    """Posting importada com fonte provisória (`legacy:`/`portal:`) passa à fonte cadastrada da mesma empresa e
    plataforma. Idempotente. Sem isso a ausência e o cache de detalhe não enxergariam o histórico importado."""
    changed = 0
    for s in registry.sources:
        if not s.adapter:
            continue
        cur = con.execute("""UPDATE source_postings SET source_id=?
                             WHERE (source_id LIKE 'legacy:%' OR source_id LIKE 'portal:%') AND platform=?
                             AND job_id IN (SELECT job_id FROM job_records WHERE company_id=?)""",
                          (s.source_id, s.platform, s.company_id))
        changed += cur.rowcount
    return changed


def find_posting(con: sqlite3.Connection, platform: str, tenant: str, external_id: str | None,
                 url: str | None) -> sqlite3.Row | None:
    if external_id:
        return con.execute("SELECT * FROM source_postings WHERE platform=? AND tenant=? AND external_id=?",
                           (platform, tenant or "", external_id)).fetchone()
    cu = canonical_url(url)
    if cu:
        return con.execute("SELECT * FROM source_postings WHERE platform=? AND canonical_url=? AND external_id IS NULL",
                           (platform, cu)).fetchone()
    return None


def create_job(con: sqlite3.Connection, *, company_id: str | None, company_name: str, title: str, location: str | None,
               workplace: str | None, origin: str, is_baseline: bool, is_fixture: bool, talent_pool: bool,
               listing_state: str, first_seen_at: str | None, first_seen_precision: str | None,
               first_seen_source: str | None, last_seen_at: str | None, imported_at: str | None,
               published: dict | None = None) -> str:
    job_id = new_id()
    now = iso()
    pub = published or {}
    con.execute(
        """INSERT INTO job_records (job_id, company_id, company_name, title, location, workplace, listing_state, talent_pool,
             published_at, published_date_precision, published_date_source, published_raw, first_seen_at,
             first_seen_precision, first_seen_source, last_seen_at, imported_at, origin, is_baseline, is_fixture,
             created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (job_id, company_id, company_name, title, location, workplace, listing_state, int(talent_pool),
         pub.get("published_at"), pub.get("published_date_precision", "unknown"), pub.get("published_date_source"),
         pub.get("published_raw"), first_seen_at, first_seen_precision, first_seen_source, last_seen_at, imported_at,
         origin, int(is_baseline), int(is_fixture), now, now))
    return job_id


def maybe_upgrade_published(con: sqlite3.Connection, job_id: str, pub: dict) -> bool:
    """Troca a data de publicação só por uma de precisão maior (nunca apaga dado bom)."""
    row = con.execute("SELECT published_date_precision FROM job_records WHERE job_id=?", (job_id,)).fetchone()
    if _PRECISION_RANK.get(pub.get("published_date_precision", "unknown"), 0) <= _PRECISION_RANK.get(
            row["published_date_precision"], 0):
        return False
    con.execute("""UPDATE job_records SET published_at=?, published_date_precision=?, published_date_source=?,
                   published_raw=?, updated_at=? WHERE job_id=?""",
                (pub.get("published_at"), pub["published_date_precision"], pub.get("published_date_source"),
                 pub.get("published_raw"), iso(), job_id))
    return True


def add_posting(con: sqlite3.Connection, *, job_id: str, source_id: str, platform: str, tenant: str,
                external_id: str | None, url: str | None, posting_state: str, first_seen_at: str | None,
                last_seen_at: str | None, origin: str, run_id: str | None = None, scope_id: str | None = None,
                is_fixture: bool = False) -> int:
    cur = con.execute(
        """INSERT INTO source_postings (job_id, source_id, platform, tenant, external_id, canonical_url, url, posting_state,
             first_seen_at, last_seen_at, last_run_id, last_scope_id, origin, is_fixture)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (job_id, source_id, platform, tenant or "", external_id, canonical_url(url), url, posting_state, first_seen_at,
         last_seen_at, run_id, scope_id, origin, int(is_fixture)))
    return cur.lastrowid


def current_version(con: sqlite3.Connection, job_id: str) -> sqlite3.Row | None:
    return con.execute("""SELECT v.* FROM job_versions v JOIN job_records j ON j.current_version_id=v.version_id
                          WHERE j.job_id=?""", (job_id,)).fetchone()


def add_version(con: sqlite3.Connection, *, job_id: str, fields: dict, observed_at: str, origin: str,
                run_id: str | None = None, source_id: str | None = None, payload: dict | None = None,
                make_current: bool = True) -> tuple[str, bool]:
    """Cria versão se o conteúdo significativo mudou. Retorna (version_id, criada)."""
    h = content_hash(fields)
    existing = con.execute("SELECT version_id FROM job_versions WHERE job_id=? AND content_hash=?",
                           (job_id, h)).fetchone()
    if existing:
        if make_current:
            con.execute("UPDATE job_records SET current_version_id=? WHERE job_id=? AND current_version_id IS NOT ?",
                        (existing["version_id"], job_id, existing["version_id"]))
        return existing["version_id"], False
    desc = fields.get("description") or ""
    vid = new_id("v-")
    con.execute(
        """INSERT INTO job_versions (version_id, job_id, content_hash, normalization_version, observed_at, run_id, source_id,
             origin, title, location, workplace, salary, department, description, description_status, description_length,
             original_length, truncation_note, payload_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (vid, job_id, h, NORMALIZATION_VERSION, observed_at, run_id, source_id, origin, norm_text(fields.get("title")),
         fields.get("location"), fields.get("workplace"), fields.get("salary"), fields.get("department"), desc,
         fields.get("description_status") or ("full" if desc else "missing"), len(desc),
         fields.get("original_length"), fields.get("truncation_note"), dumps(payload) if payload is not None else None))
    if make_current:
        con.execute("UPDATE job_records SET current_version_id=?, title=?, location=?, workplace=?, updated_at=? WHERE job_id=?",
                    (vid, norm_text(fields.get("title")), fields.get("location"), fields.get("workplace"), iso(), job_id))
    return vid, True


def add_job_event(con: sqlite3.Connection, job_id: str, kind: str, *, occurred_at: str | None = None,
                  origin: str = "system", run_id: str | None = None, alertable: bool = False,
                  payload: dict | None = None, dedupe_key: str | None = None) -> bool:
    cur = con.execute(
        """INSERT OR IGNORE INTO job_events (job_id, kind, occurred_at, recorded_at, origin, run_id, alertable,
             payload_json, dedupe_key) VALUES (?,?,?,?,?,?,?,?,?)""",
        (job_id, kind, occurred_at or iso(), iso(), origin, run_id, int(alertable),
         dumps(payload) if payload is not None else None, dedupe_key))
    return cur.rowcount == 1


def add_application_event(con: sqlite3.Connection, application_id: str, *, axis: str, from_state: str | None,
                          to_state: str | None, origin: str, occurred_at: str | None = None, reason: str | None = None,
                          proof: str | None = None, payload: dict | None = None, dedupe_key: str | None = None) -> bool:
    cur = con.execute(
        """INSERT OR IGNORE INTO application_events (application_id, axis, from_state, to_state, occurred_at, recorded_at,
             origin, reason, proof, payload_json, dedupe_key) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (application_id, axis, from_state, to_state, occurred_at or iso(), iso(), origin, reason, proof,
         dumps(payload) if payload is not None else None, dedupe_key))
    return cur.rowcount == 1
