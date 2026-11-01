"""P3.1-R: kit de CV por vaga. T28 (número fora de contexto), T29 (projeto pessoal != expertise corporativa),
T47 (nova versão de perfil não altera pacote anterior)."""
import hashlib
import json
import socket

import pytest
from conftest import apply, batch, make_source, obs

from jobos.matching import cv_packet, cv_render
from jobos.matching.analyze import analyze_job
from jobos.matching.cv_packet import (PacketError, build_packet, compose_cv_data, iter_lines, unsupported_numbers,
                                      validate_cv_data)
from jobos.matching.prepare import build_support
from jobos.matching.profile import active_profile, register_profile

PLANNER = ("Requisitos:\n- Graduação em Engenharia\n- Inglês fluente\n- Experiência com planejamento e cronograma "
           "de projetos (look-ahead, curva S, KPIs)\n- Domínio de MS Project\n- Conhecimento em Primavera P6\n"
           "- Conhecimento em SQL\n- Experiência em project controls\n" + "x" * 250)
HSE = ("Requisitos:\n- Graduação em Engenharia\n- Inglês fluente\n- Experiência em HSE e resposta a emergências "
       "em operações offshore\n- BOSIET válido\n- NR-35 válida\n- Experiência em operações marítimas e embarcações\n"
       + "x" * 250)


def _job(ctx, ext, title, desc):
    src = make_source()
    apply(ctx, batch(src, f"r{ext}", [obs(ext, title=title, desc=desc)]), src)
    job_id = ctx.con.execute("SELECT job_id FROM job_records WHERE title=?", (title,)).fetchone()[0]
    analyze_job(ctx, job_id)
    return job_id


@pytest.fixture()
def jobs(ctx):
    return {"planner": _job(ctx, "1", "Planner Offshore", PLANNER), "hse": _job(ctx, "2", "Coordenador HSE Offshore", HSE)}


def _read(result, name):
    return (result.directory / name).read_bytes()


def _json(result, name):
    return json.loads(_read(result, name))


def _tree_hashes(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file()}


def _app_state(con):
    return {t: [tuple(r) for r in con.execute(f"SELECT * FROM {t} ORDER BY 1")]
            for t in ("applications", "application_events", "job_records", "job_versions", "analyses")}


def test_two_jobs_get_honestly_different_pointered_cv(ctx, jobs, tmp_path):
    """Duas vagas diferentes produzem cv_data diferente e toda linha tem ponteiro que resolve + status."""
    a = build_packet(ctx, jobs["planner"], out_root=tmp_path / "out")
    b = build_packet(ctx, jobs["hse"], out_root=tmp_path / "out")
    assert a.input_hash != b.input_hash and a.directory != b.directory
    da, db = _json(a, "cv_data.json"), _json(b, "cv_data.json")
    profile = active_profile(ctx.con)
    for cv in (da, db):
        lines = list(iter_lines(cv))
        assert len(lines) > 15
        for ln in lines:
            assert ln["pointer"].startswith("/") and profile.resolves(ln["pointer"]), ln
            assert ln["status"] in ("atendido", "parcial")
            for ip in ln.get("item_pointers", []):
                assert profile.resolves(ip)
        assert cv["uses_ai"] is False and cv["sends_application"] is False
    texts = lambda cv: {ln["text"] for ln in iter_lines(cv)}  # noqa: E731
    assert texts(da) != texts(db)
    bul = lambda cv: {ln["text"] for e in cv["experience"] for ln in e["bullets"]}  # noqa: E731
    assert bul(da) != bul(db)
    assert any("Planejamento e controle" in t for t in bul(da))
    assert any("HSEQ" in t or "emergências" in t for t in bul(db))
    certs_b = " ".join(ln["text"] for ln in db["credentials"]["certifications"])
    assert "BOSIET" in certs_b and "reciclagem pendente" in certs_b
    assert not any("BOSIET" in ln["text"] for ln in da["credentials"]["certifications"])
    html_a = _read(a, "cv.html").decode("utf-8")
    assert "Planner Offshore" in html_a
    assert "Gerado localmente pelo JOBOS" not in html_a
    assert "Pacote local para:" not in html_a
    assert "não significa candidatura enviada" not in html_a


