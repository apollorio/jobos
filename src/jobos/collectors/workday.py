"""Workday CXS (endpoint público observado, não API oficial de candidatura).

Portado de Artifact/jobos/sources/web.py::workday e ats.py::workday. Endpoints (auditoria de 23/10/2026):
- POST {host}/wday/cxs/{tenant}/{site}/jobs  {"appliedFacets", "limit": 20, "offset", "searchText"}
  → {total, jobPostings[], facets[]}. `total` só vem preenchido na primeira página (as seguintes trazem 0).
  Uma entrada de jobPostings pode vir sem externalPath (fantasma): é ignorada com aviso.
- GET  {host}/wday/cxs/{tenant}/{site}{externalPath} → jobPostingInfo {jobDescription, location, additionalLocations,
  country{descriptor,id}, jobRequisitionLocation.country.alpha2Code, startDate, endDate, jobReqId, remoteType,
  canApply, posted}. Vaga despublicada responde 404 (HTTP_404) ou 403 (S22 "permission denied").

Modos de escopo (params da fonte; todos entram no scope_id):
- `full_board: true` (sem search_text/filtros): quadro inteiro; é o único modo compatível com coverage full_board.
- `search_text`: busca de texto livre do Workday. Ela casa também com a DESCRIÇÃO (Baker 'Brazil' devolve vagas dos
  EUA e do México): serve como rede de recall, não como filtro de país.
- `country_facet: "Brazil"`: descobre nas facetas (aninhadas: locationMainGroup → locationCountry) o id do país e
  consulta com appliedFacets {"locationCountry": [id]}. Se a faceta existe mas o país não aparece (zero vagas hoje),
  usa o id global do Workday para o país (aceito pela API, devolve total 0) e o escopo não muda. Se o tenant não tem
  faceta locationCountry (Equinor; Baker chama de 'Country' uma faceta que lista cidades), cai no filtro local abaixo
  sobre a listagem e registra aviso.
- `local_country_filter: "BR"`: depois da listagem, mantém a vaga cujo local (segmento do externalPath ou
  locationsText) começa com 'BR-' ou cita Brazil/Brasil/Rio de Janeiro/Macaé. Linhas 'N Locations' (ou sem local)
  são decididas pelo detalhe: país 'BR' ou algum additionalLocations no Brasil. Detalhe que falha deixa o lote
  parcial (a vaga não é descartada como fora do escopo sem prova).
Filtro de país é ESCOPO DA FONTE declarado, não preferência pessoal.

Localização: com detalhe, obs.location = location + additionalLocations ("; "). Sem detalhe nesta rodada, para vaga já
conhecida, a localização fica None e a persistência preserva a gravada (evita oscilar entre '3 Locations' e o texto
do detalhe). Local 'Talent Pool - Brazil' (Transocean) marca talent_pool=True: é a plataforma que informa.

probe(ctx, external_id, url) confere UM anúncio: "gone" só com 404/410 ou 403 no detalhe com a listagem do mesmo
site respondendo normalmente, ou posted=false; "alive" com jobPostingInfo publicado; "unknown" no resto (rede,
formato, canApply=false, URL fora do padrão /job/).
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from jobos.collectors.base import (Blocked, CollectContext, FormatChanged, JobObservation, SourceBatch, SourceFailure,
                                   fail, new_batch, signature, wants_detail)
from jobos.collectors.text import bounded, html_to_text
from jobos.domain.identity import fold, workday_req_id

VERSION = "workday_cxs/2"
PAGE = 20  # o CXS rejeita/ignora valores maiores; não mudar
COUNTRY_FACET_PARAM = "locationCountry"

# Id de referência global do país no Workday (igual em Shell e Baker; a API aceita mesmo sem vaga no país).
COUNTRY_WID = {"BR": "1a29bb1357b240ab99a2fa755cc87c0e"}
COUNTRY_ALPHA2 = {"brazil": "BR", "brasil": "BR"}
COUNTRY_NAMES = {"BR": ("brazil", "brasil", "rio de janeiro", "macae")}
MULTI_LOC_RE = re.compile(r"^\s*\d+\s+(locations|locais|localidades|locaciones|ubicaciones)\s*$", re.I)
POOL_RE = re.compile(r"^(talent pool|banco de talentos)\b")
ERRORS = (FormatChanged, Blocked, SourceFailure)


def _d(x) -> dict:
    return x if isinstance(x, dict) else {}


def _code(e: Exception) -> str:
    return getattr(e, "code", None) or "error"


# ------------------------------------------------------------------ filtro de país

def _text_in_country(text: str | None, cc: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if t.upper().startswith(f"{cc}-"):
        return True
    words = " " + re.sub(r"[\W_]+", " ", fold(t)) + " "
    return any(f" {name} " in words for name in COUNTRY_NAMES.get(cc, ()))


def _path_location(path: str) -> str:
    """'/job/BR-RJ-MACAE-.../Titulo_R1' → 'BR-RJ-MACAE-...'. Outros formatos: ''."""
    parts = (path or "").split("/")
    return parts[2] if len(parts) >= 4 and parts[1] == "job" else ""


def _listing_in_country(j: dict, cc: str) -> bool | None:
    """True/False pela listagem; None quando só o detalhe decide (linha 'N Locations' ou sem local)."""
    loc = j.get("locationsText") or ""
    if _text_in_country(_path_location(j.get("externalPath") or ""), cc) or _text_in_country(loc, cc):
        return True
    if not loc.strip() or MULTI_LOC_RE.match(loc):
        return None
    return False


def _detail_in_country(info: dict, cc: str) -> bool:
    country = _d(info.get("country"))
    req_country = _d(_d(info.get("jobRequisitionLocation")).get("country"))
    if cc in {str(country.get("alpha2Code") or "").upper(), str(req_country.get("alpha2Code") or "").upper()}:
        return True
    if COUNTRY_WID.get(cc) and COUNTRY_WID[cc] in (country.get("id"), req_country.get("id")):
        return True
    texts = [info.get("location"), country.get("descriptor"), *_additional(info)]
    return any(_text_in_country(t, cc) for t in texts)


def _additional(info: dict) -> list[str]:
    add = info.get("additionalLocations")
    return [str(x).strip() for x in add if isinstance(x, str) and x.strip()] if isinstance(add, list) else []


def _info(d) -> dict | None:
    info = _d(d).get("jobPostingInfo")
    return info if isinstance(info, dict) else None


def _local_filter(ctx: CollectContext, batch: SourceBatch, api: str, stubs: list[dict], cc: str,
                  cache: dict) -> list[dict]:
    budget = int(ctx.source.limits.get("max_scope_details", 40))
    kept, out, checked, undecided = [], 0, 0, 0
    for j in stubs:
        verdict = _listing_in_country(j, cc)
        if verdict is None:
            path = j["externalPath"]
            if budget <= 0:
                undecided += 1
                continue
            budget -= 1
            checked += 1
            try:
                d = ctx.http.get_json(f"{api}{path}")
                info = _info(d)
                if info is None:
                    raise FormatChanged("detalhe Workday sem jobPostingInfo")
            except ERRORS as e:
                undecided += 1
                batch.warnings.append(f"filtro {cc}: detalhe de {workday_req_id(path)} falhou ({_code(e)}): "
                                      f"{str(e)[:120]}")
                continue
            cache[path] = d
            verdict = _detail_in_country(info, cc)
        if verdict:
            kept.append(j)
        else:
            out += 1
    batch.warnings.append(f"filtro local {cc}: {len(kept)} de {len(stubs)} mantidas; {out} fora do país; "
                          f"{checked} conferidas pelo detalhe")
    if undecided:
        batch.status = "partial"
        batch.warnings.append(f"filtro {cc}: {undecided} vagas sem decisão de país (detalhe falhou ou limite "
                              "max_scope_details); lote parcial")
    return kept


# ------------------------------------------------------------------ facetas

def _find_facet_value(facets, parameter: str, descriptor: str) -> tuple[bool, str | None]:
    """Percorre facetas aninhadas. Devolve (faceta_existe, id_do_valor)."""
    want = fold(descriptor)
    found_param, found_id = False, None

    def walk(items, current: str | None):
        nonlocal found_param, found_id
        for f in items or []:
            if not isinstance(f, dict):
                continue
            param = f.get("facetParameter") or current
            if isinstance(f.get("values"), list):
                if f.get("facetParameter") == parameter:
                    found_param = True
                walk(f["values"], param)
            elif param == parameter and fold(f.get("descriptor")) == want and f.get("id") and found_id is None:
                found_id = str(f["id"])
    walk(facets, None)
    return found_param, found_id


def _resolve_country(ctx: CollectContext, api: str, country: str) -> dict:
    """{'facet': {param: [id]}, 'facet_id': id} ou {'fallback_cc': 'BR'|None}. Erros de rede/formato sobem."""
    data = ctx.http.post_json(f"{api}/jobs", {"appliedFacets": {}, "limit": PAGE, "offset": 0, "searchText": ""})
    if not isinstance(data, dict) or not isinstance(data.get("facets"), list):
        raise FormatChanged("resposta Workday sem a lista facets (descoberta de faceta de país)")
    has_param, fid = _find_facet_value(data["facets"], COUNTRY_FACET_PARAM, country)
    cc = COUNTRY_ALPHA2.get(fold(country))
    if fid:
        return {"facet": {COUNTRY_FACET_PARAM: [fid]}, "facet_id": fid}
    if has_param and cc and COUNTRY_WID.get(cc):
        return {"facet": {COUNTRY_FACET_PARAM: [COUNTRY_WID[cc]]}, "facet_id": COUNTRY_WID[cc],
                "warning": f"'{country}' ausente da faceta {COUNTRY_FACET_PARAM} (sem vagas no país hoje); "
                           "consulta com o id global do país"}
    return {"fallback_cc": cc}


# ------------------------------------------------------------------ coleta

def collect(ctx: CollectContext) -> SourceBatch:
    p = ctx.source.params
    tenant, site, dc = p["tenant"], p["site"], p.get("dc", "wd1")
    search = str(p.get("search_text") or "")
    country = str(p.get("country_facet") or "").strip() or None
    local_cc = str(p.get("local_country_filter") or "").strip().upper() or None
    full_board = bool(p.get("full_board"))
    host = f"https://{tenant}.{dc}.myworkdayjobs.com"
    api = f"{host}/wday/cxs/{tenant}/{site}"
    scope: dict = {"search_text": search}  # sem filtros novos, o escopo é o mesmo da v1
    if full_board and (search or country or local_cc):
        return fail(new_batch(ctx, VERSION, scope), "config_invalid",
                    "full_board: true não combina com search_text, country_facet ou local_country_filter")
    if local_cc:
        scope["local_country_filter"] = local_cc
    applied: dict = {}
    pre_warnings: list[str] = []
    if country:
        scope["country_facet"] = country
        try:
            r = _resolve_country(ctx, api, country)
        except ERRORS as e:
            return fail(new_batch(ctx, VERSION, scope), _code(e), f"descoberta da faceta de país: {e}")
        if "facet" in r:
            applied = r["facet"]
            scope["facet"] = applied
            if r.get("warning"):
                pre_warnings.append(r["warning"])
        else:
            if not (local_cc or r["fallback_cc"]):
                return fail(new_batch(ctx, VERSION, scope), "config_invalid",
                            f"tenant sem faceta {COUNTRY_FACET_PARAM} e país '{country}' sem código conhecido; "
                            "declare local_country_filter")
            local_cc = local_cc or r["fallback_cc"]
            scope["local_country_filter"] = local_cc
            scope["facet_fallback"] = "local_country_filter"
            pre_warnings.append(f"tenant sem faceta {COUNTRY_FACET_PARAM}: usando filtro local {local_cc} "
                                "sobre a listagem")
    batch = new_batch(ctx, VERSION, scope)
    batch.warnings += pre_warnings
    if batch.coverage_kind == "full_board" and (search or applied or local_cc):
        batch.coverage_kind = "filtered_board"
        batch.warnings.append("coverage full_board declarado, mas a consulta tem filtro: tratado como filtered_board")

    stubs, error = _list(ctx, batch, api, applied, search)
    if error is not None:
        return error
    batch.raw_count = len(stubs)
    cache: dict = {}
    if local_cc:
        stubs = _local_filter(ctx, batch, api, stubs, local_cc, cache)
    for j in stubs:
        path, loc = j["externalPath"], j.get("locationsText") or None
        title = " ".join((j.get("title") or "").split())
        batch.jobs.append(JobObservation(
            platform="workday", tenant=tenant, external_id=workday_req_id(path), url=f"{host}/{site}{path}",
            title=title, location=loc, published_raw=j.get("postedOn") or None,
            published_source="workday:postedOn(relativo)", listing_signature=signature(j.get("title"), loc),
            talent_pool=True if POOL_RE.match(fold(loc)) else None,
            raw={"externalPath": path, "bulletFields": j.get("bulletFields"), "locationsText": loc}))
    if batch.status != "partial":
        batch.status = "complete"
    _details(ctx, batch, api, cache)
    return batch.finish()


def _list(ctx: CollectContext, batch: SourceBatch, api: str, applied: dict,
          search: str) -> tuple[list[dict], SourceBatch | None]:
    """Pagina a listagem. Devolve (linhas únicas com externalPath, lote_falho_ou_None). Marca parcial no lote."""
    max_pages = int(ctx.source.limits.get("max_pages", 15))
    offset, total, received, ghosts = 0, None, 0, 0
    stubs: list[dict] = []
    seen: set[str] = set()
    for _ in range(max_pages):
        try:
            data = ctx.http.post_json(f"{api}/jobs", {"appliedFacets": applied, "limit": PAGE, "offset": offset,
                                                      "searchText": search})
            if not isinstance(data, dict) or not isinstance(data.get("jobPostings"), list):
                raise FormatChanged("resposta Workday sem a lista jobPostings")
            if total is None and (not isinstance(data.get("total"), int) or isinstance(data.get("total"), bool)):
                raise FormatChanged("primeira página Workday sem total numérico")
        except ERRORS as e:
            if batch.pages_received:
                batch.status = "partial"
                batch.error_code, batch.error_message = _code(e), f"página offset={offset}: {e}"[:500]
                break
            return stubs, fail(batch, _code(e), str(e))
        if total is None:
            total = max(0, data["total"])
            batch.pages_expected = max(1, (total + PAGE - 1) // PAGE)
        posts = data["jobPostings"]
        batch.pages_received += 1
        received += len(posts)
        for j in posts:
            path = j.get("externalPath") if isinstance(j, dict) else None
            if not isinstance(path, str) or not path.strip():
                ghosts += 1
                continue
            if path not in seen:
                seen.add(path)
                stubs.append(j)
        offset += PAGE
        if offset >= total:
            break
        if not posts:
            batch.status = "partial"
            batch.warnings.append(f"página vazia em offset={offset - PAGE} com {received} de {total} recebidas")
            break
    else:
        if total and offset < total:
            batch.status = "partial"
            batch.warnings.append(f"limite de {max_pages} páginas atingido; total informado {total}")
    if ghosts:
        batch.warnings.append(f"{ghosts} entrada(s) da listagem sem externalPath ignorada(s)")
    return stubs, None


# ------------------------------------------------------------------ detalhe

def _apply_detail(obs: JobObservation, info: dict) -> None:
    text, status, orig, note = bounded(html_to_text(info.get("jobDescription") or ""))
    obs.description, obs.description_status, obs.original_length, obs.truncation_note = text, status, orig, note
    if info.get("startDate"):
        obs.published_raw, obs.published_source = info["startDate"], "workday:startDate"
    add = _additional(info)
    locs = list(dict.fromkeys([x for x in [str(info.get("location") or "").strip(), *add] if x]))
    if locs:
        obs.location = "; ".join(locs)
        if any(POOL_RE.match(fold(x)) for x in locs):
            obs.talent_pool = True
    tw = str(info.get("remoteType") or "").lower()
    obs.workplace = ("remote" if "remote" in tw else "hybrid" if "hybrid" in tw
                     else "onsite" if tw.replace("-", "") in ("onsite", "on site") else obs.workplace)
    country = _d(info.get("country"))
    obs.raw.update({
        "additionalLocations": add,
        "country": (str(_d(_d(info.get("jobRequisitionLocation")).get("country")).get("alpha2Code") or "")
                    or country.get("descriptor") or None),
        "jobReqId": info.get("jobReqId"), "endDate": info.get("endDate"), "canApply": info.get("canApply"),
        "timeType": info.get("timeType")})


def _details(ctx: CollectContext, batch: SourceBatch, api: str, cache: dict) -> None:
    budget = int(ctx.source.limits.get("max_details", 25))
    ttl = int(ctx.source.limits.get("detail_ttl_days", 7))
    warned = False
    for obs in batch.jobs:
        path = obs.raw["externalPath"]
        d = cache.get(path)
        if d is None:
            if not wants_detail(ctx, obs, ttl):
                _keep_stored_location(ctx, obs)
                continue
            if budget <= 0:
                if not warned:
                    batch.warnings.append("limite de detalhes atingido; restantes serão detalhados nos próximos ciclos")
                    warned = True
                _keep_stored_location(ctx, obs)
                continue
            budget -= 1
            try:
                d = ctx.http.get_json(f"{api}{path}")
            except ERRORS as e:
                batch.warnings.append(f"detalhe {obs.external_id}: {_code(e)}: {str(e)[:120]}")
                _keep_stored_location(ctx, obs)
                continue
        info = _info(d)
        if info is None:
            batch.warnings.append(f"detalhe {obs.external_id}: format_changed: sem jobPostingInfo")
            _keep_stored_location(ctx, obs)
            continue
        _apply_detail(obs, info)
        batch.details_fetched += 1


def _keep_stored_location(ctx: CollectContext, obs: JobObservation) -> None:
    """Sem detalhe nesta rodada: a vaga já conhecida mantém a localização gravada (vinda do detalhe)."""
    if ctx.known(obs.external_id, obs.url):
        obs.location = None


# ------------------------------------------------------------------ probe

def _cxs_target(url: str | None, params: dict) -> tuple[str, str] | None:
    """URL pública ou da API → (url_do_detalhe_cxs, url_da_listagem_cxs). None se não reconhecer."""
    try:
        u = urlsplit((url or "").strip())
    except ValueError:
        return None
    if u.scheme not in ("http", "https") or not u.netloc:
        return None
    host = f"https://{u.netloc.lower()}"
    seg = [s for s in u.path.split("/") if s]
    anchor = next((i for i, s in enumerate(seg) if s == "job"), None)
    if anchor is None or anchor + 1 >= len(seg):
        return None
    rest = "/" + "/".join(seg[anchor:])
    if "cxs" in seg[:anchor] and anchor >= 2:
        tenant, site = seg[anchor - 2], seg[anchor - 1]
    elif u.netloc.lower().endswith(".myworkdaysite.com") and "recruiting" in seg[:anchor]:
        i = seg.index("recruiting")
        if anchor - i != 3:
            return None
        tenant, site = seg[i + 1], seg[i + 2]
    else:
        if anchor < 1:
            return None
        site = seg[anchor - 1]
        tenant = str(params.get("tenant") or "")
        if not tenant or not u.netloc.lower().startswith(f"{tenant.lower()}."):
            tenant = u.netloc.split(".")[0]
    base = f"{host}/wday/cxs/{tenant}/{site}"
    return f"{base}{rest}", f"{base}/jobs"


def _site_answers(ctx: CollectContext, list_url: str) -> bool:
    try:
        data = ctx.http.post_json(list_url, {"appliedFacets": {}, "limit": PAGE, "offset": 0, "searchText": ""})
    except Exception:  # noqa: BLE001 - qualquer falha aqui só impede a conclusão "gone"
        return False
    return isinstance(data, dict) and isinstance(data.get("jobPostings"), list)


def probe(ctx: CollectContext, external_id: str | None, url: str | None) -> str:
    """Confere um anúncio. 'gone' só com prova forte; falha de rede ou formato estranho = 'unknown'.

    404/410 (HTTP_404) e 403 (S22 'permission denied') são as respostas observadas para vaga despublicada; nos dois
    casos a listagem do mesmo site precisa responder normalmente, senão pode ser tenant/site errado ou bloqueio.
    """
    target = _cxs_target(url, ctx.source.params or {})
    if target is None:
        return "unknown"
    detail_url, list_url = target
    try:
        d = ctx.http.get_json(detail_url)
    except SourceFailure as e:
        return "gone" if e.code == "not_found" and _site_answers(ctx, list_url) else "unknown"
    except Blocked:
        return "gone" if _site_answers(ctx, list_url) else "unknown"
    except Exception:  # noqa: BLE001 - FormatChanged e erros inesperados do cliente não provam nada
        return "unknown"
    info = _info(d)
    if info is None:
        return "unknown"
    if info.get("posted") is False:
        return "gone"
    if info.get("canApply") is False:
        return "unknown"
    return "alive"
