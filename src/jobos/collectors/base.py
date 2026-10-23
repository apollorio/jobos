"""Contrato de coleta. Coletor NÃO grava no banco, não envia e-mail, não pontua.

Cada adapter recebe `CollectContext` e devolve `SourceBatch`. HTML/texto de anúncio é dado
não confiável: só é guardado e exibido como texto.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Callable, Protocol

from jobos.settings import SourceConfig
from jobos.timeutil import iso

BATCH_STATUSES = ("complete", "partial", "failed", "blocked", "unconfigured", "skipped")


class FormatChanged(RuntimeError):
    """HTTP 200 com conteúdo inesperado (login, desafio, layout novo). Nunca vira 'zero vagas'."""
    code = "format_changed"


class Blocked(RuntimeError):
    """401/403/CAPTCHA. Não há troca de identidade nem tentativa infinita."""
    code = "blocked"


class SourceFailure(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class JobObservation:
    platform: str
    tenant: str
    external_id: str | None
    url: str | None
    title: str
    location: str | None = None
    workplace: str | None = None          # remote | hybrid | onsite | None (desconhecido)
    department: str | None = None
    salary: str | None = None
    deadline: str | None = None
    description: str = ""
    description_status: str = "missing"   # full | partial | missing | truncated
    original_length: int | None = None
    truncation_note: str | None = None
    published_raw: str | None = None
    published_source: str | None = None
    listing_signature: str | None = None  # campos da listagem, para decidir se vale abrir detalhe
    talent_pool: bool | None = None        # quando a plataforma informa (ex.: Gupy vacancy_type_talent_pool)
    raw: dict = field(default_factory=dict)

    def content_fields(self) -> dict:
        return {"title": self.title, "description": self.description, "location": self.location,
                "workplace": self.workplace, "salary": self.salary, "department": self.department,
                "deadline": self.deadline, "description_status": self.description_status,
                "original_length": self.original_length, "truncation_note": self.truncation_note}


@dataclass
class SourceBatch:
    run_id: str
    source_id: str
    adapter: str | None
    adapter_version: str | None
    status: str
    coverage_kind: str
    scope_id: str | None
    started_at: str = field(default_factory=iso)
    finished_at: str | None = None
    complete: bool = False
    is_baseline: bool = False
    can_infer_absence: bool = False
    pages_expected: int | None = None
    pages_received: int = 0
    raw_count: int = 0
    jobs: list[JobObservation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    details_fetched: int = 0
    schema_version: int = 1

    @property
    def normalized_count(self) -> int:
        return len(self.jobs)

    def finish(self) -> "SourceBatch":
        if self.status not in BATCH_STATUSES:
            raise ValueError(f"status inválido {self.status}")
        self.complete = self.status == "complete"
        if not self.complete:
            self.can_infer_absence = False
        self.finished_at = iso()
        return self

    def summary(self) -> dict:
        d = asdict(self)
        d["jobs"] = len(self.jobs)
        d["normalized_count"] = self.normalized_count
        return d


@dataclass
class CollectContext:
    run_id: str
    source: SourceConfig
    http: "HttpLike"
    offline: bool = False
    known: Callable[[str | None, str | None], dict | None] = lambda ext, url: None
    """known(external_id, url) → {'listing_signature', 'detail_fetched_at', 'has_description'} ou None."""


class HttpLike(Protocol):
    def get_text(self, url: str, *, headers: dict | None = None, params: dict | None = None) -> tuple[int, str]: ...
    def get_json(self, url: str, *, headers: dict | None = None, params: dict | None = None): ...
    def post_json(self, url: str, body: dict, *, headers: dict | None = None): ...


Adapter = Callable[[CollectContext], SourceBatch]


def scope_id(source: SourceConfig, extra: dict | None = None) -> str:
    """Identifica tenant/filtros/paginação. Mudou o filtro: muda o escopo e a ausência não é comparada (T15)."""
    payload = {"source_id": source.source_id, "platform": source.platform, "adapter": source.adapter,
               "params": source.params, "coverage": source.coverage, **(extra or {})}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def new_batch(ctx: CollectContext, adapter_version: str, extra_scope: dict | None = None) -> SourceBatch:
    s = ctx.source
    return SourceBatch(run_id=ctx.run_id, source_id=s.source_id, adapter=s.adapter, adapter_version=adapter_version,
                       status="failed", coverage_kind=s.coverage, scope_id=scope_id(s, extra_scope),
                       can_infer_absence=s.coverage in ("full_board", "filtered_board"))


def fail(batch: SourceBatch, code: str, message: str) -> SourceBatch:
    batch.status = "blocked" if code == "blocked" else "failed"
    batch.error_code = code
    batch.error_message = message[:500]
    batch.jobs = batch.jobs  # lote falho pode carregar o que já veio, mas nunca autoriza ausência
    return batch.finish()


def wants_detail(ctx: CollectContext, obs: JobObservation, ttl_days: int) -> bool:
    """Detalhe para novas/alteradas primeiro; demais só depois do TTL."""
    k = ctx.known(obs.external_id, obs.url)
    if not k:
        return True
    if not k.get("has_description"):
        return True
    if obs.listing_signature and k.get("listing_signature") and obs.listing_signature != k["listing_signature"]:
        return True
    fetched = k.get("detail_fetched_at")
    if not fetched:
        return True
    from jobos.timeutil import parse_instant, utcnow
    import datetime as dt
    t = parse_instant(fetched)
    return t is None or utcnow() - t > dt.timedelta(days=ttl_days)


def signature(*parts) -> str:
    return hashlib.sha256("\x1f".join(str(p or "") for p in parts).encode()).hexdigest()[:16]
