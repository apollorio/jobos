"""Aker Solutions (aker_site_json/1): lista do site corporativo, detalhe por jobPostId, XML do SF e probe().

Sem rede: FakeHttp com respostas enlatadas por trecho de URL (copiado de test_collectors_ported.py). As páginas
imitam o HTML real de 23/10/2026: um <script> com ReactDOMClient.hydrateRoot(..., React.createElement(LayoutWrapper,
{props})) e o bloco JobListBlock com o array "jobs".
"""
from __future__ import annotations

import json

import pytest

from jobos.collectors import aker_site
from jobos.collectors.base import Blocked, CollectContext, FormatChanged, SourceFailure
from jobos.settings import SourceConfig

LIMITS = {"max_pages": 3, "max_details": 5, "detail_ttl_days": 7}
LIST = "https://www.akersolutions.com/careers/job-search/"
SF_XML = "https://career2.successfactors.eu/career"
SF_DETAIL = "https://career2.successfactors.eu/sfcareer/jobreqcareer"


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


def make_ctx(params: dict, http: FakeHttp, *, coverage: str = "full_board", limits: dict | None = None,
             known=None) -> CollectContext:
    src = SourceConfig(source_id="aker-site-teste", company_id="aker", company_name="Aker Solutions",
                       platform="successfactors", adapter="aker_site_json", enabled=True, params=params,
                       coverage=coverage, limits=limits or dict(LIMITS), priority=2, board_url=LIST,
                       configuration_origin="teste", verification_status="teste")
    kw = {"known": known} if known else {}
    return CollectContext(run_id="run-1", source=src, http=http, **kw)


def assert_failed(batch, code: str):
    assert batch.status == ("blocked" if code == "blocked" else "failed")
    assert batch.error_code == code
    assert batch.complete is False and batch.can_infer_absence is False
    assert batch.jobs == []


# ------------------------------------------------------------------ páginas sintéticas

def item(jid, title, city="St. John's", country="Canada", region="Americas", deadline="November 13, 2026",
         ptype="Permanent") -> dict:
    return {"title": {"linkText": title, "href": f"/careers/job-search?jobPostId={jid}", "linkType": 0, "size": 0,
                      "theme": 0, "fullRefreshProperties": None, "ope": {}},
            "location": city, "region": region, "country": country, "jobType": "", "positionType": ptype,
            "deadline": deadline, "fullRefreshProperties": None, "ope": {}}


def hydrate(child_items: list, *, extra_menu: dict | None = None) -> str:
    props = {"siteLayoutProps": {"topMenu": {"globalSearch": {"endpoint": "/search/"}, **(extra_menu or {})},
                                 "child": {"pageName": "GenericPage", "components": {"items": child_items}},
                                 "footer": {"items": [{"html": "<p>rodapé Aker</p>", "blockName": "RichText"}]}}}
    return ('<!DOCTYPE html><html><head><title>Job Search | Aker Solutions</title></head><body>'
            '<div id="react_abc"><div class="site-layout">conteúdo renderizado</div></div>\n<script>\n'
            'ReactDOMClient.hydrateRoot(react_abc, React.createElement(LayoutWrapper,' + json.dumps(props) + '));\n'
            '</script>\n<script>document.addEventListener("DOMContentLoaded",function(){})</script></body></html>')


def list_page(jobs: list, *, block: str = "JobListBlock", extra_menu: dict | None = None) -> str:
    return hydrate([{"jobs": jobs, "placeholderList": ["e.g. Project Manager"], "loadMoreJobsText": "Load more",
                     "filters": [{"property": "country", "label": "Country"}], "blockName": block,
                     "fullRefreshProperties": None, "ope": {}}], extra_menu=extra_menu)


