"""Cadeia de estratégias ("próxima URL lógica") e retentativa final única após atraso configurado."""
import dataclasses

from conftest import make_source, obs

from jobos import pipeline
from jobos.collectors.base import fail, new_batch
from jobos.settings import Registry


def _adapter(status, n=0, code=None):
    def collect(ctx):
        b = new_batch(ctx, "fake/1")
        if status in ("failed", "blocked"):
            return fail(b, code or "network", "simulado")
        b.jobs = [obs(f"{ctx.source.adapter}-{i}") for i in range(n)]
        b.status = status
        return b.finish()
    return collect


def _run(ctx, monkeypatch, src, plan, delay_calls):
    calls = {}

    def get_adapter(name):
        calls[name] = calls.get(name, 0) + 1
        seq = plan[name]
        return seq[min(calls[name] - 1, len(seq) - 1)]
    monkeypatch.setattr(pipeline, "get_adapter", get_adapter)
    monkeypatch.setattr(pipeline.time, "sleep", lambda s: delay_calls.append(s))
    ctx.registry = Registry((src,), "test", "test")
    return pipeline.run_cycle(ctx, trigger="test", analyze=False, notify=False), calls


def test_fallback_used_when_primary_fails(ctx, monkeypatch):
    src = dataclasses.replace(make_source(), adapter="primary", fallback_adapters=("secondary",))
    delays = []
    res, calls = _run(ctx, monkeypatch, src, {"primary": [_adapter("failed")], "secondary": [_adapter("complete", 3)]}, delays)
    assert res.sources[0]["status"] == "complete" and res.sources[0]["jobs"] == 3
    assert calls == {"primary": 1, "secondary": 1} and delays == []


def test_single_final_retry_after_delay_then_gives_up(ctx, monkeypatch):
    src = dataclasses.replace(make_source(), adapter="primary")
    delays = []
    res, calls = _run(ctx, monkeypatch, src, {"primary": [_adapter("failed"), _adapter("failed")]}, delays)
    assert delays == [30.0] and calls == {"primary": 2}   # uma retentativa, depois desiste
    assert res.sources[0]["status"] == "failed"


def test_final_retry_can_recover(ctx, monkeypatch):
    src = dataclasses.replace(make_source(), adapter="primary")
    delays = []
    res, _ = _run(ctx, monkeypatch, src, {"primary": [_adapter("failed"), _adapter("complete", 2)]}, delays)
    assert res.sources[0]["status"] == "complete" and res.sources[0]["jobs"] == 2
