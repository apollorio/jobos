"""Oracle Recruiting Candidate Experience (oracle_ce): lista filtrada por local, detalhe e probe individual.

Sem rede: FakeHttp com respostas enlatadas por trecho de URL (cópia local do padrão de test_collectors_ported.py).
Formas das respostas copiadas da auditoria ao vivo de 23/10/2026 (ABS, hbbq.fa.us2.oraclecloud.com, site CX_1).
"""
from __future__ import annotations

import pytest

from jobos.collectors import oracle_ce
from jobos.collectors.base import Blocked, CollectContext, SourceFailure
from jobos.settings import SourceConfig

LIMITS = {"max_pages": 3, "max_details": 5, "detail_ttl_days": 7}
BASE = "https://hbbq.fa.us2.oraclecloud.com"
BR = "300000000183830"
PARAMS = {"base": BASE, "site": "CX_1", "location_term": "Brazil"}
FACETS = [{"Id": int(BR), "Name": "Brazil", "TotalCount": 2},
          {"Id": 300000126009898, "Name": "RJ, Brazil", "TotalCount": 1},
          {"Id": 300000126026903, "Name": "Barueri, SP, Brazil", "TotalCount": 1}]
FACET = "userTargetFacetInputTerm=Brazil"
PAGE0 = "limit=25,offset=0,"
PAGE25 = "limit=25,offset=25,"
CONTROL = "limit=1,offset=0,"


class FakeHttp:
    """Responde por trecho de URL (vence o trecho mais longo), com filtro opcional de params, e registra as chamadas.
    Diferença da cópia original: rota repetida (mesmo trecho e params) substitui a anterior."""

    def __init__(self):
        self.routes: list[tuple[str, dict | None, object]] = []
        self.calls: list[dict] = []

    def add(self, substring: str, response, params: dict | None = None) -> "FakeHttp":
        self.routes = [r for r in self.routes if (r[0], r[1]) != (substring, params)]
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


@pytest.fixture(autouse=True)
def _limpa_controle():
    oracle_ce._CONTROL_CACHE.clear()
    yield
    oracle_ce._CONTROL_CACHE.clear()


def make_ctx(http: FakeHttp, params: dict | None = None, *, coverage: str = "filtered_board", limits: dict | None = None,
             known=None, run_id: str = "run-1") -> CollectContext:
    src = SourceConfig(source_id="abs-oracle", company_id="abs", company_name="ABS", platform="oracle_ce",
                       adapter="oracle_ce", enabled=True, params=dict(PARAMS if params is None else params),
                       coverage=coverage, limits=limits or dict(LIMITS), priority=3, board_url=None,
                       configuration_origin="teste", verification_status="teste")
    kw = {"known": known} if known else {}
    return CollectContext(run_id=run_id, source=src, http=http, **kw)


def facet_resp(facets=FACETS) -> dict:
    return {"items": [{"SiteNumber": "CX_1", "LocationId": None, "TotalJobsCount": 0, "locationsFacet": facets}],
            "count": 1, "hasMore": False}


def list_resp(rows: list, total: int, loc: str | None = BR, site: str = "CX_1") -> dict:
    # hasMore vem falso mesmo com mais páginas (observado ao vivo): o adapter não pode confiar nele
    return {"items": [{"SiteNumber": site, "LocationId": loc, "TotalJobsCount": total, "Offset": 0, "Limit": 25,
                       "requisitionList": rows}], "count": 1, "hasMore": False}


def row(rid: str, title: str = "Engineer I - Naval Architect", loc: str | None = "Rio de Janeiro, RJ, Brazil",
        code: str | None = None, wt: str = "", posted: str = "2026-10-21", short: str = "Resumo curto da vaga.",
        secondary: list | None = None, end: str | None = None) -> dict:
    return {"Id": rid, "Title": title, "PostedDate": posted, "PostingEndDate": end, "PrimaryLocation": loc,
            "PrimaryLocationCountry": "BR", "WorkplaceType": wt, "WorkplaceTypeCode": code, "ShortDescriptionStr": short,
            "Language": "US", "Department": None, "Organization": None, "JobFamily": None,
            "secondaryLocations": secondary or []}


def detail_resp(rid: str, desc: str = "<p>Performs <b>engineering</b> design review.</p>", resp: str = "",
                qual: str = "<ul><li>BSc Naval</li></ul>", start: str | None = "2026-10-21T18:29:42+00:00",
                end: str | None = None, category: str = "Engineering", title: str = "Engineer I - Naval Architect") -> dict:
    return {"items": [{"Id": rid, "Title": title, "Category": category, "ExternalDescriptionStr": desc,
                       "ExternalResponsibilitiesStr": resp, "ExternalQualificationsStr": qual,
                       "ExternalPostedStartDate": start, "ExternalPostedEndDate": end, "WorkplaceType": "",
                       "WorkplaceTypeCode": None, "JobFunction": "Engineer/Consultant.E"}],
            "count": 1, "hasMore": False}


