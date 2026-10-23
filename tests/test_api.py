"""T40-T44: API em loopback, allowlist estática, proteção de mutações, persistência e concordância com CLI."""
import pytest
from fastapi.testclient import TestClient

from conftest import apply, batch, make_source, obs

from jobos import persistence
from jobos.api.app import create_app

PORT = 8799
H = {"host": f"127.0.0.1:{PORT}"}
M = {**H, "x-jobos": "1", "origin": f"http://127.0.0.1:{PORT}"}


@pytest.fixture()
def client(ctx):
    src = make_source()
    apply(ctx, batch(src, "r1", [obs("1")]), src)
    app = create_app(port=PORT, worker=False, paths=ctx.paths)
    with TestClient(app, base_url=f"http://127.0.0.1:{PORT}") as c:
        yield c


@pytest.mark.parametrize("path", ["/_system/config/profile/master.json", "/assets/..%2f..%2f_system%2fconfig%2fapp.yaml",
                                  "/assets/../rvalle.com.br-rafael.json", "/assets/load-jobs.ts", "/rvalle.com.br-rafael.json",
                                  "/Artifact/jobs.db", "/_system/data/jobos.sqlite3", "/painel/../config/app.yaml",
                                  "/assets/%2e%2e/jobs.json"])
def test_private_files_are_not_served(client, path):
    r = client.get(path, headers=H)
    assert r.status_code in (404, 400)
    assert "truth_boundaries" not in r.text and "SQLite format" not in r.text


def test_public_portal_files_and_generated_book(client):
    assert client.get("/", headers=H).status_code == 200
    r = client.get("/assets/jobs-data.js", headers=H)
    assert r.status_code == 200 and r.text.startswith("window.JOBOS_BOOK")
    assert client.get("/jobs.json", headers=H).json()["generatedBy"].startswith("jobos-local")


def test_bad_host_rejected(client):
    assert client.get("/api/health", headers={"host": "evil.example:80"}).status_code == 400


def test_mutation_requires_header_and_origin(client, ctx):
    assert client.post("/api/work-items", json={"kind": "cycle"}, headers=H).status_code == 403
    bad = {**M, "origin": "https://evil.example"}
    assert client.post("/api/work-items", json={"kind": "cycle"}, headers=bad).status_code == 403
    assert ctx.con.execute("SELECT COUNT(*) FROM work_items").fetchone()[0] == 0
    ok = client.post("/api/work-items", json={"kind": "cycle"}, headers=M)
    assert ok.status_code == 202
    dup = client.post("/api/work-items", json={"kind": "cycle"}, headers=M).json()
    assert dup["deduplicated"] is True


def test_work_item_rejects_unknown_source_and_arbitrary_input(client):
    assert client.post("/api/work-items", json={"kind": "collect_source", "target": "https://evil"}, headers=M).status_code == 400
    assert client.post("/api/work-items", json={"kind": "shell", "target": "rm"}, headers=M).status_code == 422


def test_get_never_triggers_collection(client, ctx):
    runs_before = ctx.con.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    for p in ("/api/status", "/api/jobs", "/api/sources", "/jobs.json", "/assets/jobs-data.js"):
        client.get(p, headers=H)
    assert ctx.con.execute("SELECT COUNT(*) FROM work_items").fetchone()[0] == 0
    assert ctx.con.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == runs_before


def test_application_event_persists_and_matches_cli(client, ctx):
    from jobos.applications.service import list_applications
    jid = ctx.con.execute("SELECT job_id FROM job_records").fetchone()[0]
    r = client.post(f"/api/applications/{jid}/events", json={"action": "transition", "target": "shortlisted",
                                                             "reason": "boa vaga"}, headers=M)
    assert r.status_code == 200
    detail = client.get(f"/api/jobs/{jid}", headers=H).json()
    assert detail["application"]["prep_state"] == "shortlisted"
    assert list_applications(ctx.con)[0]["prep_state"] == "shortlisted"  # CLI e API leem o mesmo serviço
    bad = client.post(f"/api/applications/{jid}/events", json={"action": "transition", "target": "submitted_verified"},
                      headers=M)
    assert bad.status_code == 409