def detail_page(jid, *, location="St. John's, Canada", deadline="November 13, 2026", job_id=None,
                sections=("<h2>What will you be doing?</h2><ul><li>Instrument design</li><li>SIL &amp; F&amp;G</li></ul>",
                          "<h2>We think you should have:</h2><p>P. Eng.</p>")) -> str:
    rich = [{"title": None, "kicker": None, "type": 0, "blockName": "TitleSectionBlock",
             "text": {"blockName": "RichTextBlock", "items": [{"html": h, "blockName": "RichText"}]}} for h in sections]
    return hydrate([
        {"title": "Título", "kicker": "Job", "blockName": "HeroEvent"},
        {"title": "Info", "blockName": "EventArticle",
         "info": {"eventInfo": [{"label": "Location: ", "value": location}, {"label": "Apply by: ", "value": deadline},
                                {"label": "Position type: ", "value": "Permanent"},
                                {"label": "Job ID #: ", "value": str(job_id if job_id is not None else jid)}],
                  "registerLink": {"linkText": "Apply",
                                   "href": f"https://career2.successfactors.eu/sfcareer/jobreqcareer?jobId={jid}&company=akersoluti"},
                  "blockName": "EventInfo"},
         "article": {"items": rich}}])


JOBS3 = [item(21726, "Sr. Instrumentation Engineer"),
         item(21865, "Area Engineer- Piping", city="Mumbai", country="India", region="Asia Pacific",
              deadline="December 31, 2026"),
         item(21922, "AI Architect​", city="Oslo", country="Norway", region="Europe", deadline="October 31, 2026")]


def site_http(jobs=JOBS3, details: dict | None = None) -> FakeHttp:
    http = FakeHttp().add(LIST, list_page(jobs))
    for jid in [j["title"]["href"].rsplit("=", 1)[-1] for j in jobs if isinstance(j, dict) and isinstance(j.get("title"), dict)]:
        http.add(f"{LIST}?jobPostId={jid}", (details or {}).get(jid, detail_page(jid)))
    return http


# ------------------------------------------------------------------ contrato

def test_contrato_do_modulo():
    assert aker_site.VERSION == "aker_site_json/1"
    assert callable(aker_site.collect) and callable(aker_site.probe)


def test_registro_conhece_o_adapter_quando_registrado():
    """O registry é de outro dono: só confere que o caminho módulo:função existe para a chave proposta."""
    import importlib
    assert callable(getattr(importlib.import_module("jobos.collectors.aker_site"), "collect"))


# ------------------------------------------------------------------ lista do site

def test_lista_completa_todos_os_paises_e_detalhes():
    http = site_http()
    b = aker_site.collect(make_ctx({}, http))
    assert b.status == "complete" and b.complete and b.can_infer_absence
    assert b.coverage_kind == "full_board" and b.adapter_version == "aker_site_json/1"
    assert (b.raw_count, b.normalized_count, b.pages_expected, b.pages_received) == (3, 3, 1, 1)
    assert {j.raw["country"] for j in b.jobs} == {"Canada", "India", "Norway"}  # nenhum país escondido
    j = b.jobs[0]
    assert (j.platform, j.tenant, j.external_id) == ("successfactors", "akersoluti", "21726")
    assert j.url == "https://www.akersolutions.com/careers/job-search/?jobPostId=21726"
    assert j.raw["apply_url"] == "https://career2.successfactors.eu/sfcareer/jobreqcareer?jobId=21726&company=akersoluti"
    assert (j.title, j.location, j.deadline) == ("Sr. Instrumentation Engineer", "St. John's, Canada", "2026-11-13")
    assert j.raw["deadline_raw"] == "November 13, 2026" and j.raw["region"] == "Americas"
    assert j.published_raw is None  # o site não informa publicação; detecção é outra data
    assert j.description_status == "full" and j.original_length == len(j.description)
    assert "What will you be doing?" in j.description and "- SIL & F&G" in j.description
    assert "P. Eng." in j.description and "rodapé" not in j.description  # só o artigo da vaga
    assert b.jobs[2].title == "AI Architect"  # sem espaço de largura zero
    assert b.details_fetched == 3 and b.warnings == []
    assert http.calls[0]["url"] == LIST and http.calls[0]["params"] is None


