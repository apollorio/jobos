"""TOTVS "Atração de Talentos" (atracaodetalentos.totvs.app): listagem HTML com dados em atributos data-*.

Portado de Artifact/jobos/sources/totvs.py (list_tenant, normalize). Sem API pública: a listagem é HTML renderizado
no servidor, com `<div class="index__job-opportunities__grid__item" data-title=... data-page-url=...>` por vaga, e o
detalhe é outra página HTML.
Diferenças: zero itens só vale como "sem vagas" quando a página diz isso explicitamente (senão é format_changed,
porque uma página renderizada no cliente também chega sem itens); detalhe só dentro do orçamento e do TTL; texto do
detalhe sem script/style e sem colapsar parágrafos. Não portado: a pausa de 0,6 s entre detalhes (limite de ritmo
pertence ao cliente HTTP/execução, não ao adapter).
"""
from __future__ import annotations

import re

from jobos.collectors.base import (Blocked, CollectContext, FormatChanged, JobObservation, SourceBatch, SourceFailure,
                                   fail, new_batch, signature, wants_detail)
from jobos.collectors.text import bounded, clean, html_to_text
from jobos.domain.identity import totvs_number

VERSION = "totvs/1"
BASE = "https://atracaodetalentos.totvs.app"
ITEM_RE = re.compile(r'<div(?=[\s>])[^>]*class="(?:[^"]*\s)?index__job-opportunities__grid__item(?:\s[^"]*)?"[^>]*>', re.I)
NO_OPENINGS_RE = re.compile(
    r"nenhuma vaga|n[aã]o h[aá] vagas|n[aã]o possui vagas|sem vagas abertas|no open positions|no job openings|no vacancies", re.I)


def _attr(tag: str, name: str) -> str:
    m = re.search(rf'(?<![\w-]){re.escape(name)}="([^"]*)"', tag)
    return clean(m.group(1)) if m else ""


def parse_items(html: str) -> list[dict]:
    return [{"title": _attr(tag, "data-title"), "city": _attr(tag, "data-city-name"),
             "state": _attr(tag, "data-state-small-name"), "department": _attr(tag, "data-department-name"),
             "path": _attr(tag, "data-page-url"), "data_id": _attr(tag, "data-id")}
            for tag in ITEM_RE.findall(html or "")]


def collect(ctx: CollectContext) -> SourceBatch:
    tenant = ctx.source.params["tenant"]
    batch = new_batch(ctx, VERSION)
    batch.pages_expected = 1
    try:
        _, html = ctx.http.get_text(f"{BASE}/{tenant}/extended")
        items = parse_items(html)
        if not items and not NO_OPENINGS_RE.search(html_to_text(html)):
            raise FormatChanged("listagem TOTVS sem itens index__job-opportunities__grid__item e sem aviso de vagas zeradas")
    except (FormatChanged, Blocked, SourceFailure) as e:
        return fail(batch, getattr(e, "code", "error"), str(e))
    batch.pages_received = 1
    batch.raw_count = len(items)
    seen: set[str] = set()
    for it in items:
        if not it["path"] or not it["title"]:
            batch.warnings.append("item sem data-page-url ou data-title ignorado")
            continue
        ext = totvs_number(it["path"]) or it["data_id"] or None
        key = ext or it["path"]
        if key in seen:
            continue
        seen.add(key)
        url = it["path"] if it["path"].startswith("http") else f"{BASE}{it['path']}"
        location = ", ".join(p for p in (it["city"], it["state"]) if p) or None
        batch.jobs.append(JobObservation(
            platform="totvs", tenant=tenant, external_id=ext, url=url, title=it["title"], location=location,
            department=it["department"] or None,
            listing_signature=signature(it["title"], location, it["department"]),
            raw={"data_id": it["data_id"], "path": it["path"]}))
    if items and not batch.jobs:
        return fail(batch, "format_changed", "itens TOTVS encontrados, mas nenhum com data-page-url e data-title")
    _details(ctx, batch)
    batch.status = "complete"
    return batch.finish()


def _details(ctx: CollectContext, batch: SourceBatch) -> None:
    budget = int(ctx.source.limits.get("max_details", 25))
    ttl = int(ctx.source.limits.get("detail_ttl_days", 7))
    for obs in batch.jobs:
        if not wants_detail(ctx, obs, ttl):
            continue
        if budget <= 0:
            batch.warnings.append("limite de detalhes atingido; restantes serão detalhados nos próximos ciclos")
            break
        budget -= 1
        try:
            _, html = ctx.http.get_text(obs.url)
        except (FormatChanged, Blocked, SourceFailure) as e:
            batch.warnings.append(f"detalhe {obs.external_id}: {getattr(e, 'code', 'erro')}: {str(e)[:120]}")
            continue
        text, status, orig, note = bounded(html_to_text(html))
        obs.description, obs.description_status = text, status
        obs.original_length, obs.truncation_note = orig, note
        batch.details_fetched += 1
