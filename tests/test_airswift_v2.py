"""Airswift (HubSpot CMS, airswift_hubspot/1): lista filtrada por localidade, paginação por page_num, detalhe JSON-LD
e verificação individual (probe). Sem rede: FakeHttp com respostas enlatadas por trecho de URL e params.

O HTML abaixo reproduz a estrutura observada em https://www.airswift.com/jobs?location=Brazil (23/10/2026).
"""
from __future__ import annotations

import re

import pytest

from jobos.collectors import airswift
from jobos.collectors.base import Blocked, CollectContext, SourceFailure, scope_id
from jobos.settings import SourceConfig
from jobos.timeutil import iso

LIMITS = {"max_pages": 5, "max_details": 25, "detail_ttl_days": 7}
LIST = "https://www.airswift.com/jobs"


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


def make_ctx(http: FakeHttp, *, params: dict | None = None, limits: dict | None = None, known=None) -> CollectContext:
    src = SourceConfig(source_id="airswift-site", company_id="airswift", company_name="Airswift", platform="hubspot",
                       adapter="airswift_hubspot", enabled=True, params={"location": "Brazil"} if params is None else params,
                       coverage="filtered_board", limits=limits or dict(LIMITS), priority=1, board_url=None,
                       configuration_origin="teste", verification_status="teste")
    kw = {"known": known} if known else {}
    return CollectContext(run_id="run-1", source=src, http=http, **kw)


# ------------------------------------------------------------------ HTML de teste

def card(jid: str, title: str, loc: str = "Rio de Janeiro, Brazil", date: str = "6 Oct 2026", kind: str = "Permanent",
         slug: str | None = None, summary: str = "Airswift is seeking ...") -> str:
    slug = slug or title.lower().replace(" & ", "-").replace(" ", "-")
    return f'''<article class="c-card-job-item">
  <div class="c-card-job-item__top">
    <p class="c-card-job-item__top-cell c-card-job-item__top-cell--left">
      <img src="contract.svg" class="c-card-job-item__top-icon" alt="Employment Type">
      {kind}
    </p>
    <p class="c-card-job-item__top-cell c-card-job-item__top-cell--right">
      <img src="calendar.svg" class="c-card-job-item__top-icon" alt="Date Published">
      {date}
    </p>
  </div>
  <div>
    <p class="c-card-job-item__location">
      <img src="location.svg" class="c-card-job-item__top-icon" alt="Location">
      {loc}
    </p>
    <p class="c-card-job-item__title"><a href="/jobs/{slug}-{jid}">
      {title}
    </a></p>
    <p class="c-card-job-item__summary">{summary}</p>
  </div>
  <div class="c-card-job-item__bottom"><a class="c-button" href="/jobs/{slug}-{jid}">View Job and Apply</a></div>
</article>'''


def page(cards: list[str], *, total: int | None = None, pages: int = 1, offset: int | None = 0, term: str = "Brazil",
         empty_text: bool | None = None) -> str:
    header = ""
    if total is not None:
        header = (f'<header class="c-card-job-header"><h2 class="c-card-job-header__title">Latest Jobs</h2>'
                  f'<p class="c-card-job-header__summary">Found {total} jobs on {pages} page{"s" if pages > 1 else ""} </p></header>')
    comment = "" if offset is None else (f"<!--// published=1&is_open=1&expiry_date__gt=1792747477629&orderBy=-date_published"
                                         f"&location_grouped__icontains={term}&limit=24&offset={offset} //-->")
    if empty_text is None:
        empty_text = not cards
    body = ('<div class="c-card-job__list">' + "".join(cards) + "</div>") if cards else ""
    sorry = ("<p>Sorry, we couldn&#39;t find any job listings matching these search parameters. Please, change your "
             "filters and search again.</p>") if empty_text else ""
    return (f'<html><body><main>{comment}<section class="o-module c-card-job o-wrapper-parent">'
            f'<div class="c-card-job__wrapper o-wrapper-centre">{header}{body}{sorry}</div></section></main>'
            f'<footer class="c-footer">rodapé</footer></body></html>')