def test_requirement_text_and_numbers_never_leak_into_cv(ctx, jobs, tmp_path):
    """Texto/números do anúncio não viram linha de CV: só texto do perfil."""
    r = build_packet(ctx, jobs["planner"], out_root=tmp_path / "out")
    cv = _json(r, "cv_data.json")
    profile = active_profile(ctx.con)
    for ln in iter_lines(cv):
        ev = " ".join(cv_packet.evidence_text(profile.pointer(p)) for p in (ln.get("item_pointers") or [ln["pointer"]]))
        assert unsupported_numbers(ln["text"], ev) == []


def test_t28_number_from_other_context_is_dropped(ctx, jobs, monkeypatch, tmp_path):
    """T28: '10 anos' / '5 anos' não são sustentados por evidência com 3 anos e 5 meses ou '5 Medevacs'."""
    tenure = json.dumps(active_profile(ctx.con).pointer("/experience_nodes/exp_vanoord/tenure"), ensure_ascii=False)
    assert unsupported_numbers("10 anos como Superintendente", tenure) == ["10 (year)"]
    assert unsupported_numbers("3 anos e 5 meses como Superintendente", tenure) == []
    assert unsupported_numbers("41 meses como Superintendente", cv_packet.evidence_text(
        active_profile(ctx.con).pointer("/experience_nodes/exp_vanoord/tenure"))) == []
    assert unsupported_numbers("5 anos em emergências", "mais de 5 Medevacs reais") != []
    assert unsupported_numbers("mais de 5 Medevacs reais", "mais de 5 Medevacs reais") == []
    assert unsupported_numbers("Atuou 90% do tempo", "Atuou 9 vezes") != []

    original = cv_packet.compose_cv_data

    def tampered(profile, analysis, support, **kw):
        cv, drops = original(profile, analysis, support, **kw)
        cv["summary"].append({"id": "LX1", "kind": "summary", "text": "10 anos como Superintendente na Van Oord",
                              "pointer": "/experience_nodes/exp_vanoord/tenure", "status": "atendido"})
        cv["experience"][1]["bullets"].append({"id": "LX2", "kind": "bullet", "text": "Resposta: mais de 15 Medevacs reais",
                                               "pointer": "/experience_nodes/exp_vanoord/erc/real_response/0",
                                               "status": "atendido"})
        return cv, drops
    monkeypatch.setattr(cv_packet, "compose_cv_data", tampered)
    r = build_packet(ctx, jobs["planner"], out_root=tmp_path / "out")
    cv, val = _json(r, "cv_data.json"), _json(r, "validation.json")
    all_text = " ".join(ln["text"] for ln in iter_lines(cv))
    assert "10 anos" not in all_text and "15 Medevacs" not in all_text
    dropped = {d["line_id"]: d for d in val["dropped"] if d.get("line_id")}
    assert dropped["LX1"]["reason"] == dropped["LX2"]["reason"] == "T28_numero_sem_evidencia"
    assert val["summary"]["dropped_by_reason"]["T28_numero_sem_evidencia"] == 2


def test_t29_in_development_skills_keep_qualifier_and_are_not_professional(ctx, jobs, tmp_path):
    """T29: P6 e SQL (em desenvolvimento) só na seção independente, com qualificador; MS Project como profissional."""
    r = build_packet(ctx, jobs["planner"], out_root=tmp_path / "out")
    cv = _json(r, "cv_data.json")
    pro = " | ".join(s["text"] for s in cv["skills"]["professional"])
    ind = {s["text"]: s for s in cv["skills"]["independent"]}
    assert "Microsoft Project" in pro
    assert "Primavera" not in pro and "SQL" not in pro
    p6 = next(v for k, v in ind.items() if "Primavera" in k)
    sql = next(v for k, v in ind.items() if k.startswith("SQL"))
    assert "em desenvolvimento" in p6["text"] and p6["qualifier"] == "em desenvolvimento" and p6["status"] == "parcial"
    assert "em desenvolvimento" in sql["text"]
    html = _read(r, "cv.html").decode("utf-8")
    sect = html.index("Em desenvolvimento e projetos independentes")
    assert "Oracle Primavera P6 (em desenvolvimento)" in html[sect:]
    assert "Primavera" not in html[html.index("<h2>Ferramentas</h2>"):sect]


