"""Airswift: quadro próprio em HubSpot CMS (tabela HubDB), filtrado por localidade, + detalhe com JSON-LD.

Auditoria de 23/10/2026: o tenant SmartRecruiters 'airswift' é um esboço morto de 2017; as vagas reais estão em
https://www.airswift.com/jobs. Endpoints observados (HTML público, não API documentada):
- Lista: GET /jobs?location=Brazil&page_num=N (N a partir de 1), 24 cards por página. Cada card é
  <article class="c-card-job-item"> com título e link em p.c-card-job-item__title > a[href="/jobs/<slug>-<id>"],
  local em p.c-card-job-item__location (após <img alt="Location">), data da lista após <img alt="Date Published">
  ("6 Oct 2026"), tipo de contratação em p.c-card-job-item__top-cell--left e resumo em p.c-card-job-item__summary.
  O cabeçalho informa o total: "Found 6 jobs on 1 page". Lista vazia reconhecida: "Found 0 jobs" ou
  "Sorry, we couldn't find any job listings matching these search parameters". Um comentário HTML expõe a consulta
  HubDB ("...location_grouped__icontains=Brazil&limit=24&offset=0"), usado para conferir tamanho e deslocamento.
  'Brasil' devolve 0: a localidade configurada é 'Brazil' (parâmetro `location`, escopo da fonte, entra no scope_id).
- Detalhe: GET /jobs/<slug>-<id> traz <script type="application/ld+json"> com @type JobPosting (description,
  datePosted, validThrough, employmentType, jobLocation) e o corpo em div.c-jobs-article-content. Slug errado ou
  vaga inexistente: HTTP 404 (cabeçalho x-hubspot-notfound).

Identidade: platform 'hubspot', tenant 'airswift.com', external_id = número final do caminho (a "Job reference").
O slug acompanha o título; a referência não.
Datas: a data da lista ("Date Published" do card) é a última publicação/republicação; o JSON-LD datePosted é a data
original do anúncio e tem preferência quando o detalhe é lido. validThrough fica em `raw` (não vira `deadline`,
porque só chega com o detalhe e alternaria o hash de conteúdo entre ciclos com e sem detalhe).
"""
from __future__ import annotations

import datetime as dt
import json
import re
from urllib.parse import urljoin, urlsplit

from jobos.collectors.base import (Blocked, CollectContext, FormatChanged, JobObservation, SourceBatch, SourceFailure,
                                   fail, new_batch, signature, wants_detail)
from jobos.collectors.text import bounded, clean, html_to_text
from jobos.domain.identity import fold
from jobos.timeutil import brt_date

VERSION = "airswift_hubspot/1"
PLATFORM = "hubspot"
TENANT = "airswift.com"
BASE = "https://www.airswift.com"
LIST_URL = BASE + "/jobs"
PAGE_SIZE = 24
DEFAULT_LOCATION = "Brazil"

CARD_RE = re.compile(r'<article\b[^>]*class="[^"]*\bc-card-job-item\b[^"]*"[^>]*>([\s\S]*?)</article>', re.I)
CARD_OPEN_RE = re.compile(r'<article\b[^>]*class="[^"]*\bc-card-job-item\b', re.I)
TITLE_P_RE = re.compile(r'<p\b[^>]*class="[^"]*\bc-card-job-item__title\b[^"]*"[^>]*>([\s\S]*?)</p>', re.I)
ANCHOR_RE = re.compile(r'<a\b[^>]*\bhref\s*=\s*"([^"]+)"[^>]*>([\s\S]*?)</a>', re.I)
LOCATION_P_RE = re.compile(r'<p\b[^>]*class="[^"]*\bc-card-job-item__location\b[^"]*"[^>]*>([\s\S]*?)</p>', re.I)
TYPE_P_RE = re.compile(r'<p\b[^>]*class="[^"]*\bc-card-job-item__top-cell--left\b[^"]*"[^>]*>([\s\S]*?)</p>', re.I)
SUMMARY_P_RE = re.compile(r'<p\b[^>]*class="[^"]*\bc-card-job-item__summary\b[^"]*"[^>]*>([\s\S]*?)</p>', re.I)
JOB_PATH_RE = re.compile(r"^/jobs/([^/?#]*?-)?(\d+)/?$")

