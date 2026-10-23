"""DOF (Webflow CMS): vagas em atributos data-* da página /vacancies + detalhe em blocos rich-text.

Portado de Artifact/jobos/sources/web.py (webflow_dof, detalhe_dof). Não é Workable: é Webflow, com os dados no HTML.
Diferenças: o marcador `data-job-name` é obrigatório (sem ele a página é format_changed, mesmo que pareça uma página
de vagas zerada, porque um layout novo não pode virar "zero vagas"); os atributos são lidos por tag, sem depender
da ordem; a descrição não é cortada em 6000 caracteres; paginação do Webflow detectada deixa o lote parcial.
"""
from __future__ import annotations

import re

from jobos.collectors.base import (Blocked, CollectContext, FormatChanged, JobObservation, SourceBatch, SourceFailure,
                                   fail, new_batch, signature, wants_detail)
from jobos.collectors.text import bounded, clean, html_to_text

VERSION = "dof_webflow/1"
LIST_URL = "https://www.dof.com/vacancies"
DETAIL_URL = "https://www.dof.com/vacancies/{slug}"

JOB_TAG_RE = re.compile(r'<[^>]*\bdata-job-name="[^"]*"[^>]*>', re.I)
RICH_RE = re.compile(r'class="[^"]*\brich-text(?:_req)?\b[^"]*\bw-richtext\b[^"]*"[^>]*>([\s\S]*?)</div>', re.I)
NEXT_PAGE_RE = re.compile(r'class="[^"]*\bw-pagination-next\b', re.I)


def _attr(tag: str, name: str) -> str:
    m = re.search(rf'(?<![\w-]){re.escape(name)}="([^"]*)"', tag)
    return clean(m.group(1)) if m else ""


def parse_jobs(html: str) -> list[dict]:
    if "data-job-name" not in (html or ""):
        raise FormatChanged("marcador data-job-name ausente na página de vagas da DOF (login/desafio/layout novo)")
    out = []
    for tag in JOB_TAG_RE.findall(html):
        out.append({"slug": _attr(tag, "data-slug"), "title": _attr(tag, "data-job-name"),
                    "city": _attr(tag, "data-job-city"), "country": _attr(tag, "data-job-country"),
                    "department": _attr(tag, "data-job-department")})
    return out


def collect(ctx: CollectContext) -> SourceBatch:
    batch = new_batch(ctx, VERSION)
    batch.pages_expected = 1
    try:
        _, html = ctx.http.get_text(LIST_URL)
        rows = parse_jobs(html)
        if not rows:
            raise FormatChanged("data-job-name presente, mas nenhuma vaga lida: formato da DOF mudou")
    except (FormatChanged, Blocked, SourceFailure) as e:
        return fail(batch, getattr(e, "code", "error"), str(e))
    batch.pages_received = 1
    batch.raw_count = len(rows)
    seen: set[str] = set()
    for r in rows:
        if not r["slug"]:
            batch.warnings.append("item sem data-slug ignorado")
            continue
        if r["slug"] in seen:
            continue
        seen.add(r["slug"])
        location = ", ".join(p for p in (r["city"], r["country"]) if p) or None
        batch.jobs.append(JobObservation(
            platform="webflow", tenant="dof.com", external_id=r["slug"], url=DETAIL_URL.format(slug=r["slug"]),
            title=r["title"], location=location, department=r["department"] or None,
            listing_signature=signature(r["title"], location, r["department"]),
            raw={"slug": r["slug"]}))
    if not batch.jobs:
        return fail(batch, "format_changed", "vagas DOF sem data-slug: formato mudou")
    _details(ctx, batch)
    if NEXT_PAGE_RE.search(html):
        batch.status = "partial"
        batch.warnings.append("paginação do Webflow detectada (w-pagination-next); só a primeira página foi lida")
    else:
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
        blocks = [html_to_text(b) for b in RICH_RE.findall(html)]
        text, status, orig, note = bounded("\n\n".join(b for b in blocks if b))
        if not text:
            batch.warnings.append(f"detalhe {obs.external_id}: sem blocos rich-text")
            continue
        obs.description, obs.description_status = text, status
        obs.original_length, obs.truncation_note = orig, note
        batch.details_fetched += 1
