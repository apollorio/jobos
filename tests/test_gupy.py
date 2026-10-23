"""Leitor Gupy offline: formato reconhecido, layout inesperado e detalhe pela página da vaga."""
import json

from jobos.collectors import gupy
from jobos.collectors.base import CollectContext, FormatChanged
from jobos.settings import SourceConfig


class FakeHttp:
    def __init__(self, pages):
        self.pages = pages

    def get_text(self, url, headers=None, params=None):
        for k, v in self.pages.items():
            if url.endswith(k):
                return 200, v
        raise AssertionError(f"URL não simulada: {url}")


def _page(props):
    return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps({"props": {"pageProps": props}})}</script></html>'


def _ctx(http):
    src = SourceConfig("prio-gupy", "prio", "PRIO", "gupy", "gupy_tenant", True, {"tenant": "prio"}, "full_board",
                       {"max_details": 5, "detail_ttl_days": 7}, 1, None, "test", "test")
    return CollectContext(run_id="r", source=src, http=http)


def test_tenant_listing_and_job_page_detail():
    http = FakeHttp({
        "prio.gupy.io/": _page({"jobs": [{"id": 1, "title": "Planner", "workplace": {"address": {"city": "Rio de Janeiro"}}}]}),
        "/jobs/1": _page({"job": {"name": "Planner", "description": "<p>Sobre</p>", "prerequisites": "<li>Inglês</li>",
                                  "publishedAt": "2026-10-01T10:00:00.000Z", "addressCity": "Rio de Janeiro",
                                  "addressState": "Rio de Janeiro", "workplaceType": "on-site"}}),
    })
    b = gupy.collect_tenant(_ctx(http))
    assert b.status == "complete" and b.can_infer_absence and b.details_fetched == 1
    o = b.jobs[0]
    assert (o.platform, o.tenant, o.external_id) == ("gupy", "", "1")
    assert "Requisitos e qualificações" in o.description and o.published_source == "gupy:job.publishedAt"


def test_login_page_is_format_changed_not_empty():
    b = gupy.collect_tenant(_ctx(FakeHttp({"prio.gupy.io/": "<html>Faça login</html>"})))
    assert b.status == "failed" and b.error_code == "format_changed" and not b.can_infer_absence


def test_empty_board_recognized_is_complete():
    b = gupy.collect_tenant(_ctx(FakeHttp({"prio.gupy.io/": _page({"jobs": []})})))
    assert b.status == "complete" and b.jobs == []


def test_job_page_without_job_raises():
    try:
        gupy.parse_job_page(_page({"other": 1}))
    except FormatChanged:
        return
    raise AssertionError("esperava FormatChanged")


def test_probe_reads_job_status():
    alive = FakeHttp({"/jobs/1": _page({"job": {"name": "x", "status": "published"}})})
    gone = FakeHttp({"/jobs/1": _page({"job": {"name": "x", "status": "closed"}})})
    assert gupy.probe(_ctx(alive), "1", "https://prio.gupy.io/jobs/1") == "alive"
    assert gupy.probe(_ctx(gone), "1", None) == "gone"
