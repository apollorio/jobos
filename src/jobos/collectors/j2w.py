"""SAP SuccessFactors (Jobs2Web): busca pública por localidade, paginada por startrow, + detalhe da vaga.

Portado de Artifact/jobos/sources/web.py (j2w_busca, _j2w_da_busca, _limpar_titulo_j2w, _limpar_local_j2w,
detalhe_j2w, _data_j2w_para_iso) e da paginação por startrow de assets/load-jobs.ts (loadSuccessFactors).

Diferenças em relação ao legado: a busca é paginada até o fim (o legado lia só 2 páginas), o total informado
pelo rótulo de paginação é registrado, página sem marcador reconhecível vira format_changed (nunca "zero vagas"),
limite de páginas atingido = parcial, e a descrição não é cortada em 6000 caracteres.
A localidade da busca (`locationsearch`) é o escopo configurado da fonte e entra no scope_id; o adapter
não filtra nada por cidade além disso.
"""
from __future__ import annotations

import html as htmllib
import re
from urllib.parse import quote_plus, urljoin, urlsplit

from jobos.collectors.base import (Blocked, CollectContext, FormatChanged, JobObservation, SourceBatch, SourceFailure,
                                   fail, new_batch, signature, wants_detail)
from jobos.collectors.text import bounded, clean, html_to_text
from jobos.domain.identity import j2w_id

VERSION = "j2w_search/1"

ROW_RE = re.compile(r'<tr\b[^>]*class="[^"]*data-row[^"]*"[\s\S]*?</tr>', re.I)
ANCHOR_RE = re.compile(r"<a\b([^>]*jobTitle-link[^>]*)>(.*?)</a>", re.I | re.S)
HREF_RE = re.compile(r'href\s*=\s*"([^"]+)"', re.I)
LOCATION_RE = re.compile(r'class="[^"]*jobLocation[^"]*"[^>]*>([\s\S]*?)</span>', re.I)
MARKER_RE = re.compile(r"jobTitle-link|\bdata-row\b|paginationLabel", re.I)

# Rótulo de paginação: "Results 1 - 25 of 123" / "Resultados 1 - 25 de 123" (travessão do SAP incluso), com ou sem tags.
_DASH = "[" + chr(0x2013) + chr(0x2014) + "-]"  # travessões do SAP e hífen
_GAP = r"(?:<[^>]+>|\s)*"
RESULTS_RE = re.compile(rf"(?:Results?|Resultados?){_GAP}\d+{_GAP}{_DASH}{_GAP}\d+{_GAP}(?:of|de){_GAP}([\d.,]+)", re.I)
LABEL_RE = re.compile(r'class="[^"]*paginationLabel[^"]*"[^>]*>([\s\S]*?)</span>', re.I)
LABEL_TOTAL_RE = re.compile(r"\b(?:of|de)\s+([\d.,]+)", re.I)

NO_RESULTS_RE = re.compile(
    r"no results|no jobs? (?:found|match)|nenhum resultado|nenhuma vaga|sem resultados|"
    r"there are currently no open positions|no open positions|n[aã]o h[aá] vagas", re.I)
SEARCH_PAGE_RE = re.compile(r'locationsearch|action="[^"]*/search/?"|searchResultsShell', re.I)

# CEP e número de referência colados no fim do título ("Operations HSSE Manager 20021 290").
LIXO_FINAL_J2W = re.compile(r"(?:\s+\d{5}\s+\d{3}|\s+\d{6,})\s*$")
MAIS_LOCAIS = re.compile(r"\+\s*\d+\s*more.*$", re.I | re.S)

MESES_EN = {"jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05", "jun": "06",
            "jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12"}
DATA_J2W = re.compile(r"\w{3}\s+(\w{3})\s+(\d{1,2})\s+[\d:]+\s+\w+\s+(\d{4})")

DESC_OPEN_RE = re.compile(r'<(span|div|p|section|article)\b[^>]*\bitemprop="description"[^>]*>', re.I)
DATE_TAG_RE = re.compile(r'<[^>]*itemprop="datePosted"[^>]*>', re.I)


