"""Oracle Recruiting Candidate Experience (Oracle Fusion HCM, `hcmRestApi`): lista filtrada por local + detalhe.

Endpoints públicos observados (auditoria de 23/10/2026, ABS em https://hbbq.fa.us2.oraclecloud.com, site CX_1), sem
autenticação, `Accept: application/json`:
- Descoberta do local: `recruitingCEJobRequisitions?onlyData=true&finder=findReqs;siteNumber=CX_1,facetsList=LOCATIONS,
  userTargetFacetName=LOCATIONS,userTargetFacetInputTerm=Brazil,limit=1` -> `items[0].locationsFacet`
  [{Id, Name, TotalCount}]. A faceta só aparece quando o local tem vaga.
- Lista: mesmo recurso com `expand=requisitionList.secondaryLocations` e `locationId=<Id>,limit=25,offset=n,
  sortBy=POSTING_DATES_DESC`. Linhas em `items[0].requisitionList`; total em `items[0].TotalJobsCount`. O `hasMore`
  da resposta NÃO é confiável (vem false com 25 de 126), por isso a paginação segue o total.
- Detalhe: `recruitingCEJobRequisitionDetails?expand=all&onlyData=true&finder=ById;Id="<Id>",siteNumber=CX_1` ->
  `items[0]` com ExternalDescriptionStr / ExternalResponsibilitiesStr / ExternalQualificationsStr (HTML).
- Página pública da vaga: `{base}/hcmUI/CandidateExperience/{lang}/sites/{site}/job/{Id}`.

O finder usa ';' e ',' literais: a URL é montada aqui e o HTTP recebe params=None (requests não reescreve esses
caracteres; aspas vão como %22).

Armadilhas verificadas ao vivo:
- `locationId` desconhecido é IGNORADO em silêncio: a API devolve o quadro inteiro e ainda ecoa o LocationId pedido.
  Por isso, além do eco, cada linha precisa citar o local do escopo (principal ou secundário); linha fora do escopo
  = formato mudou, nunca "lista completa".
- O detalhe ignora `siteNumber` e devolve `items: []` para Id inexistente ou não publicado.

Escopo: `location_term` (ex.: "Brazil") é filtro de ESCOPO DA FONTE, declarado nos params; o id do local entra no
scope_id. `location_id` opcional fixa o id: assim um país sem nenhuma vaga é lido como lista vazia reconhecida, em vez
de "faceta não encontrada" (sem o id fixo isso é indistinguível de mudança de nome e vira falha, sem ausência).
"""
from __future__ import annotations

import datetime as dt
import re
from urllib.parse import quote

from jobos.collectors.base import (Blocked, CollectContext, FormatChanged, JobObservation, SourceBatch, SourceFailure,
                                   fail, new_batch, signature, wants_detail)
from jobos.collectors.text import bounded, clean, html_to_text
from jobos.domain.identity import fold, host_label
from jobos.timeutil import brt_date, parse_instant, utcnow

VERSION = "oracle_ce/1"
PLATFORM = "oracle_ce"
API = "/hcmRestApi/resources/latest"
HEADERS = {"Accept": "application/json"}
LIMIT = 25
SECTIONS = (("ExternalDescriptionStr", "Descrição da vaga"), ("ExternalResponsibilitiesStr", "Responsabilidades"),
            ("ExternalQualificationsStr", "Qualificações"))
WORKPLACE_CODES = {"ORA_ON_SITE": "onsite", "ORA_HYBRID": "hybrid", "ORA_REMOTE": "remote"}
WORKPLACE_TEXT = {"on-site": "onsite", "onsite": "onsite", "on site": "onsite", "presencial": "onsite",
                  "hybrid": "hybrid", "híbrido": "hybrid", "hibrido": "hybrid", "remote": "remote", "remoto": "remote"}
JOB_ID_RE = re.compile(r"/job/(\d+)(?:[/?#]|$)")
SHORT_NOTE = "resumo da listagem (ShortDescriptionStr); o texto completo vem do detalhe"

# Controle do probe: confirma, uma vez por execução, que o detalhe responde para uma vaga viva antes de aceitar
# "items vazio"/404 como prova de encerramento (evita encerrar tudo se a API passar a responder vazio para todos).
_CONTROL_CACHE: dict[tuple, bool] = {}