HEADER_RE = re.compile(r"Found\s+([\d.,]+)\s+jobs?\s+on\s+([\d.,]+)\s+pages?", re.I)
EMPTY_RE = re.compile(r"couldn['’]?t find any job listings", re.I)
HUBDB_QUERY_RE = re.compile(r"<!--//[^>]*?\blimit=(\d+)&(?:amp;)?offset=(\d+)[^>]*//-->", re.I)

LDJSON_RE = re.compile(r'<script\b[^>]*type="application/ld\+json"[^>]*>([\s\S]*?)</script>', re.I)
ARTICLE_OPEN_RE = re.compile(r'<div\b[^>]*class="[^"]*\bc-jobs-article-content\b[^"]*"[^>]*>', re.I)
STAT_RE = re.compile(r'<div\b[^>]*class="[^"]*\bc-jobs-article-stats__content\b[^"]*"[^>]*>\s*<strong>([\s\S]*?)</strong>'
                     r'([\s\S]*?)</div>', re.I)
# Marcador explícito de vaga encerrada. Só é consultado quando a página NÃO é uma página de vaga normal (sem JobPosting).
CLOSED_RE = re.compile(r"(?:this|the)\s+(?:job|position|vacancy|role)\s+(?:is\s+no\s+longer\s+available|has\s+(?:expired|"
                       r"been\s+(?:closed|filled))|is\s+closed)|job\s+no\s+longer\s+available|vacancy\s+closed", re.I)

MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9,
          "oct": 10, "nov": 11, "dec": 12}
LIST_DATE_RE = re.compile(r"^(\d{1,2})\s+([A-Za-z]{3,9})\.?\s+(\d{4})$")


# ------------------------------------------------------------------ lista

def _list_date_iso(raw: str) -> str | None:
    """'6 Oct 2026' vira '2026-10-06'. Mapa próprio de meses: %b do strptime depende do locale do processo."""
    m = LIST_DATE_RE.match(clean(raw))
    if not m:
        return None
    month = MONTHS.get(m.group(2).lower()[:4]) or MONTHS.get(m.group(2).lower()[:3])
    if not month:
        return None
    try:
        return dt.date(int(m.group(3)), month, int(m.group(1))).isoformat()
    except ValueError:
        return None


def _after_img(block: str, alt: str) -> str:
    """Texto do <p> que começa com <img alt="..."> (forma usada pelo card para data e tipo)."""
    m = re.search(rf'<p\b[^>]*>\s*<img\b[^>]*\balt="{re.escape(alt)}"[^>]*>([\s\S]*?)</p>', block, re.I)
    return clean(html_to_text(m.group(1))) if m else ""


def _int(s: str) -> int | None:
    digits = re.sub(r"\D", "", s or "")
    return int(digits) if digits else None


def parse_card(block: str) -> dict | None:
    """Um card. None quando falta título, link ou referência numérica (card ilegível)."""
    tp = TITLE_P_RE.search(block)
    am = ANCHOR_RE.search(tp.group(1)) if tp else None
    if not am:
        return None
    url = urljoin(BASE + "/", clean(am.group(1)))
    parts = urlsplit(url)
    pm = JOB_PATH_RE.match(parts.path)
    if parts.netloc.lower() not in ("www.airswift.com", "airswift.com") or not pm:
        return None
    title = clean(html_to_text(am.group(2)))
    if not title:
        return None
    lm = LOCATION_P_RE.search(block)
    location_raw = clean(html_to_text(lm.group(1))) if lm else _after_img(block, "Location")
    tm = TYPE_P_RE.search(block)
    employment = clean(html_to_text(tm.group(1))) if tm else _after_img(block, "Employment Type")
    sm = SUMMARY_P_RE.search(block)
    date_raw = _after_img(block, "Date Published")
    return {"id": pm.group(2), "path": parts.path.rstrip("/"), "url": BASE + parts.path.rstrip("/"), "title": title,
            "location_raw": location_raw, "location": re.sub(r"\s+,", ",", location_raw) or None,
            "employment_type": employment or None, "list_date_raw": date_raw or None,
            "list_date": _list_date_iso(date_raw) if date_raw else None,
            "summary": clean(html_to_text(sm.group(1))) if sm else None}