def _limpar_titulo_j2w(titulo: str, token: str = "") -> str:
    """Tira a cidade grudada na frente (quando vem de slug) e o CEP/referência colado no fim."""
    cidade = token.replace("-", " ").strip()
    if cidade and titulo.lower().startswith(cidade.lower()):
        titulo = titulo[len(cidade):].strip(" -\u2013\u2014")
    titulo = LIXO_FINAL_J2W.sub("", titulo)
    return re.sub(r"\s{2,}", " ", titulo).strip()


def _limpar_local_j2w(bruto: str) -> str:
    """'Rio de Janeiro, BR, 20021-290 +1 more...' vira 'Rio de Janeiro' (CEP, país e '+N more' saem)."""
    v = MAIS_LOCAIS.sub("", bruto or "").strip()
    v = re.sub(r",?\s*\d{5}-?\d{3}\s*$", "", v)
    v = v.split(",")[0]
    return re.sub(r"\s{2,}", " ", v).strip(" ,")


def _data_j2w_para_iso(bruto: str) -> str:
    """A SAP devolve 'Mon Aug 17 00:00:00 UTC 2026'; vira '2026-08-17'. Sem casar, devolve os 10 primeiros caracteres."""
    m = DATA_J2W.search(bruto or "")
    if not m:
        return (bruto or "")[:10]
    mes = MESES_EN.get(m.group(1).lower())
    if not mes:
        return ""
    return f"{m.group(3)}-{mes}-{int(m.group(2)):02d}"


def parse_rows(html: str, base: str) -> list[dict]:
    """Linhas da busca: tr.data-row com a.jobTitle-link e span.jobLocation. Sem linhas de tabela, cada âncora vale uma linha."""
    blocks = ROW_RE.findall(html or "") or [m.group(0) for m in ANCHOR_RE.finditer(html or "")]
    rows, seen = [], set()
    for block in blocks:
        am = ANCHOR_RE.search(block)
        if not am:
            continue
        hm = HREF_RE.search(am.group(1))
        if not hm:
            continue
        href = htmllib.unescape(hm.group(1)).strip()
        url = urljoin(base.rstrip("/") + "/", href)
        path = urlsplit(url).path
        if path in seen:
            continue
        seen.add(path)
        lm = LOCATION_RE.search(block)
        titulo_bruto = clean(html_to_text(am.group(2))) or path
        local_bruto = html_to_text(lm.group(1)) if lm else ""
        rows.append({"path": path, "url": url, "id": j2w_id(path),
                     "title_raw": titulo_bruto, "title": _limpar_titulo_j2w(titulo_bruto),
                     "location_raw": local_bruto, "location": _limpar_local_j2w(local_bruto)})
    return rows


def parse_total(html: str) -> int | None:
    """Total de resultados do rótulo de paginação, se houver."""
    m = RESULTS_RE.search(html or "")
    if not m:
        lm = LABEL_RE.search(html or "")
        m = LABEL_TOTAL_RE.search(html_to_text(lm.group(1))) if lm else None
    if not m:
        return None
    digits = re.sub(r"\D", "", m.group(1))
    return int(digits) if digits else None


def _no_results(html: str) -> bool:
    return bool(NO_RESULTS_RE.search(html_to_text(html))) and bool(SEARCH_PAGE_RE.search(html or ""))


def _read_page(html: str, base: str) -> tuple[list[dict], int | None]:
    if not (MARKER_RE.search(html or "") or _no_results(html)):
        raise FormatChanged("busca J2W sem jobTitle-link/data-row/rótulo de paginação (login/desafio/layout novo)")
    return parse_rows(html, base), parse_total(html)


