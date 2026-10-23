"""Adapters portados do legado (j2w, inhire, greenhouse, smartrecruiters, totvs, dof, workable, vagas_com_br).

Sem rede: o HTTP é um FakeHttp com respostas enlatadas por trecho de URL. Cada adapter tem o caminho feliz (lote
completo, identidade correta) e o caso de conteúdo inesperado (failed + format_changed). J2W e SmartRecruiters, que
paginam, também cobrem falha na página 2 (parcial) e limite de páginas (parcial).
"""
from __future__ import annotations

import pytest

from jobos.collectors import dof, greenhouse, inhire, j2w, smartrecruiters, totvs, vagas_com_br, workable
from jobos.collectors.base import Blocked, CollectContext, FormatChanged, SourceFailure
from jobos.settings import SourceConfig

LIMITS = {"max_pages": 3, "max_details": 5, "detail_ttl_days": 7}
EN = chr(0x2013)  # travessão que a SAP usa no rótulo de paginação


class FakeHttp:
    """Responde por trecho de URL (vence o trecho mais longo), com filtro opcional de params, e registra as chamadas."""

    def __init__(self):
        self.routes: list[tuple[str, dict | None, object]] = []
        self.calls: list[dict] = []

    def add(self, substring: str, response, params: dict | None = None) -> "FakeHttp":
        self.routes.append((substring, params, response))
        return self

    def _answer(self, method: str, url: str, params=None, headers=None, body=None):
        self.calls.append({"method": method, "url": url, "params": params, "headers": headers, "body": body})
        best = None
        for sub, want, resp in self.routes:
            if sub in url and (want is None or all((params or {}).get(k) == v for k, v in want.items())):
                if best is None or len(sub) > len(best[0]):
                    best = (sub, resp)
        if best is None:
            raise AssertionError(f"rota não mockada: {method} {url} {params}")
        if isinstance(best[1], BaseException):
            raise best[1]
        return best[1]

    def get_text(self, url, *, headers=None, params=None):
        r = self._answer("GET", url, params, headers)
        return r if isinstance(r, tuple) else (200, r)

    def get_json(self, url, *, headers=None, params=None):
        return self._answer("GET", url, params, headers)

    def post_json(self, url, body, *, headers=None):
        return self._answer("POST", url, None, headers, body)


def make_ctx(adapter: str, platform: str, params: dict, http: FakeHttp, *, coverage: str = "full_board",
             limits: dict | None = None, known=None) -> CollectContext:
    src = SourceConfig(source_id=f"{adapter}-teste", company_id="acme", company_name="Acme", platform=platform,
                       adapter=adapter, enabled=True, params=params, coverage=coverage, limits=limits or dict(LIMITS),
                       priority=1, board_url=None, configuration_origin="teste", verification_status="teste")
    kw = {"known": known} if known else {}
    return CollectContext(run_id="run-1", source=src, http=http, **kw)


def assert_failed(batch, code: str):
    assert batch.status == ("blocked" if code == "blocked" else "failed")
    assert batch.error_code == code
    assert batch.complete is False and batch.can_infer_absence is False
    assert batch.jobs == []


@pytest.mark.parametrize("module,version", [
    (j2w, "j2w_search/1"), (inhire, "inhire/1"), (greenhouse, "greenhouse/2"), (smartrecruiters, "smartrecruiters/1"),
    (totvs, "totvs/1"), (dof, "dof_webflow/1"), (workable, "workable/2"), (vagas_com_br, "vagas_com_br/1")])
def test_contrato_do_modulo(module, version):
    assert module.VERSION == version
    assert callable(module.collect)


# ------------------------------------------------------------------ J2W (SuccessFactors)

def sf_row(path: str, title: str, loc: str) -> str:
    return (f'<tr class="data-row"><td class="colTitle"><span class="jobTitle hidden-phone">'
            f'<a class="jobTitle-link" href="{path}">{title}</a></span></td>'
            f'<td class="colLocation hidden-phone"><span class="jobLocation">\n{loc}\n</span></td></tr>')


def sf_page(rows: list[str], first: int = 1, last: int = 2, total: int | None = 3) -> str:
    label = ""
    if total is not None:
        label = (f'<span class="paginationLabel" aria-label="Results {first} {EN} {last} of {total}">'
                 f'Results <b>{first} {EN} {last}</b> of <b>{total}</b></span>')
    return ('<html><body><form action="/search/"><input name="locationsearch"></form>' + label +
            '<table>' + "".join(rows) + '</table></body></html>')


P_VESSEL = "/job/Rio-de-Janeiro-Vessel-Superintendent/1234567/"
P_HSSE = "/job/Rio-de-Janeiro-Operations-HSSE-Manager/7654321/"
P_ELEC = "/job/Macae-Electrician/1111111/"
BASE = "https://careers.subsea7.com"


