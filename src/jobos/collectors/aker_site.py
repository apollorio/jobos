"""Aker Solutions: busca de vagas do site corporativo (www.akersolutions.com/careers/job-search/).

Auditoria de 23/10/2026: o SmartRecruiters 'akersolutions' é um resquício (1 vaga de 2017) e não serve de fonte.
A lista real é a página de busca do site, renderizada no servidor:
  - um único <script> chama ReactDOMClient.hydrateRoot(...) com props que contêm o literal '"jobs":[' dentro do bloco
    JobListBlock. O array é decodificado com json.JSONDecoder().raw_decode a partir do '['.
  - item: {title:{linkText, href:'/careers/job-search?jobPostId=21726'}, location:"St. John's", region, country,
    jobType, positionType, deadline:'November 13, 2026'}. jobPostId é o ReqId da requisição no SuccessFactors.
  - TODAS as vagas vêm no array (o botão 'Load more' só pagina no navegador): cobertura full_board, lote completo
    quando o array é reconhecido e todos os itens trazem jobPostId. Nenhum país é escondido (Brasil hoje: 0).
  - detalhe: a mesma página com ?jobPostId=N traz o bloco EventArticle (EventInfo com Location, Apply by,
    Position type, Job ID # e o link de candidatura) e os blocos RichText com o texto da vaga. jobPostId desconhecido
    devolve a página de lista (sem EventInfo): isso é falha do detalhe, nunca "vaga encerrada".

Modo alternativo `params.sf_xml: true`: XML público do SuccessFactors
(career2.successfactors.eu/career?company=akersoluti&career_ns=job_listing_summary&resultType=XML). É um
superconjunto (39 ReqIds contra 33 no site), sem cidade e com o texto do modelo incompleto ([[responsibilities]] etc.
não preenchidos): o lote é sempre parcial e nunca autoriza ausência.

Identidade: platform 'successfactors', tenant = empresa SF ('akersoluti'), external_id = jobPostId/ReqId. É a mesma
nos dois modos e em probe().
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from urllib.parse import urljoin

from jobos.collectors.base import (Blocked, CollectContext, FormatChanged, JobObservation, SourceBatch, SourceFailure,
                                   fail, new_batch, signature, wants_detail)
from jobos.collectors.text import bounded, clean, html_to_text
from jobos.domain.identity import fold, safe_http_url

VERSION = "aker_site_json/1"
PLATFORM = "successfactors"
LIST_URL = "https://www.akersolutions.com/careers/job-search/"
SF_COMPANY = "akersoluti"
SF_HOST = "https://career2.successfactors.eu"
SF_XML_URL = SF_HOST + "/career"
SF_DETAIL_URL = SF_HOST + "/sfcareer/jobreqcareer"
EN_HEADERS = {"Accept-Language": "en-US,en;q=0.8"}

DECODER = json.JSONDecoder()
JOBS_RE = re.compile(r'"jobs"\s*:\s*\[')
POST_ID_RE = re.compile(r"[?&](?:jobPostId|jobId)=(\d+)", re.I)
HYDRATE_RE = re.compile(r"hydrateRoot\s*\(\s*[\w$.]+\s*,\s*React\.createElement\s*\(\s*[\w$.]+\s*,\s*(?=\{)")
PLACEHOLDER_RE = re.compile(r"\[\[\s*([A-Za-z_][\w]*)\s*\]\]")
XML_PROLOG_RE = re.compile(r"^\s*(?:<\?xml[^>]*\?>\s*)?(?:<!--.*?-->\s*)*<Job-Listing\b", re.S)
# Página do SF para requisição apagada/encerrada (verificada em 23/10/2026, HTTP 200):
# "This job cannot be viewed at this time. It has either been deleted or is no longer available for application."
SF_GONE_RE = re.compile(r"cannot be viewed at this time|no longer available for application", re.I)
MONTHS = {m: i for i, m in enumerate(("january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"), start=1)}
DATE_RE = re.compile(r"^([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})$")


# ------------------------------------------------------------------ utilidades

def _title(s) -> str:
    return clean(str(s or "").replace("​", ""))


def _iso_date(raw: str | None) -> str | None:
    """'November 13, 2026' → '2026-11-13'. Nomes de mês em inglês fixos (não depende do locale do sistema)."""
    m = DATE_RE.match((raw or "").strip())
    if not m or m.group(1).lower() not in MONTHS:
        return None
    month, day, year = MONTHS[m.group(1).lower()], int(m.group(2)), int(m.group(3))
    if not 1 <= day <= 31:
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def _post_id(url: str | None) -> str | None:
    m = POST_ID_RE.search(url or "")
    return m.group(1) if m else None


def _apply_url(jid: str, company: str) -> str:
    return f"{SF_DETAIL_URL}?jobId={jid}&company={company}"


def _walk(root):
    """Percorre dicts em ordem de documento (pai antes dos filhos), sem recursão."""
    stack = [root]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            yield cur
            stack.extend(reversed(list(cur.values())))
        elif isinstance(cur, list):
            stack.extend(reversed(cur))


def _company(ctx: CollectContext) -> str:
    return str(ctx.source.params.get("sf_company") or SF_COMPANY)


# ------------------------------------------------------------------ página de lista

def parse_list_page(html: str) -> list:
    """Array do bloco JobListBlock. FormatChanged se o literal faltar, se houver mais de uma lista ou se o JSON
    não decodificar: HTTP 200 com conteúdo inesperado nunca vira lista vazia."""
    html = html or ""
    hits = list(JOBS_RE.finditer(html))
    if not hits:
        raise FormatChanged('literal "jobs":[ ausente na página de vagas da Aker (layout novo, desafio ou erro)')
    if len(hits) > 1:
        raise FormatChanged(f'{len(hits)} listas "jobs" na página da Aker: não dá para saber qual é a de vagas')
    if '"JobListBlock"' not in html:
        raise FormatChanged('bloco JobListBlock ausente: a lista "jobs" pode não ser a de vagas')
    try:
        arr, _ = DECODER.raw_decode(html, hits[0].end() - 1)
    except ValueError as e:
        raise FormatChanged(f'array "jobs" inválido na página da Aker: {e}') from e
    if not isinstance(arr, list):
        raise FormatChanged('"jobs" não é uma lista')
    return arr


def _site_obs(item, company: str, list_url: str) -> JobObservation | None:
    """Item do array → observação. None quando o item não é reconhecível (sem jobPostId ou sem título)."""
    if not isinstance(item, dict) or not isinstance(item.get("title"), dict):
        return None
    href = str(item["title"].get("href") or "")
    jid = _post_id(href)
    title = _title(item["title"].get("linkText"))
    if not jid or not title:
        return None
    city, country = clean(item.get("location")) or None, clean(item.get("country")) or None
    location = ", ".join(dict.fromkeys(p for p in (city, country) if p)) or None
    deadline_raw = clean(item.get("deadline")) or None
    region, job_type, position = (clean(item.get(k)) or None for k in ("region", "jobType", "positionType"))
    return JobObservation(
        platform=PLATFORM, tenant=company, external_id=jid, url=urljoin(list_url, f"?jobPostId={jid}"), title=title,
        location=location, deadline=_iso_date(deadline_raw) or deadline_raw,
        listing_signature=signature(title, location, region, job_type, position, deadline_raw),
        raw={"jobPostId": jid, "href": href, "city": city, "country": country, "region": region, "jobType": job_type,
             "positionType": position, "deadline_raw": deadline_raw, "apply_url": _apply_url(jid, company),
             "via": "site_json"})


# ------------------------------------------------------------------ página de detalhe

def _hydrate_props(html: str, what: str) -> dict:
    m = HYDRATE_RE.search(html or "")
    if not m:
        raise FormatChanged(f"chamada hydrateRoot ausente na {what}")
    try:
        props, _ = DECODER.raw_decode(html, m.end())
    except ValueError as e:
        raise FormatChanged(f"props de hidratação inválidas na {what}: {e}") from e
    if not isinstance(props, dict):
        raise FormatChanged(f"props de hidratação não são um objeto na {what}")
    return props


def _info_key(label: str) -> str | None:
    lab = fold(label).rstrip(": #").strip()
    for prefix, key in (("job id", "job_id"), ("location", "location"), ("apply by", "deadline"),
                        ("position type", "position_type")):
        if lab.startswith(prefix):
            return key
    return None


def parse_detail_page(html: str, jid: str) -> dict:
    """Bloco EventArticle da vaga: EventInfo (campos rotulados) + textos RichText do artigo. Exige Job ID igual ao
    pedido; jobPostId desconhecido faz o site devolver a lista, que aqui vira FormatChanged."""
    props = _hydrate_props(html, "página da vaga")
    article = next((d for d in _walk(props) if d.get("blockName") == "EventArticle"), None)
    info = next((d for d in _walk(article or props) if d.get("blockName") == "EventInfo"), None)
    if not isinstance(info, dict) or not isinstance(info.get("eventInfo"), list):
        raise FormatChanged("página da vaga sem EventInfo (o site devolveu outra página ou o layout mudou)")
    fields: dict[str, str] = {}
    for row in info["eventInfo"]:
        if isinstance(row, dict):
            key = _info_key(clean(row.get("label")))
            if key and key not in fields:
                fields[key] = clean(row.get("value"))
    if fields.get("job_id") != str(jid):
        raise FormatChanged(f"Job ID da página ({fields.get('job_id')!r}) diferente do pedido ({jid})")
    parts: list[str] = []
    for d in _walk((article or {}).get("article")):
        if d.get("blockName") == "TitleSectionBlock" and isinstance(d.get("title"), str) and d["title"].strip():
            parts.append(clean(d["title"]))
        elif d.get("blockName") == "RichText" and isinstance(d.get("html"), str):
            t = html_to_text(d["html"])
            if t:
                parts.append(t)
    link = info.get("registerLink") if isinstance(info.get("registerLink"), dict) else {}
    return {"job_id": fields["job_id"], "location": fields.get("location") or None,
            "deadline_raw": fields.get("deadline") or None, "position_type": fields.get("position_type") or None,
            "apply_url": safe_http_url(link.get("href")), "description": "\n\n".join(parts)}


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
            d = parse_detail_page(html, obs.external_id)
        except (FormatChanged, Blocked, SourceFailure) as e:
            batch.warnings.append(f"detalhe {obs.external_id}: {getattr(e, 'code', 'erro')}: {str(e)[:120]}")
            continue
        text, status, orig, note = bounded(d["description"])
        if not text:
            batch.warnings.append(f"detalhe {obs.external_id}: página sem texto da vaga")
            continue
        obs.description, obs.description_status = text, status
        obs.original_length, obs.truncation_note = orig, note
        obs.location = obs.location or d["location"]
        obs.deadline = obs.deadline or _iso_date(d["deadline_raw"]) or d["deadline_raw"]
        if d["apply_url"]:
            obs.raw["apply_url"] = d["apply_url"]
        batch.details_fetched += 1


def _collect_site(ctx: CollectContext, company: str) -> SourceBatch:
    list_url = str(ctx.source.params.get("list_url") or LIST_URL)
    batch = new_batch(ctx, VERSION, {"mode": "site_json", "list_url": list_url, "sf_company": company})
    batch.pages_expected = 1
    try:
        _, html = ctx.http.get_text(list_url)
        items = parse_list_page(html)
    except (FormatChanged, Blocked, SourceFailure) as e:
        return fail(batch, getattr(e, "code", "error"), str(e))
    batch.pages_received = 1
    batch.raw_count = len(items)
    bad, seen = 0, set()
    for item in items:
        obs = _site_obs(item, company, list_url)
        if obs is None:
            bad += 1
            continue
        if obs.external_id in seen:
            continue
        seen.add(obs.external_id)
        batch.jobs.append(obs)
    if items and not batch.jobs:
        return fail(batch, "format_changed", f"{len(items)} itens em \"jobs\", nenhum com jobPostId e título: formato mudou")
    _details(ctx, batch)
    if bad:
        batch.status = "partial"
        batch.error_code = "incomplete_listing"
        batch.error_message = f"{bad} de {len(items)} itens sem jobPostId ou título; ausência não é inferida"
    else:
        batch.status = "complete"
    return batch.finish()


# ------------------------------------------------------------------ modo alternativo: XML do SuccessFactors

def parse_sf_xml(text: str) -> list[dict]:
    """Job-Listing/Job → [{req_id, title, description_html, filters}]. Recusa DOCTYPE/ENTITY e raiz diferente."""
    s = (text or "").lstrip("﻿")
    if not XML_PROLOG_RE.match(s):
        raise FormatChanged(f"XML do SuccessFactors sem a raiz Job-Listing (ou com DOCTYPE): {s.strip()[:80]!r}")
    try:
        root = ET.fromstring(s)
    except ET.ParseError as e:
        raise FormatChanged(f"XML do SuccessFactors inválido: {e}") from e
    if root.tag != "Job-Listing":
        raise FormatChanged(f"raiz inesperada no XML do SuccessFactors: {root.tag}")
    out = []
    for job in root.findall("Job"):
        filters = {}
        for child in job:
            label, value = child.find("label"), child.find("value")
            if label is not None and value is not None:
                filters[clean(label.text)] = clean(value.text)
        out.append({"req_id": (job.findtext("ReqId") or "").strip(), "title": _title(job.findtext("JobTitle")),
                    "description_html": job.findtext("Job-Description") or "", "filters": filters})
    return out


def _collect_sf_xml(ctx: CollectContext, company: str) -> SourceBatch:
    batch = new_batch(ctx, VERSION, {"mode": "sf_xml", "sf_company": company})
    batch.can_infer_absence = False
    batch.pages_expected = 1
    try:
        _, text = ctx.http.get_text(SF_XML_URL, params={"company": company, "career_ns": "job_listing_summary",
                                                         "resultType": "XML"})
        rows = parse_sf_xml(text)
    except (FormatChanged, Blocked, SourceFailure) as e:
        return fail(batch, getattr(e, "code", "error"), str(e))
    batch.pages_received = 1
    batch.raw_count = len(rows)
    seen: set[str] = set()
    for r in rows:
        jid = r["req_id"]
        if not jid.isdigit() or not r["title"]:
            batch.warnings.append(f"item do XML sem ReqId numérico ou sem título ignorado ({jid or 'sem ReqId'})")
            continue
        if jid in seen:
            continue
        seen.add(jid)
        holes = list(dict.fromkeys(PLACEHOLDER_RE.findall(r["description_html"])))
        text, status, orig, note = bounded(html_to_text(PLACEHOLDER_RE.sub(" ", r["description_html"])))
        if text and holes:
            status = "partial"
            note = "; ".join(p for p in (note, "XML do SF com seções do modelo não preenchidas: " + ", ".join(holes)) if p)
        f = r["filters"]
        country = f.get("Country") or None
        batch.jobs.append(JobObservation(
            platform=PLATFORM, tenant=company, external_id=jid, url=_apply_url(jid, company), title=r["title"],
            location=country, description=text, description_status=status, original_length=orig, truncation_note=note,
            listing_signature=signature("sf_xml", r["title"], country, f.get("Position Type"), f.get("Posting Career Track")),
            raw={"ReqId": jid, "filters": f, "apply_url": _apply_url(jid, company), "via": "sf_xml"}))
    batch.status = "partial"
    batch.warnings.append("modo XML do SuccessFactors: superconjunto do site (inclui requisições fora da busca pública), "
                          "sem cidade e com texto incompleto; ausência não é inferida")
    return batch.finish()


# ------------------------------------------------------------------ entrada

def collect(ctx: CollectContext) -> SourceBatch:
    company = _company(ctx)
    if ctx.source.params.get("sf_xml"):
        return _collect_sf_xml(ctx, company)
    return _collect_site(ctx, company)


def probe(ctx: CollectContext, external_id: str | None, url: str | None = None) -> str:
    """Confere UM anúncio pela página de requisição do SuccessFactors. A página do site não serve: jobPostId
    desconhecido devolve a lista inteira, sem distinguir vaga encerrada de erro.
      'gone'    → a página do SF diz explicitamente que a vaga foi apagada ou não aceita mais candidaturas;
      'alive'   → a página mostra a requisição pedida (título com '(ID)' ou 'Requisition ID ID') sem o aviso acima;
      'unknown' → rede, bloqueio, HTTP 404/410 na rota (rota mudou, não é prova sobre a vaga) ou página ambígua.
    """
    jid = str(external_id or "").strip() or _post_id(url) or ""
    if not jid.isdigit():
        return "unknown"
    try:
        _, html = ctx.http.get_text(SF_DETAIL_URL, headers=EN_HEADERS, params={"jobId": jid, "company": _company(ctx)})
    except (FormatChanged, Blocked, SourceFailure):
        return "unknown"
    html = html or ""
    text = html_to_text(html)  # '&nbsp;' e tags entre rótulo e número viram espaço
    gone = bool(SF_GONE_RE.search(text))
    alive = bool(re.search(rf"\(\s*{jid}\s*\)\s*</title>", html, re.I)
                 or re.search(rf"Requisition\s+ID\s*:?\s*{jid}\b", text, re.I))
    if gone and not alive:
        return "gone"
    if alive and not gone:
        return "alive"
    return "unknown"
