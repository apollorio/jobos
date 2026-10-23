"""Datas: instantes em UTC, exibição em America/Sao_Paulo, precisão explícita."""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from zoneinfo import ZoneInfo

BRT = ZoneInfo("America/Sao_Paulo")

PRECISIONS = ("timestamp", "date_only", "relative_estimate", "unknown")


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso(ts: dt.datetime | None = None) -> str:
    return (ts or utcnow()).astimezone(dt.timezone.utc).isoformat(timespec="seconds")


def parse_instant(value: str | None) -> dt.datetime | None:
    """Lê um instante ISO com fuso. Sem fuso ou só data: None (não inventa hora)."""
    if not value:
        return None
    v = value.strip().replace("Z", "+00:00")
    if not re.match(r"^\d{4}-\d{2}-\d{2}T", v):
        return None
    try:
        d = dt.datetime.fromisoformat(v)
    except ValueError:
        return None
    if d.tzinfo is None:
        return None
    return d.astimezone(dt.timezone.utc)


def brt_date(ts: dt.datetime | None = None) -> dt.date:
    """Dia de Brasília (não usa date.today(), que depende do fuso do processo)."""
    return (ts or utcnow()).astimezone(BRT).date()


def fmt_brt(value: str | None, precision: str | None = "timestamp") -> str:
    if not value:
        return "desconhecida"
    if precision == "date_only" or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value or ""):
        try:
            return dt.date.fromisoformat(value[:10]).strftime("%d/%m/%Y")
        except ValueError:
            return value
    d = parse_instant(value)
    if not d:
        return value
    return d.astimezone(BRT).strftime("%d/%m/%Y %H:%M")


@dataclass(frozen=True)
class PublishedDate:
    value: str | None          # ISO instante (UTC) ou AAAA-MM-DD; None se desconhecida
    precision: str             # timestamp | date_only | relative_estimate | unknown
    source: str                # de onde veio
    raw: str | None            # texto original

    def as_dict(self) -> dict:
        return {"published_at": self.value, "published_date_precision": self.precision,
                "published_date_source": self.source, "published_raw": self.raw}


_RELATIVE = re.compile(r"(posted|publicad[oa])\s+(today|yesterday|hoje|ontem|\d+\+?\s+(days?|dias)\s+(ago|atr[aá]s))",
                       re.I)


def parse_published(raw: str | None, source: str) -> PublishedDate:
    """Interpreta data de publicação SEM inventar.

    - ISO com fuso → timestamp; AAAA-MM-DD → date_only.
    - `~AAAA-MM-DD` (detecção legada) → não é publicação: unknown, raw preservado.
    - Texto relativo ("Posted 3 Days Ago") → relative_estimate, sem valor calculado.
    - Vazio/N/A/outro → unknown.
    """
    text = (raw or "").strip()
    if not text or text.upper() in {"N/A", "NA", "-"}:
        return PublishedDate(None, "unknown", source, raw or None)
    if text.startswith("~"):
        return PublishedDate(None, "unknown", f"{source}:legacy_detection_estimate", text)
    inst = parse_instant(text)
    if inst:
        return PublishedDate(iso(inst), "timestamp", source, text)
    m = re.match(r"^(\d{4}-\d{2}-\d{2})(?:$|T00:00:00(?:\.0+)?$)", text)
    if m:
        try:
            dt.date.fromisoformat(m.group(1))
            return PublishedDate(m.group(1), "date_only", source, text)
        except ValueError:
            pass
    if _RELATIVE.search(text):
        return PublishedDate(None, "relative_estimate", source, text)
    return PublishedDate(None, "unknown", source, text)
