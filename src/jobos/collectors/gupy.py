"""Gupy: página própria do tenant (`__NEXT_DATA__`), enriquecida pelo portal público em uma chamada.

Portado de Artifact/jobos/sources/gupy.py (list_tenant) e assets/load-jobs.ts (gupy). Endpoints observados, não API
documentada (auditoria de 23/10/2026):
- `https://{tenant}.gupy.io/` → `props.pageProps.jobs` traz TODAS as vagas (a paginação de 10 é só visual) e
  `pageProps.careerPage` {id, companyId, name, publicationName}. O HTML mostra "N vagas encontradas".
- `https://portal.gupy.io/api/job-search/jobs?careerPageName=X&limit=100&offset=0` → descrição, publishedDate e
  applicationDeadline de todas as vagas; `careerPageName` = publicationName ou name (exato). O portal mantém vagas
  encerradas: ele NUNCA cria vaga sozinho no modo principal, só enriquece ids que estão na página do tenant.
- `https://{tenant}.gupy.io/jobs/{id}` → `pageProps.job` (detalhe de vagas que o portal não trouxer).
O antigo `employability-portal.gupy.io/api/v1/jobs` responde 404.
"""
from __future__ import annotations

import datetime as dt
import json
import re

from jobos.collectors.base import (Blocked, CollectContext, FormatChanged, JobObservation, SourceBatch, SourceFailure,
                                   fail, new_batch, signature, wants_detail)
from jobos.collectors.text import bounded, html_to_text

VERSION = "gupy_tenant/2"
NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
COUNT_RE = re.compile(r"(\d+)\s*vagas?\s+encontradas?", re.I)
PORTAL = "https://portal.gupy.io/api/job-search/jobs"
PORTAL_HEADERS = {"Referer": "https://portal.gupy.io/", "Accept": "application/json"}
PAGE = 100
TALENT_TYPES = {"vacancy_type_talent_pool"}

SECTIONS = (("description", "Descrição da vaga"), ("responsibilities", "Responsabilidades e atribuições"),
            ("prerequisites", "Requisitos e qualificações"), ("relevantExperiences", "Informações adicionais"))


def _workplace(stub: dict) -> str | None:
    wt = ((stub.get("workplace") or {}).get("workplaceType") or stub.get("workplaceType") or "").lower()
    if stub.get("isRemoteWork") or wt == "remote":
        return "remote"
    if wt in ("hybrid", "hibrido"):
        return "hybrid"
    if wt in ("on-site", "onsite", "presencial"):
        return "onsite"
    return None


def _next_data(html: str, what: str) -> dict:
    m = NEXT_DATA_RE.search(html or "")
    if not m:
        raise FormatChanged(f"__NEXT_DATA__ ausente na {what} (login/desafio/layout novo)")
    try:
        return json.loads(m.group(1))
    except ValueError as e:
        raise FormatChanged(f"__NEXT_DATA__ inválido na {what}: {e}") from e


def parse_tenant_page_full(html: str) -> dict:
    props = (_next_data(html, "página do tenant").get("props") or {}).get("pageProps")
    if not isinstance(props, dict) or not isinstance(props.get("jobs"), list):
        raise FormatChanged("pageProps.jobs ausente: formato da Gupy mudou")
    m = COUNT_RE.search(re.sub(r"<[^>]+>", " ", html))
    return {"jobs": props["jobs"], "career_page": props.get("careerPage") or {},
            "shown_count": int(m.group(1)) if m else None}


def parse_tenant_page(html: str) -> list[dict]:
    return parse_tenant_page_full(html)["jobs"]


def parse_job_page(html: str) -> dict:
    job = (_next_data(html, "página da vaga").get("props") or {}).get("pageProps", {}).get("job")
    if not isinstance(job, dict) or "name" not in job:
        raise FormatChanged("pageProps.job ausente: formato da página de vaga mudou")
    return job


def portal_rows(ctx: CollectContext, *, career_page_name: str | None = None, job_name: str | None = None,
                state: str | None = None, max_pages: int = 15) -> tuple[list[dict], bool]:
    """Lista do portal com paginação (limit ≤ 100). `total` só é confiável em offset=0. Devolve (linhas, completo)."""
    rows, offset, total = [], 0, None
    for _ in range(max_pages):
        params = {"limit": PAGE, "offset": offset}
        if career_page_name:
            params["careerPageName"] = career_page_name
        if job_name:
            params["jobName"] = job_name
        if state:
            params["state"] = state
        data = ctx.http.get_json(PORTAL, headers=PORTAL_HEADERS, params=params)
        page = data.get("data") if isinstance(data, dict) else None
        if not isinstance(page, list):
            raise FormatChanged("portal Gupy sem a lista 'data'")
        if total is None:
            total = int((data.get("pagination") or {}).get("total") or 0)
        rows += page
        offset += PAGE
        # `total` não é confiável para limit alto em buscas grandes: só a página curta prova o fim (auditoria 23/10)
        if len(page) < PAGE:
            return rows, True
    return rows, False