def collect(ctx: CollectContext) -> SourceBatch:
    p = ctx.source.params
    base = str(p["base"]).rstrip("/")
    location = str(p.get("location") or "")
    tenant = urlsplit(base).netloc.lower()
    batch = new_batch(ctx, VERSION, {"locationsearch": location})
    max_pages = int(ctx.source.limits.get("max_pages", 15))
    q = quote_plus(location)
    seen: set[str] = set()
    start, page_size, total = 0, 0, None
    for page in range(max_pages):
        url = f"{base}/search/?q=&locationsearch={q}&startrow={start}"
        try:
            _, html = ctx.http.get_text(url)
            rows, page_total = _read_page(html, base)
        except (FormatChanged, Blocked, SourceFailure) as e:
            if batch.pages_received:
                batch.status = "partial"
                batch.error_code, batch.error_message = getattr(e, "code", "error"), f"página startrow={start}: {e}"[:500]
                break
            return fail(batch, getattr(e, "code", "error"), str(e))
        batch.pages_received += 1
        if total is None:
            total = page_total
        if not rows:
            if page == 0:
                # Vazio só vale com evidência positiva: total 0 no rótulo ou mensagem explícita de "sem vagas".
                if total == 0 or _no_results(html):
                    batch.pages_expected = 1
                    batch.status = "complete"
                    return batch.finish()
                return fail(batch, "format_changed", "marcadores da busca J2W presentes, mas nenhuma vaga lida")
            break  # fim dos resultados
        fresh = [r for r in rows if r["path"] not in seen]
        if not fresh:
            break  # o servidor repetiu a última página
        for r in fresh:
            seen.add(r["path"])
            batch.jobs.append(_observation(tenant, r))
        if page == 0:
            page_size = len(rows)
            batch.pages_expected = (total + page_size - 1) // page_size if total else None
        start += page_size
        if (total is not None and start >= total) or len(rows) < page_size:
            break
    else:
        batch.status = "partial"
        batch.warnings.append(f"limite de {max_pages} páginas atingido; total informado {total}")
    batch.raw_count = len(seen)
    if batch.status != "partial":
        batch.status = "complete"
    _details(ctx, batch)
    return batch.finish()


def _observation(tenant: str, r: dict) -> JobObservation:
    return JobObservation(
        platform="successfactors_j2w", tenant=tenant, external_id=r["id"], url=r["url"], title=r["title"],
        location=r["location"] or None, listing_signature=signature(r["title"], r["location"]),
        raw={"path": r["path"], "title_raw": r["title_raw"], "location_raw": r["location_raw"]})


def _itemprop_description(html: str) -> str | None:
    """Conteúdo do elemento itemprop="description", respeitando elementos aninhados do mesmo tipo."""
    m = DESC_OPEN_RE.search(html or "")
    if not m:
        return None
    tag = m.group(1).lower()
    token = re.compile(rf"<(/?){tag}\b[^>]*?(/?)>", re.I)
    depth = 1
    for t in token.finditer(html, m.end()):
        if t.group(2):
            continue
        depth += -1 if t.group(1) else 1
        if depth == 0:
            return html[m.end():t.start()]
    return None


def _date_posted(html: str) -> str | None:
    tm = DATE_TAG_RE.search(html or "")
    if not tm:
        return None
    cm = re.search(r'content="([^"]+)"', tm.group(0))
    if cm:
        raw = cm.group(1)
    else:
        tail = re.match(r"([^<]+)", html[tm.end():])
        raw = tail.group(1) if tail else ""
    return clean(raw) or None


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
        body = _itemprop_description(html)
        if body is None:
            batch.warnings.append(f"detalhe {obs.external_id}: itemprop=description ausente ou sem fechamento")
            continue
        text, status, orig, note = bounded(html_to_text(body))
        obs.description, obs.description_status = text, status
        obs.original_length, obs.truncation_note = orig, note
        raw_date = _date_posted(html)
        if raw_date:
            iso_date = _data_j2w_para_iso(raw_date) if DATA_J2W.search(raw_date) else raw_date
            obs.published_raw, obs.published_source = iso_date or raw_date, "j2w:datePosted"
            obs.raw["datePosted"] = raw_date
        batch.details_fetched += 1
