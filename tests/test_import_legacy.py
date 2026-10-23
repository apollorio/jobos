"""T01-T04, T17, T18, T26: importação legada idempotente, procedência e datas."""
import hashlib
import json

import pytest

from jobos.legacy import importer
from jobos.storage.db import sha256_file


def _apply(ctx, path):
    return importer.apply_sqlite(ctx.con, ctx.settings, ctx.registry, path)


def test_import_is_idempotent_and_keeps_origin_intact(ctx, legacy_db):
    before = sha256_file(legacy_db)
    first = _apply(ctx, legacy_db)
    counts1 = {t: ctx.con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
               for t in ("job_records", "job_versions", "legacy_events", "applications", "application_events", "job_events")}
    second = _apply(ctx, legacy_db)
    counts2 = {t: ctx.con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in counts1}
    assert first["status"] == "imported"
    assert second["status"] == "already_imported"
    assert counts1 == counts2
    assert sha256_file(legacy_db) == before  # banco de origem intacto
    assert counts1["legacy_events"] == 4     # inclusive o evento órfão


def test_same_source_id_merges_into_one_job_with_versions(ctx, legacy_db):
    _apply(ctx, legacy_db)
    rows = ctx.con.execute("""SELECT canonical_job_id FROM legacy_id_map WHERE legacy_id IN ('h1','h2')""").fetchall()
    assert len({r[0] for r in rows}) == 1
    versions = ctx.con.execute("SELECT COUNT(*) FROM job_versions WHERE job_id=?", (rows[0][0],)).fetchone()[0]
    assert versions == 2


def test_same_title_different_ids_are_not_merged(ctx, legacy_db):
    _apply(ctx, legacy_db)
    ids = {r[0] for r in ctx.con.execute("SELECT canonical_job_id FROM legacy_id_map WHERE legacy_id IN ('h5','h6')")}
    assert len(ids) == 2


def test_presumed_applications_go_to_review_never_submitted(ctx, legacy_db):
    _apply(ctx, legacy_db)
    apps = ctx.con.execute("SELECT prep_state, legacy_source, legacy_date, legacy_hint FROM applications").fetchall()
    assert len(apps) == 2
    assert {a["prep_state"] for a in apps} == {"legacy_needs_review"}
    hints = {a["legacy_hint"] for a in apps}
    assert "auto_consolidation_by_bulletin" in hints and "legacy_manual_mark_event" in hints
    assert {a["legacy_date"] for a in apps} == {"2026-08-26", "2026-08-24"}  # data original preservada
    submitted = ctx.con.execute("SELECT COUNT(*) FROM applications WHERE prep_state LIKE 'submitted%'").fetchone()[0]
    assert submitted == 0


def test_dates_keep_precision_and_never_invent_publication(ctx, legacy_db):
    _apply(ctx, legacy_db)
    def job(legacy):
        jid = ctx.con.execute("SELECT canonical_job_id FROM legacy_id_map WHERE legacy_id=?", (legacy,)).fetchone()[0]
        return ctx.con.execute("SELECT * FROM job_records WHERE job_id=?", (jid,)).fetchone()
    j1 = job("h1")
    assert j1["published_at"] == "2026-08-01" and j1["published_date_precision"] == "date_only"
    assert j1["first_seen_at"] == "2026-08-02T08:00:00+00:00" and j1["first_seen_precision"] == "timestamp"
    j3 = job("h3")
    assert j3["published_at"] is None and j3["published_date_precision"] == "relative_estimate"
    j5 = job("h5")
    assert j5["published_at"] is None and j5["published_date_precision"] == "unknown"
    assert j5["listing_state"] == "unknown" and j5["is_baseline"] == 1  # importado não vira ativo nem alerta


def test_legacy_scores_not_reused(ctx, legacy_db):
    _apply(ctx, legacy_db)
    payload = json.loads(ctx.con.execute("SELECT payload_json FROM legacy_payloads WHERE legacy_id='h1'").fetchone()[0])
    assert payload["fit_score"] == 95 and payload["interview_prob"] == 0.7  # preservado como histórico
    from jobos.matching.analyze import analyze_pending
    analyze_pending(ctx)
    for (res,) in ctx.con.execute("SELECT result_json FROM analyses"):
        assert "interview" not in res and "0.7" not in json.loads(res).get("decision_reason", "")


def test_interrupted_import_rolls_back_and_retries(ctx, legacy_db, monkeypatch):
    calls = {"n": 0}
    real = importer.repo.add_version

    def flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("queda simulada")
        return real(*a, **kw)
    monkeypatch.setattr(importer.repo, "add_version", flaky)
    with pytest.raises(RuntimeError):
        _apply(ctx, legacy_db)
    assert ctx.con.execute("SELECT COUNT(*) FROM imports").fetchone()[0] == 0
    assert ctx.con.execute("SELECT COUNT(*) FROM job_records").fetchone()[0] == 0
    monkeypatch.setattr(importer.repo, "add_version", real)
    assert _apply(ctx, legacy_db)["status"] == "imported"
