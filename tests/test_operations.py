"""T05, T18/T19, T31-T37: CLI estrita, dry run, trava, outbox, transições de candidatura."""
import datetime as dt

import pytest

from conftest import apply, batch, make_source, obs

from jobos import persistence
from jobos.applications import service
from jobos.cli import main
from jobos.domain.states import TransitionError
from jobos.lock import CycleLock, LockBusy
from jobos.notifications import outbox
from jobos.notifications.transport import FakeTransport
from jobos.timeutil import BRT, brt_date, parse_published


def test_unknown_flag_fails_with_3(data_dir, capsys):
    with pytest.raises(SystemExit) as e:
        main(["cycle", "--dry-run", "--send-everything"])
    assert e.value.code == 3


def test_fixtures_require_dry_run(data_dir):
    assert main(["cycle", "--fixtures"]) == 3


def test_published_date_variants():
    assert parse_published("2026-10-05T15:41:57-04:00", "s").precision == "timestamp"
    assert parse_published("2026-10-05", "s").precision == "date_only"
    assert parse_published("~2026-10-05", "s").value is None
    assert parse_published("Posted 3 Days Ago", "s").precision == "relative_estimate"
    assert parse_published("N/A", "s").precision == "unknown"
    assert parse_published("Mon Aug 17 00:00:00 UTC 2026", "s").value is None


def test_brazil_day_near_utc_midnight():
    utc = dt.datetime(2026, 10, 23, 1, 30, tzinfo=dt.timezone.utc)  # 22:30 em Brasília
    assert brt_date(utc) == dt.date(2026, 10, 22)
    assert utc.astimezone(BRT).hour == 22


def test_suggestion_never_becomes_submitted(ctx):
    src = make_source()
    apply(ctx, batch(src, "r1", [obs("1")]), src)
    jid = ctx.con.execute("SELECT job_id FROM job_records").fetchone()[0]
    service.transition(ctx.con, jid, "shortlisted", origin="user_asserted")
    with pytest.raises(TransitionError):
        service.transition(ctx.con, jid, "submitted_manual", origin="system")  # sistema não confirma envio
    with pytest.raises(TransitionError):
        service.transition(ctx.con, jid, "submitted_verified", origin="user_asserted")
    # dois "boletins" depois, continua selecionada
    outbox.enqueue_digest(ctx, "r1")
    assert ctx.con.execute("SELECT prep_state FROM applications").fetchone()[0] == "shortlisted"
    service.confirm_manual(ctx.con, jid, brt_date().isoformat(), "enviei pelo site")
    a = ctx.con.execute("SELECT prep_state, provenance FROM applications").fetchone()
    assert tuple(a) == ("submitted_manual", "user_asserted")


def test_lock_is_exclusive_and_cycle_reports_overlap(ctx):
    from jobos.pipeline import EXIT_OVERLAP, run_cycle
    lk = CycleLock(ctx.paths.lock_file)
    lk.acquire({"run_id": "outro"})
    try:
        with pytest.raises(LockBusy):
            CycleLock(ctx.paths.lock_file).acquire({"run_id": "x"})
        res = run_cycle(ctx, trigger="test", only_sources=["prio-gupy"])
        assert res.exit_code == EXIT_OVERLAP and res.status == "skipped_overlap"
    finally:
        lk.release()
    assert ctx.con.execute("SELECT COUNT(*) FROM runs WHERE status='skipped_overlap'").fetchone()[0] == 1


def _queued(ctx):
    src = make_source()
    apply(ctx, batch(src, "r0", [obs("0")]), src)  # baseline
    apply(ctx, batch(src, "r1", [obs("0"), obs("1")]), src)
    ctx.settings.notifications.update(enabled=True, recipient="eu@example.invalid")
    out = outbox.enqueue_digest(ctx, "r1")
    assert out["queued"] and out["status"] == "queued"
    return out["notification_id"]


