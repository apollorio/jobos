"""Fila persistente de trabalho (work_items) com lease. O mesmo serviço do CLI executa o item."""
from __future__ import annotations

import datetime as dt
import json
import logging
import threading

from jobos.storage import repo
from jobos.storage.db import tx
from jobos.timeutil import iso, utcnow

log = logging.getLogger("jobos.worker")
KINDS = ("cycle", "collect_source", "analyze_job")


class WorkError(ValueError):
    pass


def enqueue(con, kind: str, target: str | None, origin: str, registry=None) -> dict:
    if kind not in KINDS:
        raise WorkError(f"tipo inválido: {kind}")
    if kind == "collect_source":
        if not registry or not target:
            raise WorkError("collect_source exige source_id")
        registry.get(target)  # só fontes cadastradas; nunca URL arbitrária
    if kind == "analyze_job":
        if not target or not con.execute("SELECT 1 FROM job_records WHERE job_id=?", (target,)).fetchone():
            raise WorkError("analyze_job exige job_id existente")
    if kind == "cycle":
        target = None
    dedupe = f"{kind}:{target or '*'}"
    with tx(con):
        open_item = con.execute("SELECT * FROM work_items WHERE dedupe_key=? AND status IN ('queued','leased')",
                                (dedupe,)).fetchone()
        if open_item:
            return {**dict(open_item), "deduplicated": True}
        item_id = repo.new_id("wi-")
        now = iso()
        con.execute("""INSERT INTO work_items (item_id, kind, target, status, dedupe_key, origin, created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?)""", (item_id, kind, target, "queued", dedupe, origin, now, now))
    return {**dict(con.execute("SELECT * FROM work_items WHERE item_id=?", (item_id,)).fetchone()), "deduplicated": False}


def _lease(con, owner: str, minutes: int) -> dict | None:
    now = utcnow()
    with tx(con):
        con.execute("""UPDATE work_items SET status='queued', lease_owner=NULL, lease_expires_at=NULL, updated_at=?
                       WHERE status='leased' AND lease_expires_at < ?""", (iso(), now.isoformat()))
        row = con.execute("SELECT * FROM work_items WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
        if not row:
            return None
        con.execute("""UPDATE work_items SET status='leased', lease_owner=?, lease_expires_at=?, attempts=attempts+1,
                       updated_at=? WHERE item_id=? AND status='queued'""",
                    (owner, (now + dt.timedelta(minutes=minutes)).isoformat(), iso(), row["item_id"]))
    return dict(row)


def process_queue_once(ctx, owner: str) -> dict:
    from jobos.matching.analyze import analyze_job
    from jobos.pipeline import EXIT_OVERLAP, run_cycle
    minutes = int((ctx.settings.app.get("cycle") or {}).get("lease_minutes", 60))
    item = _lease(ctx.con, owner, minutes)
    if not item:
        return {"processed": 0}
    try:
        if item["kind"] == "cycle":
            res = run_cycle(ctx, trigger="api")
            result, ok = {"run_id": res.run_id, "status": res.status, "exit_code": res.exit_code}, True
            if res.exit_code == EXIT_OVERLAP:
                ok = True  # outro ciclo já estava rodando: registro pulado, não é falha
        elif item["kind"] == "collect_source":
            res = run_cycle(ctx, trigger="api", only_sources=[item["target"]], notify=False)
            result, ok = {"run_id": res.run_id, "status": res.status, "exit_code": res.exit_code}, True
        else:
            result, ok = analyze_job(ctx, item["target"], force=True), True
        status, err = ("done" if ok else "failed"), None
    except Exception as e:  # noqa: BLE001
        log.exception("item %s falhou", item["item_id"])
        status, result, err = "failed", None, f"{type(e).__name__}: {e}"[:500]
    with tx(ctx.con):
        ctx.con.execute("""UPDATE work_items SET status=?, result_json=?, error=?, lease_owner=NULL, lease_expires_at=NULL,
                           updated_at=? WHERE item_id=?""",
                        (status, json.dumps(result, ensure_ascii=False, default=str) if result else None, err, iso(),
                         item["item_id"]))
    return {"processed": 1, "item_id": item["item_id"], "status": status, "result": result, "error": err,
            "exit_code": (result or {}).get("exit_code", 0) if isinstance(result, dict) else 0}


class Worker(threading.Thread):
    def __init__(self, ctx_factory, interval: float = 5.0):
        super().__init__(daemon=True, name="jobos-worker")
        self.ctx_factory = ctx_factory
        self.interval = interval
        self.stop_event = threading.Event()

    def run(self) -> None:
        ctx = self.ctx_factory()
        try:
            while not self.stop_event.is_set():
                try:
                    out = process_queue_once(ctx, owner=f"api-{self.ident}")
                except Exception:  # noqa: BLE001
                    log.exception("falha no worker")
                    out = {"processed": 0}
                if not out.get("processed"):
                    self.stop_event.wait(self.interval)
        finally:
            ctx.close()