def parse_list_page(html: str) -> dict:
    """Lê uma página da lista. Página sem nenhum marcador do quadro (desafio, login, layout novo) é FormatChanged."""
    html = html or ""
    blocks = CARD_RE.findall(html)
    opened = len(CARD_OPEN_RE.findall(html))
    text = html_to_text(html)
    hm = HEADER_RE.search(text)
    empty = bool(EMPTY_RE.search(text))
    if not (blocks or opened or hm or empty):
        raise FormatChanged("lista Airswift sem cards c-card-job-item, cabeçalho 'Found N jobs' ou aviso de lista vazia "
                            "(desafio/login/layout novo)")
    if opened > len(blocks):
        raise FormatChanged(f"{opened} cards abertos e só {len(blocks)} fechados: HTML truncado ou layout novo")
    rows, unparsed = [], 0
    for b in blocks:
        r = parse_card(b)
        if r is None:
            unparsed += 1
        else:
            rows.append(r)
    qm = HUBDB_QUERY_RE.search(html)
    return {"rows": rows, "cards": len(blocks), "unparsed": unparsed,
            "total": _int(hm.group(1)) if hm else None, "pages": _int(hm.group(2)) if hm else None,
            "empty_marker": empty,
            "limit": int(qm.group(1)) if qm else None, "offset": int(qm.group(2)) if qm else None}


def _location(ctx: CollectContext) -> str:
    loc = ctx.source.params.get("location", DEFAULT_LOCATION)
    return clean(str(loc)) if loc is not None else ""


