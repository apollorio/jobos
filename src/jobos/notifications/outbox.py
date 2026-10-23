"""Outbox persistente: independente da coleta e do painel. Falha de envio não desfaz coleta nem candidatura."""
from __future__ import annotations

import datetime as dt
import json
from email.message import EmailMessage
from email.utils import formatdate
from pathlib import Path

from jobos.notifications.render import collect_digest, render_html, render_text, subject
from jobos.notifications.transport import FakeTransport, SmtpTransport
from jobos.storage import repo
from jobos.storage.db import tx
from jobos.timeutil import brt_date, iso, parse_instant, utcnow

EXIT_OK, EXIT_PARTIAL, EXIT_CONFIG = 0, 2, 5


def _message_id(notification_id: str) -> str:
    return f"<{notification_id}@jobos.local>"


def build_eml(row) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = row["subject"]
    msg["From"] = "JOBOS local <jobos@localhost>"
    msg["To"] = row["recipient_ref"] or "destinatario-nao-configurado@invalid"
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = row["message_id"]  # estável: reduz (não elimina) duplicidade em reenvio
    msg.set_content(row["body_text"])
    if row["body_html"]:
        msg.add_alternative(row["body_html"], subtype="html")
    return msg


def write_preview(row, out_root: Path) -> Path:
    d = out_root / row["notification_id"]
    d.mkdir(parents=True, exist_ok=True)
    (d / "message.txt").write_text(row["body_text"], encoding="utf-8")
    (d / "message.html").write_text(row["body_html"] or "", encoding="utf-8")
    (d / "message.eml").write_bytes(bytes(build_eml(row)))
    return d


def enqueue_digest(ctx, run_id: str) -> dict:
    cfg = ctx.settings.notifications
    policy = cfg.get("policy") or {}
    d = collect_digest(ctx.con, run_id, int(policy.get("max_items", 10)))
    failed_key = ",".join(sorted(f["source_id"] for f in d["failed"]))
    if not d["total_items"]:
        if not d["failed"] and not policy.get("send_when_nothing_new"):
            return {"queued": False, "reason": "nada novo e nenhuma falha"}
        # Só falhas: no máximo um aviso por dia por conjunto de fontes (sem repetir o dia todo)
        key = f"failures:{brt_date().isoformat()}:{failed_key}" if d["failed"] else f"daily:{brt_date().isoformat()}"
    else:
        key = f"digest:{run_id}"
    enabled = bool(cfg.get("enabled")) and bool(cfg.get("recipient"))
    nid = repo.new_id("ntf-")
    now = iso()
    with tx(ctx.con):
        cur = ctx.con.execute(
            """INSERT OR IGNORE INTO notification_outbox (notification_id, idempotency_key, channel, recipient_ref, subject,
                 payload_ref, body_text, body_html, message_id, run_id, created_at, attempts, next_attempt_at, status, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,0,?,?,?)""",
            (nid, key, cfg.get("channel", "email"), cfg.get("recipient"), subject(d), f"run:{run_id}", render_text(d),
             render_html(d), _message_id(nid), run_id, now, now if enabled else None,
             "queued" if enabled else "draft", now))
    if cur.rowcount == 0:
        return {"queued": False, "reason": f"já existe item com chave {key}"}
    row = ctx.con.execute("SELECT * FROM notification_outbox WHERE notification_id=?", (nid,)).fetchone()
    preview = write_preview(row, ctx.preview_dir)
    return {"queued": True, "notification_id": nid, "status": row["status"], "items": d["total_items"],
            "preview_dir": str(preview), "sending": "habilitado" if enabled else "desligado (preview apenas)"}


def preview(ctx, run_id: str | None = None) -> dict:
    sql = "SELECT * FROM notification_outbox " + ("WHERE run_id=? " if run_id else "") + "ORDER BY created_at DESC LIMIT 1"
    row = ctx.con.execute(sql, (run_id,) if run_id else ()).fetchone()
    if not row:
        return {"dir": None}
    return {"dir": str(write_preview(row, ctx.preview_dir)), "subject": row["subject"], "status": row["status"],
            "notification_id": row["notification_id"]}


