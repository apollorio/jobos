"""SmartRecruiters (api.smartrecruiters.com): lista paginada de postings + detalhe com jobAd.

Portado de Artifact/jobos/sources/ats.py (smartrecruiters) e assets/load-jobs.ts (loadSmart).
O país configurado (`country`) é escopo da consulta e entra no scope_id; o adapter não filtra mais nada.
Diferenças: total informado (`totalFound`) vira pages_expected, limite de páginas atingido = parcial (o legado
cortava em 500 sem avisar), URL pública montada na mão (o campo `ref` é link interno da API) e descrição
vinda de jobAd.sections no detalhe, sem corte em 6000 caracteres.
"""
from __future__ import annotations

from jobos.collectors.base import (Blocked, CollectContext, FormatChanged, JobObservation, SourceBatch, SourceFailure,
                                   fail, new_batch, signature, wants_detail)
from jobos.collectors.text import bounded, html_to_text

VERSION = "smartrecruiters/1"
API = "https://api.smartrecruiters.com/v1/companies/{company}/postings"
LIMIT = 100
SECTIONS = (("companyDescription", "Descrição da empresa"), ("jobDescription", "Descrição da vaga"),
            ("qualifications", "Qualificações"), ("additionalInformation", "Informações adicionais"))


def _page(ctx: CollectContext, company: str, country: str | None, offset: int) -> dict:
    params = {"limit": LIMIT, "offset": offset}
    if country:
        params["country"] = country
    data = ctx.http.get_json(API.format(company=company), params=params)
    if not isinstance(data, dict) or not isinstance(data.get("content"), list):
        raise FormatChanged("resposta SmartRecruiters sem a lista content")
    return data


def _location(loc: dict) -> str | None:
    return loc.get("fullLocation") or ", ".join(p for p in (loc.get("city"), loc.get("region"), loc.get("country")) if p) or None


def _workplace(loc: dict) -> str | None:
    if loc.get("remote"):
        return "remote"
    if loc.get("hybrid"):
        return "hybrid"
    return None


def collect(ctx: CollectContext) -> SourceBatch:
    p = ctx.source.params
    company, country = p["company_id"], p.get("country")
    batch = new_batch(ctx, VERSION, {"country": country})
    max_pages = int(ctx.source.limits.get("max_pages", 15))
    offset, total, seen = 0, None, set()
    for _ in range(max_pages):
        try:
            data = _page(ctx, company, country, offset)
        except (FormatChanged, Blocked, SourceFailure) as e:
            if batch.pages_received:
                batch.status = "partial"
                batch.error_code, batch.error_message = getattr(e, "code", "error"), f"página offset={offset}: {e}"[:500]
                break
            return fail(batch, getattr(e, "code", "error"), str(e))
        if total is None and isinstance(data.get("totalFound"), int):
            total = data["totalFound"]
            batch.pages_expected = (total + LIMIT - 1) // LIMIT if total else 1
        content = data["content"]
        batch.pages_received += 1
        for j in content:
            jid = str(j.get("id") or "").strip() if isinstance(j, dict) else ""
            if not jid:
                batch.warnings.append("item sem id ignorado")
                continue
            if jid in seen:
                continue
            seen.add(jid)
            batch.jobs.append(_observation(company, jid, j))
        offset += len(content)
        if not content or (total is not None and offset >= total) or (total is None and len(content) < LIMIT):
            break
    else:
        batch.status = "partial"
        batch.warnings.append(f"limite de {max_pages} páginas atingido; total informado {total}")
    batch.raw_count = len(seen)
    if batch.status != "partial":
        batch.status = "complete"
    _details(ctx, batch, company)
    return batch.finish()


def _observation(company: str, jid: str, j: dict) -> JobObservation:
    loc = j.get("location") or {}
    location = _location(loc)
    department = (j.get("department") or {}).get("label") or None
    return JobObservation(
        platform="smartrecruiters", tenant=company, external_id=jid, url=f"https://jobs.smartrecruiters.com/{company}/{jid}",
        title=(j.get("name") or "").strip(), location=location, workplace=_workplace(loc), department=department,
        published_raw=j.get("releasedDate") or None, published_source="smartrecruiters:releasedDate",
        listing_signature=signature(j.get("name"), location, department, j.get("releasedDate")),
        raw={"id": jid, "country": loc.get("country")})


def _details(ctx: CollectContext, batch: SourceBatch, company: str) -> None:
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
            d = ctx.http.get_json(f"{API.format(company=company)}/{obs.external_id}")
            sections = ((d or {}).get("jobAd") or {}).get("sections") if isinstance(d, dict) else None
            if not isinstance(sections, dict):
                raise FormatChanged("detalhe SmartRecruiters sem jobAd.sections")
        except (FormatChanged, Blocked, SourceFailure) as e:
            batch.warnings.append(f"detalhe {obs.external_id}: {getattr(e, 'code', 'erro')}: {str(e)[:120]}")
            continue
        parts = []
        for key, default_title in SECTIONS:
            sec = sections.get(key) or {}
            body = html_to_text(sec.get("text") or "")
            if body:
                parts.append(f"{(sec.get('title') or default_title).strip()}:\n{body}")
        text, status, orig, note = bounded("\n\n".join(parts))
        obs.description, obs.description_status = text, status
        obs.original_length, obs.truncation_note = orig, note
        batch.details_fetched += 1