# ------------------------------------------------------------------ URLs

def _q(value) -> str:
    return quote(str(value), safe="")


def facet_url(base: str, site: str, term: str) -> str:
    return (f"{base}{API}/recruitingCEJobRequisitions?onlyData=true&finder=findReqs;siteNumber={_q(site)},"
            f"facetsList=LOCATIONS,userTargetFacetName=LOCATIONS,userTargetFacetInputTerm={_q(term)},limit=1")


def list_url(base: str, site: str, location_id: str | None, offset: int, limit: int = LIMIT) -> str:
    loc = f",locationId={_q(location_id)}" if location_id else ""
    return (f"{base}{API}/recruitingCEJobRequisitions?onlyData=true&expand=requisitionList.secondaryLocations"
            f"&finder=findReqs;siteNumber={_q(site)},facetsList=LOCATIONS,limit={limit},offset={offset},"
            f"sortBy=POSTING_DATES_DESC{loc}")


def detail_url(base: str, site: str, req_id: str) -> str:
    return (f"{base}{API}/recruitingCEJobRequisitionDetails?expand=all&onlyData=true"
            f"&finder=ById;Id=%22{_q(req_id)}%22,siteNumber={_q(site)}")


def job_url(base: str, site: str, req_id: str, lang: str = "en") -> str:
    return f"{base}/hcmUI/CandidateExperience/{lang}/sites/{site}/job/{req_id}"


def _config(ctx: CollectContext) -> tuple[str, str]:
    p = ctx.source.params
    base, site = str(p.get("base") or "").strip().rstrip("/"), str(p.get("site") or "").strip()
    if not base.startswith("https://") or not site:
        raise SourceFailure("config", "params 'base' (https://...) e 'site' são obrigatórios")
    return base, site


# ------------------------------------------------------------------ respostas

def _search_item(data, what: str) -> dict:
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        raise FormatChanged(f"{what}: resposta sem items[0] (login/desafio/formato novo)")
    return items[0]


def _int(value, what: str) -> int:
    if isinstance(value, bool):
        raise FormatChanged(f"{what} inválido: {value!r}")
    try:
        return int(value)
    except (TypeError, ValueError) as e:
        raise FormatChanged(f"{what} inválido: {value!r}") from e


def discover_location(ctx: CollectContext, base: str, site: str, term: str) -> list[dict]:
    """Facetas de local que respondem ao termo. Lista vazia = nenhum local com vaga para o termo (não é erro)."""
    item = _search_item(ctx.http.get_json(facet_url(base, site, term), headers=HEADERS), "descoberta de local")
    facets = item.get("locationsFacet")
    if not isinstance(facets, list):
        raise FormatChanged("descoberta de local sem a lista locationsFacet")
    return [f for f in facets if isinstance(f, dict) and f.get("Id") is not None and f.get("Name")]


def _list_page(ctx: CollectContext, base: str, site: str, location_id: str, offset: int) -> tuple[list, int]:
    item = _search_item(ctx.http.get_json(list_url(base, site, location_id, offset), headers=HEADERS), "lista")
    rows = item.get("requisitionList")
    if not isinstance(rows, list):
        raise FormatChanged("lista sem requisitionList")
    total = _int(item.get("TotalJobsCount"), "TotalJobsCount")
    if str(item.get("LocationId") or "") != str(location_id):
        raise FormatChanged(f"filtro de local não ecoado: pedido {location_id}, resposta {item.get('LocationId')!r}")
    if item.get("SiteNumber") and str(item["SiteNumber"]) != site:
        raise FormatChanged(f"site ecoado diferente: pedido {site}, resposta {item['SiteNumber']!r}")
    return rows, total


def _location_names(row: dict) -> list[str]:
    names = [clean(row.get("PrimaryLocation"))]
    for s in row.get("secondaryLocations") or []:
        if isinstance(s, dict):
            names.append(clean(s.get("Name")))
    return list(dict.fromkeys(n for n in names if n))


def _in_scope(names: list[str], label: str) -> bool:
    lab = fold(label)
    return any(re.search(rf"(?<![a-z0-9]){re.escape(lab)}(?![a-z0-9])", fold(n)) for n in names)