def sf_detail(desc: str = "<p>Lead <b>marine</b> ops.</p><span>aninhado</span><ul><li>HSSE</li></ul>",
              date: str = "Mon Aug 17 00:00:00 UTC 2026") -> str:
    return (f'<html><head><meta itemprop="datePosted" content="{date}"/></head><body>'
            f'<span class="jobdescription" itemprop="description">{desc}</span><footer>rodapé</footer></body></html>')


def sf_ctx(http: FakeHttp, **kw) -> CollectContext:
    return make_ctx("j2w_search", "successfactors_j2w", {"base": BASE, "location": "Rio de Janeiro"}, http,
                    coverage="filtered_board", **kw)


def sf_two_pages() -> FakeHttp:
    http = FakeHttp()
    http.add("startrow=0", sf_page([sf_row(P_VESSEL, "Vessel Superintendent", "Rio de Janeiro, BR, 20021-290\n +1 more..."),
                                    sf_row(P_HSSE, "Operations HSSE Manager 20021 290", "Rio de Janeiro, BR")]))
    http.add("startrow=2", sf_page([sf_row(P_ELEC, "Electrician", "Macae, BR")], first=3, last=3))
    return http


def test_j2w_caminho_feliz():
    http = sf_two_pages()
    for path in (P_VESSEL, P_HSSE, P_ELEC):
        http.add(path, sf_detail())
    b = j2w.collect(sf_ctx(http))
    assert b.status == "complete" and b.complete and b.can_infer_absence
    assert b.adapter_version == "j2w_search/1"
    assert (b.pages_received, b.pages_expected, b.raw_count) == (2, 2, 3)
    assert [j.external_id for j in b.jobs] == ["1234567", "7654321", "1111111"]
    assert {j.platform for j in b.jobs} == {"successfactors_j2w"}
    assert {j.tenant for j in b.jobs} == {"careers.subsea7.com"}
    assert [j.title for j in b.jobs] == ["Vessel Superintendent", "Operations HSSE Manager", "Electrician"]
    assert [j.location for j in b.jobs] == ["Rio de Janeiro", "Rio de Janeiro", "Macae"]
    assert b.jobs[0].url == BASE + P_VESSEL
    assert b.jobs[1].raw["title_raw"] == "Operations HSSE Manager 20021 290"
    assert b.details_fetched == 3
    j = b.jobs[0]
    assert "Lead marine ops." in j.description and "aninhado" in j.description and "rodapé" not in j.description
    assert j.description_status == "full"
    assert (j.published_raw, j.published_source) == ("2026-08-17", "j2w:datePosted")
    assert "locationsearch=Rio+de+Janeiro&startrow=0" in http.calls[0]["url"]


def test_j2w_conteudo_inesperado_e_format_changed():
    http = FakeHttp().add("startrow=0", "<html><body>Please sign in to continue</body></html>")
    assert_failed(j2w.collect(sf_ctx(http)), "format_changed")


def test_j2w_marcador_sem_vagas_legiveis_e_format_changed():
    http = FakeHttp().add("startrow=0", '<html><body><span class="jobTitle-link">sem ancora</span></body></html>')
    assert_failed(j2w.collect(sf_ctx(http)), "format_changed")


def test_j2w_sem_vagas_explicito_e_completo():
    html = ('<html><body><form action="/search/"><input name="locationsearch"></form>'
            '<p>There are currently no open positions that match your search.</p></body></html>')
    b = j2w.collect(sf_ctx(FakeHttp().add("startrow=0", html)))
    assert b.status == "complete" and b.jobs == [] and b.pages_received == 1 and b.can_infer_absence


def test_j2w_bloqueio_na_primeira_pagina():
    b = j2w.collect(sf_ctx(FakeHttp().add("startrow=0", Blocked("HTTP 403"))))
    assert_failed(b, "blocked")


def test_j2w_falha_na_pagina_2_e_parcial():
    http = FakeHttp()
    http.add("startrow=0", sf_page([sf_row(P_VESSEL, "Vessel Superintendent", "Rio de Janeiro, BR"),
                                    sf_row(P_HSSE, "Operations HSSE Manager", "Rio de Janeiro, BR")]))
    http.add("startrow=2", SourceFailure("http_500", "HTTP 500 em /search"))
    for path in (P_VESSEL, P_HSSE):
        http.add(path, sf_detail())
    b = j2w.collect(sf_ctx(http))
    assert b.status == "partial" and b.complete is False and b.can_infer_absence is False
    assert b.error_code == "http_500" and "startrow=2" in b.error_message
    assert len(b.jobs) == 2 and b.pages_received == 1


