"""Sage People fRecruit (Salesforce Sites): lista Visualforce, detalhe por vacancyNo e probe individual.

Sem rede: FakeHttp com HTML enlatado no formato observado em tridentenergy-hr.my.salesforce-sites.com (23/10/2026):
linhas `tr.dataRow` (classe às vezes com espaço antes), células `<span><span>VALOR</span></span>`, cabeçalho com seta de
ordenação, `pagingPanel` com "Page 1 of N", detalhe em `table.detailList` com rich text em tabela aninhada e a
mensagem "That job is no longer open for applications." para vaga encerrada.
"""
from __future__ import annotations

import pytest

from jobos.collectors import sage_frecruit
from jobos.collectors.base import Blocked, CollectContext, FormatChanged, SourceFailure
from jobos.settings import SourceConfig

LIMITS = {"max_pages": 3, "max_details": 5, "detail_ttl_days": 7}
BASE = "https://tridentenergy-hr.my.salesforce-sites.com"
HOST = "tridentenergy-hr.my.salesforce-sites.com"
LIST = "/recruit/fRecruit__ApplyJobList"


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


def make_ctx(http: FakeHttp, params: dict | None = None, *, coverage: str = "full_board", limits: dict | None = None,
             known=None) -> CollectContext:
    src = SourceConfig(source_id="trident-frecruit", company_id="trident", company_name="Trident Energy",
                       platform="sage_frecruit", adapter="sage_frecruit", enabled=True,
                       params={"base": BASE} if params is None else params, coverage=coverage,
                       limits=limits or dict(LIMITS), priority=1, board_url=None, configuration_origin="teste",
                       verification_status="teste")
    kw = {"known": known} if known else {}
    return CollectContext(run_id="run-1", source=src, http=http, **kw)


# ------------------------------------------------------------------ HTML enlatado

def cell(value: str, n: int = 0) -> str:
    return (f'<td class="dataCell  " id="j_id0:x:{n}" colspan="1"><span id="a{n}"><span id="b{n}">{value}</span>'
            f'</span></td>')


def row(vn: str | None, title: str, country: str = "Brazil", region: str = "Onshore - Rio de Janeiro",
        close: str = "", emp: str = "Permanent", cls: str = "dataRow even ") -> str:
    link = (f'<a href="/recruit/fRecruit__ApplyJob?vacancyNo={vn}">{title}</a>' if vn else title)
    first = f'<td class="dataCell  " id="j_id0:t" colspan="1"><span id="t">{link}</span></td>'
    return (f'<tr class="{cls}" onmouseover="if (window.hiOn){{hiOn(this);}} ">' + first + cell(vn or "", 1) +
            cell(emp, 2) + cell(country, 3) + cell(region, 4) + cell(close, 5) + "</tr>")


HEADERS = ["Vacancy Name&#9650;", "Vacancy No", "Employment Type", "Location Country", "Location Region",
           "Applications Close Date"]


def header(labels=None) -> str:
    ths = "".join(f'<th class="headerRow" scope="col" colspan="1"><div id="h{i}:sortDiv"><a href="#" '
                  f'onclick="A4J.AJAX.Submit(\'f\',event,{{}});return false;">{lab}</a></div></th>'
                  for i, lab in enumerate(labels or HEADERS))
    return f'<tr class=" headerRow">{ths}</tr>'


def paging(text: str | None = "Page 1 of 1", next_link: bool = False) -> str:
    if text is None:
        return ""
    nxt = ('<a href="#" onclick="A4J.AJAX.Submit(\'f\',event,{});return false;" class="link-pagination">Next</a>'
           if next_link else '<span class="link-pagination">Next</span>')
    return ('<div class="pagingPanel"><span class="link-pagination">First</span><span class="link-pagination">Previous'
            f'</span><span class="link-pagination">{text}</span>{nxt}<span class="link-pagination">Last</span></div>')


