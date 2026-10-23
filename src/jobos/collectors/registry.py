"""Adapter por nome. Import tardio: carregar o registro não abre rede nem lê disco."""
from __future__ import annotations

import importlib
import json
from pathlib import Path

from jobos.collectors.base import Adapter, CollectContext, JobObservation, SourceBatch, fail, new_batch

ADAPTERS: dict[str, tuple[str, str]] = {
    "gupy_tenant": ("jobos.collectors.gupy", "collect_tenant"),
    "gupy_portal_search": ("jobos.collectors.gupy", "collect_portal_queries"),
    "gupy_portal_company": ("jobos.collectors.gupy", "collect_portal_company"),
    "workday_cxs": ("jobos.collectors.workday", "collect"),
    "j2w_search": ("jobos.collectors.j2w", "collect"),
    "inhire": ("jobos.collectors.inhire", "collect"),
    "greenhouse": ("jobos.collectors.greenhouse", "collect"),
    "smartrecruiters": ("jobos.collectors.smartrecruiters", "collect"),
    "totvs": ("jobos.collectors.totvs", "collect"),
    "dof_webflow": ("jobos.collectors.dof", "collect"),
    "workable": ("jobos.collectors.workable", "collect"),
    "vagas_com_br": ("jobos.collectors.vagas_com_br", "collect"),
}


class UnknownAdapter(LookupError):
    pass


def get_adapter(name: str) -> Adapter:
    if name not in ADAPTERS:
        raise UnknownAdapter(name)
    mod, fn = ADAPTERS[name]
    return getattr(importlib.import_module(mod), fn)


def unconfigured(ctx: CollectContext, reason: str) -> SourceBatch:
    b = new_batch(ctx, "none")
    b.status = "unconfigured"
    b.error_code = "unconfigured"
    b.error_message = reason
    return b.finish()


def fixture_adapter(fixtures_dir: Path):
    """Modo --fixtures: lê tests/fixtures/sources/<source_id>.json. Offline e rotulado."""
    def collect(ctx: CollectContext) -> SourceBatch:
        f = fixtures_dir / f"{ctx.source.source_id}.json"
        batch = new_batch(ctx, "fixture/1")
        if not f.is_file():
            batch.status = "skipped"
            batch.error_message = "sem fixture para esta fonte"
            return batch.finish()
        data = json.loads(f.read_text(encoding="utf-8"))
        if data.get("fail"):
            return fail(batch, data["fail"].get("code", "format_changed"), data["fail"].get("message", "fixture"))
        for j in data.get("jobs", []):
            batch.jobs.append(JobObservation(**j))
        batch.raw_count = len(batch.jobs)
        batch.pages_expected = batch.pages_received = 1
        batch.status = data.get("status", "complete")
        return batch.finish()
    return collect