def _job_page_detail(ctx: CollectContext, tenant: str, jid, obs: JobObservation) -> None:
    _, html = ctx.http.get_text(f"https://{tenant}.gupy.io/jobs/{jid}")
    job = parse_job_page(html)
    parts = [f"{label}:\n{html_to_text(job[key])}" for key, label in SECTIONS if job.get(key)]
    text, status, orig, note = bounded("\n\n".join(parts))
    obs.description, obs.description_status = text, status if text else "missing"
    obs.original_length, obs.truncation_note = orig, note
    if job.get("publishedAt"):
        obs.published_raw, obs.published_source = job["publishedAt"], "gupy:job.publishedAt"
    obs.deadline = job.get("registerEndDate") or job.get("expiresAt") or obs.deadline
    obs.workplace = _workplace({"workplaceType": job.get("workplaceType")}) or obs.workplace
    city, state = job.get("addressCity"), job.get("addressState")
    if city or state:
        obs.location = ", ".join(p for p in (city, state) if p)
    obs.raw["job_status"] = job.get("status")


def _apply_portal_row(obs: JobObservation, row: dict) -> None:
    text, status, orig, note = bounded(html_to_text(row.get("description") or ""))
    if text:
        obs.description, obs.description_status, obs.original_length, obs.truncation_note = text, status, orig, note
    if row.get("publishedDate"):
        obs.published_raw, obs.published_source = row["publishedDate"], "gupy_portal:publishedDate"
    obs.deadline = row.get("applicationDeadline") or obs.deadline


def _tenants(ctx: CollectContext) -> list[str]:
    p = ctx.source.params
    return list(dict.fromkeys([*(p.get("tenants") or []), *([p["tenant"]] if p.get("tenant") else [])]))


def collect_tenant(ctx: CollectContext) -> SourceBatch:
    tenants = _tenants(ctx)
    batch = new_batch(ctx, VERSION, {"tenants": tenants})
    batch.pages_expected = len(tenants)
    limits = ctx.source.limits
    ttl = int(limits.get("detail_ttl_days", 7))
    budget = int(limits.get("max_details", 25))
    partial_reasons: list[str] = []
    seen: set[str] = set()
    for tenant in tenants:
        try:
            _, html = ctx.http.get_text(f"https://{tenant}.gupy.io/")
            page = parse_tenant_page_full(html)
        except (FormatChanged, Blocked, SourceFailure) as e:
            if len(tenants) == 1:
                return fail(batch, getattr(e, "code", "error"), str(e))
            partial_reasons.append(f"{tenant}: {getattr(e, 'code', 'erro')}: {str(e)[:100]}")
            continue
        batch.pages_received += 1
        stubs = page["jobs"]
        if page["shown_count"] is not None and page["shown_count"] != len(stubs):
            partial_reasons.append(f"{tenant}: página mostra {page['shown_count']} vagas, __NEXT_DATA__ trouxe {len(stubs)}")
        cp = page["career_page"]
        # Nome exato de cada página (publicationName, inclusive espaço final, ou name). `portal_name` só se faltar.
        portal_name = cp.get("publicationName") or cp.get("name") or ctx.source.params.get("portal_name")
        tenant_obs: list[JobObservation] = []
        for stub in stubs:
            jid = stub.get("id")
            if jid is None or str(jid) in seen:
                continue
            seen.add(str(jid))
            addr = (stub.get("workplace") or {}).get("address") or {}
            location = ", ".join(p for p in (addr.get("city"), addr.get("stateShortName") or addr.get("state")) if p) or None
            obs = JobObservation(
                platform="gupy", tenant="", external_id=str(jid), url=f"https://{tenant}.gupy.io/jobs/{jid}",
                title=(stub.get("title") or stub.get("name") or "").strip(), location=location, workplace=_workplace(stub),
                department=stub.get("department") or None, talent_pool=stub.get("type") in TALENT_TYPES,
                listing_signature=signature(stub.get("title"), location, stub.get("department"), stub.get("type")),
                raw={"tenant": tenant, "type": stub.get("type"), "careerPageId": cp.get("id"),
                     "companyId": cp.get("companyId")})
            tenant_obs.append(obs)
        # Enriquecimento em lote: uma chamada ao portal cobre descrição e data de todas as vagas do tenant
        portal_by_id: dict[str, dict] = {}
        if portal_name and tenant_obs:
            try:
                rows, _ = portal_rows(ctx, career_page_name=portal_name, max_pages=int(limits.get("max_pages", 15)))
                portal_by_id = {str(r.get("id")): r for r in rows if r.get("id") is not None}
            except (FormatChanged, Blocked, SourceFailure) as e:
                batch.warnings.append(f"{tenant}: portal indisponível para enriquecimento ({str(e)[:80]}); usando páginas")
        for obs in tenant_obs:
            row = portal_by_id.get(obs.external_id)
            if row and row.get("publishedDate"):
                obs.published_raw, obs.published_source = row["publishedDate"], "gupy_portal:publishedDate"
            if not wants_detail(ctx, obs, ttl):
                batch.jobs.append(obs)
                continue
            if row and row.get("description"):
                _apply_portal_row(obs, row)
                batch.details_fetched += 1
            elif budget > 0:
                budget -= 1
                try:
                    _job_page_detail(ctx, tenant, obs.external_id, obs)
                    batch.details_fetched += 1
                except (FormatChanged, Blocked, SourceFailure) as e:
                    batch.warnings.append(f"detalhe {obs.external_id}: {getattr(e, 'code', 'erro')}: {str(e)[:100]}")
            batch.jobs.append(obs)
    batch.raw_count = len(seen)
    if budget <= 0:
        batch.warnings.append("limite de detalhes por página atingido; restantes nos próximos ciclos")
    if partial_reasons:
        batch.status = "partial"
        batch.error_code, batch.error_message = "incomplete_listing", "; ".join(partial_reasons)[:500]
    else:
        batch.status = "complete"
    return batch.finish()