def list_page(rows: list[str], *, pages: str | None = "Page 1 of 1", labels=None, next_link: bool = False,
              with_header: bool = True) -> str:
    return ('<html><head><title>Current Vacancies</title><style>.pagingPanel{text-align:center}</style></head><body>'
            '<form id="j_id0:f" method="post" action="/recruit/fRecruit__ApplyJobList">'
            '<table class="list" border="0">' + (f"<thead>{header(labels)}</thead>" if with_header else "") +
            "<tbody>" + "".join(rows) + "</tbody></table>" + paging(pages, next_link) +
            '<input type="hidden" name="com.salesforce.visualforce.ViewState" value="i:AAAA"/></form></body></html>')


def dl_row(label: str, value: str, extra: str = "") -> str:
    return (f'<tr><th class="labelCol vfLabelColTextWrap {extra}" scope="row"><label>\n{label}</label></th>'
            f'<td class="data2Col {extra}"><span id="s"><span id="v">{value}</span></span></td></tr>')


def detail_page(vn: str, title: str, *, job_details: str = "<b>Lidera</b> a equipe de conv&eacute;s.<br>Segunda linha.",
                requirements: str = "&#8226; Licen&ccedil;a v&aacute;lida.<br>\n&#8226; Ingl&ecirc;s.") -> str:
    rich = ('<table class="htmlDetailElementTable" border="0"><tr><td><div class="sfdc_richtext">' + job_details +
            '</div></td></tr></table><script>x = window.onload; window.onload=function(){ if (x) x(); };</script>')
    rows = (dl_row("Vacancy Name", title, "first") + dl_row("Vacancy No", vn) + dl_row("Location Country", "Brazil") +
            dl_row("Location Region", "Offshore - Rio de Janeiro") + dl_row("Job Details", rich) +
            dl_row("Key Requirements", requirements) + dl_row("Currency", "BRL", "last"))
    return (f'<html><head><title>{title} | Job Details</title></head><body><div class="pbBody">'
            f'<table class="detailList" border="0" cellpadding="0" cellspacing="0">{rows}</table></div>'
            '<div class="pbBottomButtons"><input type="submit" value="Apply"/><ul class="social"><li>'
            '<a href="https://www.facebook.com/sharer">rodapé social</a></li></ul></div></body></html>')


GONE_PAGE = ('<html><head><title>| Job Details</title></head><body><span id="m"><div class="message errorM3" role="alert">'
             '<table class="messageTable"><tr valign="top"><td><img alt="ERROR" class="msgIcon" src="/s.gif"/></td>'
             '<td class="messageCell"><div id="j_id0:mt" class="messageText"><span style="color:#cc0000">\n'
             '<h4>Error:</h4></span>That job is no longer open for applications.<br /></div></td></tr></table></div>'
             '</span><form id="j_id0:f" method="post" action="/recruit/fRecruit__ApplyJob"></form></body></html>')

ROWS3 = [row("VN823", "Banco de Talentos - Pessoas com Defici&ecirc;ncia(PcD/ PwDs)", cls="dataRow even  first "),
         row("VN880", "Bosun", region="Offshore - Rio de Janeiro", cls=" dataRow odd "),
         row("VN899", "HR Analyst", close="31/10/2026", cls="dataRow even  last ")]


def happy_http(rows=None, **kw) -> FakeHttp:
    http = FakeHttp().add(LIST, list_page(ROWS3 if rows is None else rows, **kw))
    http.add("vacancyNo=VN823", detail_page("VN823", "Banco de Talentos - PcD"))
    http.add("vacancyNo=VN880", detail_page("VN880", "Bosun"))
    http.add("vacancyNo=VN899", detail_page("VN899", "HR Analyst"))
    return http


# ------------------------------------------------------------------ contrato

def test_contrato_do_modulo():
    assert sage_frecruit.VERSION == "sage_frecruit/1"
    assert callable(sage_frecruit.collect) and callable(sage_frecruit.probe)