def detail(jid: str, *, posted: str = "2026-05-25", valid: str = "2999-12-05", article: bool = True,
           desc_ld: str = "Texto do JSON-LD sem quebras.", ref: str | None = None, function: str = "Commissioning") -> str:
    ld = ('{"@context": "https://schema.org/", "@type": "JobPosting", "title": "X", '
          f'"description": "{desc_ld}\nlinha", "datePosted": "{posted}", "validThrough": "{valid}", '
          '"employmentType": "Permanent", "industry": {"name": "Oil & Gas - Onshore Oil"}, '
          '"jobLocation": {"@type": "Place", "address": {"addressLocality": "Rio de Janeiro", "addressCountry": "Brazil"}}}')
    body = ('<div class="c-jobs-article-content o-content-editor"><p>Primeiro parágrafo.</p><div><p>Aninhado.</p></div>'
            '<p>JOB RESPONSIBILITIES</p><ul><li>Item A</li></ul></div>') if article else ""
    stats = (f'<div class="c-jobs-article-stats"><div class="c-jobs-article-stats__item"><div class="c-jobs-article-stats__content">'
             f'<strong>Job reference</strong>\n {ref or jid}\n</div></div>'
             f'<div class="c-jobs-article-stats__item"><div class="c-jobs-article-stats__content"><strong>Sector</strong>'
             f' Energy - Oil &amp; Gas</div></div>'
             f'<div class="c-jobs-article-stats__item"><div class="c-jobs-article-stats__content"><strong>Function</strong>'
             f' {function}</div></div></div>')
    return (f'<html><head><script type="application/ld+json">{ld}</script></head><body><main>'
            f'<section class="c-jobs-article"><h1 class="c-jobs-article-header__title">X</h1>{stats}{body}'
            f'<div id="form"><iframe src="https://app.airswift.com/quickapply-embedded/{jid}"></iframe></div>'
            f'</section></main><footer>rodapé</footer></body></html>')


BRAZIL6 = [card("1273574", "Mechanical & Rotating Engineer", "Rio de Janeiro, Rio de Janeiro, Brazil"),
           card("1273952", "Subsea Controls Engineer", "Rio de Janeiro, Brazil", kind="Contract"),
           card("1273379", "Business Development Manager", "Houston , Texas, Brazil", date="5 Oct 2026"),
           card("1281014", "Senior Lawyer", "Rio de Janeiro, Brazil", date="28 Sep 2026"),
           card("1280889", "Assistente Administrativo", "Niteroi, Brazil", date="25 Sep 2026", summary=""),
           card("1280890", "Wind Sales Manager", "Niteroi, Brazil", date="25 Sep 2026")]
IDS6 = ["1273574", "1273952", "1273379", "1281014", "1280889", "1280890"]


def n_cards(start: int, n: int) -> list[str]:
    return [card(str(2000000 + i), f"Engineer {i}", "Macae, Brazil") for i in range(start, start + n)]


def durl(jid: str) -> str:
    """URL completa do detalhe (rota mais longa que a da lista, que é prefixo dela)."""
    for c in BRAZIL6:
        m = re.search(rf'href="(/jobs/[^"]*-{jid})"', c)
        if m:
            return "https://www.airswift.com" + m.group(1)
    raise KeyError(jid)


def with_details(http: FakeHttp, ids: list[str]) -> FakeHttp:
    for jid in ids:
        http.add(durl(jid), detail(jid))
    return http


def assert_failed(batch, code: str):
    assert batch.status == ("blocked" if code == "blocked" else "failed")
    assert batch.error_code == code
    assert batch.complete is False and batch.can_infer_absence is False
    assert batch.jobs == []


# ------------------------------------------------------------------ contrato

def test_contrato_do_modulo():
    assert airswift.VERSION == "airswift_hubspot/1"
    assert callable(airswift.collect) and callable(airswift.probe)


@pytest.mark.parametrize("raw,iso_date", [("6 Oct 2026", "2026-10-06"), ("25 Sep 2026", "2026-09-25"),
                                          ("1 Sept 2026", "2026-09-01"), ("3 June 2026", "2026-06-03"),
                                          ("31 Feb 2026", None), ("Oct 6, 2026", None), ("", None)])