def test_j2w_limite_de_paginas_e_parcial():
    http = FakeHttp()
    for n in range(3):
        paths = [f"/job/Cargo-{n}-{i}/{n}00000{i}/" for i in (1, 2)]
        http.add(f"startrow={2 * n}", sf_page([sf_row(p, f"Cargo {n} {i}", "Rio de Janeiro, BR") for i, p in enumerate(paths)],
                                              first=2 * n + 1, last=2 * n + 2, total=100))
    b = j2w.collect(sf_ctx(http, limits={**LIMITS, "max_details": 0}))
    assert b.status == "partial" and b.can_infer_absence is False
    assert b.pages_received == 3 and len(b.jobs) == 6
    assert any("limite de 3 páginas" in w for w in b.warnings)
    assert all("startrow=6" not in c["url"] for c in http.calls)


def test_j2w_pagina_repetida_encerra_sem_total():
    rows = [sf_row(P_VESSEL, "Vessel Superintendent", "Rio de Janeiro, BR"),
            sf_row(P_HSSE, "Operations HSSE Manager", "Rio de Janeiro, BR")]
    http = FakeHttp().add("startrow=0", sf_page(rows, total=None)).add("startrow=2", sf_page(rows, total=None))
    b = j2w.collect(sf_ctx(http, limits={**LIMITS, "max_details": 0}))
    assert b.status == "complete" and len(b.jobs) == 2 and b.pages_received == 2


def test_j2w_detalhe_respeita_orcamento_e_known():
    http = sf_two_pages()
    http.add(P_VESSEL, sf_detail()).add(P_HSSE, SourceFailure("not_found", "HTTP 404"))
    b = j2w.collect(sf_ctx(http, limits={**LIMITS, "max_details": 2}))
    assert b.status == "complete" and b.details_fetched == 1
    assert any("not_found" in w for w in b.warnings) and any("limite de detalhes" in w for w in b.warnings)
    assert b.jobs[2].description_status == "missing"

    http2 = sf_two_pages()
    known = lambda ext, url: {"listing_signature": None, "detail_fetched_at": "2999-01-01T00:00:00+00:00", "has_description": True}
    b2 = j2w.collect(sf_ctx(http2, known=known))
    assert b2.details_fetched == 0 and len(http2.calls) == 2


# ------------------------------------------------------------------ inHire

IH_API = "job-posts/public/pages"
IH_LIST = {"jobsPage": [
    {"jobId": "11111111-aaaa", "displayName": "Analista de Operações", "location": "Macaé, RJ", "workplaceType": "hybrid"},
    {"jobId": "22222222-bbbb", "displayName": "Gerente de Base", "location": "Rio de Janeiro, RJ"}]}
IH_DETAIL = {"jobId": "11111111-aaaa", "description": "<p>Descrição <b>completa</b></p>",
             "publishedAt": "2026-08-10T12:00:00.000Z", "department": "Operações", "workplaceType": "hybrid"}


def ih_ctx(http: FakeHttp) -> CollectContext:
    return make_ctx("inhire", "inhire", {"tenant": "oceanpact"}, http)


def test_inhire_caminho_feliz():
    http = FakeHttp().add(IH_API, IH_LIST)
    http.add(IH_API + "/11111111-aaaa", IH_DETAIL).add(IH_API + "/22222222-bbbb", {"createdAt": "2026-07-01T00:00:00Z", "description": "Texto"})
    b = inhire.collect(ih_ctx(http))
    assert b.status == "complete" and b.can_infer_absence and b.pages_received == 1 and b.raw_count == 2
    assert [j.external_id for j in b.jobs] == ["11111111-aaaa", "22222222-bbbb"]
    j = b.jobs[0]
    assert (j.platform, j.tenant) == ("inhire", "oceanpact")
    assert j.url == "https://oceanpact.inhire.app/vagas/11111111-aaaa"
    assert j.title == "Analista de Operações" and j.location == "Macaé, RJ" and j.workplace == "hybrid"
    assert j.description == "Descrição completa" and j.description_status == "full"
    assert (j.published_raw, j.published_source) == ("2026-08-10T12:00:00.000Z", "inhire:publishedAt")
    assert j.department == "Operações"
    assert (b.jobs[1].published_raw, b.jobs[1].published_source) == ("2026-07-01T00:00:00Z", "inhire:createdAt")
    assert b.details_fetched == 2
    h = http.calls[0]["headers"]
    assert h["X-Tenant"] == "oceanpact" and h["Origin"] == "https://oceanpact.inhire.app"
    assert h["Referer"] == "https://oceanpact.inhire.app/vagas" and h["Accept"] == "application/json"
    assert http.calls[1]["url"] == "https://api.inhire.app/job-posts/public/pages/11111111-aaaa"
    assert http.calls[1]["headers"]["X-Tenant"] == "oceanpact"