def det(rid: str) -> str:
    return f"Id=%22{rid}%22"


def happy_http() -> FakeHttp:
    http = FakeHttp()
    http.add(FACET, facet_resp())
    http.add(PAGE0, list_resp([row("4900"), row("4847", "Contractor, Auditor/Inspector", "Barueri, SP, Brazil",
                                                 code="ORA_REMOTE", wt="Remote")], total=2))
    http.add(det("4900"), detail_resp("4900"))
    http.add(det("4847"), detail_resp("4847", desc="<p>Audit</p>", qual="", title="Contractor, Auditor/Inspector"))
    return http


# ------------------------------------------------------------------ contrato e URLs

def test_contrato_do_modulo():
    assert oracle_ce.VERSION == "oracle_ce/1"
    assert callable(oracle_ce.collect) and callable(oracle_ce.probe)


def test_urls_mantem_finder_literal():
    f = oracle_ce.facet_url(BASE, "CX_1", "Brazil")
    assert f == (f"{BASE}/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true&finder=findReqs;"
                 "siteNumber=CX_1,facetsList=LOCATIONS,userTargetFacetName=LOCATIONS,userTargetFacetInputTerm=Brazil,limit=1")
    lst = oracle_ce.list_url(BASE, "CX_1", BR, 25)
    assert lst.endswith("&finder=findReqs;siteNumber=CX_1,facetsList=LOCATIONS,limit=25,offset=25,"
                        f"sortBy=POSTING_DATES_DESC,locationId={BR}")
    assert "expand=requisitionList.secondaryLocations" in lst
    assert oracle_ce.detail_url(BASE, "CX_1", "4900").endswith('finder=ById;Id=%224900%22,siteNumber=CX_1')
    assert oracle_ce.job_url(BASE, "CX_1", "4900") == f"{BASE}/hcmUI/CandidateExperience/en/sites/CX_1/job/4900"


# ------------------------------------------------------------------ coleta

def test_caminho_feliz_identidade_detalhe_e_escopo():
    http = happy_http()
    b = oracle_ce.collect(make_ctx(http))
    assert b.status == "complete" and b.complete is True and b.can_infer_absence is True
    assert b.adapter_version == "oracle_ce/1"
    assert (b.pages_expected, b.pages_received, b.raw_count, b.details_fetched) == (1, 1, 2, 2)
    assert all(c["params"] is None for c in http.calls)
    assert all((c["headers"] or {}).get("Accept") == "application/json" for c in http.calls)
    j = {o.external_id: o for o in b.jobs}
    rio, bar = j["4900"], j["4847"]
    assert (rio.platform, rio.tenant, rio.external_id) == ("oracle_ce", "hbbq", "4900")
    assert rio.url == f"{BASE}/hcmUI/CandidateExperience/en/sites/CX_1/job/4900"
    assert rio.title == "Engineer I - Naval Architect" and rio.location == "Rio de Janeiro, RJ, Brazil"
    assert rio.workplace is None  # WorkplaceType vazio: desconhecido, não presencial
    assert bar.workplace == "remote" and bar.location == "Barueri, SP, Brazil"
    assert rio.description_status == "full" and rio.truncation_note is None
    assert rio.description.startswith("Descrição da vaga:\nPerforms engineering design review.")
    assert "Qualificações:\n- BSc Naval" in rio.description and "Responsabilidades" not in rio.description
    assert rio.published_raw == "2026-10-21T18:29:42+00:00"
    assert rio.published_source == "oracle_ce:ExternalPostedStartDate"
    assert rio.department == "Engineering" and rio.talent_pool is None
    assert not b.warnings


def test_scope_id_muda_com_o_id_do_local():
    a = oracle_ce.collect(make_ctx(happy_http()))
    http = happy_http()
    http.add(FACET, facet_resp([{"Id": 999, "Name": "Brazil", "TotalCount": 2}]))
    http.add(PAGE0, list_resp([row("4900")], total=1, loc="999"))
    b = oracle_ce.collect(make_ctx(http))
    assert b.status == "complete" and a.scope_id != b.scope_id
    c = oracle_ce.collect(make_ctx(happy_http(), {**PARAMS, "location_term": "Brazil", "site": "CX_1"}))
    assert c.scope_id == a.scope_id