def test_orcamento_de_detalhes_nao_torna_o_lote_parcial():
    b = aker_site.collect(make_ctx({}, site_http(), limits={**LIMITS, "max_details": 1}))
    assert b.status == "complete" and b.details_fetched == 1
    assert [j.description_status for j in b.jobs] == ["full", "missing", "missing"]
    assert any("limite de detalhes" in w for w in b.warnings)


def test_detalhe_conhecido_e_igual_nao_e_buscado_de_novo():
    from jobos.collectors.base import signature
    first = aker_site.collect(make_ctx({}, site_http()))
    sigs = {j.external_id: j.listing_signature for j in first.jobs}
    from jobos.timeutil import iso

    def known(ext, url):
        return {"listing_signature": sigs.get(ext), "detail_fetched_at": iso(), "has_description": True}
    http = site_http()
    b = aker_site.collect(make_ctx({}, http, known=known))
    assert b.status == "complete" and b.details_fetched == 0
    assert [c["url"] for c in http.calls] == [LIST]
    assert signature("x") != sigs["21726"]


def test_detalhe_que_cai_na_lista_vira_aviso_e_nao_encerra_nada():
    """jobPostId desconhecido: o site devolve a página de lista (sem EventInfo)."""
    http = site_http(details={"21726": list_page(JOBS3)})
    b = aker_site.collect(make_ctx({}, http))
    assert b.status == "complete" and b.details_fetched == 2
    assert b.jobs[0].description_status == "missing"
    assert any(w.startswith("detalhe 21726: format_changed") for w in b.warnings)


def test_detalhe_com_job_id_diferente_e_rejeitado():
    http = site_http(details={"21865": detail_page("21865", job_id="99999")})
    b = aker_site.collect(make_ctx({}, http))
    assert b.jobs[1].description_status == "missing"
    assert any("detalhe 21865" in w and "99999" in w for w in b.warnings)


def test_detalhe_com_falha_de_rede_vira_aviso():
    http = site_http(details={"21922": SourceFailure("network", "timeout")})
    b = aker_site.collect(make_ctx({}, http))
    assert b.status == "complete" and b.jobs[2].description_status == "missing"
    assert any(w.startswith("detalhe 21922: network") for w in b.warnings)


def test_detalhe_sem_texto_fica_missing():
    http = site_http(details={"21726": detail_page("21726", sections=())})
    b = aker_site.collect(make_ctx({}, http))
    assert b.jobs[0].description_status == "missing"
    assert any("sem texto" in w for w in b.warnings)


def test_lista_vazia_reconhecida_e_completa():
    b = aker_site.collect(make_ctx({}, FakeHttp().add(LIST, list_page([]))))
    assert b.status == "complete" and b.can_infer_absence and b.jobs == [] and b.raw_count == 0


def test_ids_repetidos_sao_deduplicados():
    b = aker_site.collect(make_ctx({}, site_http(jobs=[JOBS3[0], JOBS3[0], JOBS3[1]])))
    assert b.status == "complete" and [j.external_id for j in b.jobs] == ["21726", "21865"] and b.raw_count == 3


def test_item_sem_jobpostid_torna_o_lote_parcial():
    broken = item(1, "Sem id")
    broken["title"]["href"] = "/careers/job-search/"
    b = aker_site.collect(make_ctx({}, site_http(jobs=[JOBS3[0], broken])))
    assert b.status == "partial" and b.error_code == "incomplete_listing"
    assert b.complete is False and b.can_infer_absence is False
    assert [j.external_id for j in b.jobs] == ["21726"]


def test_todos_os_itens_irreconheciveis_e_format_changed():
    b = aker_site.collect(make_ctx({}, FakeHttp().add(LIST, list_page([{"name": "x"}, {"title": "sem dict"}]))))
    assert b.status == "failed" and b.error_code == "format_changed" and b.can_infer_absence is False