def test_data_da_lista_sem_depender_de_locale(raw, iso_date):
    assert airswift._list_date_iso(raw) == iso_date


# ------------------------------------------------------------------ lista

def test_caminho_feliz_brasil_seis_vagas():
    http = with_details(FakeHttp().add(LIST, page(BRAZIL6, total=6)), IDS6)
    b = airswift.collect(make_ctx(http))
    assert b.status == "complete" and b.complete and b.can_infer_absence
    assert b.adapter_version == "airswift_hubspot/1" and b.coverage_kind == "filtered_board"
    assert (b.pages_received, b.pages_expected, b.raw_count) == (1, 1, 6)
    assert [j.external_id for j in b.jobs] == IDS6
    assert {(j.platform, j.tenant) for j in b.jobs} == {("hubspot", "airswift.com")}
    j = b.jobs[0]
    assert j.title == "Mechanical & Rotating Engineer"
    assert j.url == "https://www.airswift.com/jobs/mechanical-rotating-engineer-1273574"
    assert j.location == "Rio de Janeiro, Rio de Janeiro, Brazil"
    assert b.jobs[2].location == "Houston, Texas, Brazil" and b.jobs[2].raw["location_raw"] == "Houston , Texas, Brazil"
    assert b.jobs[1].raw["employment_type"] == "Contract" and j.raw["list_date"] == "6 Oct 2026"
    # Detalhe: JSON-LD datePosted vence a data da lista; corpo do artigo com estrutura; Function vira departamento
    assert (j.published_raw, j.published_source) == ("2026-05-25", "airswift:jsonld.datePosted")
    assert j.description_status == "full" and "Primeiro parágrafo." in j.description and "Aninhado." in j.description
    assert "- Item A" in j.description and "rodapé" not in j.description and "Job reference" not in j.description
    assert j.department == "Commissioning" and j.deadline is None
    assert j.raw["validThrough"] == "2999-12-05" and j.raw["sector"] == "Energy - Oil & Gas"
    assert j.raw["description_from"] == "article" and j.raw["job_reference"] == "1273574"
    assert b.details_fetched == 6 and not b.warnings
    first = http.calls[0]
    assert first["url"] == LIST and first["params"] == {"location": "Brazil", "page_num": 1}


def test_localidade_padrao_e_escopo():
    http = with_details(FakeHttp().add(LIST, page(BRAZIL6, total=6)), IDS6)
    b = airswift.collect(make_ctx(http, params={}))
    assert b.status == "complete" and http.calls[0]["params"] == {"location": "Brazil", "page_num": 1}
    s_br = make_ctx(FakeHttp(), params={"location": "Brazil"}).source
    s_uk = make_ctx(FakeHttp(), params={"location": "United Kingdom"}).source
    assert scope_id(s_br, {"location": "Brazil", "board": airswift.LIST_URL}) != \
        scope_id(s_uk, {"location": "United Kingdom", "board": airswift.LIST_URL})
    assert b.scope_id == scope_id(make_ctx(FakeHttp(), params={}).source, {"location": "Brazil", "board": airswift.LIST_URL})


def test_lista_vazia_reconhecida_e_completa():
    http = FakeHttp().add(LIST, page([], total=0))
    b = airswift.collect(make_ctx(http))
    assert b.status == "complete" and b.complete and b.can_infer_absence and b.jobs == []
    assert len(http.calls) == 1


def test_lista_vazia_so_com_aviso_sem_cabecalho_e_completa():
    b = airswift.collect(make_ctx(FakeHttp().add(LIST, page([], total=None, offset=None, empty_text=True))))
    assert b.status == "complete" and b.jobs == []


@pytest.mark.parametrize("html", [
    "<html><body><h1>Just a moment...</h1><form id='challenge-form'></form></body></html>",
    "<html><body><p>Página nova da Airswift</p></body></html>",
    "",
])
def test_conteudo_inesperado_e_format_changed(html):
    assert_failed(airswift.collect(make_ctx(FakeHttp().add(LIST, html))), "format_changed")