def test_t29_guard_rejects_personal_project_in_professional_section_and_unqualified_mentions(ctx):
    """T29: mesmo que a composição erre, a validação bloqueia (seção errada, sem qualificador, no resumo)."""
    profile = active_profile(ctx.con)
    ptr = "/software_systems_tree/web_dev_and_automation/sw_python"
    cv = {"identity": {"name": {"id": "L1", "kind": "identity", "text": "Rafael Valle", "status": "atendido",
                                "pointer": "/identity/professional_name_used_on_cv"}, "contacts": []},
          "headline": None, "headline_candidates": [], "experience": [],
          "summary": [{"id": "L2", "kind": "summary", "text": "Especialista em Python e automação", "pointer": "/career_summary/canonical_one_liner",
                       "status": "atendido"}],
          "skills": {"professional": [{"id": "L3", "kind": "skill", "text": "Python", "pointer": ptr, "status": "atendido"}],
                     "independent": [{"id": "L4", "kind": "skill", "text": "Python", "pointer": ptr, "status": "parcial",
                                      "qualifier": "projeto pessoal"}]},
          "credentials": {}}
    clean, report = validate_cv_data(cv, profile)
    reasons = {d["line_id"]: d["reason"] for d in report["dropped"]}
    assert reasons["L2"] == "T29_competencia_nao_corporativa"
    assert reasons["L3"] == "T29_competencia_nao_corporativa"
    assert reasons["L4"] == "T29_qualificador_ausente"
    assert clean["skills"] == {"professional": [], "independent": []}


def test_do_not_claim_and_truth_boundaries_are_not_rendered(ctx, tmp_path):
    """Competência do-not-claim vira descarte registrado; nunca entra no CV."""
    desc = "Requisitos:\n- Graduação em Engenharia\n- Experiência com AMOS e HYSYS\n- Domínio de MS Project\n" + "x" * 250
    job = _job(ctx, "9", "Engenheiro de Manutenção Naval", desc)
    r = build_packet(ctx, job, out_root=tmp_path / "out")
    cv, val = _json(r, "cv_data.json"), _json(r, "validation.json")
    blob = json.dumps(cv, ensure_ascii=False).lower()
    assert "amos" not in blob.replace("amostr", "") and "hysys" not in blob
    assert any(g["boundary"] for g in val["not_claimed"])


def test_t47_same_inputs_reuse_dir_and_new_profile_makes_new_dir(ctx, jobs, tmp_path):
    """T47: mesmas entradas => mesma pasta e bytes inalterados; SHA de perfil novo => pasta nova, antiga intocada."""
    out = tmp_path / "out"
    first = build_packet(ctx, jobs["planner"], out_root=out)
    assert first.reused is False
    snapshot = _tree_hashes(out)
    again = build_packet(ctx, jobs["planner"], out_root=out)
    assert again.reused is True and again.directory == first.directory and again.input_hash == first.input_hash
    assert _tree_hashes(out) == snapshot
    assert json.loads(_read(first, "manifest.json"))["files"]["cv.html"]["sha256"] == first.files["cv.html"]

    data = json.loads(ctx.paths.profile_master.read_text(encoding="utf-8"))
    data["meta"]["version"] = "teste-novo-sha"
    p2 = tmp_path / "master2.json"
    p2.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert register_profile(ctx.con, p2)["file_valid"]
    analyze_job(ctx, jobs["planner"])  # análise do perfil novo
    new = build_packet(ctx, jobs["planner"], out_root=out)
    assert new.directory != first.directory and new.reused is False
    assert new.manifest["profile_id"] != first.manifest["profile_id"]
    after = _tree_hashes(out)
    assert all(after[k] == v for k, v in snapshot.items())  # pacote anterior (ex.: PDF/HTML enviado) intocado
    assert len(after) == 2 * len(snapshot)


def test_inconsistent_existing_dir_is_never_overwritten(ctx, jobs, tmp_path):
    out = tmp_path / "out"
    first = build_packet(ctx, jobs["planner"], out_root=out)
    (first.directory / "cv.html").write_text("alterado à mão", encoding="utf-8")
    with pytest.raises(PacketError):
        build_packet(ctx, jobs["planner"], out_root=out)
    assert (first.directory / "cv.html").read_text(encoding="utf-8") == "alterado à mão"