@pytest.mark.parametrize("html", [
    "<html><body><h1>Just a moment...</h1><form id='challenge'></form></body></html>",
    "",
    list_page(JOBS3, block="OtherBlock"),
    list_page(JOBS3, extra_menu={"jobs": [{"x": 1}]}),
    list_page(JOBS3).replace('"jobs": [{', '"jobs": [{{', 1),
])
def test_conteudo_inesperado_e_format_changed(html):
    assert_failed(aker_site.collect(make_ctx({}, FakeHttp().add(LIST, html))), "format_changed")


@pytest.mark.parametrize("exc,code", [(Blocked("HTTP 403"), "blocked"), (SourceFailure("network", "timeout"), "network"),
                                      (SourceFailure("not_found", "HTTP 404"), "not_found")])
def test_falha_na_lista_falha_o_lote(exc, code):
    assert_failed(aker_site.collect(make_ctx({}, FakeHttp().add(LIST, exc))), code)


def test_escopo_muda_com_modo_e_empresa():
    http = site_http()
    site = aker_site.collect(make_ctx({}, http)).scope_id
    other = aker_site.collect(make_ctx({"sf_company": "outra"}, site_http())).scope_id
    xml = aker_site.collect(make_ctx({"sf_xml": True}, FakeHttp().add(SF_XML, sf_xml([])))).scope_id
    assert len({site, other, xml}) == 3


@pytest.mark.parametrize("raw,iso_", [("November 13, 2026", "2026-11-13"), ("December 1, 2026", "2026-12-01"),
                                      ("May 5 2027", "2027-05-05"), ("13/11/2026", None), ("", None), (None, None),
                                      ("Smarch 1, 2026", None)])
def test_data_limite_em_ingles(raw, iso_):
    assert aker_site._iso_date(raw) == iso_


def test_data_limite_nao_reconhecida_fica_crua():
    b = aker_site.collect(make_ctx({}, site_http(jobs=[item(21726, "X", deadline="ASAP")])))
    assert b.jobs[0].deadline == "ASAP"


# ------------------------------------------------------------------ modo XML do SuccessFactors

def sf_job(rid, title, country="Norway", desc="<p>Intro</p><h1>What will you be doing?</h1><p>[[responsibilities]]</p>"):
    return (f"<Job>\n<JobTitle><![CDATA[{title}]]></JobTitle>\n<Job-Description><![CDATA[{desc}]]></Job-Description>\n"
            f"<ReqId><![CDATA[{rid}]]></ReqId>\n<filter7>\n<label><![CDATA[Country]]></label>\n"
            f"<value><![CDATA[{country}]]></value>\n</filter7>\n<filter4>\n<label><![CDATA[Position Type]]></label>\n"
            f"<value><![CDATA[Permanent]]></value>\n</filter4>\n</Job>\n")


def sf_xml(jobs: list[str]) -> str:
    return '<?xml version="1.0" encoding="UTF-8"?>\n<Job-Listing>\n' + "".join(jobs) + "</Job-Listing>\n"


def test_xml_e_sempre_parcial_sem_ausencia():
    xml = sf_xml([sf_job("21922", "AI Platform &amp; Infrastructure Enginee"),
                  sf_job("21165", "Rope Access Technician", country="Canada", desc="<p>Texto completo</p>"),
                  sf_job("", "Sem ReqId")])
    http = FakeHttp().add(SF_XML, xml, params={"resultType": "XML", "company": "akersoluti"})
    b = aker_site.collect(make_ctx({"sf_xml": True}, http))
    assert b.status == "partial" and b.complete is False and b.can_infer_absence is False
    assert (b.raw_count, b.normalized_count) == (3, 2)
    j = b.jobs[0]
    assert (j.platform, j.tenant, j.external_id) == ("successfactors", "akersoluti", "21922")
    assert j.title == "AI Platform & Infrastructure Enginee" and j.location == "Norway"
    assert j.url == "https://career2.successfactors.eu/sfcareer/jobreqcareer?jobId=21922&company=akersoluti"
    assert j.description_status == "partial" and "[[" not in j.description and "responsibilities" in j.truncation_note
    assert b.jobs[1].description_status == "full" and b.jobs[1].description == "Texto completo"
    assert any("sem ReqId" in w for w in b.warnings) and any("superconjunto" in w for w in b.warnings)
    assert http.calls[0]["params"] == {"company": "akersoluti", "career_ns": "job_listing_summary", "resultType": "XML"}


