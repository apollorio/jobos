"""vagas.com.br (página corporativa trabalheconosco.vagas.com.br/{slug}/oportunidades).

Portado de Artifact/jobos/sources/web.py::vagas_com_br. A página da Sapura (seagems) já veio sem vagas abertas, e a
própria página diz isso: "zero confirmado" é diferente de "falhei ao ler". Por isso zero resultados só vira lote
completo quando o texto explícito de página vazia aparece; sem isso (e sem nenhum link de vaga) é format_changed.
Não há rota de detalhe no legado: a descrição fica "missing" e o local, desconhecido.
"""
from __future__ import annotations

import re

from jobos.collectors.base import (Blocked, CollectContext, FormatChanged, JobObservation, SourceBatch, SourceFailure,
                                   fail, new_batch, signature)
from jobos.collectors.text import clean, html_to_text

VERSION = "vagas_com_br/1"
SITE = "https://www.vagas.com.br"
LINK_RE = re.compile(r'<a\b[^>]*\bhref="((?:https?://www\.vagas\.com\.br)?/vagas/[^"]+)"[^>]*>([\s\S]{3,140}?)</a>', re.I)
VAGAS_VAZIO = re.compile(r"nenhuma vaga|n[aã]o h[aá] vagas|no momento n[aã]o", re.I)
ID_RE = re.compile(r"/vagas/(v\d+)", re.I)


def collect(ctx: CollectContext) -> SourceBatch:
    slug = ctx.source.params["slug"]
    batch = new_batch(ctx, VERSION)
    batch.pages_expected = 1
    try:
        _, html = ctx.http.get_text(f"https://trabalheconosco.vagas.com.br/{slug}/oportunidades")
    except (FormatChanged, Blocked, SourceFailure) as e:
        return fail(batch, getattr(e, "code", "error"), str(e))
    batch.pages_received = 1
    seen: set[str] = set()
    for m in LINK_RE.finditer(html or ""):
        href, title = m.group(1), clean(html_to_text(m.group(2)))
        path = href[len(SITE):] if href.startswith("http") else href
        if not title or path in seen:
            continue
        seen.add(path)
        idm = ID_RE.search(path)
        ext = idm.group(1) if idm else path.rstrip("/").rsplit("/", 1)[-1]
        batch.jobs.append(JobObservation(
            platform="vagas_com_br", tenant=slug, external_id=ext, url=SITE + path, title=title,
            listing_signature=signature(title), raw={"path": path}))
    batch.raw_count = len(batch.jobs)
    if not batch.jobs and not VAGAS_VAZIO.search(html_to_text(html)):
        return fail(batch, "format_changed", "vagas.com.br: nenhum link de vaga e sem texto explícito de página vazia")
    batch.status = "complete"
    return batch.finish()
