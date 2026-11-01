"""Laço de candidatura: prazo do ciclo, currículo, prova, modo de envio e leitores registrados.

Sem rede. O banco é o temporário do conftest. Gerar currículo não cria candidatura enviada.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import re

import pytest
from fastapi.testclient import TestClient

from conftest import apply, batch, make_source, obs

from jobos.api.app import create_app
from jobos.applications.service import TransitionError, confirm_manual, transition
from jobos.collectors.gupy import quick_apply_value
from jobos.collectors.j2w import detect_apply as j2w_detect
from jobos.collectors.registry import get_adapter
from jobos.collectors.totvs import detect_apply as totvs_detect
from jobos.matching.cv_packet import build_answers, build_gupy_sheet, build_packet, keyword_coverage
from jobos.matching.cv_render import render_html
from jobos.matching.profile import active_profile
from jobos.status import freshness, sources_markdown

PORT = 8797
H = {"host": f"127.0.0.1:{PORT}"}
M = {**H, "x-jobos": "1", "origin": f"http://127.0.0.1:{PORT}"}


@pytest.fixture()
def client(ctx):
    src = make_source()
    apply(ctx, batch(src, "r1", [obs("1")]), src)
    app = create_app(port=PORT, worker=False, paths=ctx.paths)
    with TestClient(app, base_url=f"http://127.0.0.1:{PORT}") as c:
        yield c


def test_cycle_stops_dispatch_past_deadline(ctx, monkeypatch):
    from jobos import pipeline

    clock = {"t": pipeline.utcnow()}

    def now():
        return clock["t"]

    original = pipeline.collect_chain

    def wrapped(ctx, source, run_id, *, fixtures, known):
        batch_out = original(ctx, source, run_id, fixtures=fixtures, known=known)
        if source.source_id == "prio-gupy":
            clock["t"] = clock["t"] + dt.timedelta(minutes=10)
        return batch_out

    monkeypatch.setattr(pipeline, "utcnow", now)
    monkeypatch.setattr(pipeline, "collect_chain", wrapped)
    cycle = ctx.settings.app.setdefault("cycle", {})
    cycle["max_minutes"] = 5
    cycle["max_parallel_sources"] = 1
    res = pipeline.run_cycle(ctx, trigger="test", fixtures=True, only_sources=["prio-gupy", "modec-gupy"],
                             analyze=False, notify=False)
    by_id = {s["source_id"]: s for s in res.sources}
    assert by_id["prio-gupy"]["status"] == "complete"
    assert by_id["modec-gupy"]["status"] == "deadline"
    assert res.stages["deadline"]["skipped"] == ["modec-gupy"]
    assert res.exit_code == 2


def test_cv_download_uses_style_hash_and_blocks_scripts(client, ctx):
    html = render_html({"identity": {"name": {"text": "Rafael", "pointer": "/n"}}, "headline": None,
                        "summary": [], "experience": [], "skills": {}, "credentials": {},
                        "job": {"title": "Planner", "company": "PRIO"}})
    style = re.search(r"<style>(.*?)</style>", html, re.S).group(1)
    token = base64.b64encode(hashlib.sha256(style.encode("utf-8")).digest()).decode("ascii")
    jid = ctx.con.execute("SELECT job_id FROM job_records").fetchone()[0]
    rel = f"{jid}/kit/cv.html"
    target = ctx.paths.artifacts / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html, encoding="utf-8")
    ctx.con.execute("""INSERT INTO artifacts (artifact_id, job_id, rel_path, sha256, kind, created_at)
                       VALUES ('art-cv', ?, ?, 'abc', 'cv_html', '2026-10-30T00:00:00+00:00')""", (jid, rel))
    ctx.con.commit()
    page = client.get("/api/health", headers=H)
    assert "style-src 'self'" in page.headers["content-security-policy"]
    downloaded = client.get("/api/artifacts/art-cv/download", headers=H)
    assert downloaded.status_code == 200
    policy = downloaded.headers["content-security-policy"]
    assert f"style-src 'sha256-{token}'" in policy
    assert "script-src 'none'" in policy and "default-src 'none'" in policy
    assert "<script" not in downloaded.text and "src=" not in downloaded.text


def test_confirm_records_proof_and_legacy_confirm_still_works(client, ctx):
    src = make_source()
    apply(ctx, batch(src, "r2", [obs("2", title="Com prova"), obs("3", title="Sem prova")]), src)
    proved = ctx.con.execute("SELECT job_id FROM job_records WHERE title='Com prova'").fetchone()[0]
    plain = ctx.con.execute("SELECT job_id FROM job_records WHERE title='Sem prova'").fetchone()[0]
    sha = "ab" * 32
    ctx.con.execute("""INSERT INTO artifacts (artifact_id, job_id, rel_path, sha256, kind, created_at)
                       VALUES ('art-proof', ?, 'p/cv.html', ?, 'cv_html', '2026-10-30T00:00:00+00:00')""",
                    (proved, sha))
    ctx.con.commit()
    ok = client.post(f"/api/applications/{proved}/events", headers=M, json={
        "action": "confirm", "date": "2026-10-29", "confirmation": "codigo 12345", "artifact_sha256": sha})
    assert ok.status_code == 200 and ok.json()["proof_recorded"] is True
    payload = json.loads(ctx.con.execute(
        "SELECT payload_json FROM application_events WHERE to_state='submitted_manual' AND application_id="
        "(SELECT application_id FROM applications WHERE job_id=?)", (proved,)).fetchone()[0])
    assert payload["artifact_sha256"] == sha
    assert payload["confirmation_sha256"] == hashlib.sha256(b"codigo 12345").hexdigest()
    linked = ctx.con.execute("SELECT application_id FROM artifacts WHERE artifact_id='art-proof'").fetchone()[0]
    assert linked
    bare = client.post(f"/api/applications/{plain}/events", headers=M, json={"action": "confirm", "date": "2026-10-29"})
    assert bare.status_code == 200
    assert ctx.con.execute("SELECT prep_state FROM applications WHERE job_id=?", (plain,)).fetchone()[0] == "submitted_manual"
    bare_payload = ctx.con.execute(
        "SELECT payload_json FROM application_events WHERE application_id="
        "(SELECT application_id FROM applications WHERE job_id=?)", (plain,)).fetchone()[0]
    assert bare_payload is None


def test_cv_ready_and_verified_require_artifact_or_proof(client, ctx):
    src = make_source()
    apply(ctx, batch(src, "r4", [obs("4", title="Sem curriculo")]), src)
    jid = ctx.con.execute("SELECT job_id FROM job_records WHERE title='Sem curriculo'").fetchone()[0]
    for target in ("shortlisted", "cv_draft"):
        moved = client.post(f"/api/applications/{jid}/events", headers=M,
                            json={"action": "transition", "target": target, "reason": "seguir"})
        assert moved.status_code == 200
    blocked = client.post(f"/api/applications/{jid}/events", headers=M,
                          json={"action": "transition", "target": "cv_ready", "reason": "sem arquivo"})
    assert blocked.status_code == 409 and "cv_ready" in blocked.text
    other = ctx.con.execute("SELECT job_id FROM job_records WHERE job_id!=?", (jid,)).fetchone()[0]
    confirm_manual(ctx.con, other, "2026-10-29")
    with pytest.raises(TransitionError):
        transition(ctx.con, other, "submitted_verified", origin="platform_confirmation", reason="sem prova")


def test_duplicate_warns_and_still_records(ctx):
    src = make_source()
    apply(ctx, batch(src, "r5", [obs("5", title="Original"), obs("6", title="Repetida")]), src)
    first = ctx.con.execute("SELECT job_id FROM job_records WHERE title='Original'").fetchone()[0]
    second = ctx.con.execute("SELECT job_id FROM job_records WHERE title='Repetida'").fetchone()[0]
    confirm_manual(ctx.con, first, "2026-10-29")
    ctx.con.execute("""INSERT INTO job_relations (a_job_id, b_job_id, kind, reason, status, created_at)
                       VALUES (?,?,?,?,?,?)""",
                    (first, second, "possible_duplicate", "teste", "suggested", "2026-10-30T00:00:00+00:00"))
    ctx.con.commit()
    out = confirm_manual(ctx.con, second, "2026-10-29")
    assert "possível repetição" in out["duplicate_warning"]
    assert ctx.con.execute("SELECT prep_state FROM applications WHERE job_id=?", (second,)).fetchone()[0] == "submitted_manual"


def test_keyword_report_inserts_nothing(ctx, tmp_path):
    from jobos.matching import cv_packet
    from jobos.matching.analyze import analyze_job
    from jobos.matching.cv_packet import iter_lines
    src = make_source()
    token = "zzzzkeywordtoken"
    desc = ("Requisitos:\n- Graduação em Engenharia\n- Inglês fluente\n- Experiência com planejamento e cronograma "
            "de projetos (look-ahead, curva S, KPIs)\n- Domínio de MS Project\n" + "x" * 250)
    apply(ctx, batch(src, "r7", [obs("7", title="Planner " + token, desc=desc)]), src)
    jid = ctx.con.execute("SELECT job_id FROM job_records WHERE title LIKE 'Planner %'").fetchone()[0]
    analyze_job(ctx, jid)
    result = build_packet(ctx, jid, out_root=tmp_path / "out")
    report = json.loads((result.directory / "validation.json").read_text(encoding="utf-8"))
    coverage = report["keyword_coverage"]
    assert set(coverage) >= {"present", "available_not_chosen", "absent_from_profile", "note"}
    assert "inserido" in coverage["note"]
    cv = json.loads((result.directory / "cv_data.json").read_text(encoding="utf-8"))
    lines = list(iter_lines(cv))
    assert lines and all(ln["pointer"].startswith("/") for ln in lines)
    assert token not in " ".join(ln["text"] for ln in lines)
    assert cv["job"]["title"].endswith(token)
    profile = active_profile(ctx.con)
    state = cv_packet._prepare_state(profile, {"domains": []}, {"requirements": [
        {"status": "met", "text": token + " planejamento"}]})
    before = json.dumps(cv, sort_keys=True)
    direct = keyword_coverage(state, cv)
    assert token in direct["absent_from_profile"]
    assert json.dumps(cv, sort_keys=True) == before


def test_portuguese_job_falls_back_to_english_headline(ctx):
    from jobos.matching import cv_packet
    profile = active_profile(ctx.con)
    templates = [t for t in profile.data["positioning_layer"]["headline_templates"] if isinstance(t, dict)]
    english_only = next(t for t in templates if t.get("headline_en") and not t.get("headline_pt"))
    portuguese = next(t for t in templates if t.get("headline_pt"))
    analysis = {"requirements": [{"text": "Requisitos obrigatórios de formação e experiência na área de atuação"}]}
    assert cv_packet._job_language(analysis) == "pt"
    assert cv_packet._job_language({"requirements": [{"text": "Requirements and experience with the role"}]}) == "en"

    def compose(tpl):
        chosen = {"id": tpl["id"], "domains": []}
        st = cv_packet._State(profile, {"headline": chosen, "headline_candidates": [chosen]}, analysis, [], [], {}, set(), {})
        return cv_packet._compose_headline(st, None, "pt")[0]

    kept_en = compose(english_only)
    assert kept_en["pointer"].endswith("/headline_en") and kept_en["text"] == english_only["headline_en"]
    used_pt = compose(portuguese)
    assert used_pt["pointer"].endswith("/headline_pt") and used_pt["text"] == portuguese["headline_pt"]


def test_preapproved_sensitive_answers_need_approval(ctx):
    profile = active_profile(ctx.con)
    bare = build_answers(profile, None)
    omitted = {row["key"]: row for row in bare["omitted"]}
    for key in ("phone", "cpf", "diversity", "salary_expectation"):
        assert omitted[key]["status"] == "MANUAL_REQUIRED"
    approved = build_answers(profile, {"items": {
        "phone": {"answer": "21999990000", "approval": "rafael", "updated_at": "2026-10-30"},
        "cpf": {"answer": "sem aprovacao"},
    }})
    phones = [i for i in approved["items"] if i["key"] == "phone"]
    assert phones and phones[0]["answer"] == "21999990000"
    assert phones[0]["source"] == "config/profile/answers_preapproved.json"
    still = {row["key"] for row in approved["omitted"]}
    assert "cpf" in still and "diversity" in still
    sheet = build_gupy_sheet(profile, None)
    assert sheet["sends_application"] is False and sheet["uses_ai"] is False
    assert isinstance(sheet["do_not_claim"], list) and sheet["do_not_claim"]
    assert "21999990000" not in json.dumps(sheet)


def test_apply_mode_badges_are_explicit():
    assert quick_apply_value({"quickApply": True}) is True
    assert quick_apply_value({"quickApply": False}) is False
    assert quick_apply_value({}) == "unknown"
    assert quick_apply_value({"quickApply": "yes"}) == "unknown"
    central = totvs_detect('<a href="https://atracaodetalentos.totvs.app/bram/job-opportunity-application/9">Abrir</a>')
    assert central["apply_mode"] == "central_candidato" and central["apply_url"].endswith("/9")
    simple = totvs_detect("<p>Candidatura simplificada</p><a href='https://wa.me/5500'>zap</a>")
    assert simple["apply_mode"] == "simplified" and simple["apply_url"] is None and simple["whatsapp"] is True
    foreign = totvs_detect('<a href="https://evil.example/job-opportunity-application/1">x</a>')
    assert foreign["apply_mode"] == "unknown" and foreign["apply_url"] is None
    assert totvs_detect("<p>sem modo</p>")["apply_mode"] == "unknown"
    page = "https://careers.example.com/job/1"
    both = j2w_detect(
        '<a href="https://careers.example.com/job/1/apply">Apply now</a>'
        '<a href="https://www.linkedin.com/jobs/view/1">LinkedIn</a>'
        '<a href="https://www.indeed.com/viewjob?jk=1">Indeed</a>', page)
    assert both["apply_mode"] == "apply_now" and both["apply_url"].startswith("https://careers.example.com/")
    assert both["apply_options"] == ["apply_now", "linkedin", "indeed"]
    offhost = j2w_detect('<a href="https://evil.example/apply">Apply now</a>'
                         '<a href="https://www.linkedin.com/x">LinkedIn</a>', page)
    assert offhost["apply_url"] is None and offhost["apply_mode"] == "unknown"
    assert "apply_now" in offhost["apply_options"] and "linkedin" in offhost["apply_options"]


def test_registered_adapters_resolve_without_network(ctx):
    expected = {
        "aker_site_json": "jobos.collectors.aker_site",
        "airswift_hubspot": "jobos.collectors.airswift",
        "oracle_ce": "jobos.collectors.oracle_ce",
        "sage_frecruit": "jobos.collectors.sage_frecruit",
    }
    for name, module in expected.items():
        fn = get_adapter(name)
        assert fn.__module__ == module and fn.__name__ == "collect"
    by_id = {s.source_id: s for s in ctx.registry.sources}
    assert by_id["aker-smart"].adapter == "aker_site_json"
    assert by_id["aker-smart"].params["sf_company"] == "akersoluti"
    assert by_id["airswift-smart"].adapter == "airswift_hubspot"
    assert by_id["airswift-smart"].params["location"] == "Brazil"
    assert by_id["trident-workable"].adapter == "sage_frecruit"
    assert by_id["abs-oracle"].adapter == "oracle_ce"
    assert by_id["abs-oracle"].params["site"] == "CX_1"
    brava = by_id["brava-gupy"].fallback_adapters
    assert brava == ("gupy_portal_company",) or brava == ["gupy_portal_company"]
    assert any(s.adapter is None for s in ctx.registry.sources)


def test_generating_cv_does_not_open_an_application(client, ctx):
    jid = ctx.con.execute("SELECT job_id FROM job_records").fetchone()[0]
    before = ctx.con.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
    denied = client.post(f"/api/jobs/{jid}/cv", headers=M, json={})
    assert denied.status_code == 409
    assert ctx.con.execute("SELECT COUNT(*) FROM applications").fetchone()[0] == before
    detail = client.get(f"/api/jobs/{jid}", headers=H).json()
    assert detail["apply"]["quick_apply"] == "unknown"
    assert detail["cv_packets"] == []
    assert detail["support"]["sends_application"] is False
    assert "não envia" in detail["note"]


def test_freshness_and_source_markdown(ctx):
    fresh = freshness(ctx.con, ctx.settings)
    assert fresh["missed_slots"] > 1 and fresh["banner"] is True
    text = sources_markdown([{
        "source_id": "aker-smart", "company_name": "Aker|Solutions", "platform": "successfactors",
        "adapter": "aker_site_json", "enabled": True, "health": "never_run", "active_jobs": 0,
    }])
    assert "| aker-smart |" in text and "Aker/Solutions" in text and "Não edite à mão" in text


def test_backup_copies_artifact_bytes(ctx, tmp_path):
    from jobos.backup import make_backup
    marker = ctx.paths.artifacts / "nota.txt"
    marker.write_text("cv local", encoding="utf-8")
    out = make_backup(ctx, dest_root=tmp_path, label="teste")
    from pathlib import Path
    dest = Path(out["path"])
    assert (dest / "artifacts" / "nota.txt").read_text(encoding="utf-8") == "cv local"
    assert "artifacts/nota.txt" in out["artifact_files"]