def test_outbox_transient_then_retry(ctx):
    nid = _queued(ctx)
    res = outbox.process(ctx, transport=FakeTransport(["transient"]))
    row = ctx.con.execute("SELECT status, next_attempt_at, attempts FROM notification_outbox WHERE notification_id=?", (nid,)).fetchone()
    assert row["status"] == "failed_transient" and row["next_attempt_at"] and res["sent"] == 0
    assert ctx.con.execute("SELECT COUNT(*) FROM job_records").fetchone()[0] == 2  # coleta intacta


def test_outbox_ambiguous_is_unknown_and_not_resent(ctx):
    nid = _queued(ctx)
    t = FakeTransport(["ambiguous", "accepted"])
    outbox.process(ctx, transport=t)
    assert ctx.con.execute("SELECT status FROM notification_outbox WHERE notification_id=?", (nid,)).fetchone()[0] == "unknown"
    outbox.process(ctx, transport=t)
    assert t.sent == []  # não reenviou às cegas


def test_outbox_accepted_is_not_delivered(ctx):
    nid = _queued(ctx)
    outbox.process(ctx, transport=FakeTransport(["accepted"]))
    row = ctx.con.execute("SELECT status, smtp_accepted_at, delivery_confirmed_at FROM notification_outbox").fetchone()
    assert row["status"] == "accepted" and row["smtp_accepted_at"] and row["delivery_confirmed_at"] is None


def test_outbox_not_configured_returns_5(ctx):
    ctx.settings.notifications.update(enabled=True, recipient=None)
    assert outbox.process(ctx)["exit_code"] == 5
    ctx.settings.notifications.update(enabled=False)
    assert outbox.process(ctx)["exit_code"] == 5


def test_outbox_crash_while_sending_becomes_unknown(ctx):
    nid = _queued(ctx)
    ctx.con.execute("UPDATE notification_outbox SET status='sending' WHERE notification_id=?", (nid,))
    assert outbox.recover_stuck(ctx) == 1
    assert ctx.con.execute("SELECT status FROM notification_outbox").fetchone()[0] == "unknown"


def test_digest_dedupe_per_run(ctx):
    _queued(ctx)
    again = outbox.enqueue_digest(ctx, "r1")
    assert again["queued"] is False
    assert ctx.con.execute("SELECT COUNT(*) FROM notification_outbox").fetchone()[0] == 1


def test_dry_run_cycle_does_not_touch_real_db(ctx, data_dir):
    from jobos.context import open_context
    from jobos.pipeline import run_cycle
    from jobos.storage.db import sha256_file
    src = make_source()
    apply(ctx, batch(src, "r1", [obs("1")]), src)
    ctx.con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    before = sha256_file(ctx.paths.db)
    dry = open_context(dry_run=True)
    try:
        res = run_cycle(dry, trigger="test", fixtures=True)
        assert res.mode == "fixtures"
        assert dry.con.execute("SELECT COUNT(*) FROM job_records WHERE is_fixture=1").fetchone()[0] >= 1
    finally:
        dry.close()
    ctx.con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    assert sha256_file(ctx.paths.db) == before
    assert ctx.con.execute("SELECT COUNT(*) FROM notification_outbox").fetchone()[0] == 0
    assert not any(ctx.paths.outbox_preview.iterdir())


def test_tags_distinguish_auto_and_manual(ctx, legacy_db):
    from jobos.legacy import importer
    importer.apply_sqlite(ctx.con, ctx.settings, ctx.registry, legacy_db)
    tags = {a["tag"]["label"] for a in service.list_applications(ctx.con)}
    assert "Auto aplicado" in tags
    plan = service.confirm_legacy_manual_marks(ctx.con, apply=False, confirmed_on="2026-10-22")
    assert plan["count"] == 1
    service.confirm_legacy_manual_marks(ctx.con, apply=True, confirmed_on="2026-10-22")
    service.confirm_legacy_manual_marks(ctx.con, apply=True, confirmed_on="2026-10-22")  # idempotente
    apps = {a["tag"]["label"]: a for a in service.list_applications(ctx.con)}
    assert apps["Aplicado"]["tag"]["hint"].startswith("manual original")
    assert apps["Aplicado"]["submitted_at"] == "2026-08-24" and apps["Aplicado"]["provenance"] == "user_asserted"
    assert apps["Auto aplicado"]["tag"]["counts_as_applied"] is False
