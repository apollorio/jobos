"""Transporte de e-mail separado da renderização e da persistência.

Resultado classificado: accepted (aceito pelo servidor, NÃO entregue), transient, permanent, config, ambiguous.
Exception depois do início do DATA = ambíguo: não reenviar automaticamente (T34).
"""
from __future__ import annotations

import os
import smtplib
import socket
import ssl
from dataclasses import dataclass
from email.message import EmailMessage


@dataclass
class SendResult:
    outcome: str            # accepted | transient | permanent | config | ambiguous
    code: str | None = None
    detail: str | None = None
    provider_message_id: str | None = None


class SmtpTransport:
    def __init__(self, cfg: dict):
        self.cfg = cfg

    def configured(self) -> tuple[bool, str]:
        smtp = self.cfg.get("smtp") or {}
        if not self.cfg.get("recipient"):
            return False, "destinatário não configurado"
        if not smtp.get("host"):
            return False, "host SMTP não configurado"
        if not os.environ.get(smtp.get("username_env") or "") or not os.environ.get(smtp.get("password_env") or ""):
            return False, "credenciais SMTP ausentes no ambiente do processo"
        return True, "ok"

    def send(self, msg: EmailMessage) -> SendResult:
        ok, why = self.configured()
        if not ok:
            return SendResult("config", "not_configured", why)
        smtp = self.cfg["smtp"]
        user, pwd = os.environ[smtp["username_env"]], os.environ[smtp["password_env"]]
        phase = "connect"
        try:
            if smtp.get("tls", "ssl") == "ssl":
                server = smtplib.SMTP_SSL(smtp["host"], int(smtp.get("port", 465)), timeout=30,
                                          context=ssl.create_default_context())
            else:
                server = smtplib.SMTP(smtp["host"], int(smtp.get("port", 587)), timeout=30)
                server.starttls(context=ssl.create_default_context())
            with server:
                phase = "auth"
                server.login(user, pwd)
                phase = "data"
                refused = server.send_message(msg)
            if refused:
                return SendResult("permanent", "recipient_refused", str(refused)[:200])
            return SendResult("accepted", None, "aceito pelo servidor SMTP (não é confirmação de entrega)")
        except smtplib.SMTPAuthenticationError as e:
            return SendResult("config", "auth_failed", f"autenticação recusada ({e.smtp_code})")
        except smtplib.SMTPRecipientsRefused as e:
            return SendResult("permanent", "recipient_refused", str(e)[:200])
        except smtplib.SMTPResponseException as e:
            if phase == "data" and 400 <= e.smtp_code < 500:
                return SendResult("transient", f"smtp_{e.smtp_code}", str(e.smtp_error)[:200])
            if phase == "data":
                return SendResult("permanent", f"smtp_{e.smtp_code}", str(e.smtp_error)[:200])
            return SendResult("transient", f"smtp_{e.smtp_code}", str(e)[:200])
        except (smtplib.SMTPServerDisconnected, socket.timeout, TimeoutError, OSError) as e:
            if phase == "data":
                return SendResult("ambiguous", "disconnected_during_data", f"{type(e).__name__}: {e}"[:200])
            return SendResult("transient", "network", f"{type(e).__name__}: {e}"[:200])


class FakeTransport:
    """Transporte simulado para preview/testes. `script` define o resultado de cada envio."""

    def __init__(self, script: list[str] | None = None):
        self.script = list(script or ["accepted"])
        self.sent: list[EmailMessage] = []

    def configured(self) -> tuple[bool, str]:
        return True, "simulado"

    def send(self, msg: EmailMessage) -> SendResult:
        outcome = self.script.pop(0) if self.script else "accepted"
        if outcome == "accepted":
            self.sent.append(msg)
        return SendResult(outcome, None if outcome == "accepted" else f"simulated_{outcome}", "transporte simulado")