def collect_portal_company(ctx: CollectContext) -> SourceBatch:
    """Alternativa quando a página do tenant falha: lista pelo portal (careerPageName). Nunca autoriza ausência e
    descarta vagas com prazo vencido, porque o índice do portal guarda vagas encerradas."""
    batch = new_batch(ctx, "gupy_portal_company/1", {"portal_name": ctx.source.params.get("portal_name")})
    batch.can_infer_absence = False
    name = ctx.source.params.get("portal_name") or ctx.source.company_name
    try:
        rows, complete = portal_rows(ctx, career_page_name=name, max_pages=int(ctx.source.limits.get("max_pages", 15)))
    except (FormatChanged, Blocked, SourceFailure) as e:
        return fail(batch, getattr(e, "code", "error"), str(e))
    today = dt.date.today().isoformat()
    for r in rows:
        if r.get("applicationDeadline") and str(r["applicationDeadline"])[:10] < today:
            continue
        obs = JobObservation(
            platform="gupy", tenant="", external_id=str(r.get("id")), url=r.get("jobUrl"), title=(r.get("name") or "").strip(),
            location=", ".join(p for p in (r.get("city"), r.get("state")) if p) or None, workplace=_workplace(r),
            talent_pool=r.get("type") in TALENT_TYPES, raw={"careerPageName": r.get("careerPageName"), "via": "portal"})
        _apply_portal_row(obs, r)
        batch.jobs.append(obs)
    batch.raw_count = len(rows)
    batch.pages_received = 1
    batch.status = "partial"  # índice do portal não substitui a página do tenant
    batch.warnings.append("lista obtida pelo portal (alternativa): sem inferência de ausência")
    return batch.finish()


def collect_portal_queries(ctx: CollectContext) -> SourceBatch:
    """Consultas por palavra-chave no portal agregado. Escopo incremental: nunca infere ausência."""
    batch = new_batch(ctx, "gupy_portal_search/2")
    batch.can_infer_absence = False
    seen: set[str] = set()
    capped = False
    for q in ctx.source.params.get("queries") or []:
        try:
            rows, complete = portal_rows(ctx, job_name=q, state=ctx.source.params.get("state"),
                                         max_pages=int(ctx.source.limits.get("max_pages", 15)))
        except (FormatChanged, Blocked, SourceFailure) as e:
            batch.warnings.append(f"consulta '{q}': {str(e)[:120]}")
            batch.status = "partial"
            continue
        capped = capped or not complete
        batch.pages_received += 1
        for r in rows:
            jid = str(r.get("id"))
            if jid in seen:
                continue
            seen.add(jid)
            obs = JobObservation(
                platform="gupy", tenant="", external_id=jid, url=r.get("jobUrl"), title=r.get("name") or "",
                location=", ".join(p for p in (r.get("city"), r.get("state")) if p) or None, workplace=_workplace(r),
                talent_pool=r.get("type") in TALENT_TYPES, raw={"careerPageName": r.get("careerPageName")})
            _apply_portal_row(obs, r)
            batch.jobs.append(obs)
    batch.raw_count = len(seen)
    if capped:
        batch.warnings.append("limite de páginas atingido em alguma consulta")
    if batch.status != "partial":
        batch.status = "partial" if capped else "complete"
    return batch.finish()


def probe(ctx: CollectContext, external_id: str | None, url: str | None) -> str:
    """Confirma um anúncio pela página pública: status 'published' = vivo; 'closed'/'canceled' ou 404 = encerrado."""
    if not external_id:
        return "unknown"
    tenants = _tenants(ctx)
    m = re.match(r"https://([a-z0-9-]+)\.gupy\.io/", url or "")
    tenant = m.group(1) if m else (tenants[0] if tenants else None)
    if not tenant:
        return "unknown"
    try:
        _, html = ctx.http.get_text(f"https://{tenant}.gupy.io/jobs/{external_id}")
    except SourceFailure as e:
        return "gone" if e.code == "not_found" else "unknown"
    except (Blocked, FormatChanged):
        return "unknown"
    if "/candidates/signin" in html[:5000] and "__NEXT_DATA__" not in html:
        return "unknown"  # vaga privada/interna: não é prova de encerramento
    try:
        status = (parse_job_page(html).get("status") or "").lower()
    except FormatChanged:
        return "unknown"
    if status in ("closed", "canceled", "cancelled", "frozen"):
        return "gone"
    return "alive" if status == "published" else "unknown"