@pytest.mark.parametrize("payload", [{"foo": []}, [], {"jobsPage": "x"}, FormatChanged("resposta não-JSON")])
def test_inhire_conteudo_inesperado_e_format_changed(payload):
    assert_failed(inhire.collect(ih_ctx(FakeHttp().add(IH_API, payload))), "format_changed")


def test_inhire_lista_vazia_reconhecida_e_completa():
    b = inhire.collect(ih_ctx(FakeHttp().add(IH_API, {"jobsPage": []})))
    assert b.status == "complete" and b.jobs == [] and b.raw_count == 0


def test_inhire_falha_de_detalhe_e_so_aviso_e_403_bloqueia():
    http = FakeHttp().add(IH_API, IH_LIST)
    http.add(IH_API + "/11111111-aaaa", SourceFailure("not_found", "HTTP 404")).add(IH_API + "/22222222-bbbb", {"description": "ok"})
    b = inhire.collect(ih_ctx(http))
    assert b.status == "complete" and b.details_fetched == 1
    assert b.jobs[0].description_status == "missing" and any("11111111-aaaa" in w for w in b.warnings)
    assert_failed(inhire.collect(ih_ctx(FakeHttp().add(IH_API, Blocked("HTTP 403")))), "blocked")


# ------------------------------------------------------------------ Greenhouse

GH_OFFICE = {"id": 114971, "name": "Brazil - Rio de Janeiro", "departments": [
    {"id": 1, "name": "Engineering", "jobs": [
        {"id": 501, "title": "Developer", "absolute_url": "https://job-boards.greenhouse.io/capco/jobs/501",
         "location": {"name": "Brazil - Rio de Janeiro"}, "updated_at": "2026-08-06T10:00:00-04:00"}]},
    {"id": 2, "name": "Consulting", "jobs": [
        {"id": 502, "title": "Consultant", "absolute_url": "https://job-boards.greenhouse.io/capco/jobs/502",
         "location": {"name": "Brazil - Rio de Janeiro"}, "updated_at": "2026-08-07T10:00:00-04:00"},
        {"id": 501, "title": "Developer", "location": {"name": "Brazil - Rio de Janeiro"}}]}],
    "child_ids": [9]}  # formato real: filhos só por id (auditoria 23/10/2026)

GH_CHILD = {"id": 9, "name": "Filho", "parent_id": 114971, "child_ids": [], "departments": [{"id": 3, "name": "Ops", "jobs": [
    {"id": 503, "title": "Ops  Analyst", "absolute_url": "https://job-boards.greenhouse.io/capco/jobs/503",
     "location": {"name": "Brazil - Rio de Janeiro"}}]}]}


def gh_ctx(http: FakeHttp, params: dict | None = None) -> CollectContext:
    return make_ctx("greenhouse", "greenhouse", params or {"board": "capco", "office_id": 114971}, http,
                    coverage="filtered_board")


def test_greenhouse_escritorio_caminho_feliz():
    http = FakeHttp().add("boards/capco/offices/114971", GH_OFFICE)
    http.add("boards/capco/offices/9", GH_CHILD)
    http.add("boards/capco/jobs/501", {"id": 501, "content": "&lt;p&gt;Build &amp;amp; ship&lt;/p&gt;",
                                       "first_published": "2026-03-11T10:00:00-03:00",
                                       "updated_at": "2026-08-06T10:00:00-04:00",
                                       "location": {"name": "Brazil - Rio de Janeiro"}})
    http.add("boards/capco/jobs/502", {"id": 502, "content": "&lt;p&gt;Advise&lt;/p&gt;"})
    http.add("boards/capco/jobs/503", SourceFailure("http_500", "HTTP 500"))
    b = greenhouse.collect(gh_ctx(http))
    assert b.status == "complete" and b.can_infer_absence and b.raw_count == 3
    assert [j.external_id for j in b.jobs] == ["501", "502", "503"]
    j = b.jobs[0]
    assert (j.platform, j.tenant) == ("greenhouse", "capco")
    assert j.title == "Developer" and j.location == "Brazil - Rio de Janeiro" and j.department == "Engineering"
    assert j.url == "https://job-boards.greenhouse.io/capco/jobs/501"
    assert j.description == "Build & ship" and j.description_status == "full"
    assert (j.published_raw, j.published_source) == ("2026-03-11T10:00:00-03:00", "greenhouse:first_published")
    assert (b.jobs[1].published_raw, b.jobs[1].published_source) == ("2026-08-07T10:00:00-04:00", "greenhouse:updated_at")
    assert b.jobs[2].title == "Ops Analyst" and b.jobs[2].department == "Ops" and b.jobs[2].description_status == "missing"
    assert b.details_fetched == 2 and any("503" in w for w in b.warnings)