def test_caminho_feliz_lista_completa_e_detalhe():
    http = happy_http()
    b = sage_frecruit.collect(make_ctx(http))
    assert b.status == "complete" and b.complete and b.can_infer_absence
    assert b.adapter_version == "sage_frecruit/1" and b.error_code is None
    assert (b.pages_received, b.pages_expected, b.raw_count) == (1, 1, 3)
    assert http.calls[0]["url"] == BASE + LIST
    assert [j.external_id for j in b.jobs] == ["VN823", "VN880", "VN899"]
    assert {(j.platform, j.tenant) for j in b.jobs} == {("sage_frecruit", HOST)}
    pcd, bosun, hr = b.jobs
    assert pcd.title == "Banco de Talentos - Pessoas com Deficiência(PcD/ PwDs)"
    assert pcd.talent_pool is True and bosun.talent_pool is None and hr.talent_pool is None
    assert bosun.url == BASE + "/recruit/fRecruit__ApplyJob?vacancyNo=VN880"
    assert bosun.location == "Offshore - Rio de Janeiro, Brazil" and bosun.raw["workplace_hint"] == "offshore"
    assert hr.location == "Onshore - Rio de Janeiro, Brazil" and hr.raw["workplace_hint"] == "onshore"
    assert bosun.workplace is None  # dica fica em raw; 'offshore' não é remote/hybrid/onsite do contrato
    assert bosun.raw["employment_type"] == "Permanent" and bosun.raw["country"] == "Brazil"
    assert hr.deadline == "31/10/2026" and bosun.deadline is None
    assert all(j.published_raw is None and j.published_source is None for j in b.jobs)
    assert b.details_fetched == 3
    d = bosun.description
    assert d.startswith("Job Details:\nLidera a equipe de convés.\nSegunda linha.")
    assert "Key Requirements:\n• Licença válida.\n• Inglês." in d
    assert "window.onload" not in d and "rodapé social" not in d and "Apply" not in d
    assert "Vacancy No" not in d and "Currency" not in d and "BRL" not in d
    assert bosun.description_status == "full" and bosun.original_length == len(d)
    assert bosun.raw["currency"] == "BRL" and "Job Details" in bosun.raw["detail_labels"]
    assert bosun.listing_signature and bosun.listing_signature != hr.listing_signature


def test_scope_id_muda_com_escopo_e_nao_com_ordem():
    http = happy_http().add("/careers/fRecruit__ApplyJobList", list_page(ROWS3))
    a = sage_frecruit.collect(make_ctx(http)).scope_id
    a2 = sage_frecruit.collect(make_ctx(http)).scope_id
    c = sage_frecruit.collect(make_ctx(http, {"base": BASE, "country": "Brazil"})).scope_id
    p = sage_frecruit.collect(make_ctx(http, {"base": BASE, "site_path": "/careers"})).scope_id
    assert a == a2 and len({a, c, p}) == 3


# ------------------------------------------------------------------ conteúdo inesperado e falhas

@pytest.mark.parametrize("resp,code", [
    ("<html><body>Please log in to continue</body></html>", "format_changed"),
    ("<html><head><title>Down for Maintenance</title></head><body>Site em manutenção</body></html>", "format_changed"),
    (Blocked("HTTP 403"), "blocked"),
    (SourceFailure("network", "ConnectionError"), "network"),
    (SourceFailure("not_found", "HTTP 404"), "not_found"),
])
def test_primeira_pagina_inesperada_ou_falha(resp, code):
    b = sage_frecruit.collect(make_ctx(FakeHttp().add(LIST, resp)))
    assert b.status == ("blocked" if code == "blocked" else "failed") and b.error_code == code
    assert b.complete is False and b.can_infer_absence is False and b.jobs == []


def test_base_invalida_e_falha_de_configuracao():
    b = sage_frecruit.collect(make_ctx(FakeHttp(), {"base": "tridentenergy-hr"}))
    assert b.status == "failed" and b.error_code == "config" and b.jobs == []


def test_lista_vazia_reconhecida_e_completa():
    b = sage_frecruit.collect(make_ctx(FakeHttp().add(LIST, list_page([], pages="Page 1 of 1"))))
    assert b.status == "complete" and b.jobs == [] and b.can_infer_absence