def collect(ctx: CollectContext) -> SourceBatch:
    location = _location(ctx)
    batch = new_batch(ctx, VERSION, {"location": location, "board": LIST_URL})
    max_pages = max(1, int(ctx.source.limits.get("max_pages", 15)))
    seen: set[str] = set()
    cards_total = 0
    total = None
    page_size = PAGE_SIZE
    partial: list[str] = []
    capped = True
    for n in range(1, max_pages + 1):
        params = {"location": location, "page_num": n} if location else {"page_num": n}
        try:
            _, html = ctx.http.get_text(LIST_URL, params=params)
            page = parse_list_page(html)
            if page["limit"] is not None and page["offset"] is not None:
                if page["offset"] != (n - 1) * page["limit"]:
                    raise FormatChanged(f"page_num={n} ignorado: consulta HubDB com offset {page['offset']} "
                                        f"(esperado {(n - 1) * page['limit']})")
            if n == 1 and location and page["rows"] and not any(fold(location) in fold(r["location_raw"])
                                                               for r in page["rows"]):
                raise FormatChanged(f"nenhum card da primeira página contém '{location}': filtro de localidade ignorado")
            if n == 1 and page["cards"] and not page["rows"]:
                raise FormatChanged("cards c-card-job-item presentes, mas nenhum legível (título/link/referência)")
        except (FormatChanged, Blocked, SourceFailure) as e:
            if batch.pages_received:
                partial.append(f"página {n}: {getattr(e, 'code', 'erro')}: {str(e)[:160]}")
                batch.error_code = getattr(e, "code", "error")
                capped = False
                break
            return fail(batch, getattr(e, "code", "error"), str(e))
        batch.pages_received += 1
        cards_total += page["cards"]
        if n == 1:
            total = page["total"]
            batch.pages_expected = page["pages"]
            if page["limit"]:
                page_size = page["limit"]
        if page["unparsed"]:
            partial.append(f"página {n}: {page['unparsed']} card(s) ilegível(is)")
        if not page["cards"]:
            if n == 1:
                # Zero só com evidência positiva: "Found 0 jobs" ou o aviso explícito de lista vazia.
                if total == 0 or page["empty_marker"]:
                    batch.pages_expected = 1
                    batch.status = "complete"
                    return batch.finish()
                return fail(batch, "format_changed", "lista Airswift sem cards e sem aviso de lista vazia")
            if not page["empty_marker"] and total is None:
                partial.append(f"página {n} sem cards e sem aviso de lista vazia")
            capped = False
            break
        fresh = [r for r in page["rows"] if r["id"] not in seen]
        for r in fresh:
            seen.add(r["id"])
            batch.jobs.append(_observation(r))
        if page["rows"] and not fresh:
            if total is None:
                partial.append(f"página {n} repetiu vagas já lidas; sem total no cabeçalho para confirmar o fim")
            capped = False
            break  # o servidor repetiu a página anterior
        if page["cards"] < page_size or (total is not None and len(seen) >= total):
            capped = False
            break
    if capped:
        partial.append(f"limite de {max_pages} páginas atingido com página cheia; total informado {total}")
        batch.warnings.append(f"limite de {max_pages} páginas atingido")
    if total is not None and len(seen) != total:
        partial.append(f"cabeçalho informa {total} vagas, lidas {len(seen)}")
    batch.raw_count = cards_total
    _details(ctx, batch)
    if partial:
        batch.status = "partial"
        batch.error_code = batch.error_code or "incomplete_listing"
        batch.error_message = "; ".join(partial)[:500]
    else:
        batch.status = "complete"
    return batch.finish()


def _observation(r: dict) -> JobObservation:
    return JobObservation(
        platform=PLATFORM, tenant=TENANT, external_id=r["id"], url=r["url"], title=r["title"], location=r["location"],
        published_raw=r["list_date"], published_source="airswift:list_date" if r["list_date"] else None,
        listing_signature=signature(r["title"], r["location"], r["employment_type"], r["list_date"]),
        raw={"path": r["path"], "location_raw": r["location_raw"], "employment_type": r["employment_type"],
             "list_date": r["list_date_raw"], "summary": r["summary"]})


# ------------------------------------------------------------------ detalhe

def job_posting(html: str) -> dict | None:
    """Primeiro objeto JSON-LD com @type JobPosting (aceita lista e @graph). JSON inválido é ignorado."""
    for m in LDJSON_RE.finditer(html or ""):
        try:
            data = json.loads(m.group(1), strict=False)
        except ValueError:
            continue
        stack = [data]
        while stack:
            d = stack.pop(0)
            if isinstance(d, list):
                stack += d
            elif isinstance(d, dict):
                t = d.get("@type")
                if t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t):
                    return d
                if isinstance(d.get("@graph"), list):
                    stack += d["@graph"]
    return None


def _article_body(html: str) -> str | None:
    """Conteúdo de div.c-jobs-article-content, respeitando divs aninhadas."""
    m = ARTICLE_OPEN_RE.search(html or "")
    if not m:
        return None
    depth = 1
    for t in re.finditer(r"<(/?)div\b[^>]*>", html[m.end():], re.I):
        depth += -1 if t.group(1) else 1
        if depth == 0:
            return html[m.end():m.end() + t.start()]
    return None


def _stats(html: str) -> dict:
    return {clean(html_to_text(k)): clean(html_to_text(v)) for k, v in STAT_RE.findall(html or "")}