def test_greenhouse_quadro_inteiro_sem_detalhe():
    board = {"jobs": [{"id": 7, "title": "Analyst", "absolute_url": "https://x/7", "location": {"name": "Remote"},
                       "content": "&lt;p&gt;Hello &amp;amp; team&lt;/p&gt;", "first_published": "2026-01-02T03:04:05-03:00",
                       "departments": [{"name": "Eng"}, {"name": "Data"}]}], "meta": {"total": 1}}
    http = FakeHttp().add("boards/capco/jobs?content=true", board)
    b = greenhouse.collect(gh_ctx(http, {"board": "capco"}))
    assert b.status == "complete" and len(http.calls) == 1 and b.details_fetched == 0
    j = b.jobs[0]
    assert (j.external_id, j.tenant, j.location, j.department) == ("7", "capco", "Remote", "Eng; Data")
    assert j.description == "Hello & team" and j.published_source == "greenhouse:first_published"


@pytest.mark.parametrize("params,route,payload", [
    ({"board": "capco", "office_id": 114971}, "offices/114971", {"error": "x"}),
    ({"board": "capco", "office_id": 114971}, "offices/114971", {"departments": [{"id": 1, "name": "Sem chave jobs"}]}),
    ({"board": "capco"}, "jobs?content=true", {"foo": 1}),
    ({"board": "capco"}, "jobs?content=true", FormatChanged("resposta não-JSON"))])
def test_greenhouse_conteudo_inesperado_e_format_changed(params, route, payload):
    assert_failed(greenhouse.collect(gh_ctx(FakeHttp().add(route, payload), params)), "format_changed")


def test_greenhouse_escritorio_vazio_reconhecido_e_completo():
    b = greenhouse.collect(gh_ctx(FakeHttp().add("offices/114971", {"id": 114971, "departments": []})))
    assert b.status == "complete" and b.jobs == []


# ------------------------------------------------------------------ SmartRecruiters

SR_URL = "https://api.smartrecruiters.com/v1/companies/akersolutions/postings"


def sr_item(i: int) -> dict:
    return {"id": f"74300{i}", "name": f"Engenheiro {i}", "releasedDate": f"2026-08-0{i}T10:00:00.000Z",
            "location": {"city": "Rio de Janeiro", "region": "RJ", "country": "br", "fullLocation": "Rio de Janeiro, RJ, Brazil"},
            "department": {"label": "Engenharia"}}


def sr_ctx(http: FakeHttp, **kw) -> CollectContext:
    return make_ctx("smartrecruiters", "smartrecruiters", {"company_id": "akersolutions", "country": "br"}, http,
                    coverage="filtered_board", **kw)


def sr_http(total: int = 3, fail_page2: bool = False) -> FakeHttp:
    http = FakeHttp()
    http.add(SR_URL, {"totalFound": total, "content": [sr_item(1), sr_item(2)]}, params={"offset": 0})
    http.add(SR_URL, SourceFailure("http_502", "HTTP 502") if fail_page2 else {"totalFound": total, "content": [sr_item(3)]},
             params={"offset": 2})
    http.add(SR_URL, {"totalFound": total, "content": [sr_item(4), sr_item(5)]}, params={"offset": 4})
    return http


def test_smartrecruiters_caminho_feliz():
    http = sr_http()
    http.add(SR_URL + "/743001", {"jobAd": {"sections": {
        "companyDescription": {"title": "Company Description", "text": "<p>Sobre a <b>empresa</b></p>"},
        "jobDescription": {"title": "Job Description", "text": "<p>Projetar</p>"},
        "qualifications": {"text": "<ul><li>CREA</li></ul>"},
        "additionalInformation": {"text": ""}}}})
    b = smartrecruiters.collect(sr_ctx(http, limits={**LIMITS, "max_details": 1}))
    assert b.status == "complete" and b.can_infer_absence
    assert (b.pages_received, b.pages_expected, b.raw_count) == (2, 1, 3)
    assert [j.external_id for j in b.jobs] == ["743001", "743002", "743003"]
    j = b.jobs[0]
    assert (j.platform, j.tenant) == ("smartrecruiters", "akersolutions")
    assert j.url == "https://jobs.smartrecruiters.com/akersolutions/743001"
    assert j.title == "Engenheiro 1" and j.location == "Rio de Janeiro, RJ, Brazil" and j.department == "Engenharia"
    assert (j.published_raw, j.published_source) == ("2026-08-01T10:00:00.000Z", "smartrecruiters:releasedDate")
    assert "Company Description:\nSobre a empresa" in j.description
    assert "Job Description:\nProjetar" in j.description and "Qualificações:\n- CREA" in j.description
    assert j.description_status == "full" and b.details_fetched == 1
    assert any("limite de detalhes" in w for w in b.warnings)
    first = http.calls[0]
    assert first["params"] == {"limit": 100, "offset": 0, "country": "br"}
    assert http.calls[1]["params"]["offset"] == 2