def test_lista_vazia_sem_paginacao_e_parcial():
    b = sage_frecruit.collect(make_ctx(FakeHttp().add(LIST, list_page([], pages=None))))
    assert b.status == "partial" and not b.can_infer_absence and b.error_code == "incomplete_listing"


def test_varias_paginas_sem_postback_e_parcial():
    http = happy_http(pages="Page 1 of 3", next_link=True)
    b = sage_frecruit.collect(make_ctx(http))
    assert b.status == "partial" and not b.complete and not b.can_infer_absence
    assert (b.pages_expected, b.pages_received) == (3, 1)
    assert len(b.jobs) == 3 and "postback" in b.error_message
    assert all(c["method"] == "GET" for c in http.calls)


def test_sem_painel_de_paginacao_e_parcial():
    b = sage_frecruit.collect(make_ctx(happy_http(pages=None)))
    assert b.status == "partial" and not b.can_infer_absence and len(b.jobs) == 3
    assert "Page X of N" in b.error_message


def test_cabecalho_desconhecido_le_por_posicao_mas_e_parcial():
    b = sage_frecruit.collect(make_ctx(happy_http(with_header=False)))
    assert b.status == "partial" and "cabeçalho" in b.error_message
    assert [j.external_id for j in b.jobs] == ["VN823", "VN880", "VN899"]
    assert b.jobs[1].location == "Offshore - Rio de Janeiro, Brazil"


def test_cabecalho_em_outra_ordem_mapeia_por_rotulo():
    labels = ["Vacancy Name", "Vacancy No", "Employment Type", "Location Region", "Location Country",
              "Applications Close Date"]
    rows = [row("VN880", "Bosun", country="Offshore - Rio de Janeiro", region="Brazil")]  # colunas trocadas
    http = FakeHttp().add(LIST, list_page(rows, labels=labels)).add("vacancyNo=VN880", detail_page("VN880", "Bosun"))
    b = sage_frecruit.collect(make_ctx(http))
    assert b.status == "complete" and b.jobs[0].location == "Offshore - Rio de Janeiro, Brazil"


def test_linha_sem_vacancy_no_torna_parcial():
    rows = [*ROWS3, row(None, "Vaga sem link")]
    b = sage_frecruit.collect(make_ctx(happy_http(rows=rows)))
    assert b.status == "partial" and not b.can_infer_absence
    assert b.raw_count == 4 and len(b.jobs) == 3 and "vacancyNo" in b.error_message


def test_escopo_de_pais_declarado_filtra_e_avisa():
    rows = [*ROWS3, row("VN900", "Production Operator", country="Congo", region="Offshore - Pointe-Noire")]
    b = sage_frecruit.collect(make_ctx(happy_http(rows=rows), {"base": BASE, "country": "brazil"},
                                       coverage="filtered_board"))
    assert b.status == "complete" and b.can_infer_absence
    assert [j.external_id for j in b.jobs] == ["VN823", "VN880", "VN899"] and b.raw_count == 4
    assert any("fora do escopo" in w for w in b.warnings)


def test_sem_filtro_de_pais_nada_e_escondido():
    rows = [*ROWS3, row("VN900", "Production Operator", country="Congo", region="Offshore - Pointe-Noire")]
    http = happy_http(rows=rows).add("vacancyNo=VN900", detail_page("VN900", "Production Operator"))
    b = sage_frecruit.collect(make_ctx(http))
    assert b.status == "complete" and len(b.jobs) == 4
    assert b.jobs[3].location == "Offshore - Pointe-Noire, Congo"


# ------------------------------------------------------------------ detalhe

def test_orcamento_de_detalhes():
    http = happy_http()
    b = sage_frecruit.collect(make_ctx(http, limits={**LIMITS, "max_details": 1}))
    assert b.status == "complete" and b.details_fetched == 1
    assert [j.description_status for j in b.jobs] == ["full", "missing", "missing"]
    assert any("limite de detalhes" in w for w in b.warnings)