def test_cabecalho_sem_cards_e_sem_aviso_e_format_changed():
    """'Found 3 jobs' e nenhum card nem aviso de vazio: nunca vira zero vagas."""
    assert_failed(airswift.collect(make_ctx(FakeHttp().add(LIST, page([], total=3, empty_text=False)))), "format_changed")


def test_cards_ilegiveis_na_primeira_pagina_e_format_changed():
    broken = '<article class="c-card-job-item"><p class="c-card-job-item__title">sem link</p></article>'
    assert_failed(airswift.collect(make_ctx(FakeHttp().add(LIST, page([broken, broken], total=2)))), "format_changed")


def test_card_truncado_e_format_changed():
    html = page(BRAZIL6[:2], total=3).replace("</div></section>", '<article class="c-card-job-item"><p>corte')
    assert_failed(airswift.collect(make_ctx(FakeHttp().add(LIST, html))), "format_changed")


def test_filtro_de_localidade_ignorado_e_format_changed():
    world = [card("1", "A", "Aberdeen, United Kingdom"), card("2", "B", "Perth, Australia")]
    assert_failed(airswift.collect(make_ctx(FakeHttp().add(LIST, page(world, total=864, pages=36)))), "format_changed")


def test_card_ilegivel_entre_legiveis_deixa_parcial():
    broken = '<article class="c-card-job-item"><p class="c-card-job-item__title"><a href="/about">x</a></p></article>'
    http = with_details(FakeHttp().add(LIST, page(BRAZIL6[:2] + [broken], total=3)), IDS6[:2])
    b = airswift.collect(make_ctx(http))
    assert b.status == "partial" and not b.can_infer_absence
    assert [j.external_id for j in b.jobs] == IDS6[:2]
    assert "ilegível" in b.error_message and b.error_code == "incomplete_listing"


def test_total_do_cabecalho_diferente_do_lido_deixa_parcial():
    http = with_details(FakeHttp().add(LIST, page(BRAZIL6, total=7)), IDS6)
    b = airswift.collect(make_ctx(http))
    assert b.status == "partial" and not b.can_infer_absence and len(b.jobs) == 6
    assert "informa 7" in b.error_message


def test_paginacao_le_ate_pagina_incompleta():
    http = FakeHttp()
    http.add(LIST, page(n_cards(0, 24), total=30, pages=2), params={"page_num": 1})
    http.add(LIST, page(n_cards(24, 6), total=30, pages=2, offset=24), params={"page_num": 2})
    http.add(LIST + "/engineer-", detail("0"))
    b = airswift.collect(make_ctx(http, limits={**LIMITS, "max_details": 0}))
    assert b.status == "complete" and b.can_infer_absence
    assert (b.pages_received, b.pages_expected, b.raw_count, len(b.jobs)) == (2, 2, 30, 30)
    assert [c["params"]["page_num"] for c in http.calls] == [1, 2]
    assert "limite de detalhes" in " ".join(b.warnings)


def test_paginacao_para_quando_total_e_atingido_com_pagina_cheia():
    http = FakeHttp().add(LIST, page(n_cards(0, 24), total=24), params={"page_num": 1})
    b = airswift.collect(make_ctx(http, limits={**LIMITS, "max_details": 0}))
    assert b.status == "complete" and len(b.jobs) == 24 and len(http.calls) == 1


def test_sem_cabecalho_pagina_seguinte_vazia_reconhecida_encerra_completo():
    http = FakeHttp()
    http.add(LIST, page(n_cards(0, 24), total=None, offset=None), params={"page_num": 1})
    http.add(LIST, page([], total=None, offset=None, empty_text=True), params={"page_num": 2})
    b = airswift.collect(make_ctx(http, limits={**LIMITS, "max_details": 0}))
    assert b.status == "complete" and len(b.jobs) == 24 and b.pages_received == 2


