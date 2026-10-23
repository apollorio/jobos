"""Greenhouse (boards-api.greenhouse.io): quadro inteiro ou escritório específico.

Portado de Artifact/jobos/sources/web.py (greenhouse) e assets/load-jobs.ts (loadGreenhouse + walkDepts).
Dois modos, escolhidos pelos params da fonte:
  - com `office_id`: GET /boards/{board}/offices/{office_id}, percorrendo departments[].jobs (e escritórios/departamentos
    filhos). A lista não traz descrição: ela vem de GET /boards/{board}/jobs/{id} dentro do orçamento de detalhes.
  - sem `office_id`: GET /boards/{board}/jobs?content=true (quadro completo, com descrição).
O escritório configurado é escopo da consulta e entra no scope_id. O `content` vem com HTML escapado duas vezes;
html_to_text desescapa antes e depois de tirar as tags.
Não portado: local_greenhouse (inferência de cidade pelo título, dependente do módulo triage legado). A localização
fica como a API informa: location.name, que é o ESCRITÓRIO e não necessariamente a cidade da vaga.
"""
from __future__ import annotations

from jobos.collectors.base import (Blocked, CollectContext, FormatChanged, JobObservation, SourceBatch, SourceFailure,
                                   fail, new_batch, signature, wants_detail)
from jobos.collectors.text import bounded, html_to_text

VERSION = "greenhouse/2"
API = "https://boards-api.greenhouse.io/v1/boards/{board}"


def _published(j: dict) -> tuple[str | None, str | None]:
    """first_published primeiro: updated_at é a última mexida no anúncio, não a publicação."""
    if j.get("first_published"):
        return j["first_published"], "greenhouse:first_published"
    if j.get("updated_at"):
        return j["updated_at"], "greenhouse:updated_at"
    return None, None


def _walk_departments(depts, into: list, seen: set) -> bool:
    """Coleta jobs de departments[].jobs (e children). Devolve True se algum departamento trouxe a chave `jobs`."""
    saw_jobs = False
    for dept in depts or []:
        if not isinstance(dept, dict):
            continue
        if isinstance(dept.get("jobs"), list):
            saw_jobs = True
            for j in dept["jobs"]:
                if isinstance(j, dict) and j.get("id") is not None and str(j["id"]) not in seen:
                    seen.add(str(j["id"]))
                    into.append((j, dept.get("name") or None))
        saw_jobs = _walk_departments(dept.get("children"), into, seen) or saw_jobs
    return saw_jobs


def _office_stubs(ctx: CollectContext, board: str, office_id) -> tuple[list[tuple[dict, str | None]], str | None]:
    """Escritório e TODOS os descendentes. A API devolve só `child_ids` (sem filhos embutidos): cada filho é buscado."""
    stubs: list[tuple[dict, str | None]] = []
    seen_jobs: set[str] = set()
    visited: set = set()
    pending = [office_id]
    root_name = None
    cap = int(ctx.source.limits.get("max_pages", 15))
    while pending:
        oid = pending.pop(0)
        if oid in visited:
            continue
        if len(visited) >= cap:
            raise SourceFailure("page_cap", f"mais de {cap} escritórios na árvore; leitura interrompida")
        visited.add(oid)
        data = ctx.http.get_json(f"{API.format(board=board)}/offices/{oid}")
        if not isinstance(data, dict) or not isinstance(data.get("departments"), list):
            raise FormatChanged("resposta do escritório Greenhouse sem a lista departments")
        saw = _walk_departments(data["departments"], stubs, seen_jobs)
        if data["departments"] and not saw:
            raise FormatChanged("departments presentes, mas nenhum com a chave jobs: formato do escritório mudou")
        root_name = root_name or data.get("name")
        pending += [c for c in (data.get("child_ids") or []) if c not in visited]
        pending += [c.get("id") for c in (data.get("children") or []) if isinstance(c, dict) and c.get("id") not in visited]
    return stubs, root_name


def _subtree_stubs(ctx: CollectContext, board: str, root_id) -> list[tuple[dict, str | None]]:
    """Quadro completo (com descrição) filtrado pela árvore de escritórios: fica a vaga cujo escritório OU algum
    ancestral é o escritório-raiz (ex.: 'Brazil' 69385 inclui 'Brazil - Rio de Janeiro' e 'Brazil - Sao Paulo')."""
    data = ctx.http.get_json(f"{API.format(board=board)}/jobs?content=true")
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        raise FormatChanged("resposta do quadro Greenhouse sem a lista jobs")
    parent: dict = {}
    for j in data["jobs"]:
        for o in j.get("offices") or []:
            if isinstance(o, dict) and o.get("id") is not None:
                parent[o["id"]] = o.get("parent_id")
    if data["jobs"] and not parent:
        raise FormatChanged("jobs sem offices[]: não é possível aplicar o escopo por escritório")

    def under_root(oid) -> bool:
        hops = 0
        while oid is not None and hops < 20:
            if str(oid) == str(root_id):
                return True
            oid, hops = parent.get(oid), hops + 1
        return False
    out, seen = [], set()
    for j in data["jobs"]:
        if not isinstance(j, dict) or j.get("id") is None or str(j["id"]) in seen:
            continue
        if any(isinstance(o, dict) and under_root(o.get("id")) for o in j.get("offices") or []):
            seen.add(str(j["id"]))
            names = [d.get("name") for d in (j.get("departments") or []) if isinstance(d, dict) and d.get("name")]
            out.append((j, "; ".join(dict.fromkeys(names)) or None))
    return out