@pytest.mark.parametrize("payload", [{"content": "nope"}, {"foo": []}, [], FormatChanged("resposta não-JSON")])
def test_smartrecruiters_conteudo_inesperado_e_format_changed(payload):
    http = FakeHttp().add(SR_URL, payload)
    assert_failed(smartrecruiters.collect(sr_ctx(http)), "format_changed")


def test_smartrecruiters_lista_vazia_reconhecida_e_completa():
    b = smartrecruiters.collect(sr_ctx(FakeHttp().add(SR_URL, {"totalFound": 0, "content": []})))
    assert b.status == "complete" and b.jobs == [] and b.pages_expected == 1


def test_smartrecruiters_falha_na_pagina_2_e_parcial():
    http = sr_http(total=3, fail_page2=True)
    b = smartrecruiters.collect(sr_ctx(http, limits={**LIMITS, "max_details": 0}))
    assert b.status == "partial" and b.complete is False and b.can_infer_absence is False
    assert b.error_code == "http_502" and "offset=2" in b.error_message
    assert len(b.jobs) == 2 and b.pages_received == 1


def test_smartrecruiters_limite_de_paginas_e_parcial():
    http = sr_http(total=10)
    b = smartrecruiters.collect(sr_ctx(http, limits={**LIMITS, "max_pages": 2, "max_details": 0}))
    assert b.status == "partial" and b.can_infer_absence is False
    assert b.pages_received == 2 and len(b.jobs) == 3
    assert any("limite de 2 páginas" in w for w in b.warnings)


# ------------------------------------------------------------------ TOTVS

TV_ITEM = ('<div class="index__job-opportunities__grid__item" data-id="abc-1" data-title="Analista de Logística" '
           'data-city-name="Macaé" data-state-small-name="RJ" data-department-name="Logística" '
           'data-page-url="/bramoffshore/job-opportunity/12345/analista-de-logistica"></div>')
TV_ITEM2 = ('<div class="index__job-opportunities__grid__item" data-id="abc-2" data-title="Técnico" '
            'data-city-name="Niterói" data-state-small-name="RJ" data-department-name="Operações" '
            'data-page-url="/bramoffshore/job-opportunity/67890/tecnico"></div>')
TV_URL = "https://atracaodetalentos.totvs.app/bramoffshore/extended"


def tv_ctx(http: FakeHttp) -> CollectContext:
    return make_ctx("totvs", "totvs", {"tenant": "bramoffshore"}, http)


def test_totvs_caminho_feliz():
    html = f'<html><body><div class="index__job-opportunities__grid">{TV_ITEM}{TV_ITEM2}{TV_ITEM}</div></body></html>'
    http = FakeHttp().add(TV_URL, html)
    http.add("/12345/", "<html><head><style>.a{color:red}</style></head><body><script>var segredo=1;</script>"
                        "<h1>Analista</h1><p>Rotinas de <b>logística</b> e frota.</p></body></html>")
    http.add("/67890/", SourceFailure("not_found", "HTTP 404"))
    b = totvs.collect(tv_ctx(http))
    assert b.status == "complete" and b.can_infer_absence and b.pages_received == 1 and b.raw_count == 3
    assert [j.external_id for j in b.jobs] == ["12345", "67890"]
    j = b.jobs[0]
    assert (j.platform, j.tenant) == ("totvs", "bramoffshore")
    assert j.url == "https://atracaodetalentos.totvs.app/bramoffshore/job-opportunity/12345/analista-de-logistica"
    assert j.title == "Analista de Logística" and j.location == "Macaé, RJ" and j.department == "Logística"
    assert "Rotinas de logística e frota." in j.description and "segredo" not in j.description and "color" not in j.description
    assert b.details_fetched == 1 and b.jobs[1].description_status == "missing" and any("67890" in w for w in b.warnings)


def test_totvs_conteudo_inesperado_e_format_changed():
    assert_failed(totvs.collect(tv_ctx(FakeHttp().add(TV_URL, "<html><body>Entre com seu login</body></html>"))), "format_changed")
    grid_so = '<html><body><div class="index__job-opportunities__grid"></div></body></html>'
    assert_failed(totvs.collect(tv_ctx(FakeHttp().add(TV_URL, grid_so))), "format_changed")