def test_sem_detalhe_fica_resumo_parcial_da_listagem():
    http = happy_http()
    http.add(det("4900"), {"items": [], "count": 0, "hasMore": False})
    http.add(det("4847"), SourceFailure("network", "timeout"))
    b = oracle_ce.collect(make_ctx(http))
    assert b.status == "complete" and b.details_fetched == 0
    o = b.jobs[0]
    assert o.description == "Resumo curto da vaga." and o.description_status == "partial"
    assert o.truncation_note == oracle_ce.SHORT_NOTE
    assert o.published_raw == "2026-10-21" and o.published_source == "oracle_ce:PostedDate"
    assert any("items vazio" in w for w in b.warnings) and any("4847: network" in w for w in b.warnings)


def test_paginacao_pelo_total_ignora_hasmore():
    http = FakeHttp().add(FACET, facet_resp([{"Id": int(BR), "Name": "Brazil", "TotalCount": 27}]))
    http.add(PAGE0, list_resp([row(str(5000 + i)) for i in range(25)], total=27))
    http.add(PAGE25, list_resp([row("6000"), row("6001")], total=27))
    b = oracle_ce.collect(make_ctx(http, limits={**LIMITS, "max_details": 0}))
    assert b.status == "complete" and b.can_infer_absence is True
    assert (b.pages_expected, b.pages_received, b.raw_count, len(b.jobs)) == (2, 2, 27, 27)
    assert any("limite de detalhes" in w for w in b.warnings)


def test_falha_na_pagina_2_e_parcial():
    http = FakeHttp().add(FACET, facet_resp())
    http.add(PAGE0, list_resp([row(str(5000 + i)) for i in range(25)], total=27))
    http.add(PAGE25, SourceFailure("http_500", "HTTP 500"))
    b = oracle_ce.collect(make_ctx(http, limits={**LIMITS, "max_details": 0}))
    assert b.status == "partial" and b.complete is False and b.can_infer_absence is False
    assert len(b.jobs) == 25 and b.error_code == "http_500" and "offset=25" in b.error_message


def test_limite_de_paginas_e_parcial():
    http = FakeHttp().add(FACET, facet_resp())
    http.add(PAGE0, list_resp([row(str(5000 + i)) for i in range(25)], total=27))
    b = oracle_ce.collect(make_ctx(http, limits={**LIMITS, "max_pages": 1, "max_details": 0}))
    assert b.status == "partial" and b.can_infer_absence is False
    assert b.error_code == "incomplete_listing" and "limite de 1 páginas" in b.error_message


def test_lista_vazia_reconhecida_e_completa_com_id_fixo():
    http = FakeHttp().add(FACET, facet_resp([])).add(PAGE0, list_resp([], total=0))
    b = oracle_ce.collect(make_ctx(http, {**PARAMS, "location_id": int(BR)}))
    assert b.status == "complete" and b.jobs == [] and b.can_infer_absence is True
    assert any("faceta 'Brazil' ausente" in w for w in b.warnings)


def test_faceta_ausente_sem_id_fixo_falha_sem_ausencia():
    http = FakeHttp().add(FACET, facet_resp([{"Id": 1, "Name": "RJ, Brazil", "TotalCount": 1}]))
    b = oracle_ce.collect(make_ctx(http))
    assert b.status == "failed" and b.error_code == "scope_not_found" and b.can_infer_absence is False


def test_id_fixo_diferente_da_faceta_falha():
    http = FakeHttp().add(FACET, facet_resp())
    b = oracle_ce.collect(make_ctx(http, {**PARAMS, "location_id": "123"}))
    assert b.status == "failed" and b.error_code == "scope_mismatch"


def test_descoberta_falha_com_id_fixo_segue_com_aviso():
    http = FakeHttp().add(FACET, SourceFailure("network", "timeout"))
    http.add(PAGE0, list_resp([row("4900")], total=1)).add(det("4900"), detail_resp("4900"))
    b = oracle_ce.collect(make_ctx(http, {**PARAMS, "location_id": BR}))
    assert b.status == "complete" and len(b.jobs) == 1
    assert any("descoberta do local 'Brazil' falhou" in w for w in b.warnings)


@pytest.mark.parametrize("payload,trecho", [
    ({"items": []}, "items[0]"),
    ("<html>login</html>", "items[0]"),
    ({"items": [{"LocationId": BR, "SiteNumber": "CX_1", "TotalJobsCount": 2}]}, "requisitionList"),
    ({"items": [{"LocationId": BR, "SiteNumber": "CX_1", "requisitionList": []}]}, "TotalJobsCount"),
    (list_resp([row("4900")], total=1, loc=None), "não ecoado"),
    (list_resp([row("4900")], total=1, site="CX_9"), "site ecoado"),
])
def test_conteudo_inesperado_e_format_changed(payload, trecho):
    http = FakeHttp().add(FACET, facet_resp()).add(PAGE0, payload)
    b = oracle_ce.collect(make_ctx(http))
    assert b.status == "failed" and b.error_code == "format_changed" and trecho in b.error_message
    assert b.jobs == [] and b.can_infer_absence is False