def parse_detail(html: str) -> dict:
    jp = job_posting(html)
    body = _article_body(html)
    if jp is None and body is None:
        raise FormatChanged("detalhe Airswift sem JSON-LD JobPosting e sem c-jobs-article-content")
    stats = _stats(html)
    desc_html = body if body and body.strip() else (jp or {}).get("description") or ""
    return {"posting": jp or {}, "description_html": desc_html, "stats": stats,
            "description_from": "article" if body and body.strip() else "jsonld"}


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
            d = parse_detail(html)
        except (FormatChanged, Blocked, SourceFailure) as e:
            batch.warnings.append(f"detalhe {obs.external_id}: {getattr(e, 'code', 'erro')}: {str(e)[:120]}")
            continue
        jp = d["posting"]
        text, status, orig, note = bounded(html_to_text(d["description_html"]))
        if text:
            obs.description, obs.description_status = text, status
            obs.original_length, obs.truncation_note = orig, note
        else:
            batch.warnings.append(f"detalhe {obs.external_id}: descrição vazia")
        if jp.get("datePosted"):
            obs.published_raw, obs.published_source = clean(str(jp["datePosted"])), "airswift:jsonld.datePosted"
        obs.department = d["stats"].get("Function") or obs.department
        obs.raw.update({"validThrough": jp.get("validThrough"), "datePosted": jp.get("datePosted"),
                        "jsonld_employmentType": jp.get("employmentType"),
                        "industry": (jp.get("industry") or {}).get("name") if isinstance(jp.get("industry"), dict)
                        else jp.get("industry"),
                        "sector": d["stats"].get("Sector"), "job_reference": d["stats"].get("Job reference"),
                        "description_from": d["description_from"]})
        ref = d["stats"].get("Job reference")
        if ref and ref != obs.external_id:
            batch.warnings.append(f"detalhe {obs.external_id}: página mostra a referência {ref}")
        batch.details_fetched += 1


# ------------------------------------------------------------------ verificação individual

def _past(value) -> bool:
    """validThrough anterior ao dia de hoje em Brasília. Só a parte de data conta; formato desconhecido não conta."""
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", str(value or "").strip())
    if not m:
        return False
    try:
        day = dt.date.fromisoformat(m.group(1))
    except ValueError:
        return False
    return day < brt_date()


def probe(ctx: CollectContext, external_id: str | None, url: str | None) -> str:
    """Confere UM anúncio. 'gone' só com evidência forte: HTTP 404/410 da própria Airswift na URL da vaga, a URL
    devolvendo a lista de vagas (redirecionamento para /jobs), validThrough no passado ou marcador explícito de
    encerramento. Erro de rede, bloqueio, conteúdo irreconhecível ou URL incoerente: 'unknown'."""
    if not url:
        return "unknown"  # o slug faz parte da URL: sem ela não há como montar o endereço
    parts = urlsplit(url)
    pm = JOB_PATH_RE.match(parts.path)
    if parts.netloc.lower() not in ("www.airswift.com", "airswift.com") or not pm:
        return "unknown"
    if external_id and pm.group(2) != str(external_id):
        return "unknown"
    try:
        status, html = ctx.http.get_text(BASE + parts.path.rstrip("/"))
    except SourceFailure as e:
        return "gone" if e.code == "not_found" else "unknown"
    except (Blocked, FormatChanged):
        return "unknown"
    except Exception:  # noqa: BLE001 - verificação não derruba o chamador
        return "unknown"
    if status in (404, 410):
        return "gone"
    if status != 200:
        return "unknown"
    jp = job_posting(html)
    if jp is not None:
        ref = _stats(html).get("Job reference")
        if ref and external_id and ref != str(external_id):
            return "unknown"
        return "gone" if _past(jp.get("validThrough")) else "alive"
    if _article_body(html) is not None:
        return "alive"
    text = html_to_text(html)
    if CARD_OPEN_RE.search(html) or HEADER_RE.search(text) or EMPTY_RE.search(text):
        return "gone"  # a URL da vaga caiu na lista de vagas
    if CLOSED_RE.search(text):
        return "gone"
    return "unknown"
