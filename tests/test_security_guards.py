"""Travas antes de qualquer automação de navegador. Não chama rede e não aceita a DEC-022."""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

from jobos.api.app import create_app
from jobos.exports.portal import build_book

PORT = 8796
H = {"host": f"127.0.0.1:{PORT}"}
M = {**H, "x-jobos": "1", "origin": f"http://127.0.0.1:{PORT}", "sec-fetch-site": "same-origin"}
ROOT = Path(__file__).resolve().parents[1]
DENY = ("win32crypt", "browser_cookie3", "keyring", "Login Data", "Local State",
        "CryptUnprotectData", "storage_state(", "cookies()")
BOOK_KEYS = {"updatedAt", "checkedAt", "platforms", "companies", "generatedBy"}
COMPANY_KEYS = {"id", "name", "platform", "kind", "boardUrl", "note", "logo", "scanned", "error",
                "lastError", "fetchedAt", "jobs"}
JOB_KEYS = {"id", "title", "location", "url", "date", "department", "workplace", "status", "finishedAt", "seenAt"}
FORBIDDEN_EXPORT = {"email", "phone", "cpf", "fit_score", "prep_state", "notes", "salary_expectation", "cv_html"}


def test_source_tree_has_no_secret_or_browser_store_api():
    hits = []
    for path in (ROOT / "src").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in DENY:
            if token in text:
                hits.append(f"{path.relative_to(ROOT)}:{token}")
        if "import playwright" in text or "from playwright" in text:
            hits.append(f"{path.relative_to(ROOT)}:playwright")
    assert hits == []


def test_runtime_imports_do_not_load_playwright():
    import jobos.api.app
    import jobos.cli
    import jobos.pipeline
    assert "playwright" not in sys.modules
    assert jobos.cli and jobos.pipeline and jobos.api.app


def test_cross_site_mutation_is_refused(ctx):
    app = create_app(port=PORT, worker=False, paths=ctx.paths)
    with TestClient(app, base_url=f"http://127.0.0.1:{PORT}") as client:
        same = client.post("/api/work-items", json={"kind": "cycle"}, headers=M)
        assert same.status_code == 202
        crossed = {**M, "sec-fetch-site": "cross-site"}
        denied = client.post("/api/work-items", json={"kind": "cycle"}, headers=crossed)
        assert denied.status_code == 403
        assert "cross-site" in denied.text


def test_public_book_uses_an_explicit_key_allowlist(ctx):
    book = build_book(ctx)
    assert set(book) == BOOK_KEYS
    assert book["platforms"][-1] == "Outras"
    by_id = {c["id"]: c for c in book["companies"]}
    assert by_id["aker"]["platform"] == "SuccessFactors"
    assert by_id["airswift"]["platform"] == "HubSpot"
    assert by_id["trident"]["platform"] == "Sage fRecruit"
    assert by_id["abs"]["platform"] == "Oracle"
    for company in book["companies"]:
        assert set(company) == COMPANY_KEYS
        for job in company["jobs"]:
            assert set(job) == JOB_KEYS
            assert FORBIDDEN_EXPORT.isdisjoint(job)
    blob = str(book)
    for secret in ("fit_score", "prep_state", "truth_boundaries"):
        assert secret not in blob
