"""Ciclo único: coleta → persistência → análise → fila de notificação. Resultado estruturado e código coerente.

Códigos: 0 concluído, 2 parcial, 3 falha impeditiva, 4 pulado por sobreposição, 5 configuração necessária.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import os
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from jobos.collectors.base import CollectContext, SourceBatch, new_batch
from jobos.collectors.http import HttpClient
from jobos.collectors.registry import fixture_adapter, get_adapter, unconfigured
from jobos.context import Context
from jobos.lock import CycleLock, LockBusy
from jobos.persistence import apply_batch
from jobos.settings import SourceConfig
from jobos.storage import repo
from jobos.storage.db import tx
from jobos.timeutil import iso

EXIT_OK, EXIT_PARTIAL, EXIT_FAILED, EXIT_OVERLAP, EXIT_CONFIG = 0, 2, 3, 4, 5

log = logging.getLogger("jobos")


@dataclass
class CycleResult:
    run_id: str
    status: str
    exit_code: int
    mode: str
    trigger: str
    sources: list[dict] = field(default_factory=list)
    stages: dict = field(default_factory=dict)
    counts: dict = field(default_factory=dict)
    error: str | None = None
    lock_owner: dict | None = None

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def _known_map(con, source_id: str):
    rows = con.execute("""SELECT p.external_id, p.url, p.listing_signature, p.detail_fetched_at, v.description_length
                          FROM source_postings p JOIN job_records j ON j.job_id=p.job_id
                          LEFT JOIN job_versions v ON v.version_id=j.current_version_id WHERE p.source_id=?""",
                       (source_id,)).fetchall()
    by_ext, by_url = {}, {}
    for r in rows:
        info = {"listing_signature": r["listing_signature"], "detail_fetched_at": r["detail_fetched_at"],
                "has_description": bool(r["description_length"])}
        if r["external_id"]:
            by_ext[r["external_id"]] = info
        if r["url"]:
            by_url[r["url"]] = info
    return lambda ext, url: by_ext.get(ext) if ext and ext in by_ext else by_url.get(url)


def collect_one(ctx: Context, source: SourceConfig, run_id: str, *, fixtures: bool, known) -> SourceBatch:
    limits = source.limits
    http = HttpClient(timeout=float(limits.get("timeout_seconds", 25)), max_attempts=int(limits.get("max_attempts", 3)))
    cctx = CollectContext(run_id=run_id, source=source, http=http, offline=fixtures, known=known)
    if not source.adapter:
        return unconfigured(cctx, source.note or "fonte sem leitor configurado")
    try:
        adapter = fixture_adapter(ctx.paths.fixtures / "sources") if fixtures else get_adapter(source.adapter)
        return adapter(cctx)
    except Exception as e:  # noqa: BLE001  adapter com bug não derruba o ciclo; vira falha visível da fonte
        b = new_batch(cctx, "error")
        b.status, b.error_code = "failed", "adapter_exception"
        b.error_message = f"{type(e).__name__}: {str(e)[:300]}"
        log.error("adapter %s falhou: %s", source.source_id, traceback.format_exc(limit=3))
        return b.finish()


RETRYABLE_CODES = {"network", "adapter_exception", "http_429", "http_500", "http_502", "http_503", "http_504", "http_408",
                   "blocked", "format_changed", "not_found"}


def _variants(source: SourceConfig) -> list[SourceConfig]:
    """Estratégia principal + alternativas declaradas em `fallback_adapters` ("próxima URL lógica")."""
    out = [source]
    for fb in source.fallback_adapters or ():
        if isinstance(fb, str):
            out.append(dataclasses.replace(source, adapter=fb))
        elif isinstance(fb, dict) and fb.get("adapter"):
            out.append(dataclasses.replace(source, adapter=fb["adapter"], params={**source.params, **(fb.get("params") or {})},
                                           coverage=fb.get("coverage", source.coverage)))
    return out


def _rank(b: SourceBatch) -> tuple:
    order = {"complete": 3, "partial": 2, "blocked": 1, "failed": 0}
    return (order.get(b.status, -1), b.normalized_count)


def collect_chain(ctx: Context, source: SourceConfig, run_id: str, *, fixtures: bool, known) -> SourceBatch:
    """Tenta a estratégia principal e, se não vier completa, as alternativas em ordem. Fica com a melhor leitura;
    cada tentativa fica registrada nos avisos (procedência da estratégia usada)."""
    variants = [source] if fixtures or not source.adapter else _variants(source)
    attempts, best = [], None
    for v in variants:
        b = collect_one(ctx, v, run_id, fixtures=fixtures, known=known)
        attempts.append(f"{v.adapter}: {b.status} ({b.normalized_count} vagas{', ' + b.error_code if b.error_code else ''})")
        if best is None or _rank(b) > _rank(best):
            best = b
        if b.status in ("complete", "unconfigured", "skipped"):
            break
    if len(attempts) > 1:
        best.warnings.insert(0, "estratégias tentadas: " + " | ".join(attempts))
    return best


def _needs_final_retry(b: SourceBatch) -> bool:
    return b.status in ("failed", "blocked") or (b.status == "partial" and (b.error_code or "") in RETRYABLE_CODES)


def run_cycle(ctx: Context, *, trigger: str, fixtures: bool = False, only_sources: list[str] | None = None,
              analyze: bool = True, notify: bool = True) -> CycleResult:
    mode = "fixtures" if fixtures else ("dry_run" if ctx.dry_run else "normal")
    run_id = f"run-{iso()[:19].replace(':', '').replace('-', '')}-{uuid.uuid4().hex[:6]}"
    lock = CycleLock(ctx.paths.lock_file)
    if not ctx.dry_run:
        try:
            lock.acquire({"run_id": run_id, "trigger": trigger})
        except LockBusy as busy:
            with tx(ctx.con):
                ctx.con.execute("""INSERT INTO runs (run_id, trigger, mode, started_at, finished_at, status, exit_code, error, pid)
                                   VALUES (?,?,?,?,?,?,?,?,?)""",
                                (run_id, trigger, mode, iso(), iso(), "skipped_overlap", EXIT_OVERLAP,
                                 f"ciclo ativo: {busy.owner.get('run_id')}", os.getpid()))
            return CycleResult(run_id, "skipped_overlap", EXIT_OVERLAP, mode, trigger, lock_owner=busy.owner)
    try:
        return _run_locked(ctx, run_id, mode, trigger, fixtures, only_sources, analyze, notify)
    finally:
        lock.release()


def _run_locked(ctx, run_id, mode, trigger, fixtures, only_sources, analyze, notify) -> CycleResult:
    con = ctx.con
    if not ctx.dry_run:
        recover_stale_runs(ctx, owner_alive=False)  # temos a trava: qualquer 'running' é órfão
    with tx(con):
        con.execute("INSERT INTO runs (run_id, trigger, mode, started_at, stage, status, pid) VALUES (?,?,?,?,?,?,?)",
                    (run_id, trigger, mode, iso(), "collect", "running", os.getpid()))
    result = CycleResult(run_id, "running", EXIT_OK, mode, trigger)
    sources = list(ctx.registry.sources)
    if only_sources:
        sources = [s for s in sources if s.source_id in only_sources]
    else:
        sources = [s for s in sources if s.enabled]
    try:
        knowns = {s.source_id: _known_map(con, s.source_id) for s in sources}
        workers = int((ctx.settings.app.get("cycle") or {}).get("max_parallel_sources", 4))
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = [(s, pool.submit(collect_chain, ctx, s, run_id, fixtures=fixtures, known=knowns[s.source_id]))
                       for s in sources]
            batches = [(s, f.result()) for s, f in futures]
        # Última chance: fontes que falharam ganham UMA nova rodada após 30 s; se falhar de novo, desiste (sem loop).
        retry_idx = [i for i, (s, b) in enumerate(batches) if _needs_final_retry(b)]
        if retry_idx and not fixtures:
            delay = float((ctx.settings.app.get("cycle") or {}).get("final_retry_delay_seconds", 30))
            result.stages["final_retry"] = {"sources": [batches[i][0].source_id for i in retry_idx], "delay_s": delay}
            time.sleep(delay)
            with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
                again = {i: pool.submit(collect_chain, ctx, batches[i][0], run_id, fixtures=False,
                                        known=knowns[batches[i][0].source_id]) for i in retry_idx}
                for i, fut in again.items():
                    s, first = batches[i]
                    second = fut.result()
                    better = second if _rank(second) > _rank(first) else first
                    better.warnings.insert(0, f"retentativa final após {delay:.0f}s: {first.status} → {second.status}")
                    batches[i] = (s, better)
        totals = {"new": 0, "changed": 0, "missing": 0, "closed": 0, "reappeared": 0}
        for s, batch in batches:
            outcome = apply_batch(con, batch, s, ctx.settings, is_fixture=fixtures)
            for k in totals:
                totals[k] += outcome.get(k, 0)
            _save_raw(ctx, run_id, batch)
            result.sources.append({"source_id": s.source_id, "status": batch.status, "jobs": batch.normalized_count,
                                   "new": outcome["new"], "changed": outcome["changed"], "missing": outcome["missing"],
                                   "closed": outcome["closed"], "baseline": outcome["baseline"],
                                   "absence": "aplicada" if outcome["absence_applied"] else outcome["absence_note"],
                                   "error": batch.error_message, "warnings": len(batch.warnings),
                                   "details": batch.details_fetched})
        result.counts = totals
        result.stages["collect"] = "complete"
        if not fixtures:
            result.stages["probe"] = _probe_stage(ctx, [(s, b) for s, b in batches], run_id)
    except Exception as e:  # noqa: BLE001
        result.stages["collect"] = f"failed: {type(e).__name__}: {e}"
        return _finish(ctx, result, "failed", EXIT_FAILED, str(e))

    if analyze:
        _stage(ctx, result, "analyze", lambda: __import__("jobos.matching.analyze", fromlist=["x"]).analyze_pending(ctx))
    if not ctx.dry_run and not fixtures and (ctx.settings.app.get("exports") or {}).get("portal_files"):
        _stage(ctx, result, "export", lambda: __import__("jobos.exports.portal", fromlist=["x"]).write_workspace_files(ctx))
    if notify:
        _stage(ctx, result, "notify", lambda: __import__("jobos.notifications.outbox", fromlist=["x"]).enqueue_digest(ctx, run_id))

    runnable = [s for s in result.sources if s["status"] != "unconfigured"]
    bad = [s for s in runnable if s["status"] not in ("complete", "skipped")]
    stage_fail = any(str(v).startswith("failed") for v in result.stages.values())
    if runnable and len(bad) == len(runnable):
        return _finish(ctx, result, "failed", EXIT_FAILED, "nenhuma fonte concluiu a leitura")
    if bad or stage_fail:
        return _finish(ctx, result, "partial", EXIT_PARTIAL, None)
    return _finish(ctx, result, "complete", EXIT_OK, None)


def _probe_stage(ctx: Context, batches, run_id: str) -> dict:
    """Confirma individualmente anúncios antigos que a listagem atual não cobre (fora do escopo ou importados).
    Rede fora de transação; cada resultado grava em transação curta. Limite por fonte e por ciclo."""
    import importlib
    from jobos.collectors.registry import ADAPTERS
    from jobos.persistence import apply_probe, probe_candidates
    cfg = ctx.settings.app.get("cycle") or {}
    per_source, total_cap = int(cfg.get("probe_per_source", 15)), int(cfg.get("probe_per_cycle", 120))
    out = {"probed": 0, "gone": 0, "alive": 0, "unknown": 0, "closed": 0}
    for source, batch in batches:
        if out["probed"] >= total_cap or not source.adapter or source.adapter not in ADAPTERS:
            continue
        if batch.status not in ("complete", "partial"):
            continue  # fonte fora do ar: não confunde falha de rede com vaga encerrada
        fn = getattr(importlib.import_module(ADAPTERS[source.adapter][0]), "probe", None)
        if fn is None:
            continue
        http = HttpClient(timeout=float(source.limits.get("timeout_seconds", 25)), max_attempts=1)
        cctx = CollectContext(run_id=run_id, source=source, http=http)
        for p in probe_candidates(ctx.con, source.source_id, run_id, min(per_source, total_cap - out["probed"])):
            try:
                res = fn(cctx, p["external_id"], p["url"])
            except Exception as e:  # noqa: BLE001  probe nunca derruba o ciclo
                log.warning("probe %s %s: %s", source.source_id, p["external_id"], e)
                res = "unknown"
            res = res if res in ("alive", "gone") else "unknown"
            state = apply_probe(ctx.con, p, res, run_id)
            out["probed"] += 1
            out[res] += 1
            out["closed"] += int(state == "closed_confirmed")
    return out


def _stage(ctx, result: CycleResult, name: str, fn) -> None:
    with tx(ctx.con):
        ctx.con.execute("UPDATE runs SET stage=? WHERE run_id=?", (name, result.run_id))
    try:
        out = fn()
        result.stages[name] = out if out is not None else "complete"
    except Exception as e:  # noqa: BLE001  falha de etapa não desfaz coleta (T39)
        log.error("etapa %s falhou: %s", name, traceback.format_exc(limit=5))
        result.stages[name] = f"failed: {type(e).__name__}: {str(e)[:200]}"


def _finish(ctx, result: CycleResult, status: str, code: int, error: str | None) -> CycleResult:
    result.status, result.exit_code, result.error = status, code, error
    with tx(ctx.con):
        ctx.con.execute("""UPDATE runs SET finished_at=?, stage='done', status=?, exit_code=?, counts_json=?, error=?
                           WHERE run_id=?""",
                        (iso(), status, code, repo.dumps({"counts": result.counts, "stages": result.stages,
                                                          "sources": result.sources}), error, result.run_id))
    return result


def _save_raw(ctx: Context, run_id: str, batch: SourceBatch) -> None:
    try:
        d = ctx.raw_dir / run_id
        d.mkdir(parents=True, exist_ok=True)
        payload = batch.summary()
        payload["observations"] = [{"external_id": o.external_id, "url": o.url, "title": o.title, "location": o.location,
                                    "description_status": o.description_status, "description_length": len(o.description),
                                    "published_raw": o.published_raw, "raw": o.raw} for o in batch.jobs]
        (d / f"{batch.source_id}.json").write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")
    except OSError as e:
        log.warning("raw não salvo para %s: %s", batch.source_id, e)


def recover_stale_runs(ctx: Context, owner_alive: bool) -> int:
    """Run 'running' sem trava ativa = processo morreu. Marca como interrompida (sem efeitos de ausência)."""
    if owner_alive:
        return 0
    with tx(ctx.con):
        cur = ctx.con.execute("""UPDATE runs SET status='interrupted', finished_at=?, exit_code=?, error=
                                 'processo encerrado antes do fim; fontes não aplicadas ficam sem efeito de ausência'
                                 WHERE status='running'""", (iso(), EXIT_FAILED))
    return cur.rowcount