def test_xml_vazio_reconhecido_continua_parcial():
    b = aker_site.collect(make_ctx({"sf_xml": True}, FakeHttp().add(SF_XML, sf_xml([]))))
    assert b.status == "partial" and b.jobs == [] and b.error_code is None


@pytest.mark.parametrize("text", [
    "<html><body>Login</body></html>",
    '<?xml version="1.0"?><Other><Job/></Other>',
    '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><Job-Listing><Job>&a;</Job></Job-Listing>',
    '<?xml version="1.0"?><Job-Listing><Job><ReqId>1</ReqId></Job>',
    "",
])
def test_xml_inesperado_e_format_changed(text):
    assert_failed(aker_site.collect(make_ctx({"sf_xml": True}, FakeHttp().add(SF_XML, text))), "format_changed")


def test_xml_bloqueado():
    assert_failed(aker_site.collect(make_ctx({"sf_xml": True}, FakeHttp().add(SF_XML, Blocked("HTTP 403")))), "blocked")


# ------------------------------------------------------------------ probe()

SF_ALIVE = ('<html><head><title>Career Opportunities: Sr. Instrumentation Engineer (21726) </title></head><body>'
            '<div tabindex="0">Requisition ID&nbsp;<b>21726</b>&nbsp;-&nbsp;Posted&nbsp;<b id="postedOnDate"></b></div>'
            '<p>Job Description</p></body></html>')
SF_GONE = ('<html><head><title></title></head><body><table><tr><td>This job cannot be viewed at this time. It has either '
           'been deleted or is no longer available for application. For more job opportunities, please click '
           '<a href="/portalcareer?company=akersoluti">here</a>.</td></tr></table></body></html>')


def probe_ctx(response) -> tuple[CollectContext, FakeHttp]:
    http = FakeHttp().add(SF_DETAIL, response)
    return make_ctx({}, http), http


def test_probe_vaga_viva():
    c, http = probe_ctx(SF_ALIVE)
    assert aker_site.probe(c, "21726", None) == "alive"
    assert http.calls[0]["params"] == {"jobId": "21726", "company": "akersoluti"}
    assert http.calls[0]["headers"]["Accept-Language"].startswith("en")


def test_probe_vaga_apagada_ou_encerrada():
    c, _ = probe_ctx(SF_GONE)
    assert aker_site.probe(c, "20001", "https://www.akersolutions.com/careers/job-search/?jobPostId=20001") == "gone"


def test_probe_usa_o_id_da_url_quando_falta_external_id():
    c, http = probe_ctx(SF_ALIVE)
    assert aker_site.probe(c, None, "https://www.akersolutions.com/careers/job-search/?jobPostId=21726") == "alive"
    assert http.calls[0]["params"]["jobId"] == "21726"


def test_probe_sem_id_nao_faz_requisicao():
    c, http = probe_ctx(SF_ALIVE)
    assert aker_site.probe(c, None, "https://www.akersolutions.com/careers/") == "unknown"
    assert aker_site.probe(c, "abc", None) == "unknown"
    assert http.calls == []


@pytest.mark.parametrize("response", [
    SourceFailure("network", "timeout"), Blocked("HTTP 403"), SourceFailure("not_found", "HTTP 404"),
    SourceFailure("http_500", "HTTP 500"), FormatChanged("x"),
    "<html><body>Loading...</body></html>",                       # página ambígua
    SF_ALIVE.replace("21726", "21815"),                           # outra requisição
    SF_ALIVE + SF_GONE,                                           # sinais contraditórios
])
def test_probe_sem_prova_forte_e_unknown(response):
    c, _ = probe_ctx(response)
    assert aker_site.probe(c, "21726", None) == "unknown"