def list_items(ctx) -> list[dict]:
    return [dict(r) for r in ctx.con.execute(
        """SELECT notification_id, idempotency_key, status, subject, attempts, next_attempt_at, last_error_code,
                  smtp_accepted_at, delivery_confirmed_at, created_at, run_id FROM notification_outbox
           ORDER BY created_at DESC LIMIT 100""")]


def recover_stuck(ctx) -> int:
    """Item em 'sending' de processo que caiu: resultado desconhecido, nunca some (T36) nem reenvia às cegas."""
    with tx(ctx.con):
        cur = ctx.con.execute("""UPDATE notification_outbox SET status='unknown', last_error_code='interrupted_while_sending',
                                 updated_at=? WHERE status='sending'""", (iso(),))
    return cur.rowcount


def process(ctx, *, simulate: bool = False, transport=None) -> dict:
    cfg = ctx.settings.notifications
    policy = cfg.get("policy") or {}
    backoff = [int(x) for x in policy.get("retry_backoff_minutes", [5, 30, 120])]
    max_attempts = int(policy.get("max_attempts", 4))
    recovered = recover_stuck(ctx)
    if transport is None:
        transport = FakeTransport() if simulate else SmtpTransport(cfg)
    if not simulate:
        if not cfg.get("enabled"):
            return {"exit_code": EXIT_CONFIG, "sent": 0, "reason": "envio desligado em notifications.yaml",
                    "recovered_unknown": recovered}
        ok, why = transport.configured()
        if not ok:
            return {"exit_code": EXIT_CONFIG, "sent": 0, "reason": why, "recovered_unknown": recovered}
    now = utcnow()
    statuses = ("queued", "failed_transient", "draft") if simulate else ("queued", "failed_transient")
    rows = [r for r in ctx.con.execute(
        f"SELECT * FROM notification_outbox WHERE status IN ({','.join('?' * len(statuses))}) ORDER BY created_at", statuses)
        if not r["next_attempt_at"] or (parse_instant(r["next_attempt_at"]) or now) <= now]
    results = []
    for r in rows:
        with tx(ctx.con):  # compare-and-set: outro processo não pega o mesmo item
            cur = ctx.con.execute("""UPDATE notification_outbox SET status='sending', attempts=attempts+1, updated_at=?
                                     WHERE notification_id=? AND status=?""", (iso(), r["notification_id"], r["status"]))
        if cur.rowcount == 0:
            continue
        res = transport.send(build_eml(r))
        attempts = r["attempts"] + 1
        if res.outcome == "accepted":
            new, extra = ("accepted", {"smtp_accepted_at": iso(), "provider_message_id": res.provider_message_id})
        elif res.outcome == "transient" and attempts < max_attempts:
            delay = backoff[min(attempts - 1, len(backoff) - 1)]
            new, extra = ("failed_transient", {"next_attempt_at": (now + dt.timedelta(minutes=delay)).isoformat()})
        elif res.outcome == "ambiguous":
            new, extra = ("unknown", {})
        elif res.outcome == "config":
            new, extra = ("failed_permanent", {})
        else:
            new, extra = ("failed_permanent", {})
        sets = ", ".join(f"{k}=?" for k in extra)
        with tx(ctx.con):
            ctx.con.execute(f"""UPDATE notification_outbox SET status=?, last_error_code=?, last_error=?, updated_at=?
                                {', ' + sets if sets else ''} WHERE notification_id=?""",
                            (new, res.code, res.detail, iso(), *extra.values(), r["notification_id"]))
        results.append({"notification_id": r["notification_id"], "outcome": res.outcome, "status": new})
    sent = sum(1 for x in results if x["status"] == "accepted")
    code = EXIT_OK if all(x["status"] == "accepted" for x in results) else EXIT_PARTIAL
    if any(x["outcome"] == "config" for x in results):
        code = EXIT_CONFIG
    return {"exit_code": code, "sent": sent, "results": results, "simulated": simulate, "recovered_unknown": recovered,
            "note": "accepted = aceito pelo servidor; entrega na caixa não é confirmada automaticamente"}
