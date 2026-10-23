"""Sage People fRecruit em Salesforce Sites (Visualforce): lista pública de vagas + página de detalhe.

Auditoria de 23/10/2026 (Trident Energy): a conta Workable 'trident-energy' está vazia; o portal de candidatos do site
trident-energy.com é um iframe de `https://tridentenergy-hr.my.salesforce-sites.com/recruit/fRecruit__ApplyJobList`.
- Lista: GET {base}{site_path}/fRecruit__ApplyJobList. Linhas `<tr class="dataRow ...">` (às vezes " dataRow odd "),
  colunas pelo cabeçalho `th.headerRow`: Vacancy Name (link `fRecruit__ApplyJob?vacancyNo=VNnnn`), Vacancy No,
  Employment Type, Location Country, Location Region, Applications Close Date (quase sempre vazia).
  `div.pagingPanel` mostra "Page 1 of N". A navegação de páginas é postback A4J com ViewState (formulário), que o
  HttpLike não faz: com N > 1 o lote é parcial e avisa. Sem data de publicação na lista nem no detalhe.
- Detalhe: GET {base}{site_path}/fRecruit__ApplyJob?vacancyNo=VNnnn. `table.detailList` com linhas
  `th.labelCol > label` + `td.data2Col` (Vacancy Name, Vacancy No, Location Country, Location Region, Job Details,
  Key Requirements, Key Responsibilities, Currency...). O valor pode conter tabela aninhada (rich text).
- Vaga inexistente/encerrada: HTTP 200 sem `detailList` e com mensagem de página `errorM3`
  "That job is no longer open for applications." (verificado com VN99999).
Identidade: platform 'sage_frecruit', tenant = host do site, external_id = vacancyNo (VNnnn).
"""
from __future__ import annotations

import html as htmllib
import re
from urllib.parse import urljoin, urlsplit

from jobos.collectors.base import (Blocked, CollectContext, FormatChanged, JobObservation, SourceBatch, SourceFailure,
                                   fail, new_batch, signature, wants_detail)
from jobos.collectors.text import bounded, clean, html_to_text
from jobos.domain.identity import fold

VERSION = "sage_frecruit/1"
PLATFORM = "sage_frecruit"
DEFAULT_SITE_PATH = "/recruit"
LIST_PAGE = "fRecruit__ApplyJobList"
DETAIL_PAGE = "fRecruit__ApplyJob"

VN_RE = re.compile(r"vacancyNo=(VN\d+)", re.I)
VN_FULL_RE = re.compile(r"VN\d+", re.I)
ROW_RE = re.compile(r'<tr\b[^>]*\bclass="[^"]*\bdataRow\b[^"]*"[^>]*>(.*?)</tr>', re.S | re.I)
CELL_RE = re.compile(r"<td\b[^>]*>(.*?)</td>", re.S | re.I)
HEADER_RE = re.compile(r'<th\b[^>]*\bclass="[^"]*\bheaderRow\b[^"]*"[^>]*>(.*?)</th>', re.S | re.I)
LINK_RE = re.compile(r'<a\b[^>]*\bhref="([^"]*vacancyNo=VN\d+[^"]*)"[^>]*>(.*?)</a>', re.S | re.I)
PAGING_RE = re.compile(r'<[a-z]+\b[^>]*\bclass="[^"]*\bpagingPanel\b[^"]*"[^>]*>(.{0,4000})', re.S | re.I)
PAGE_OF_RE = re.compile(r"Page\s+(\d+)\s+of\s+(\d+)", re.I)
DETAIL_TABLE_RE = re.compile(r'<table\b[^>]*\bclass="[^"]*\bdetailList\b[^"]*"[^>]*>', re.I)
TABLE_TAG_RE = re.compile(r"<(/?)table\b", re.I)
LABEL_COL_SPLIT_RE = re.compile(r'<th\b[^>]*\bclass="[^"]*\blabelCol\b[^"]*"[^>]*>', re.I)
LABEL_RE = re.compile(r"<label\b[^>]*>(.*?)</label>", re.S | re.I)
DATA_COL_RE = re.compile(r'<td\b[^>]*\bclass="[^"]*\bdata2?Col\b[^"]*"[^>]*>', re.I)
MESSAGE_RE = re.compile(r'<div\b[^>]*\bclass="[^"]*\bmessageText\b[^"]*"[^>]*>(.*?)</div>', re.S | re.I)
ERROR_BLOCK_RE = re.compile(r'class="[^"]*\bmessage\s+error[A-Z]\d*\b', re.I)
# Evidência explícita de vaga fechada/inexistente (texto já dobrado: minúsculas, sem acentos)
CLOSED_RE = re.compile(r"no longer (open|available|accepting)|not (currently )?open|(has been|is) closed|vacancy closed"
                       r"|not found|does not exist|no longer exists|expired|nao esta mais|encerrad|nao (foi )?encontrad")