def test_filtro_ignorado_pela_plataforma_e_format_changed():
    """locationId desconhecido: a API ecoa o id, mas devolve o quadro inteiro (observado ao vivo)."""
    http = FakeHttp().add(FACET, facet_resp())
    http.add(PAGE0, list_resp([row("4634", loc="San Francisco, CA, United States"), row("4900")], total=126))
    b = oracle_ce.collect(make_ctx(http))
    assert b.status == "failed" and b.error_code == "format_changed" and "fora de 'Brazil'" in b.error_message


def test_descoberta_sem_lista_de_facetas_e_format_changed():
    http = FakeHttp().add(FACET, {"items": [{"SiteNumber": "CX_1"}]})
    b = oracle_ce.collect(make_ctx(http))
    assert b.status == "failed" and b.error_code == "format_changed"


def test_bloqueio_e_rede_na_primeira_pagina():
    http = FakeHttp().add(FACET, facet_resp()).add(PAGE0, Blocked("HTTP 403"))
    b = oracle_ce.collect(make_ctx(http))
    assert b.status == "blocked" and b.error_code == "blocked" and b.can_infer_absence is False
    http = FakeHttp().add(FACET, SourceFailure("network", "ConnectionError"))
    b = oracle_ce.collect(make_ctx(http))
    assert b.status == "failed" and b.error_code == "network"


def test_contagem_distinta_menor_que_total_e_parcial():
    http = FakeHttp().add(FACET, facet_resp())
    http.add(PAGE0, list_resp([row("4900"), row("4900"), {"Title": "sem id"}], total=3))
    b = oracle_ce.collect(make_ctx(http, limits={**LIMITS, "max_details": 0}))
    assert b.status == "partial" and "lidas 1 vagas distintas de 3" in b.error_message
    assert any("sem Id" in w for w in b.warnings)


def test_total_muda_durante_a_paginacao_e_parcial():
    http = FakeHttp().add(FACET, facet_resp())
    http.add(PAGE0, list_resp([row(str(5000 + i)) for i in range(25)], total=27))
    http.add(PAGE25, list_resp([row("6000"), row("6001"), row("6002")], total=28))
    b = oracle_ce.collect(make_ctx(http, limits={**LIMITS, "max_details": 0}))
    assert b.status == "partial" and "total mudou" in b.error_message


def test_pagina_repetida_e_parcial():
    rows = [row(str(5000 + i)) for i in range(25)]
    http = FakeHttp().add(FACET, facet_resp())
    http.add(PAGE0, list_resp(rows, total=60)).add(PAGE25, list_resp(rows, total=60))
    b = oracle_ce.collect(make_ctx(http, limits={**LIMITS, "max_details": 0}))
    assert b.status == "partial" and "página repetida" in b.error_message and len(b.jobs) == 25


def test_local_secundario_no_escopo_vem_primeiro():
    sec = [{"Name": "Rio de Janeiro, RJ, Brazil", "CountryCode": "BR"}]
    http = FakeHttp().add(FACET, facet_resp())
    http.add(PAGE0, list_resp([row("7000", loc="Houston, TX, United States", secondary=sec)], total=1))
    b = oracle_ce.collect(make_ctx(http, limits={**LIMITS, "max_details": 0}))
    assert b.status == "complete"
    assert b.jobs[0].location == "Rio de Janeiro, RJ, Brazil; Houston, TX, United States"
    assert b.jobs[0].raw["secondary_locations"] == ["Rio de Janeiro, RJ, Brazil"]


def test_known_com_descricao_nao_reabre_detalhe():
    sig = {}

    def known(ext, url):
        return {"listing_signature": sig.get(ext), "detail_fetched_at": "2026-10-22T10:00:00+00:00",
                "has_description": True}
    first = oracle_ce.collect(make_ctx(happy_http()))
    sig.update({o.external_id: o.listing_signature for o in first.jobs})
    http = FakeHttp().add(FACET, facet_resp())
    http.add(PAGE0, list_resp([row("4900"), row("4847", "Contractor, Auditor/Inspector", "Barueri, SP, Brazil",
                                                 code="ORA_REMOTE", wt="Remote")], total=2))
    b = oracle_ce.collect(make_ctx(http, known=known))
    assert b.status == "complete" and b.details_fetched == 0
    assert not any("Id=%22" in c["url"] for c in http.calls)


