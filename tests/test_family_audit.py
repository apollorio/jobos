import json

import pytest

from conftest import apply, batch, make_source, obs
from jobos.matching.analyze import Evaluated, analyze_pending, evaluate, role_fit, score
from jobos.matching.cv_packet import build_packet, iter_lines
from jobos.matching.evidence import build_index
from jobos.matching.families import classify, concepts
from jobos.matching.profile import active_profile
from jobos.matching.requirements import Requirement, extract


@pytest.mark.parametrize('title', ['Estágio em Engenharia', 'Estagiário de Planejamento', 'Estagiária Offshore',
                                  'Engineering Intern', 'Planning Internship', 'Aprendiz de Operações'])
def test_internships_never_score_full_fit(ctx, title):
    src = make_source()
    description = 'Requisitos:\n- Graduação em Engenharia\n- Inglês fluente\n- MS Project\n' + ' ' * 210
    apply(ctx, batch(src, 'r1', [obs('1', title=title, desc=description)]), src)
    analyze_pending(ctx)
    data = json.loads(ctx.con.execute('SELECT result_json FROM analyses').fetchone()[0])
    assert data['decision'] == 'not_eligible'
    assert data['fit_score'] == 0
    assert data['preferences']['role_fit']['label'] == 'internship'
    assert not data['eligibility']['eligible']


def test_international_is_not_internship():
    assert role_fit('International Operations Engineer')['label'] == 'natural'


def test_unknown_reduces_score_without_faking_coverage(ctx):
    items = [Evaluated(Requirement(str(i), 'mandatory', 'test'), 'other', status)
             for i, status in enumerate(['met', 'met', 'met', 'unknown'])]
    result = score(items, ctx.settings.matching)
    assert result['fit_score'] == 75
    assert result['known_items_score'] == 100
    assert result['coverage'] == .75
    assert result['audit']['total_weight'] == 4


def test_sap_modules_and_primavera_products_are_not_equivalent(ctx):
    idx = build_index(active_profile(ctx.con))
    for text in ['SAP PS', 'SAP módulo PS', 'Primavera Risk Analysis']:
        result = evaluate(Requirement(text, 'mandatory', 'test'), idx)
        assert result.status == 'unknown'
        assert not result.evidence
    assert evaluate(Requirement('SAP RT', 'mandatory', 'test'), idx).status == 'met'
    assert evaluate(Requirement('10 anos de experiência com MS Project', 'mandatory', 'test'), idx).status == 'gap'


def test_canonical_aliases_and_multifamily():
    assert concepts('cronograma schedule scheduling planejamento físico') == {'schedule'}
    f = classify('Engenheiro de Projetos Sr – Planejamento Físico', ['cronograma', 'custos', 'riscos'])
    assert {f['primary'], f['secondary']} == {'ENG_PLANNING', 'ENG_PROJECT'}
    for title in ['Quality Engineer', 'Reliability Engineer', 'Engenheiro de Processos', 'Rotating Equipment Engineer']:
        assert classify(title, ['cronograma', 'custos'])['primary'] is None


def test_extract_responsibilities_tools_and_alias_duplicates():
    reqs, _ = extract('Requisitos:\nMS Project, Excel e SAP PS\ncronograma\nschedule\nResponsabilidades:\nAcompanhar custos e desvios')
    assert sum(r.text in ('cronograma', 'schedule') for r in reqs) == 1
    assert any(r.text == 'SAP PS' for r in reqs)
    assert any(r.importance == 'responsibility' for r in reqs)


def test_family_bases_coverage_and_truth(ctx, tmp_path):
    src = make_source()
    desc = 'Requisitos:\n- MS Project\n- SAP PS\n- Forecast\n- Inglês fluente\n' + ' ' * 210
    apply(ctx, batch(src, 'r1', [obs('1', title='Engenheiro de Planejamento', desc=desc)]), src)
    analyze_pending(ctx)
    job = ctx.con.execute('SELECT job_id FROM job_records').fetchone()[0]
    result = build_packet(ctx, job, out_root=tmp_path / 'artifacts')
    data = json.loads((result.directory / 'cv_data.json').read_text(encoding='utf-8'))
    manifest = json.loads((result.directory / 'coverage_manifest.json').read_text(encoding='utf-8'))
    assert data['family']['primary'] == 'ENG_PLANNING'
    assert len(list((tmp_path / 'artifacts/family-bases').rglob('CV-BASE-*.json'))) == 3
    sap = next(r for r in manifest['requirements'] if r['original'] == 'SAP PS')
    assert sap['status'] == 'unknown' and sap['cv_locations'] == []
    assert 'SAP PS' not in ' '.join(l['text'] for l in iter_lines(data))
    assert manifest['family_base']['sha256']
    assert any(b.get('selection') == 'family_base' for e in data['experience'] for b in e['bullets'])
    html = (result.directory / 'cv.html').read_text(encoding='utf-8')
    assert '<h2>Ferramentas</h2>' in html
    assert 'Competências-Chave' not in html and 'Core Competencies' not in html


def test_specific_professional_evidence_beats_domain(ctx):
    idx = build_index(active_profile(ctx.con))
    result = evaluate(Requirement('Experiência em forecast', 'mandatory', 'test'), idx)
    assert result.status == 'met'
    assert result.evidence[0]['pointer'].startswith('/experience_nodes/exp_vanoord/planning_controls/')
