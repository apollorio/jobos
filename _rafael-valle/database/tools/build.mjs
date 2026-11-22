#!/usr/bin/env node
// Validates every part, checks cross-references, and regenerates:
//   index.json                     - manifest of all parts (load order, titles, sizes, sources)
//   _bundle/rafael-bible.full.json - the whole database as ONE JSON (parts keyed by id)
// Usage: node tools/build.mjs        (exit 1 if validation errors)

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const DB = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const TODAY = new Date().toISOString().slice(0, 10);
const errors = [], warnings = [];

function walk(dir) {
  const out = [];
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) { if (!['_bundle', 'tools', 'node_modules'].includes(e.name)) out.push(...walk(p)); }
    else if (e.name.endsWith('.json') && !(dir === DB && e.name === 'index.json')) out.push(p);
  }
  return out;
}

const parts = [];
for (const file of walk(DB).sort()) {
  const rel = path.relative(DB, file).split(path.sep).join('/');
  let j;
  try { j = JSON.parse(fs.readFileSync(file, 'utf8')); } catch (e) { errors.push(`${rel}: JSON inválido (${e.message})`); continue; }
  if (!j._part || !('data' in j)) { errors.push(`${rel}: envelope {_part, data} ausente`); continue; }
  if (j._part.id !== rel.slice(0, -5)) errors.push(`${rel}: _part.id '${j._part.id}' difere do caminho`);
  if (!Array.isArray(j._part.sources) || !j._part.sources.length) warnings.push(`${rel}: sem fontes`);
  parts.push({ rel, part: j._part, data: j.data, bytes: fs.statSync(file).size });
}
const byId = Object.fromEntries(parts.map((p) => [p.part.id, p]));
const D = (id) => byId[id]?.data;

// ------------------------------------------------------------------ known ids
const known = new Set();
const add = (o) => o && Object.keys(o).forEach((k) => known.add(k));
for (const p of parts) {
  if (p.rel.startsWith('04_experience/exp_')) known.add(p.data.id);
  if (p.rel.startsWith('06_skills/software/') && p.data.nodes) add(p.data.nodes);
  if (p.rel.startsWith('09_domains/') && p.data.id) known.add(p.data.id);
  if (p.rel.startsWith('05_projects/proj_') && p.data.id) known.add(p.data.id);
}
add(D('07_ai/ai_coding_tools')?.nodes); add(D('07_ai/ai_profile')?.practices);
add(D('03_education/degrees')?.nodes); add(D('03_education/certifications_training')?.nodes);
add(D('03_education/volunteer_leadership')?.nodes);
add(D('05_projects/vanoord_portfolio')?.phases);
['proj_apollo', 'proj_sos', 'proj_dismantle', 'proj_cv_builder'].forEach((x) => known.add(x));
const vessels = D('06_skills/vessels_assets');
vessels?.vessel_types?.forEach((v) => known.add(v.id)); add(vessels?.named_vessels);
D('06_skills/standards_regulatory')?.nodes?.forEach((s) => known.add(s.id));
add(D('10_career_strategy/interview_story_bank')?.stories);
add(D('11_truth/truth_boundaries')?.boundaries);
const cvSlugs = new Set((D('12_cv_variants/_index')?.variants ?? []).map((v) => v.slug));
const headlineIds = new Set((D('02_profile/headlines')?.headline_templates ?? []).map((h) => h.id));

// ------------------------------------------------------------------ reference checks
for (const p of parts.filter((x) => x.rel.startsWith('09_domains/') && x.data.refs)) {
  for (const [kind, ids] of Object.entries(p.data.refs)) {
    for (const id of ids) if (!known.has(id)) errors.push(`${p.rel}: refs.${kind} -> '${id}' não existe`);
  }
}
for (const a of D('14_matching/archetypes')?.archetypes ?? []) {
  for (const lang of ['pt', 'en']) { const s = a.cv?.[lang]; if (s && !cvSlugs.has(s)) errors.push(`archetypes: ${a.id}.cv.${lang} -> '${s}' não existe`); }
  if (a.headline && !headlineIds.has(a.headline)) errors.push(`archetypes: ${a.id}.headline -> '${a.headline}' não existe`);
  for (const s of a.stories ?? []) if (!known.has(s)) errors.push(`archetypes: ${a.id}.stories -> '${s}' não existe`);
  for (const pat of a.title_patterns) if (pat.startsWith('re:')) { try { new RegExp(pat.slice(3)); } catch { errors.push(`archetypes: regex inválida ${pat}`); } }
}
const conceptIds = new Set();
for (const c of D('14_matching/concepts')?.concepts ?? []) {
  if (conceptIds.has(c.id)) errors.push(`concepts: id duplicado ${c.id}`); conceptIds.add(c.id);
  for (const pat of c.patterns) {
    if (/[\x00-\x1f]/.test(pat)) errors.push(`concepts: ${c.id} tem caractere de controle em '${JSON.stringify(pat)}'`);
    if (pat.startsWith('re:')) { try { new RegExp(pat.slice(3)); } catch { errors.push(`concepts: ${c.id} regex inválida ${pat}`); } }
  }
  for (const ref of [...(c.evidence_refs ?? []), ...(typeof c.guardrail === 'string' && /^\d\d_/.test(c.guardrail) ? [c.guardrail] : [])]) {
    const f = ref.split('#')[0];
    if (!fs.existsSync(path.join(DB, f))) errors.push(`concepts: ${c.id} referencia arquivo inexistente ${f}`);
  }
}
for (const id of [...(D('14_matching/engine_config')?.industry?.core_concepts ?? []), ...(D('14_matching/engine_config')?.industry?.adjacent_concepts ?? [])]) {
  if (!conceptIds.has(id)) errors.push(`engine_config.industry -> conceito '${id}' não existe`);
}
for (const v of D('12_cv_variants/_index')?.variants ?? []) if (!fs.existsSync(path.join(DB, v.file))) errors.push(`cv index: ${v.file} não existe`);