TALENT_TERMS = ("banco de talentos", "talent pool")

# Cabeçalho da lista → campo. Ordem padrão observada, usada só se o cabeçalho não vier.
COLUMNS = {"vacancy name": "title", "vacancy no": "vacancy_no", "employment type": "employment_type",
           "location country": "country", "location region": "region", "applications close date": "close_date"}
DEFAULT_ORDER = ["title", "vacancy_no", "employment_type", "country", "region", "close_date"]
# Rótulos do detalhe que são metadados (não entram na descrição)
DETAIL_META = {"vacancy name", "vacancy no", "location country", "location region", "employment type",
               "applications close date", "closing date", "currency"}


def _strip(fragment: str | None) -> str:
    """Texto de célula: sem tags, entidades resolvidas (Defici&ecirc;ncia), espaços normalizados."""
    return clean(re.sub(r"<[^>]+>", " ", fragment or ""))


def _label_key(fragment: str | None) -> str:
    """Rótulo comparável: sem tags, acentos, caixa e símbolos (a coluna ordenada ganha '▲'/'▼')."""
    return re.sub(r"[^a-z0-9]+", " ", fold(_strip(fragment))).strip()


def _site(ctx: CollectContext) -> tuple[str, str]:
    p = ctx.source.params
    base = str(p.get("base") or "").strip().rstrip("/")
    if not base.startswith(("http://", "https://")) or not urlsplit(base).netloc:
        raise SourceFailure("config", f"params.base inválido para fRecruit: {base!r}")
    path = "/" + str(p.get("site_path") or DEFAULT_SITE_PATH).strip().strip("/")
    return base, path


def _countries(ctx: CollectContext) -> list[str]:
    raw = ctx.source.params.get("country")
    vals = raw if isinstance(raw, list) else [raw] if raw else []
    return sorted({fold(str(v)) for v in vals if str(v).strip()})


def list_url(base: str, site_path: str) -> str:
    return f"{base}{site_path}/{LIST_PAGE}"


def detail_url(base: str, site_path: str, vacancy_no: str) -> str:
    return f"{base}{site_path}/{DETAIL_PAGE}?vacancyNo={vacancy_no}"


def parse_list(html: str) -> dict:
    """Devolve {rows, header_ok, page, pages}. Sem linhas e sem tabela reconhecível → FormatChanged."""
    headers = [_label_key(h) for h in HEADER_RE.findall(html or "")]
    header_ok = "vacancy name" in headers and "vacancy no" in headers
    order = [COLUMNS.get(h) for h in headers] if header_ok else DEFAULT_ORDER
    rows = []
    for body in ROW_RE.findall(html or ""):
        cells = CELL_RE.findall(body)
        rec: dict = {k: None for k in DEFAULT_ORDER}
        for i, cell in enumerate(cells):
            key = order[i] if i < len(order) else None
            if key:
                rec[key] = _strip(cell) or None
        link = LINK_RE.search(body)
        rec["href"] = htmllib.unescape(link.group(1)) if link else None
        if link:
            rec["title"] = _strip(link.group(2)) or rec["title"]
        m = VN_RE.search(rec["href"] or "")
        vn_cell = (rec.get("vacancy_no") or "").strip()
        rec["external_id"] = (m.group(1) if m else vn_cell if VN_FULL_RE.fullmatch(vn_cell) else None)
        rec["external_id"] = rec["external_id"].upper() if rec["external_id"] else None
        rows.append(rec)
    page = pages = None
    pm = PAGING_RE.search(html or "")
    if pm:
        po = PAGE_OF_RE.search(_strip(pm.group(1)))
        if po:
            page, pages = int(po.group(1)), int(po.group(2))
    if not rows and not header_ok:
        raise FormatChanged("lista fRecruit sem linhas dataRow e sem cabeçalho reconhecível (login/manutenção/layout novo)")
    return {"rows": rows, "header_ok": header_ok, "page": page, "pages": pages}


