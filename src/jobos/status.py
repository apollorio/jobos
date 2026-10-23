"""Estado do sistema: mesma função para CLI (`status`) e API (`/api/status`)."""
from __future__ import annotations

import datetime as dt
import json
import sqlite3

from jobos.settings import Registry, Settings
from jobos.timeutil import BRT, fmt_brt, parse_instant, utcnow


def schedule_slots(settings: Settings) -> list[dt.time]:
    times = (settings.app.get("schedule") or {}).get("times") or []
    return [dt.time(int(t[:2]), int(t[3:5])) for t in times]


def next_and_previous_slot(settings: Settings, now: dt.datetime | None = None) -> tuple[dt.datetime | None, dt.datetime | None]:
    now = (now or utcnow()).astimezone(BRT)
    slots = schedule_slots(settings)
    if not slots:
        return None, None
    cands = []
    for day in (-1, 0, 1):
        d = (now + dt.timedelta(days=day)).date()
        cands += [dt.datetime.combine(d, t, tzinfo=BRT) for t in slots]
    cands.sort()
    nxt = next((c for c in cands if c > now), None)
    prev = max((c for c in cands if c <= now), default=None)
    return nxt, prev


def source_health(con: sqlite3.Connection, registry: Registry) -> list[dict]:
    out = []
    for s in registry.sources:
        last = con.execute("""SELECT * FROM source_runs WHERE source_id=? ORDER BY COALESCE(finished_at, started_at) DESC
                              LIMIT 1""", (s.source_id,)).fetchone()
        last_ok = con.execute("""SELECT finished_at, normalized_count FROM source_runs WHERE source_id=? AND status='complete'
                                 ORDER BY finished_at DESC LIMIT 1""", (s.source_id,)).fetchone()
        last_err = con.execute("""SELECT finished_at, error_code, error_message FROM source_runs WHERE source_id=?
                                  AND status IN ('failed','blocked','partial') ORDER BY finished_at DESC LIMIT 1""",
                               (s.source_id,)).fetchone()
        active = con.execute("""SELECT COUNT(DISTINCT p.job_id) FROM source_postings p JOIN job_records j ON j.job_id=p.job_id
                                WHERE p.source_id=? AND j.listing_state='active' AND j.is_fixture=0""", (s.source_id,)).fetchone()[0]
        out.append({
            "source_id": s.source_id, "company_id": s.company_id, "company_name": s.company_name, "platform": s.platform,
            "adapter": s.adapter, "enabled": s.enabled, "coverage": s.coverage, "priority": s.priority,
            "board_url": s.board_url, "verification_status": s.verification_status, "note": s.note,
            "last_status": last["status"] if last else ("unconfigured" if not s.adapter else "never_run"),
            "last_run_id": last["run_id"] if last else None,
            "last_finished_at": last["finished_at"] if last else None,
            "last_count": last["normalized_count"] if last else None,
            "last_warnings": json.loads(last["warnings_json"] or "[]") if last else [],
            "absence_applied": bool(last["absence_applied"]) if last else False,
            "last_success_at": last_ok["finished_at"] if last_ok else None,
            "last_success_count": last_ok["normalized_count"] if last_ok else None,
            "last_error_at": last_err["finished_at"] if last_err else None,
            "last_error": (f"{last_err['error_code']}: {last_err['error_message']}" if last_err else None),
            "active_jobs": active,
        })
    return out


