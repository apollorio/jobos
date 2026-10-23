"""inHire (api.inhire.app): listagem pública por tenant + detalhe por vaga.

Portado de Artifact/jobos/sources/web.py (inhire, detalhe_inhire) e assets/load-jobs.ts (loadInhire).
A API devolve 403 sem os cabeçalhos X-Tenant, Origin e Referer; com eles responde normalmente.
Diferenças: a chave `jobsPage` precisa existir (lista) para a resposta valer como reconhecida, a descrição não é
cortada em 6000 caracteres e falha de detalhe vira aviso, nunca falha do lote.
"""
from __future__ import annotations

from jobos.collectors.base import (Blocked, CollectContext, FormatChanged, JobObservation, SourceBatch, SourceFailure,
                                   fail, new_batch, signature, wants_detail)
from jobos.collectors.text import bounded, html_to_text

VERSION = "inhire/1"
API = "https://api.inhire.app/job-posts/public/pages"


def _headers(tenant: str) -> dict:
    return {"Accept": "application/json", "X-Tenant": tenant, "Origin": f"https://{tenant}.inhire.app",
            "Referer": f"https://{tenant}.inhire.app/vagas"}


def _workplace(value) -> str | None:
    wt = str(value or "").lower()
    if "remote" in wt or "remoto" in wt:
        return "remote"
    if "hybrid" in wt or "hibrid" in wt or "híbrid" in wt:
        return "hybrid"
    if wt.replace("-", "").replace("_", "") in ("onsite", "presencial") or "presencial" in wt:
        return "onsite"
    return None


def collect(ctx: CollectContext) -> SourceBatch:
    tenant = ctx.source.params["tenant"]
    batch = new_batch(ctx, VERSION)
    batch.pages_expected = 1
    try:
        data = ctx.http.get_json(API, headers=_headers(tenant))
        if not isinstance(data, dict) or not isinstance(data.get("jobsPage"), list):
            raise FormatChanged("resposta inHire sem a lista jobsPage")
    except (FormatChanged, Blocked, SourceFailure) as e:
        return fail(batch, getattr(e, "code", "error"), str(e))
    items = data["jobsPage"]
    batch.pages_received = 1
    batch.raw_count = len(items)
    seen: set[str] = set()
    for j in items:
        jid = str(j.get("jobId") or "").strip() if isinstance(j, dict) else ""
        if not jid:
            batch.warnings.append("item sem jobId ignorado")
            continue
        if jid in seen:
            continue
        seen.add(jid)
        location = j.get("location") or None
        department = j.get("department") or None
        batch.jobs.append(JobObservation(
            platform="inhire", tenant=tenant, external_id=jid, url=f"https://{tenant}.inhire.app/vagas/{jid}",
            title=(j.get("displayName") or "").strip(), location=location, department=department,
            workplace=_workplace(j.get("workplaceType")),
            published_raw=j.get("publishedAt") or None, published_source="inhire:publishedAt",
            listing_signature=signature(j.get("displayName"), location, department, j.get("workplaceType")),
            raw={"jobId": jid, "workplaceType": j.get("workplaceType")}))
    _details(ctx, batch, tenant)
    batch.status = "complete"
    return batch.finish()


def _details(ctx: CollectContext, batch: SourceBatch, tenant: str) -> None:
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
            d = ctx.http.get_json(f"{API}/{obs.external_id}", headers=_headers(tenant))
            if not isinstance(d, dict):
                raise FormatChanged("detalhe inHire não é um objeto JSON")
        except (FormatChanged, Blocked, SourceFailure) as e:
            batch.warnings.append(f"detalhe {obs.external_id}: {getattr(e, 'code', 'erro')}: {str(e)[:120]}")
            continue
        text, status, orig, note = bounded(html_to_text(d.get("description") or ""))
        obs.description, obs.description_status = text, status
        obs.original_length, obs.truncation_note = orig, note
        if d.get("publishedAt"):
            obs.published_raw, obs.published_source = d["publishedAt"], "inhire:publishedAt"
        elif d.get("createdAt"):
            obs.published_raw, obs.published_source = d["createdAt"], "inhire:createdAt"
        obs.location = d.get("location") or obs.location
        obs.department = d.get("department") or obs.department
        obs.workplace = _workplace(d.get("workplaceType")) or obs.workplace
        batch.details_fetched += 1