def _detail_tables(html: str) -> list[str]:
    """Conteúdo de cada table.detailList até o </table> correspondente (há tabelas aninhadas no rich text)."""
    out = []
    for m in DETAIL_TABLE_RE.finditer(html or ""):
        depth, pos = 1, m.end()
        for t in TABLE_TAG_RE.finditer(html, m.end()):
            depth += -1 if t.group(1) else 1
            pos = t.start()
            if depth == 0:
                break
        else:
            pos = len(html)
        out.append(html[m.end():pos])
    return out


def parse_detail(html: str) -> dict:
    """{fields: [(rótulo, texto)], values: {rótulo dobrado: texto}, error: mensagem da página ou None}."""
    fields: list[tuple[str, str]] = []
    for table in _detail_tables(html):
        for part in LABEL_COL_SPLIT_RE.split(table)[1:]:
            lm = LABEL_RE.search(part)
            label = _strip(lm.group(1) if lm else part.split("</th>", 1)[0])
            dm = DATA_COL_RE.search(part)
            if not label or not dm:
                continue
            # Quebra de linha crua no HTML é só espaço; quem quebra linha é o <br> (evita linhas em branco dobradas)
            fields.append((label, html_to_text(re.sub(r"[\r\n]+", " ", part[dm.end():]))))
    error = None
    if ERROR_BLOCK_RE.search(html or "") or MESSAGE_RE.search(html or ""):
        msgs = [html_to_text(x) for x in MESSAGE_RE.findall(html or "")]
        error = " ".join(m for m in msgs if m) or "mensagem de erro sem texto"
        error = re.sub(r"^\s*(error|erro)\s*:\s*", "", error, flags=re.I).strip()
    return {"fields": fields, "values": {_label_key(k): v for k, v in fields}, "error": error}


def _is_talent_pool(title: str) -> bool | None:
    t = fold(title)
    return True if any(term in t for term in TALENT_TERMS) else None


def _apply_detail(obs: JobObservation, d: dict) -> None:
    sections = [f"{label}:\n{text}" for label, text in d["fields"] if _label_key(label) not in DETAIL_META and text]
    text, status, orig, note = bounded("\n\n".join(sections))
    obs.description, obs.description_status = text, status
    obs.original_length, obs.truncation_note = orig, note
    vals = d["values"]
    close = vals.get("applications close date") or vals.get("closing date")
    if close:
        obs.deadline = close
    if vals.get("currency"):
        obs.raw["currency"] = vals["currency"]
    obs.raw["detail_labels"] = [label for label, _ in d["fields"]]