def test_sem_cabecalho_pagina_seguinte_sem_marcador_e_parcial():
    http = FakeHttp()
    http.add(LIST, page(n_cards(0, 24), total=None, offset=None), params={"page_num": 1})
    http.add(LIST, "<html><body>layout novo</body></html>", params={"page_num": 2})
    b = airswift.collect(make_ctx(http, limits={**LIMITS, "max_details": 0}))
    assert b.status == "partial" and not b.can_infer_absence and len(b.jobs) == 24
    assert b.error_code == "format_changed"


def test_falha_na_pagina_2_e_parcial():
    http = FakeHttp()
    http.add(LIST, page(n_cards(0, 24), total=30, pages=2), params={"page_num": 1})
    http.add(LIST, SourceFailure("network", "timeout"), params={"page_num": 2})
    b = airswift.collect(make_ctx(http, limits={**LIMITS, "max_details": 0}))
    assert b.status == "partial" and not b.complete and not b.can_infer_absence
    assert b.error_code == "network" and len(b.jobs) == 24 and "página 2" in b.error_message


def test_page_num_ignorado_pelo_servidor_e_parcial():
    """A consulta HubDB da página 2 voltou com offset=0: o servidor ignorou page_num."""
    http = FakeHttp()
    http.add(LIST, page(n_cards(0, 24), total=30, pages=2), params={"page_num": 1})
    http.add(LIST, page(n_cards(0, 24), total=30, pages=2, offset=0), params={"page_num": 2})
    b = airswift.collect(make_ctx(http, limits={**LIMITS, "max_details": 0}))
    assert b.status == "partial" and b.error_code == "format_changed" and len(b.jobs) == 24


def test_pagina_repetida_sem_total_e_parcial():
    http = FakeHttp()
    http.add(LIST, page(n_cards(0, 24), total=None, offset=None), params={"page_num": 1})
    http.add(LIST, page(n_cards(0, 24), total=None, offset=None), params={"page_num": 2})
    b = airswift.collect(make_ctx(http, limits={**LIMITS, "max_details": 0}))
    assert b.status == "partial" and "repetiu" in b.error_message and len(b.jobs) == 24


def test_limite_de_paginas_e_parcial():
    http = FakeHttp()
    for n in (1, 2):
        http.add(LIST, page(n_cards((n - 1) * 24, 24), total=72, pages=3, offset=(n - 1) * 24), params={"page_num": n})
    b = airswift.collect(make_ctx(http, limits={**LIMITS, "max_pages": 2, "max_details": 0}))
    assert b.status == "partial" and not b.can_infer_absence and len(b.jobs) == 48
    assert len(http.calls) == 2 and "limite de 2 páginas" in " ".join(b.warnings)


@pytest.mark.parametrize("exc,code", [(SourceFailure("network", "ConnectionError"), "network"),
                                      (Blocked("HTTP 403"), "blocked"),
                                      (SourceFailure("not_found", "HTTP 404"), "not_found")])
def test_falha_na_primeira_pagina(exc, code):
    assert_failed(airswift.collect(make_ctx(FakeHttp().add(LIST, exc))), code)


# ------------------------------------------------------------------ detalhe

def test_detalhe_respeita_orcamento_e_known():
    http = with_details(FakeHttp().add(LIST, page(BRAZIL6, total=6)), IDS6)
    b = airswift.collect(make_ctx(http, limits={**LIMITS, "max_details": 2}))
    assert b.status == "complete" and b.details_fetched == 2
    assert [j.description_status for j in b.jobs] == ["full", "full"] + ["missing"] * 4
    # Sem detalhe, a data é a da lista (rotulada)
    assert (b.jobs[2].published_raw, b.jobs[2].published_source) == ("2026-10-05", "airswift:list_date")
    assert "limite de detalhes" in " ".join(b.warnings)

    known = lambda ext, url: {"listing_signature": None, "detail_fetched_at": iso(), "has_description": True}  # noqa: E731
    http2 = FakeHttp().add(LIST, page(BRAZIL6, total=6))
    b2 = airswift.collect(make_ctx(http2, known=known))
    assert b2.status == "complete" and b2.details_fetched == 0 and len(http2.calls) == 1


