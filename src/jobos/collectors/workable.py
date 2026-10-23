"""Workable (widget público): GET apply.workable.com/api/v1/widget/accounts/{account}.

Portado de Artifact/jobos/sources/web.py::workable e ats.py::workable. A chave `jobs` (lista) precisa existir para a
resposta valer como reconhecida; lista vazia com a chave presente é "sem vagas" legítimo. O widget não tem rota de
detalhe própria: a descrição só entra se o item já a trouxer (campo `description`), caso contrário fica "missing".
"""
from __future__ import annotations

from jobos.collectors.base import (Blocked, CollectContext, FormatChanged, JobObservation, SourceBatch, SourceFailure,
                                   fail, new_batch, signature)
from jobos.collectors.text import bounded, html_to_text

VERSION = "workable/2"
API = "https://apply.workable.com/api/v1/widget/accounts/{account}"


def _location(j: dict) -> str | None:
    loc = j.get("location")
    if isinstance(loc, dict):
        loc = ", ".join(str(v) for v in loc.values() if v)
    if loc:
        return str(loc)
    return ", ".join(str(p) for p in (j.get("city"), j.get("state"), j.get("country")) if p) or None


def collect(ctx: CollectContext) -> SourceBatch:
    account = ctx.source.params["account"]
    batch = new_batch(ctx, VERSION)
    batch.pages_expected = 1
    try:
        # details=true traz a descrição de todas as vagas numa resposta (verificado em 23/10/2026 com a conta da DOF)
        params = {"details": "true"} if ctx.source.params.get("details", True) else None
        data = ctx.http.get_json(API.format(account=account), headers={"Accept": "application/json"}, params=params)
        if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
            raise FormatChanged("resposta Workable sem a lista jobs")
    except (FormatChanged, Blocked, SourceFailure) as e:
        return fail(batch, getattr(e, "code", "error"), str(e))
    items = data["jobs"]
    batch.pages_received = 1
    batch.raw_count = len(items)
    seen: set[str] = set()
    for j in items:
        ext = str(j.get("shortcode") or j.get("id") or "").strip() if isinstance(j, dict) else ""
        if not ext:
            batch.warnings.append("item sem shortcode ignorado")
            continue
        if ext in seen:
            continue
        seen.add(ext)
        location = _location(j)
        department = j.get("department") or None
        url = j.get("url") or j.get("shortlink") or f"https://apply.workable.com/{account}/j/{ext}/"
        text, status, orig, note = bounded(html_to_text(j.get("description") or ""))
        pub_raw = j.get("published_on") or j.get("created_at") or None
        batch.jobs.append(JobObservation(
            platform="workable", tenant=account, external_id=ext, url=url, title=(j.get("title") or "").strip(),
            location=location, workplace="remote" if j.get("telecommuting") is True else None, department=department,
            description=text, description_status=status, original_length=orig, truncation_note=note,
            published_raw=pub_raw, published_source="workable:published_on" if j.get("published_on") else "workable:created_at",
            listing_signature=signature(j.get("title"), location, department, pub_raw),
            raw={"shortcode": ext, "employment_type": j.get("employment_type")}))
    batch.status = "complete"
    return batch.finish()