def collect(ctx: CollectContext) -> SourceBatch:
    countries = _countries(ctx)
    p = ctx.source.params
    batch = new_batch(ctx, VERSION, {"base": str(p.get("base") or "").rstrip("/"),
                                     "site_path": p.get("site_path") or DEFAULT_SITE_PATH, "country": countries or None})
    batch.pages_expected = 1
    try:
        base, site_path = _site(ctx)
        url = list_url(base, site_path)
        _, html = ctx.http.get_text(url)
        page = parse_list(html)
    except (FormatChanged, Blocked, SourceFailure) as e:
        return fail(batch, getattr(e, "code", "error"), str(e))
    batch.pages_received = 1
    tenant = urlsplit(base).netloc.lower()
    partial: list[str] = []
    if not page["header_ok"]:
        partial.append("cabeçalho da tabela não reconhecido; colunas lidas pela posição padrão")
    pages = page["pages"]
    if pages is None:
        partial.append("painel de paginação sem 'Page X of N': não dá para confirmar que a lista terminou")
    elif pages > 1:
        batch.pages_expected = pages
        partial.append(f"lista com {pages} páginas; a navegação do Visualforce é postback com ViewState (não suportada): "
                       f"lida só a página {page['page'] or 1}")
    rows = page["rows"]
    batch.raw_count = len(rows)
    seen: set[str] = set()
    skipped_scope = 0
    for rec in rows:
        ext = rec["external_id"]
        if not ext:
            partial.append("linha da lista sem vacancyNo (não identificável)")
            continue
        if ext in seen:
            continue
        seen.add(ext)
        if countries and fold(rec.get("country")) not in countries:
            skipped_scope += 1
            continue
        region, country = rec.get("region"), rec.get("country")
        location = ", ".join(x for x in (region, country) if x) or None
        title = rec.get("title") or ""
        raw = {"vacancy_no": ext, "employment_type": rec.get("employment_type"), "country": country, "region": region}
        if region and fold(region).startswith("offshore"):
            raw["workplace_hint"] = "offshore"
        elif region and fold(region).startswith("onshore"):
            raw["workplace_hint"] = "onshore"
        href = rec.get("href")
        job_url = urljoin(url, href) if href else detail_url(base, site_path, ext)
        batch.jobs.append(JobObservation(
            platform=PLATFORM, tenant=tenant, external_id=ext, url=job_url, title=title, location=location,
            deadline=rec.get("close_date"), talent_pool=_is_talent_pool(title),
            listing_signature=signature(title, location, rec.get("employment_type"), rec.get("close_date")), raw=raw))
    if skipped_scope:
        batch.warnings.append(f"{skipped_scope} vaga(s) fora do escopo de país declarado ({', '.join(countries)})")
    if not rows and pages is not None and pages <= 1:
        batch.warnings.append("lista reconhecida e vazia (Page 1 of 1/0)")
    _details(ctx, batch, base, site_path)
    if partial:
        batch.status = "partial"
        batch.error_code, batch.error_message = "incomplete_listing", "; ".join(dict.fromkeys(partial))[:500]
        batch.warnings.extend(dict.fromkeys(partial))
    else:
        batch.status = "complete"
    return batch.finish()


def _details(ctx: CollectContext, batch: SourceBatch, base: str, site_path: str) -> None:
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
            _, html = ctx.http.get_text(detail_url(base, site_path, obs.external_id))
            d = parse_detail(html)
        except (FormatChanged, Blocked, SourceFailure) as e:
            batch.warnings.append(f"detalhe {obs.external_id}: {getattr(e, 'code', 'erro')}: {str(e)[:120]}")
            continue
        if not d["fields"]:
            why = f"página diz: {d['error'][:100]}" if d["error"] else "sem table.detailList (layout novo?)"
            batch.warnings.append(f"detalhe {obs.external_id}: {why}; mantida a vaga da lista")
            continue
        vno = (d["values"].get("vacancy no") or "").strip().upper()
        if vno and vno != obs.external_id:
            batch.warnings.append(f"detalhe {obs.external_id}: página trouxe a vaga {vno}; descrição ignorada")
            continue
        _apply_detail(obs, d)
        batch.details_fetched += 1


def probe(ctx: CollectContext, external_id: str | None, url: str | None) -> str:
    """Confere UM anúncio. 'gone' só com evidência forte: HTTP 404/410 ou página sem detailList com mensagem explícita
    de vaga fechada/inexistente ("That job is no longer open for applications."). 'alive' quando o detailList traz a
    mesma vaga. Rede, bloqueio, configuração ou página sem detailList e sem mensagem explícita → 'unknown'."""
    vn = (external_id or "").strip().upper()
    if not VN_FULL_RE.fullmatch(vn):
        m = VN_RE.search(url or "")
        vn = m.group(1).upper() if m else ""
    if not vn:
        return "unknown"
    try:
        base, site_path = _site(ctx)
        target = detail_url(base, site_path, vn)
    except SourceFailure:
        if not (url or "").startswith(("http://", "https://")):
            return "unknown"
        target = url
    try:
        status, html = ctx.http.get_text(target)
    except SourceFailure as e:
        return "gone" if e.code == "not_found" else "unknown"
    except (Blocked, FormatChanged):
        return "unknown"
    if status in (404, 410):
        return "gone"
    if status != 200:
        return "unknown"
    d = parse_detail(html)
    if d["fields"]:
        vno = (d["values"].get("vacancy no") or "").strip().upper()
        return "alive" if not vno or vno == vn else "unknown"
    if d["error"] and CLOSED_RE.search(fold(d["error"])):
        return "gone"
    return "unknown"