def _workplace(d: dict) -> str | None:
    code = str(d.get("WorkplaceTypeCode") or "").strip().upper()
    if code in WORKPLACE_CODES:
        return WORKPLACE_CODES[code]
    return WORKPLACE_TEXT.get(fold(d.get("WorkplaceType")))


def _observation(base: str, site: str, tenant: str, lang: str, rid: str, row: dict, label: str) -> JobObservation:
    names = _location_names(row)
    ordered = [n for n in names if _in_scope([n], label)] + [n for n in names if not _in_scope([n], label)]
    location = "; ".join(ordered) or None
    title = clean(row.get("Title"))
    short = html_to_text(row.get("ShortDescriptionStr") or "")
    text, _, orig, _ = bounded(short)
    obs = JobObservation(
        platform=PLATFORM, tenant=tenant, external_id=rid, url=job_url(base, site, rid, lang), title=title,
        location=location, workplace=_workplace(row),
        department=clean(row.get("Department") or row.get("Organization") or row.get("JobFamily")) or None,
        deadline=row.get("PostingEndDate") or None,
        description=text, description_status="partial" if text else "missing", original_length=orig,
        truncation_note=SHORT_NOTE if text else None,
        published_raw=row.get("PostedDate") or None, published_source="oracle_ce:PostedDate",
        listing_signature=signature(title, "|".join(names), row.get("WorkplaceTypeCode"), row.get("PostedDate"),
                                    row.get("PostingEndDate"), signature(short)),
        raw={"id": rid, "site": site, "primary_location": row.get("PrimaryLocation"),
             "country": row.get("PrimaryLocationCountry"), "secondary_locations": names[1:],
             "workplace_code": row.get("WorkplaceTypeCode"), "language": row.get("Language")})
    return obs


# ------------------------------------------------------------------ detalhe

def fetch_detail(ctx: CollectContext, base: str, site: str, req_id: str) -> dict | None:
    """items[0] do detalhe, ou None quando a plataforma responde lista vazia (Id inexistente ou não publicado)."""
    data = ctx.http.get_json(detail_url(base, site, req_id), headers=HEADERS)
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise FormatChanged("detalhe sem a lista items")
    if not items:
        return None
    d = items[0]
    if not isinstance(d, dict):
        raise FormatChanged("detalhe com item que não é objeto")
    if str(d.get("Id") or "") != str(req_id):
        raise FormatChanged(f"detalhe devolveu outra requisição ({d.get('Id')!r} em vez de {req_id})")
    return d


def _apply_detail(obs: JobObservation, d: dict) -> bool:
    """Aplica o detalhe. Devolve True se trouxe texto de descrição."""
    parts = []
    for key, label in SECTIONS:
        body = html_to_text(d.get(key) or "")
        if body:
            parts.append(f"{label}:\n{body}")
    if parts:
        text, status, orig, note = bounded("\n\n".join(parts))
        obs.description, obs.description_status = text, status
        obs.original_length, obs.truncation_note = orig, note
    if d.get("ExternalPostedStartDate"):
        obs.published_raw, obs.published_source = d["ExternalPostedStartDate"], "oracle_ce:ExternalPostedStartDate"
    # Título, local e prazo ficam só com a listagem (presente em todo ciclo): trocar a fonte entre ciclos com e sem
    # detalhe criaria versões alternadas. Departamento e modalidade só preenchem o que a listagem não trouxe.
    obs.workplace = obs.workplace or _workplace(d)
    obs.department = obs.department or clean(d.get("Department") or d.get("Organization") or d.get("Category")) or None
    obs.raw.update({"category": d.get("Category"), "job_function": d.get("JobFunction"),
                    "requisition_type": d.get("RequisitionType"), "job_schedule": d.get("JobSchedule"),
                    "external_posted_end": d.get("ExternalPostedEndDate"), "content_locale": d.get("ContentLocale")})
    return bool(parts)


