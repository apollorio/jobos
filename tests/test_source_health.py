"""P1-R: matriz de saúde das fontes (GET /api/sources). Leitura pura; falha/parcial nunca fecha vaga."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jobos.api.app import create_app
from jobos.status import HEALTH_ORDER, derive_health, health_summary, source_health

PORT = 8798
H = {"host": f"127.0.0.1:{PORT}"}
M = {**H, "x-jobos": "1", "origin": f"http://127.0.0.1:{PORT}"}
PAINEL_JS = Path(__file__).resolve().parents[1] / "web" / "painel" / "painel.js"


def read_row(status="complete", *, n=3, complete=None, scope="abc123", coverage="full_board", expected=1, received=1):
    """Linha mínima de leitura para derive_health (mesmas chaves do SELECT de source_health)."""
    return {"status": status, "complete": int(status == "complete") if complete is None else complete,
            "coverage_kind": coverage, "scope_id": scope, "pages_expected": expected, "pages_received": received,
            "raw_count": n, "normalized_count": n, "can_infer_absence": 1, "finished_at": None, "started_at": None}


# ------------------------------------------------------------------ derivação pura

def level(reads, **kw):
    kw.setdefault("configured", True)
    kw.setdefault("has_reader", True)
    return derive_health(reads=reads, **kw)


def test_complete_with_jobs_is_ok():
    h = level([read_row(n=5)])
    assert h["health"] == "ok" and h["health_label"] == "ok" and h["failure_streak"] == 0
    assert h["scope_evidence"]["ok"] is True


def test_zero_jobs_ok_only_with_scope_evidence():
    ok = level([read_row(n=0)])
    assert ok["health"] == "ok" and ok["scope_evidence"]["ok"] is True
    for bad in (read_row(n=0, scope=None), read_row(n=0, coverage=None), read_row(n=0, received=0),
                read_row(n=0, expected=3, received=1)):
        h = level([bad])
        assert h["health"] == "attention", bad
        assert h["scope_evidence"]["ok"] is False


def test_partial_is_attention_not_ok():
    h = level([read_row("partial", n=7, complete=0)])
    assert h["health"] == "attention" and h["health_label"] == "atenção"


@pytest.mark.parametrize("status", ["failed", "blocked"])
def test_failure_and_streak(status):
    reads = [read_row(status, n=0, complete=0), read_row("failed", n=0, complete=0), read_row("blocked", n=0, complete=0),
             read_row("complete"), read_row("failed", n=0, complete=0)]
    h = level(reads)
    assert h["health"] == "failure" and h["failure_streak"] == 3  # a leitura completa interrompe a sequência
    assert level([read_row(status, n=0, complete=0)])["failure_streak"] == 1


def test_recovery_after_failures_resets_streak():
    h = level([read_row("complete"), read_row("failed", n=0, complete=0), read_row("failed", n=0, complete=0)])
    assert h["health"] == "ok" and h["failure_streak"] == 0


def test_unconfigured_and_never_run():
    assert level([], configured=False, has_reader=False)["health"] == "no_reader"
    disabled = level([], configured=False, has_reader=True)
    assert disabled["health"] == "no_reader" and "desativada" in disabled["health_reason"]
    nr = level([])
    assert nr["health"] == "never_run" and nr["health_label"] == "nunca rodou" and nr["scope_evidence"] is None


def test_summary_has_every_level_and_total():
    items = [{"health": "ok"}, {"health": "failure"}, {"health": "ok"}]
    s = health_summary(items)
    assert set(s["counts"]) == set(HEALTH_ORDER) and s["counts"]["ok"] == 2 and s["total"] == 3
    assert HEALTH_ORDER[0] == "failure"  # falhas primeiro
    assert "nunca encerra vagas" in s["note"]


# ------------------------------------------------------------------ API com banco temporário

def put_run(con, source_id, run_id, status, *, n=0, error=None, code=None, at="2026-10-24T10:00:00+00:00", scope="s1",
            coverage="full_board", expected=1, received=1, warnings="[]"):
    con.execute("INSERT OR IGNORE INTO runs (run_id, trigger, mode, started_at, status) VALUES (?,?,?,?,?)",
                (run_id, "test", "normal", at, "complete"))
    con.execute("""INSERT INTO source_runs (run_id, source_id, adapter, adapter_version, status, complete, coverage_kind, scope_id,
                   can_infer_absence, pages_expected, pages_received, raw_count, normalized_count, error_code, error_message,
                   warnings_json, started_at, finished_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (run_id, source_id, "test", "t/1", status, int(status == "complete"), coverage, scope, 1, expected, received,
                 n, n, code, error, warnings, at, at))
    con.commit()


@pytest.fixture()
def client(ctx):
    app = create_app(port=PORT, worker=False, paths=ctx.paths)
    with TestClient(app, base_url=f"http://127.0.0.1:{PORT}") as c:
        yield c


def sources_of(ctx):
    runnable = [s.source_id for s in ctx.registry.sources if s.adapter and s.enabled]
    no_reader = next(s.source_id for s in ctx.registry.sources if not s.adapter)
    return runnable, no_reader


def by_id(client):
    return {s["source_id"]: s for s in client.get("/api/sources", headers=H).json()["sources"]}