// ------------------------------------------------------------------ index + bundle
const folders = {};
for (const p of parts) {
  const folder = p.rel.split('/')[0];
  (folders[folder] ??= []).push({ id: p.part.id, file: p.rel, title: p.part.title, bytes: p.bytes, sources: p.part.sources });
}
const FOLDER_INFO = {
  '00_meta': 'Fontes, schema/escala de evidência, fila de validação',
  '01_identity': 'Identidade, documentos, contatos, idiomas',
  '02_profile': 'Resumo, headlines, redação segura, soft skills, recomendações, background criativo',
  '03_education': 'Formação, certificações/treinamentos, livro, voluntariado',
  '04_experience': 'Uma parte por experiência + timeline + banco de bullets',
  '05_projects': 'Portfólio Van Oord + projetos independentes (Apollo, SOS, Dismantle, CV Builder, jobOS, sites)',
  '06_skills': 'Software atômico, programação, normas, embarcações, árvores de conhecimento',
  '07_ai': 'Ferramentas de IA, panorama de modelos, comparativos, perfil de IA',
  '08_dev_environment': 'Toolchain observado na estação',
  '09_domains': '13 domínios de carreira com refs cruzadas',
  '10_career_strategy': 'Preferências, encaixe por tier, alvos de mercado, histórias, perfis de CV',
  '11_truth': 'Limites de verdade, lacunas, métricas, evidências',
  '12_cv_variants': '18 CVs adaptados (cópia sem perdas)',
  '13_applications': 'Vagas rastreadas, descrições, boards, estatísticas do jobOS',
  '14_matching': 'Motor de compatibilidade: config, léxico, arquétipos, anos por domínio',
};
const schema = D('00_meta/schema');
const index = {
  _part: { id: 'index', title: 'RAFAEL PERINI VALLE - BIBLE DATABASE (índice)', updated: TODAY, sources: ['all'] },
  data: {
    name: 'rafael-perini-valle-bible',
    version: `${TODAY}.1`,
    subject: 'Rafael Perini Valle',
    purpose: ['Fonte única de verdade (SSOT) sobre formação, experiência, projetos, skills, programação e IA', 'Verificação automática de compatibilidade de vagas (tools/match.mjs)', 'Geração de CVs/cartas sem inventar fatos (respeitar 11_truth/)'],
    how_to_use: {
      check_job: 'node tools/match.mjs --file vaga.txt --format text   (exit 0 = compatible)',
      check_job_json: 'node tools/match.mjs --json vaga.json            (saída JSON com "compatible": true|false)',
      batch: 'node tools/match.mjs --batch ../vagas-latest.json   |   node tools/match.mjs --batch-db',
      rebuild_index_and_bundle: 'node tools/build.mjs',
      edit_rule: 'Edite as partes; rode tools/build.mjs; nunca edite _bundle/ à mão.',
      llm_rule: 'Para usar com IA, envie _bundle/rafael-bible.full.json + instrução: só afirmar o que estiver em proven/used, respeitar 11_truth/truth_boundaries.',
    },
    evidence_scale: schema?.evidence_scale,
    load_order: Object.keys(FOLDER_INFO),
    folders: Object.fromEntries(Object.entries(folders).sort().map(([k, v]) => [k, { description: FOLDER_INFO[k] ?? '', parts: v }])),
    stats: {
      parts: parts.length,
      bytes: parts.reduce((n, p) => n + p.bytes, 0),
      experiences: parts.filter((p) => p.rel.startsWith('04_experience/exp_')).length,
      software_nodes: parts.filter((p) => p.rel.startsWith('06_skills/software/') && p.data.nodes).reduce((n, p) => n + Object.keys(p.data.nodes).length, 0) + Object.keys(D('07_ai/ai_coding_tools')?.nodes ?? {}).length,
      domains: parts.filter((p) => p.rel.startsWith('09_domains/') && p.data.id).length,
      cv_variants: cvSlugs.size,
      vacancies_tracked: D('13_applications/vacancies_index')?.vacancies?.length ?? 0,
      matcher_concepts: conceptIds.size,
      matcher_archetypes: D('14_matching/archetypes')?.archetypes?.length ?? 0,
      known_ids: known.size,
    },
    validation: { errors, warnings, checked_at: TODAY },
  },
};
fs.writeFileSync(path.join(DB, 'index.json'), JSON.stringify(index, null, 2) + '\n');

fs.mkdirSync(path.join(DB, '_bundle'), { recursive: true });
const bundle = {
  _bundle: { name: 'rafael-perini-valle-bible.full', generated: TODAY, generated_by: 'tools/build.mjs', note: 'Gerado automaticamente a partir das partes. Não editar à mão.', parts: parts.length },
  index: index.data,
  parts: Object.fromEntries(parts.map((p) => [p.part.id, { _part: p.part, data: p.data }])),
};
fs.writeFileSync(path.join(DB, '_bundle', 'rafael-bible.full.json'), JSON.stringify(bundle) + '\n');

console.log(`parts=${parts.length} bytes=${index.data.stats.bytes} known_ids=${known.size} concepts=${conceptIds.size}`);
console.log(`errors=${errors.length} warnings=${warnings.length}`);
errors.forEach((e) => console.log('  ERROR ' + e));
warnings.slice(0, 20).forEach((w) => console.log('  warn  ' + w));
process.exit(errors.length ? 1 : 0);