def _board_stubs(ctx: CollectContext, board: str) -> list[tuple[dict, str | None]]:
    data = ctx.http.get_json(f"{API.format(board=board)}/jobs?content=true")
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        raise FormatChanged("resposta do quadro Greenhouse sem a lista jobs")
    out, seen = [], set()
    for j in data["jobs"]:
        if isinstance(j, dict) and j.get("id") is not None and str(j["id"]) not in seen:
            seen.add(str(j["id"]))
            names = [d.get("name") for d in (j.get("departments") or []) if isinstance(d, dict) and d.get("name")]
            out.append((j, "; ".join(dict.fromkeys(names)) or None))
    return out


def collect(ctx: CollectContext) -> SourceBatch:
    p = ctx.source.params
    board = p["board"]
    office_id = p.get("office_id")
    root_id = p.get("office_root_id")
    scope = {"office_root_id": root_id} if root_id else {"office_id": office_id} if office_id else {"scope": "board"}
    batch = new_batch(ctx, VERSION, scope)
    batch.pages_expected = 1
    office_name = None
    try:
        if root_id:
            stubs = _subtree_stubs(ctx, board, root_id)
        elif office_id:
            stubs, office_name = _office_stubs(ctx, board, office_id)
        else:
            stubs = _board_stubs(ctx, board)
    except (FormatChanged, Blocked, SourceFailure) as e:
        return fail(batch, getattr(e, "code", "error"), str(e))
    batch.pages_received = 1
    batch.raw_count = len(stubs)
    for j, department in stubs:
        jid = str(j["id"])
        location = (j.get("location") or {}).get("name") or office_name or None
        title = " ".join((j.get("title") or "").split())
        pub_raw, pub_src = _published(j)
        text, status, orig, note = bounded(html_to_text(j.get("content") or ""))
        batch.jobs.append(JobObservation(
            platform="greenhouse", tenant=board, external_id=jid, url=j.get("absolute_url") or None, title=title,
            location=location, department=department, description=text, description_status=status,
            original_length=orig, truncation_note=note, published_raw=pub_raw, published_source=pub_src,
            listing_signature=signature(title, location, department, j.get("updated_at")),
            raw={"id": jid, "updated_at": j.get("updated_at"), "office": office_name}))
    _details(ctx, batch, board)
    batch.status = "complete"
    return batch.finish()


def _details(ctx: CollectContext, batch: SourceBatch, board: str) -> None:
    budget = int(ctx.source.limits.get("max_details", 25))
    ttl = int(ctx.source.limits.get("detail_ttl_days", 7))
    for obs in batch.jobs:
        if obs.description_status != "missing" or not wants_detail(ctx, obs, ttl):
            continue
        if budget <= 0:
            batch.warnings.append("limite de detalhes atingido; restantes serão detalhados nos próximos ciclos")
            break
        budget -= 1
        try:
            d = ctx.http.get_json(f"{API.format(board=board)}/jobs/{obs.external_id}")
            if not isinstance(d, dict):
                raise FormatChanged("detalhe Greenhouse não é um objeto JSON")
        except (FormatChanged, Blocked, SourceFailure) as e:
            batch.warnings.append(f"detalhe {obs.external_id}: {getattr(e, 'code', 'erro')}: {str(e)[:120]}")
            continue
        text, status, orig, note = bounded(html_to_text(d.get("content") or ""))
        obs.description, obs.description_status = text, status
        obs.original_length, obs.truncation_note = orig, note
        pub_raw, pub_src = _published(d)
        if pub_raw:
            obs.published_raw, obs.published_source = pub_raw, pub_src
        obs.location = (d.get("location") or {}).get("name") or obs.location
        obs.url = d.get("absolute_url") or obs.url
        if not obs.department:
            names = [x.get("name") for x in (d.get("departments") or []) if isinstance(x, dict) and x.get("name")]
            obs.department = "; ".join(dict.fromkeys(names)) or None
        batch.details_fetched += 1


def probe(ctx: CollectContext, external_id: str | None, url: str | None) -> str:
    """GET /jobs/{id} no quadro: 200 = vivo, 404 = removido do quadro."""
    if not external_id:
        return "unknown"
    try:
        d = ctx.http.get_json(f"{API.format(board=ctx.source.params['board'])}/jobs/{external_id}")
    except SourceFailure as e:
        return "gone" if e.code == "not_found" else "unknown"
    except (Blocked, FormatChanged):
        return "unknown"
    return "alive" if isinstance(d, dict) and str(d.get("id")) == str(external_id) else "unknown"