def test_artifact_traversal_blocked(client, ctx):
    ctx.con.execute("INSERT INTO artifacts (artifact_id, rel_path, sha256, kind, created_at) VALUES ('a1','../../config/app.yaml','x','cv','now')")
    assert client.get("/api/artifacts/a1/download", headers=H).status_code == 404


def test_csp_on_panel_and_api(client):
    r = client.get("/api/health", headers=H)
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY"


def test_portal_refresh_respects_cooldown(client, ctx):
    # já houve execução recente (fixture): abrir o portal não enfileira ciclo
    assert client.post("/api/refresh", headers=M).json()["queued"] is None
    ctx.con.execute("DELETE FROM source_runs")
    ctx.con.execute("DELETE FROM runs")
    first = client.post("/api/refresh", headers=M).json()
    second = client.post("/api/refresh", headers=M).json()
    assert first["queued"] and second["queued"] is None
    assert ctx.con.execute("SELECT COUNT(*) FROM work_items").fetchone()[0] == 1


def test_insight_endpoints(client, ctx):
    m = client.get("/api/map", headers=H).json()
    assert m["total_open"] >= 1 and any(p["name"] == "Rio de Janeiro" for p in m["places"])
    s = client.get("/api/signals", headers=H).json()
    assert "companies" in s and s["note"].startswith("Proxy")
    k = client.get("/api/kanban", headers=H).json()
    assert [c["key"] for c in k["columns"]][:2] == ["suggested", "shortlisted"]
    assert client.get("/painel/data/rj-municipios.geojson", headers=H).status_code == 200


def test_job_detail_support_never_applies(client, ctx):
    jid = ctx.con.execute("SELECT job_id FROM job_records").fetchone()[0]
    detail = client.get(f"/api/jobs/{jid}", headers=H).json()
    assert detail["support"]["sends_application"] is False
    assert detail["support"]["uses_ai"] is False
    assert detail["support"]["writes_cv"] is False
    assert detail["support"]["available"] is False
    script = client.get("/painel/preparo.js", headers=H)
    assert script.status_code == 200 and "JobosPreparo" in script.text
    assert "preparo.js" in client.get("/painel/", headers=H).text


def test_panel_manifest_is_a_local_app(client):
    page = client.get("/painel/", headers=H)
    assert page.status_code == 200
    assert 'rel="manifest"' in page.text and "manifest.webmanifest" in page.text
    manifest = client.get("/painel/manifest.webmanifest", headers=H)
    assert manifest.status_code == 200
    assert manifest.headers["content-type"].startswith("application/manifest+json")
    body = manifest.json()
    assert body["start_url"] == "/painel/" and body["scope"] == "/painel/"
    assert body["display"] == "standalone"
    assert body["id"] == "/painel/"
    icon = client.get("/painel/icon-192.png", headers=H)
    assert icon.status_code == 200 and icon.content.startswith(b"\x89PNG")
    assert client.get("/painel/icon-512.png", headers=H).status_code == 200
    assert client.get("/painel/src/preparo.ts", headers=H).status_code == 404


def test_hr_role_detection():
    from jobos.insights import is_hr_role
    assert is_hr_role("Analista de Recrutamento e Seleção") and is_hr_role("Talent Acquisition Partner")
    assert is_hr_role("Business Partner RH") and not is_hr_role("Engenheiro de Projetos")


def test_workspace_projection_is_public_only(ctx, tmp_path, monkeypatch):
    import json
    from jobos.exports import portal
    from jobos.paths import Paths
    ws = tmp_path / "ws"
    (ws / "assets").mkdir(parents=True)
    (ws / "jobs.json").write_text('{"old": true}', encoding="utf-8")
    fake = Paths(ctx.paths.root)
    monkeypatch.setattr(type(fake), "workspace", property(lambda self: ws))
    ctx.paths = fake
    out = portal.write_workspace_files(ctx)
    data = json.loads((ws / "jobs.json").read_text(encoding="utf-8"))
    assert "companies" in data and out["jobs"] >= 0
    js = (ws / "assets" / "jobs-data.js").read_text(encoding="utf-8")
    assert js.startswith("window.JOBOS_BOOK = ") and "prep_state" not in js and "fit_score" not in js
    assert (ctx.paths.backups / "portal-files-original" / "jobs.json").read_text(encoding="utf-8") == '{"old": true}'