def test_api_returns_health_fields_for_every_configured_source(client, ctx):
    r = client.get("/api/sources", headers=H)
    assert r.status_code == 200
    body = r.json()
    assert len(body["sources"]) == len(ctx.registry.sources)
    need = {"source_id", "company_name", "platform", "adapter", "configured", "last_status", "last_run_at", "last_success_at",
            "last_success_count", "failure_streak", "scope_evidence", "last_error_short", "health", "health_label",
            "health_reason"}
    for s in body["sources"]:
        assert need <= set(s), need - set(s)
        assert s["health"] in HEALTH_ORDER
    assert body["health_summary"]["total"] == len(body["sources"])
    assert sum(body["health_summary"]["counts"].values()) == len(body["sources"])


def test_api_health_derivation_end_to_end(client, ctx):
    runnable, no_reader = sources_of(ctx)
    ok_id, zero_id, partial_id, fail_id, never_id = runnable[:5]
    put_run(ctx.con, ok_id, "r1", "complete", n=4, at="2026-10-24T09:00:00+00:00")
    put_run(ctx.con, zero_id, "r1", "complete", n=0, at="2026-10-24T09:00:00+00:00")
    put_run(ctx.con, partial_id, "r1", "partial", n=2, at="2026-10-24T09:00:00+00:00", error="página 2 falhou",
            code="http_500", expected=3, received=1)
    put_run(ctx.con, fail_id, "r0", "complete", n=9, at="2026-10-23T09:00:00+00:00")
    for i, hh in enumerate(("10", "14", "18")):
        put_run(ctx.con, fail_id, f"rf{i}", "failed", error="HTTP 422 <b>x</b>\n" + "y" * 400, code="http_422",
                at=f"2026-10-24T{hh}:00:00+00:00", scope=None, received=0, expected=None)
    # leitura sem leitor registrada como 'unconfigured' não conta como leitura
    put_run(ctx.con, never_id, "ru", "unconfigured", error="fonte sem leitor configurado", code="unconfigured",
            at="2026-10-24T09:00:00+00:00", received=0)
    s = by_id(client)

    assert s[ok_id]["health"] == "ok" and s[ok_id]["last_success_count"] == 4
    assert s[ok_id]["last_run_at"] == "2026-10-24T09:00:00+00:00" and s[ok_id]["scope_evidence"]["ok"] is True
    assert s[zero_id]["health"] == "ok" and s[zero_id]["last_success_count"] == 0
    assert s[partial_id]["health"] == "attention" and s[partial_id]["scope_evidence"]["ok"] is False
    f = s[fail_id]
    assert f["health"] == "failure" and f["failure_streak"] == 3 and f["last_success_count"] == 9
    assert f["last_success_at"] == "2026-10-23T09:00:00+00:00"
    assert len(f["last_error_short"]) <= 160 and "\n" not in f["last_error_short"]
    assert "<b>x</b>" in f["last_error_short"]  # texto cru: o painel escapa (textContent)
    assert s[never_id]["health"] == "never_run" and s[never_id]["failure_streak"] == 0
    assert s[no_reader]["health"] == "no_reader" and s[no_reader]["configured"] is False
    disabled = [x for x in ctx.registry.sources if x.adapter and not x.enabled]
    for d in disabled:
        assert s[d.source_id]["health"] == "no_reader" and "desativada" in s[d.source_id]["health_reason"]


def test_zero_jobs_without_scope_evidence_is_attention_via_api(client, ctx):
    runnable, _ = sources_of(ctx)
    put_run(ctx.con, runnable[0], "rz", "complete", n=0, scope=None, received=0)
    s = by_id(client)[runnable[0]]
    assert s["health"] == "attention" and "escopo" in s["health_reason"]


def snapshot(con):
    return {t: con.execute(f"SELECT * FROM {t}").fetchall()
            for t in ("runs", "source_runs", "job_records", "job_events", "work_items", "source_postings")}


def test_health_call_does_not_write(client, ctx):
    runnable, _ = sources_of(ctx)
    put_run(ctx.con, runnable[0], "rw", "failed", error="boom", code="http_500", scope=None, received=0)
    before = snapshot(ctx.con)
    for _ in range(2):
        assert client.get("/api/sources", headers=H).status_code == 200
    source_health(ctx.con, ctx.registry)
    assert snapshot(ctx.con) == before


def test_route_is_get_only_and_loopback_only(client):
    assert client.get("/api/sources", headers={"host": "evil.example:80"}).status_code == 400
    assert client.get("/api/sources", headers={"host": "192.168.0.10:%d" % PORT}).status_code == 400
    assert client.post("/api/sources", headers=M).status_code == 405
    assert client.delete("/api/sources", headers=M).status_code == 405


# ------------------------------------------------------------------ painel: escape e sintaxe estática

def test_panel_renders_source_text_without_innerhtml():
    js = PAINEL_JS.read_text(encoding="utf-8")
    start, end = js.index("let fontesFilter"), js.index("function renderFontes")
    section = js[start:end]
    assert "innerHTML" not in section and "insertAdjacentHTML" not in section
    assert "Falha não encerra vagas" in section
    for needed in ("failure", "attention", "never_run", "no_reader", "ok"):
        assert needed in section