def test_totvs_sem_vagas_explicito_e_completo():
    html = '<html><body><div class="index__job-opportunities__grid"><p>Nenhuma vaga disponível no momento.</p></div></body></html>'
    b = totvs.collect(tv_ctx(FakeHttp().add(TV_URL, html)))
    assert b.status == "complete" and b.jobs == [] and b.pages_received == 1


# ------------------------------------------------------------------ DOF (Webflow)

DOF_HTML = ('<html><body><div class="w-dyn-list">'
            '<div role="listitem" data-slug="oil-rig-manager" data-job-name="Oil Rig Manager" data-job-city="Macaé" '
            'data-job-country="Brazil" data-job-department="Operations" class="w-dyn-item"></div>'
            '<div role="listitem" class="w-dyn-item" data-job-department="Marine" data-job-country="Brazil" '
            'data-job-city="Niterói" data-job-name="Captain &amp; Pilot" data-slug="captain-pilot"></div>'
            '<div role="listitem" data-slug="oil-rig-manager" data-job-name="Oil Rig Manager" data-job-city="Macaé" '
            'data-job-country="Brazil" data-job-department="Operations"></div>'
            '</div></body></html>')


def dof_ctx(http: FakeHttp) -> CollectContext:
    return make_ctx("dof_webflow", "webflow", {}, http)


def test_dof_caminho_feliz():
    http = FakeHttp().add("dof.com/vacancies", DOF_HTML)
    http.add("vacancies/oil-rig-manager", '<html><div class="rich-text w-richtext"><p>Intro</p></div>'
                                            '<div class="rich-text_req w-richtext"><ul><li>Requisito</li></ul></div></html>')
    http.add("vacancies/captain-pilot", "<html><body>sem blocos</body></html>")
    b = dof.collect(dof_ctx(http))
    assert b.status == "complete" and b.can_infer_absence and b.raw_count == 3
    assert [j.external_id for j in b.jobs] == ["oil-rig-manager", "captain-pilot"]
    j = b.jobs[0]
    assert (j.platform, j.tenant) == ("webflow", "dof.com")
    assert j.url == "https://www.dof.com/vacancies/oil-rig-manager"
    assert j.title == "Oil Rig Manager" and j.location == "Macaé, Brazil" and j.department == "Operations"
    assert "Intro" in j.description and "- Requisito" in j.description and j.description_status == "full"
    assert b.jobs[1].title == "Captain & Pilot" and b.jobs[1].description_status == "missing"
    assert b.details_fetched == 1 and any("captain-pilot" in w for w in b.warnings)


def test_dof_conteudo_inesperado_e_format_changed():
    assert_failed(dof.collect(dof_ctx(FakeHttp().add("dof.com/vacancies", "<html><body>Just a moment...</body></html>"))),
                  "format_changed")
    # mesmo uma página que parece de vagas zeradas não vira "zero vagas" sem o marcador
    assert_failed(dof.collect(dof_ctx(FakeHttp().add("dof.com/vacancies", "<html><body>No vacancies at the moment</body></html>"))),
                  "format_changed")


def test_dof_paginacao_webflow_deixa_parcial():
    html = DOF_HTML.replace("</body>", '<a href="?abc_page=2" class="w-pagination-next">Next</a></body>')
    http = FakeHttp().add("dof.com/vacancies", html)
    http.add("vacancies/oil-rig-manager", "<html></html>").add("vacancies/captain-pilot", "<html></html>")
    b = dof.collect(dof_ctx(http))
    assert b.status == "partial" and b.can_infer_absence is False and len(b.jobs) == 2


# ------------------------------------------------------------------ Workable

WK_URL = "https://apply.workable.com/api/v1/widget/accounts/trident-energy"


def wk_ctx(http: FakeHttp) -> CollectContext:
    return make_ctx("workable", "workable", {"account": "trident-energy"}, http)