def _details(ctx: CollectContext, batch: SourceBatch, base: str, site: str) -> None:
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
            d = fetch_detail(ctx, base, site, obs.external_id)
        except (FormatChanged, Blocked, SourceFailure) as e:
            batch.warnings.append(f"detalhe {obs.external_id}: {getattr(e, 'code', 'erro')}: {str(e)[:120]}")
            continue
        if d is None:
            batch.warnings.append(f"detalhe {obs.external_id}: items vazio (despublicada entre a lista e o detalhe?)")
            continue
        if not _apply_detail(obs, d):
            batch.warnings.append(f"detalhe {obs.external_id}: sem texto externo; mantido o resumo da listagem")
        batch.details_fetched += 1


# ------------------------------------------------------------------ coleta

def _resolve_location(ctx: CollectContext, base: str, site: str, term: str, pinned: str | None,
                      warnings: list[str]) -> tuple[str, str, int | None]:
    """Devolve (location_id, rótulo para validar linhas, TotalCount da faceta ou None)."""
    try:
        facets = discover_location(ctx, base, site, term)
    except (FormatChanged, Blocked, SourceFailure) as e:
        if not pinned:
            raise
        warnings.append(f"descoberta do local '{term}' falhou ({getattr(e, 'code', 'erro')}); usando location_id fixo")
        return pinned, term, None
    matches = [f for f in facets if fold(f.get("Name")) == fold(term)]
    ids = list(dict.fromkeys(str(f["Id"]) for f in matches))
    if pinned:
        if not matches:
            warnings.append(f"faceta '{term}' ausente (país sem vagas agora ou nome mudou); usando location_id fixo")
            return pinned, term, None
        if pinned not in ids:
            raise SourceFailure("scope_mismatch", f"location_id fixo {pinned} difere da faceta '{term}' ({', '.join(ids)})")
        f = next(f for f in matches if str(f["Id"]) == pinned)
    else:
        if not matches:
            raise SourceFailure("scope_not_found", f"faceta de local '{term}' não encontrada: sem vagas no local ou nome "
                                                   "mudou (indistinguível sem location_id fixo)")
        if len(ids) > 1:
            raise SourceFailure("scope_ambiguous", f"mais de uma faceta '{term}': {', '.join(ids)}; fixe location_id")
        f = matches[0]
    total = f.get("TotalCount")
    return str(f["Id"]), clean(f.get("Name")) or term, total if isinstance(total, int) and not isinstance(total, bool) else None