def test_descricao_longa_e_truncada_com_registro():
    http = happy_http()
    http.add(det("4900"), detail_resp("4900", desc="<p>" + "x" * 70000 + "</p>", qual=""))
    b = oracle_ce.collect(make_ctx(http))
    o = {j.external_id: j for j in b.jobs}["4900"]
    assert o.description_status == "truncated" and o.original_length > 60000 and o.truncation_note


def test_config_incompleta_falha():
    b = oracle_ce.collect(make_ctx(FakeHttp(), {"base": BASE, "site": "CX_1"}))
    assert b.status == "failed" and b.error_code == "config"


# ------------------------------------------------------------------ probe

def control_routes(http: FakeHttp) -> FakeHttp:
    http.add(CONTROL, list_resp([row("4916")], total=126, loc=None))
    http.add(det("4916"), detail_resp("4916"))
    return http


def test_probe_viva():
    http = FakeHttp().add(det("4900"), detail_resp("4900"))
    assert oracle_ce.probe(make_ctx(http), "4900", None) == "alive"


def test_probe_items_vazio_com_controle_positivo_e_gone():
    http = control_routes(FakeHttp().add(det("1"), {"items": [], "count": 0}))
    assert oracle_ce.probe(make_ctx(http), "1", None) == "gone"


def test_probe_items_vazio_sem_controle_e_unknown():
    http = FakeHttp().add(det("1"), {"items": [], "count": 0})
    http.add(CONTROL, list_resp([row("4916")], total=126, loc=None)).add(det("4916"), {"items": []})
    assert oracle_ce.probe(make_ctx(http), "1", None) == "unknown"


def test_probe_404_com_controle_e_gone():
    http = control_routes(FakeHttp().add(det("4800"), SourceFailure("not_found", "HTTP 404")))
    assert oracle_ce.probe(make_ctx(http), "4800", None) == "gone"


def test_probe_404_com_api_fora_e_unknown():
    http = FakeHttp().add(det("4800"), SourceFailure("not_found", "HTTP 404"))
    http.add(CONTROL, SourceFailure("not_found", "HTTP 404"))
    assert oracle_ce.probe(make_ctx(http), "4800", None) == "unknown"


@pytest.mark.parametrize("exc", [SourceFailure("network", "timeout"), Blocked("HTTP 403"),
                                 SourceFailure("http_500", "HTTP 500")])
def test_probe_erros_sao_unknown(exc):
    http = FakeHttp().add(det("4900"), exc)
    assert oracle_ce.probe(make_ctx(http), "4900", None) == "unknown"


def test_probe_formato_inesperado_e_outra_requisicao_sao_unknown():
    assert oracle_ce.probe(make_ctx(FakeHttp().add(det("4900"), "<html>")), "4900", None) == "unknown"
    http = FakeHttp().add(det("4900"), detail_resp("4901"))
    assert oracle_ce.probe(make_ctx(http), "4900", None) == "unknown"


def test_probe_fim_de_publicacao_vencido_e_gone():
    http = FakeHttp().add(det("4900"), detail_resp("4900", end="2026-01-01T00:00:00+00:00"))
    assert oracle_ce.probe(make_ctx(http), "4900", None) == "gone"
    http = FakeHttp().add(det("4900"), detail_resp("4900", end="2099-01-01T00:00:00+00:00"))
    assert oracle_ce.probe(make_ctx(http), "4900", None) == "alive"
    http = FakeHttp().add(det("4900"), detail_resp("4900", end="2026-01-01"))
    assert oracle_ce.probe(make_ctx(http), "4900", None) == "gone"


def test_probe_id_pela_url_e_sem_id():
    http = FakeHttp().add(det("4900"), detail_resp("4900"))
    url = f"{BASE}/hcmUI/CandidateExperience/en/sites/CX_1/job/4900?utm_source=x"
    assert oracle_ce.probe(make_ctx(http), None, url) == "alive"
    assert oracle_ce.probe(make_ctx(FakeHttp()), None, "https://exemplo.com/vaga") == "unknown"


def test_probe_controle_e_feito_uma_vez_por_execucao():
    http = control_routes(FakeHttp().add(det("1"), {"items": []}).add(det("2"), {"items": []}))
    ctx = make_ctx(http)
    assert oracle_ce.probe(ctx, "1", None) == "gone" and oracle_ce.probe(ctx, "2", None) == "gone"
    assert sum(1 for c in http.calls if CONTROL in c["url"]) == 1