def test_workable_caminho_feliz():
    payload = {"name": "Trident", "jobs": [
        {"title": "Reservoir Engineer", "shortcode": "ABC123", "url": "https://apply.workable.com/j/ABC123",
         "department": "Subsurface", "city": "Macaé", "state": "Rio de Janeiro", "country": "Brazil",
         "published_on": "2026-08-01", "telecommuting": False, "description": "<p>Modelar <b>reservatórios</b></p>"},
        {"title": "Remote Analyst", "shortcode": "DEF456", "location": {"city": "Rio", "country": "Brazil"},
         "created_at": "2026-07-02T00:00:00Z", "telecommuting": True}]}
    http = FakeHttp().add(WK_URL, payload)
    b = workable.collect(wk_ctx(http))
    assert b.status == "complete" and b.can_infer_absence and b.pages_received == 1 and b.raw_count == 2
    assert [j.external_id for j in b.jobs] == ["ABC123", "DEF456"]
    j = b.jobs[0]
    assert (j.platform, j.tenant) == ("workable", "trident-energy")
    assert j.url == "https://apply.workable.com/j/ABC123" and j.title == "Reservoir Engineer"
    assert j.location == "Macaé, Rio de Janeiro, Brazil" and j.department == "Subsurface"
    assert j.description == "Modelar reservatórios" and (j.published_raw, j.published_source) == ("2026-08-01", "workable:published_on")
    r = b.jobs[1]
    assert r.workplace == "remote" and r.location == "Rio, Brazil" and r.description_status == "missing"
    assert r.url == "https://apply.workable.com/trident-energy/j/DEF456/"
    assert (r.published_raw, r.published_source) == ("2026-07-02T00:00:00Z", "workable:created_at")


@pytest.mark.parametrize("payload", [{"foo": 1}, {"jobs": "x"}, [], FormatChanged("resposta não-JSON")])
def test_workable_conteudo_inesperado_e_format_changed(payload):
    assert_failed(workable.collect(wk_ctx(FakeHttp().add(WK_URL, payload))), "format_changed")


def test_workable_lista_vazia_reconhecida_e_completa():
    b = workable.collect(wk_ctx(FakeHttp().add(WK_URL, {"name": "Trident", "jobs": []})))
    assert b.status == "complete" and b.jobs == []


# ------------------------------------------------------------------ vagas.com.br

VG_URL = "https://trabalheconosco.vagas.com.br/seagems/oportunidades"


def vg_ctx(http: FakeHttp) -> CollectContext:
    return make_ctx("vagas_com_br", "vagas_com_br", {"slug": "seagems"}, http)


def test_vagas_com_br_caminho_feliz():
    html = ('<html><body><a href="/vagas/v1234567/analista-de-sistemas">Analista de <b>Sistemas</b></a>'
            '<a href="https://www.vagas.com.br/vagas/v7654321/tecnico-offshore">Técnico Offshore</a>'
            '<a href="/vagas/v1234567/analista-de-sistemas">Analista de Sistemas</a>'
            '<a href="/sobre">Sobre</a></body></html>')
    b = vagas_com_br.collect(vg_ctx(FakeHttp().add(VG_URL, html)))
    assert b.status == "complete" and b.can_infer_absence and b.pages_received == 1 and b.raw_count == 2
    assert [j.external_id for j in b.jobs] == ["v1234567", "v7654321"]
    j = b.jobs[0]
    assert (j.platform, j.tenant) == ("vagas_com_br", "seagems")
    assert j.url == "https://www.vagas.com.br/vagas/v1234567/analista-de-sistemas" and j.title == "Analista de Sistemas"
    assert j.location is None and j.description_status == "missing"
    assert b.jobs[1].url == "https://www.vagas.com.br/vagas/v7654321/tecnico-offshore"


def test_vagas_com_br_zero_vagas_so_com_texto_explicito():
    ok = vagas_com_br.collect(vg_ctx(FakeHttp().add(VG_URL, "<html><body><h2>No momento n&atilde;o h&aacute; vagas abertas</h2></body></html>")))
    assert ok.status == "complete" and ok.jobs == [] and ok.pages_received == 1


def test_vagas_com_br_conteudo_inesperado_e_format_changed():
    assert_failed(vagas_com_br.collect(vg_ctx(FakeHttp().add(VG_URL, "<html><body><div id='app'></div><script>nao há vagas</script></body></html>"))),
                  "format_changed")
    assert_failed(vagas_com_br.collect(vg_ctx(FakeHttp().add(VG_URL, "<html><body>Faça login</body></html>"))), "format_changed")



def test_greenhouse_subarvore_de_escritorio_pelo_quadro_completo():
    board = {"jobs": [
        {"id": 1, "title": "Rio", "content": "&lt;p&gt;a&lt;/p&gt;", "offices": [{"id": 114971, "parent_id": 69385}],
         "location": {"name": "Brazil - Rio de Janeiro"}},
        {"id": 2, "title": "Brasil", "content": "b", "offices": [{"id": 69385, "parent_id": None}], "location": {"name": "Brazil"}},
        {"id": 3, "title": "Londres", "content": "", "offices": [{"id": 500, "parent_id": None}], "location": {"name": "London"}},
    ]}
    b = greenhouse.collect(gh_ctx(FakeHttp().add("boards/capco/jobs?content=true", board), {"board": "capco", "office_root_id": 69385}))
    assert b.status == "complete" and sorted(j.external_id for j in b.jobs) == ["1", "2"]