def test_detalhe_sem_artigo_usa_descricao_do_json_ld():
    http = FakeHttp().add(LIST, page(BRAZIL6[:1], total=1))
    http.add(durl("1273574"), detail("1273574", article=False, desc_ld="Descrição <b>só</b> no JSON-LD."))
    b = airswift.collect(make_ctx(http))
    j = b.jobs[0]
    assert j.description_status == "full" and j.description.startswith("Descrição só no JSON-LD.")
    assert j.raw["description_from"] == "jsonld"


def test_falha_ou_formato_de_detalhe_e_so_aviso():
    http = FakeHttp().add(LIST, page(BRAZIL6[:2], total=2))
    http.add(durl("1273574"), "<html><body>sem json-ld nem artigo</body></html>")
    http.add(durl("1273952"), SourceFailure("not_found", "HTTP 404"))
    b = airswift.collect(make_ctx(http))
    assert b.status == "complete" and b.details_fetched == 0 and len(b.jobs) == 2
    assert all(j.description_status == "missing" for j in b.jobs)
    assert b.jobs[0].published_source == "airswift:list_date"
    assert len(b.warnings) == 2 and "format_changed" in b.warnings[0] and "not_found" in b.warnings[1]


def test_detalhe_bloqueado_nao_derruba_o_lote():
    http = FakeHttp().add(LIST, page(BRAZIL6[:1], total=1)).add(durl("1273574"), Blocked("HTTP 403"))
    b = airswift.collect(make_ctx(http))
    assert b.status == "complete" and "blocked" in b.warnings[0]


# ------------------------------------------------------------------ probe

URL = "https://www.airswift.com/jobs/mechanical-rotating-engineer-1273574"


def probe_with(response, *, ext="1273574", url=URL):
    http = FakeHttp().add("airswift.com", response)
    return airswift.probe(make_ctx(http), ext, url), http


def test_probe_vaga_ativa():
    r, http = probe_with(detail("1273574"))
    assert r == "alive" and http.calls[0]["url"] == URL


@pytest.mark.parametrize("response", [SourceFailure("not_found", "HTTP 404"), (404, "<html>not found</html>"),
                                      (410, "")])
def test_probe_404_410_e_encerrada(response):
    assert probe_with(response)[0] == "gone"


def test_probe_valid_through_no_passado_e_encerrada():
    assert probe_with(detail("1273574", valid="2001-01-31"))[0] == "gone"
    assert probe_with(detail("1273574", valid="2999-01-31T00:00:00Z"))[0] == "alive"
    assert probe_with(detail("1273574", valid="sem data"))[0] == "alive"


def test_probe_redirecionada_para_a_lista_e_encerrada():
    assert probe_with(page(BRAZIL6, total=6))[0] == "gone"
    assert probe_with(page([], total=0))[0] == "gone"


def test_probe_marcador_explicito_de_encerramento():
    assert probe_with("<html><body><h1>This job is no longer available.</h1></body></html>")[0] == "gone"


@pytest.mark.parametrize("response", [SourceFailure("network", "timeout"), SourceFailure("http_503", "HTTP 503"),
                                      Blocked("HTTP 403"), RuntimeError("inesperado"), (500, "erro"),
                                      "<html><body>Just a moment...</body></html>"])
def test_probe_sem_evidencia_forte_e_desconhecido(response):
    assert probe_with(response)[0] == "unknown"


def test_probe_url_ausente_estranha_ou_incoerente_e_desconhecido():
    assert probe_with(detail("1273574"), url=None)[0] == "unknown"
    assert probe_with(detail("1273574"), url="https://jobs.smartrecruiters.com/Airswift/1273574")[0] == "unknown"
    assert probe_with(detail("1273574"), ext="999")[0] == "unknown"
    # Página de outra vaga (referência diferente) não confirma nada
    assert probe_with(detail("1273574", ref="555"))[0] == "unknown"


def test_probe_sem_external_id_usa_a_url():
    r, http = probe_with(detail("1273574"), ext=None)
    assert r == "alive" and len(http.calls) == 1