def build_status(con: sqlite3.Connection, settings: Settings, registry: Registry) -> dict:
    def count(sql, *a):
        return con.execute(sql, a).fetchone()[0]

    listing = {r[0]: r[1] for r in con.execute(
        "SELECT listing_state, COUNT(*) FROM job_records WHERE is_fixture=0 GROUP BY 1")}
    prep = {r[0]: r[1] for r in con.execute("SELECT prep_state, COUNT(*) FROM applications GROUP BY 1")}
    stages = {r[0]: r[1] for r in con.execute("SELECT selection_stage, COUNT(*) FROM applications GROUP BY 1")}
    outbox = {r[0]: r[1] for r in con.execute("SELECT status, COUNT(*) FROM notification_outbox GROUP BY 1")}
    last = con.execute("SELECT * FROM runs WHERE mode='normal' ORDER BY started_at DESC LIMIT 1").fetchone()
    last_done = con.execute("""SELECT * FROM runs WHERE mode='normal' AND status IN ('complete','partial')
                               ORDER BY started_at DESC LIMIT 1""").fetchone()
    nxt, prev = next_and_previous_slot(settings)
    late = False
    if prev is not None:
        last_t = parse_instant(last_done["started_at"]) if last_done else None
        late = last_t is None or last_t < prev - dt.timedelta(minutes=5) and utcnow() - prev > dt.timedelta(minutes=45)
    health = source_health(con, registry)
    hs = {"complete": 0, "partial": 0, "failed": 0, "blocked": 0, "unconfigured": 0, "never_run": 0, "skipped": 0}
    for h in health:
        hs[h["last_status"]] = hs.get(h["last_status"], 0) + 1
    profile = con.execute("SELECT profile_id, received_at FROM profile_versions WHERE is_active=1").fetchone()
    invalid_profile = con.execute("""SELECT error, received_at FROM profile_versions WHERE valid=0
                                     ORDER BY received_at DESC LIMIT 1""").fetchone()
    new_24h = count("""SELECT COUNT(*) FROM job_events WHERE kind='job.discovered' AND alertable=1
                       AND occurred_at >= ?""", (utcnow() - dt.timedelta(hours=24)).isoformat())
    changed_24h = count("""SELECT COUNT(*) FROM job_events WHERE kind='job.changed' AND alertable=1
                           AND occurred_at >= ?""", (utcnow() - dt.timedelta(hours=24)).isoformat())
    notif = settings.notifications
    return {
        "generated_at": utcnow().isoformat(timespec="seconds"),
        "database": str(settings.paths.db),
        "schema_version": con.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0],
        "jobs": {"total": sum(listing.values()), "by_listing_state": listing,
                 "fixtures_excluded": count("SELECT COUNT(*) FROM job_records WHERE is_fixture=1"),
                 "talent_pool": count("SELECT COUNT(*) FROM job_records WHERE talent_pool=1 AND is_fixture=0"),
                 "alertable_new_24h": new_24h, "alertable_changed_24h": changed_24h},
        "applications": {"by_prep_state": prep, "by_stage": stages,
                         "proven_submitted": prep.get("submitted_manual", 0) + prep.get("submitted_verified", 0),
                         "legacy_needs_review": prep.get("legacy_needs_review", 0)},
        "runs": {
            "last": _run(last), "last_completed": _run(last_done),
            "next_scheduled_brt": nxt.strftime("%d/%m/%Y %H:%M") if nxt else None,
            "late": bool(late),
        },
        "sources": {"total": len(health), "by_last_status": hs},
        "outbox": {"by_status": outbox, "sending_enabled": bool(notif.get("enabled")),
                   "recipient_configured": bool(notif.get("recipient"))},
        "profile": {"active_profile_id": profile["profile_id"] if profile else None,
                    "last_invalid": dict(invalid_profile) if invalid_profile else None},
        "imports": [dict(r) for r in con.execute(
            "SELECT import_id, kind, sha256, status, finished_at FROM imports ORDER BY started_at")],
        "relations_suggested": count("SELECT COUNT(*) FROM job_relations WHERE status='suggested'"),
        "ai": {"enabled": bool((settings.matching.get("ai") or {}).get("enabled"))},
    }


def _run(r) -> dict | None:
    if not r:
        return None
    d = dict(r)
    d["started_brt"] = fmt_brt(d.get("started_at"))
    d["finished_brt"] = fmt_brt(d.get("finished_at")) if d.get("finished_at") else None
    d.pop("counts_json", None)
    return d