def test_master_json_and_application_state_unchanged(ctx, jobs, tmp_path):
    """O perfil não é modificado e nenhuma candidatura/evento/vaga/análise muda; só `artifacts` ganha linhas."""
    master = ctx.paths.profile_master
    before_master = hashlib.sha256(master.read_bytes()).hexdigest()
    before = _app_state(ctx.con)
    ctx.con.execute("INSERT INTO applications (application_id, job_id, prep_state, created_at, updated_at) "
                    "VALUES ('app-1', ?, 'cv_draft', '2026-10-01T00:00:00+00:00', '2026-10-01T00:00:00+00:00')",
                    (jobs["planner"],))
    before = _app_state(ctx.con)
    r = build_packet(ctx, jobs["planner"], out_root=tmp_path / "out")
    assert hashlib.sha256(master.read_bytes()).hexdigest() == before_master
    assert _app_state(ctx.con) == before
    row = ctx.con.execute("SELECT prep_state, submitted_at, provenance FROM applications").fetchone()
    assert row["prep_state"] == "cv_draft" and row["submitted_at"] is None and row["provenance"] is None
    assert json.loads(_read(r, "manifest.json"))["application_state_changed"] is False


def test_artifacts_table_registration_is_idempotent(ctx, jobs, tmp_path):
    out = tmp_path / "out"
    r = build_packet(ctx, jobs["planner"], out_root=out)
    assert r.registered and len(r.artifact_ids) == 6
    rows = ctx.con.execute("SELECT * FROM artifacts WHERE job_id=?", (jobs["planner"],)).fetchall()
    assert {x["kind"] for x in rows} == {"cv_html", "cv_data", "cv_answers", "cv_validation", "cv_manifest", "cv_coverage"}
    for x in rows:
        assert x["application_id"] is None
        assert hashlib.sha256((out / x["rel_path"]).read_bytes()).hexdigest() == x["sha256"]
        assert ".." not in x["rel_path"] and not x["rel_path"].startswith("/")
    build_packet(ctx, jobs["planner"], out_root=out)
    assert ctx.con.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == 6


def test_default_output_goes_to_data_artifacts(ctx, jobs):
    r = build_packet(ctx, jobs["planner"])
    assert r.directory == (ctx.paths.artifacts / jobs["planner"] / r.input_hash[:12]).resolve()
    assert (ctx.paths.data.resolve() / "artifacts") in r.directory.parents


def test_html_escapes_malicious_job_title(ctx, tmp_path):
    """O título da vaga é dado externo: nunca vira HTML/script."""
    evil = "<script>alert(1)</script>"
    job = _job(ctx, "7", evil, PLANNER)
    r = build_packet(ctx, job, out_root=tmp_path / "out")
    html = _read(r, "cv.html").decode("utf-8")
    assert "<script" not in html.lower().replace("<script>alert", "X") or "<script>" not in html
    assert "<script>" not in html and "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "http://" not in html and "src=" not in html and "<link" not in html and "@import" not in html
    assert "Content-Security-Policy" in html


def test_render_is_self_contained_and_escapes_all_fields():
    cv = {"identity": {"name": {"text": "<b>N</b>", "pointer": "/x"}, "contacts": [{"text": "https://a.b/?q=\"1\"&r=<2>",
                                                                                      "pointer": "/y"}]},
          "headline": {"text": "H & <i>", "pointer": "/h"}, "summary": [{"text": "<img src=x onerror=1>", "pointer": "/s"}],
          "experience": [{"id": "e", "scope": "corporate", "role": {"text": "R<", "pointer": "/r"},
                          "company": {"text": "C>", "pointer": "/c"}, "period": {"text": "P&", "pointer": "/p"},
                          "bullets": [{"text": "b\"'", "pointer": "/b\"><x"}]}],
          "skills": {"professional": [], "independent": []}, "credentials": {},
          "job": {"title": "</title><script>1</script>", "company": "<co>"}}
    html = cv_render.render_html(cv)
    for raw in ("<b>N</b>", "<img", "<script>", "R<", "C>", "<co>", "</title><script>"):
        assert raw not in html
    assert "&lt;b&gt;N&lt;/b&gt;" in html and "https://a.b/?q=&quot;1&quot;&amp;r=&lt;2&gt;" in html
    assert "Gerado localmente pelo JOBOS" not in html
    assert "Pacote local para:" not in html
    assert "não significa candidatura enviada" not in html
    assert "salve como PDF" not in html
    assert "<style>" in html and "@page" in html and "<script" not in html and "<a " not in html
    assert html.count("<h1>") == 1 and "<h2>" in html