def test_detalhe_falho_ou_encerrado_nao_derruba_o_lote():
    http = FakeHttp().add(LIST, list_page(ROWS3))
    http.add("vacancyNo=VN823", GONE_PAGE)
    http.add("vacancyNo=VN880", SourceFailure("network", "Timeout"))
    http.add("vacancyNo=VN899", detail_page("VN123", "Outra vaga"))
    b = sage_frecruit.collect(make_ctx(http))
    assert b.status == "complete" and len(b.jobs) == 3 and b.details_fetched == 0
    assert all(j.description_status == "missing" and j.description == "" for j in b.jobs)
    w = " | ".join(b.warnings)
    assert "VN823: página diz: That job is no longer open" in w
    assert "VN880: network" in w and "VN899: página trouxe a vaga VN123" in w


def test_detalhe_sem_detaillist_e_sem_mensagem_avisa_layout():
    http = FakeHttp().add(LIST, list_page(ROWS3[:1])).add("vacancyNo=VN823", "<html><body>Algo novo</body></html>")
    b = sage_frecruit.collect(make_ctx(http))
    assert b.status == "complete" and b.jobs[0].description_status == "missing"
    assert any("sem table.detailList" in w for w in b.warnings)


def test_detalhe_pulado_quando_ja_conhecido_e_sem_mudanca():
    first = sage_frecruit.collect(make_ctx(happy_http()))
    sigs = {j.external_id: j.listing_signature for j in first.jobs}
    import datetime as dt
    fresh = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).isoformat()

    def known(ext, url):
        return {"listing_signature": sigs.get(ext), "detail_fetched_at": fresh, "has_description": True}
    http = happy_http()
    b = sage_frecruit.collect(make_ctx(http, known=known))
    assert b.status == "complete" and b.details_fetched == 0
    assert [c["url"] for c in http.calls] == [BASE + LIST]


def test_parse_detail_rotulos_e_mensagem():
    d = sage_frecruit.parse_detail(detail_page("VN880", "Bosun"))
    assert [k for k, _ in d["fields"]] == ["Vacancy Name", "Vacancy No", "Location Country", "Location Region",
                                          "Job Details", "Key Requirements", "Currency"]
    assert d["values"]["vacancy no"] == "VN880" and d["error"] is None
    g = sage_frecruit.parse_detail(GONE_PAGE)
    assert g["fields"] == [] and g["error"] == "That job is no longer open for applications."


# ------------------------------------------------------------------ probe

def probe(resp, ext="VN880", url=None, params=None):
    http = FakeHttp().add("fRecruit__ApplyJob", resp)
    res = sage_frecruit.probe(make_ctx(http, params), ext, url)
    return res, http


def test_probe_alive():
    res, http = probe(detail_page("VN880", "Bosun"))
    assert res == "alive"
    assert http.calls[0]["url"] == BASE + "/recruit/fRecruit__ApplyJob?vacancyNo=VN880"


@pytest.mark.parametrize("resp", [GONE_PAGE, SourceFailure("not_found", "HTTP 404"), (410, "")])
def test_probe_gone_so_com_evidencia_forte(resp):
    assert probe(resp)[0] == "gone"


@pytest.mark.parametrize("resp", [
    SourceFailure("network", "Timeout"), SourceFailure("http_503", "HTTP 503"), Blocked("HTTP 403"),
    FormatChanged("x"), "<html><body>Down for maintenance</body></html>",
    ('<html><body><div class="message errorM3"><div class="messageText">An internal server error has occurred'
     '</div></div></body></html>'),
    detail_page("VN123", "Outra vaga")])
def test_probe_unknown_sem_evidencia(resp):
    assert probe(resp)[0] == "unknown"


def test_probe_usa_url_quando_falta_external_id_e_base():
    url = BASE + "/recruit/fRecruit__ApplyJob?vacancyNo=VN880"
    res, http = probe(GONE_PAGE, ext=None, url=url, params={})
    assert res == "gone" and http.calls[0]["url"] == url
    assert probe(GONE_PAGE, ext=None, url=None)[0] == "unknown"