def collect(ctx: CollectContext) -> SourceBatch:
    p = ctx.source.params
    term = clean(p.get("location_term"))
    pinned = str(p["location_id"]).strip() if p.get("location_id") not in (None, "") else None
    lang = str(p.get("lang") or "en")
    try:
        base, site = _config(ctx)
        if not term:
            raise SourceFailure("config", "param 'location_term' é obrigatório (valida que o filtro foi aplicado)")
    except SourceFailure as e:
        return fail(new_batch(ctx, VERSION, {"location_id": pinned}), e.code, str(e))
    warnings: list[str] = []
    try:
        location_id, label, facet_total = _resolve_location(ctx, base, site, term, pinned, warnings)
    except (FormatChanged, Blocked, SourceFailure) as e:
        b = new_batch(ctx, VERSION, {"location_id": pinned})
        b.warnings += warnings
        return fail(b, getattr(e, "code", "error"), str(e))

    batch = new_batch(ctx, VERSION, {"location_id": location_id})
    batch.warnings += warnings
    tenant = host_label(base)
    max_pages = int(ctx.source.limits.get("max_pages", 15))
    partial: list[str] = []
    offset, total, seen = 0, None, set()
    for _ in range(max_pages):
        try:
            rows, page_total = _list_page(ctx, base, site, location_id, offset)
            outside = [str((r or {}).get("Id")) for r in rows
                       if isinstance(r, dict) and _location_names(r) and not _in_scope(_location_names(r), label)]
            if outside:
                raise FormatChanged(f"filtro de local ignorado: {len(outside)} linha(s) fora de '{label}' "
                                    f"(ex.: {', '.join(outside[:3])})")
        except (FormatChanged, Blocked, SourceFailure) as e:
            if batch.pages_received:
                partial.append(f"página offset={offset}: {getattr(e, 'code', 'erro')}: {str(e)[:160]}")
                batch.error_code = getattr(e, "code", "error")
                break
            return fail(batch, getattr(e, "code", "error"), str(e))
        if total is None:
            total = page_total
            batch.pages_expected = max(1, -(-total // LIMIT))
        elif page_total != total:
            partial.append(f"total mudou durante a paginação ({total} -> {page_total})")
        batch.pages_received += 1
        new = 0
        for r in rows:
            rid = clean(str(r.get("Id") or "")) if isinstance(r, dict) else ""
            if not rid:
                batch.warnings.append("linha sem Id ignorada")
                continue
            if not _location_names(r):
                batch.warnings.append(f"vaga {rid} sem local informado; aceita pelo filtro da plataforma")
            if rid in seen:
                continue
            seen.add(rid)
            new += 1
            batch.jobs.append(_observation(base, site, tenant, lang, rid, r, label))
        offset += len(rows)
        if offset >= total:
            break
        if not rows:
            partial.append(f"página vazia em offset={offset} antes do total {total}")
            break
        if new == 0:
            partial.append(f"página repetida em offset={offset - len(rows)}")
            break
    else:
        partial.append(f"limite de {max_pages} páginas atingido; total informado {total}")
    batch.raw_count = len(seen)
    if not partial and total is not None and len(seen) != total:
        partial.append(f"lidas {len(seen)} vagas distintas de {total} informadas")
    if facet_total is not None and total is not None and facet_total != total:
        batch.warnings.append(f"faceta '{label}' informa {facet_total} vagas, a lista informa {total}")
    _details(ctx, batch, base, site)
    if partial:
        batch.status = "partial"
        batch.error_code = batch.error_code or "incomplete_listing"
        batch.error_message = "; ".join(partial)[:500]
    else:
        batch.status = "complete"
    return batch.finish()


# ------------------------------------------------------------------ probe (confirmação individual)

def _ended(d: dict) -> bool:
    """ExternalPostedEndDate vencido. Só data: vencida apenas se anterior ao dia de hoje em Brasília."""
    raw = str(d.get("ExternalPostedEndDate") or "").strip()
    end = parse_instant(raw)
    if end is not None:
        return end < utcnow()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        try:
            return dt.date.fromisoformat(raw) < brt_date()
        except ValueError:
            return False
    return False


def _control_ok(ctx: CollectContext, base: str, site: str) -> bool:
    """Uma vaga viva qualquer do site precisa responder no detalhe; senão 'vazio'/404 não prova nada."""
    key = (ctx.run_id, base, site)
    if key in _CONTROL_CACHE:
        return _CONTROL_CACHE[key]
    ok = False
    try:
        item = _search_item(ctx.http.get_json(list_url(base, site, None, 0, limit=1), headers=HEADERS), "controle")
        rows = item.get("requisitionList")
        rid = str(rows[0].get("Id") or "") if isinstance(rows, list) and rows and isinstance(rows[0], dict) else ""
        ok = bool(rid) and fetch_detail(ctx, base, site, rid) is not None
    except (FormatChanged, Blocked, SourceFailure):
        ok = False
    _CONTROL_CACHE[key] = ok
    return ok


def probe(ctx: CollectContext, external_id: str | None, url: str | None) -> str:
    """Confere UMA vaga: 'alive' | 'gone' | 'unknown'.

    'gone' só com prova forte: 404/410 ou `items` vazio no detalhe ById (com controle positivo de que o detalhe
    responde para outra vaga viva do mesmo site), ou ExternalPostedEndDate já vencido. Rede, bloqueio, formato
    inesperado ou controle negativo -> 'unknown'.
    """
    try:
        base, site = _config(ctx)
    except SourceFailure:
        return "unknown"
    rid = clean(str(external_id or ""))
    if not rid:
        m = JOB_ID_RE.search(url or "")
        rid = m.group(1) if m else ""
    if not rid:
        return "unknown"
    try:
        d = fetch_detail(ctx, base, site, rid)
    except SourceFailure as e:
        if e.code == "not_found":
            return "gone" if _control_ok(ctx, base, site) else "unknown"
        return "unknown"
    except (FormatChanged, Blocked):
        return "unknown"
    if d is None:
        return "gone" if _control_ok(ctx, base, site) else "unknown"
    if _ended(d):
        return "gone"
    return "alive"