def test_no_network(ctx, jobs, tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("rede proibida")
    monkeypatch.setattr(socket, "socket", boom)
    monkeypatch.setattr(socket, "create_connection", boom)
    monkeypatch.setattr(socket, "getaddrinfo", boom)
    r = build_packet(ctx, jobs["hse"], out_root=tmp_path / "out")
    assert r.kept > 0


def test_headline_tie_is_not_chosen_but_can_be_chosen_by_user(ctx, jobs, tmp_path):
    profile = active_profile(ctx.con)
    an = json.loads(ctx.con.execute("SELECT result_json FROM analyses WHERE job_id=?", (jobs["hse"],)).fetchone()[0])
    support = build_support(profile, an)
    if support["headline"] is None and support["headline_candidates"]:
        r = build_packet(ctx, jobs["hse"], out_root=tmp_path / "out")
        assert _json(r, "cv_data.json")["headline"] is None
        pick = support["headline_candidates"][0]["id"]
        r2 = build_packet(ctx, jobs["hse"], out_root=tmp_path / "out", headline_id=pick)
        assert r2.directory != r.directory
        assert _json(r2, "cv_data.json")["headline"]["pointer"].endswith("/headline_en")
    with pytest.raises(PacketError):
        build_packet(ctx, jobs["hse"], out_root=tmp_path / "out", headline_id="nao_existe")


def test_answers_only_evidenced_and_unknowns_omitted(ctx, jobs, tmp_path):
    r = build_packet(ctx, jobs["planner"], out_root=tmp_path / "out")
    ans = _json(r, "answers.json")
    keys = {i["key"] for i in ans["items"]}
    assert {"full_name", "english_level", "drivers_license"} <= keys
    omitted = {o["key"] for o in ans["omitted"]}
    assert {"salary_expectation", "employment_regime", "work_authorization"} <= omitted
    profile = active_profile(ctx.con)
    for it in ans["items"]:
        assert profile.resolves(it["pointer"])
    assert next(i for i in ans["items"] if i["key"] == "relocation")["needs_review"] is True


def test_errors_without_analysis_or_job(ctx, tmp_path):
    with pytest.raises(PacketError):
        build_packet(ctx, "nao-existe", out_root=tmp_path / "out")
    with pytest.raises(PacketError):
        build_packet(ctx, "../fora", out_root=tmp_path / "out")
    src = make_source()
    apply(ctx, batch(src, "r1", [obs("5", title="Sem análise")]), src)
    job = ctx.con.execute("SELECT job_id FROM job_records WHERE title='Sem análise'").fetchone()[0]
    with pytest.raises(PacketError):
        build_packet(ctx, job, out_root=tmp_path / "out")
    assert not (tmp_path / "out").exists() or not any((tmp_path / "out").rglob("*.json"))


def test_cli_cv_build_generates_then_reuses_and_never_marks_sent(ctx, jobs, capsys):
    """CLI `cv build`: gera, reaproveita com as mesmas entradas e não toca candidaturas (CV gerado != envio)."""
    from jobos import cli
    before = _app_state(ctx.con)
    assert cli.main(["--json", "cv", "build", "--job", jobs["planner"]]) == cli.EXIT_OK
    first = json.loads(capsys.readouterr().out)
    assert first["reused"] is False and first["registered"] is True and first["kept"] > 0
    assert cli.main(["--json", "cv", "build", "--job", jobs["planner"][:12]]) == cli.EXIT_OK
    second = json.loads(capsys.readouterr().out)
    assert second["reused"] is True and second["directory"] == first["directory"]
    assert _app_state(ctx.con) == before


def test_cli_cv_build_unknown_job_is_exit_3(ctx, capsys):
    from jobos import cli
    assert cli.main(["cv", "build", "--job", "naoexiste-123456"]) == cli.EXIT_FAILED
    assert "vaga não encontrada" in capsys.readouterr().err
