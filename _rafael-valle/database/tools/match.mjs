#!/usr/bin/env node
// Truth-aware job-offer compatibility check against the Rafael Perini Valle database.
// Zero dependencies (Node 18+).
//
//   node tools/match.mjs --file vaga.txt            (texto puro / markdown)
//   node tools/match.mjs --json vaga.json           ({title|titulo, company|empresa, location|local, description|descricao, date_posted|data_publicacao, remote_status})
//   node tools/match.mjs --text "Planner Offshore ..." [--title "..."] [--company "..."] [--location "..."]
//   type vaga.txt | node tools/match.mjs            (stdin)
//   node tools/match.mjs --batch ../vagas-latest.json   (lista de vagas; também aceita {vagas:[...]}, {data:{jobs:[...]}})
//   node tools/match.mjs --batch-db                 (reavalia as 65 vagas de 13_applications/)
// Flags: --format json|text (padrão: json p/ uma vaga, text p/ batch) --ignore-preferences --threshold N --out arquivo.json
// Exit code (vaga única): 0 = compatible, 1 = not compatible, 3 = erro.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const DB = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const load = (rel) => JSON.parse(fs.readFileSync(path.join(DB, rel), 'utf8')).data;

const CFG = load('14_matching/engine_config.json');
const LEX = load('14_matching/concepts.json');
const ARCH = load('14_matching/archetypes.json');
const YEARS = load('14_matching/experience_years.json');
const PREF = load('10_career_strategy/preferences.json');
const CVIDX = load('12_cv_variants/_index.json').variants;
const HEADLINES = load('02_profile/headlines.json').headline_templates;

// ---------------------------------------------------------------- utils
const norm = (s) => String(s ?? '')
  .normalize('NFD').replace(/[̀-ͯ]/g, '')
  .toLowerCase()
  .replace(/[‐-―]/g, '-')
  .replace(/[‘’`´]/g, "'")
  .replace(/[\t  ]+/g, ' ');
const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const compile = (p) => p.startsWith('re:')
  ? new RegExp(p.slice(3), 'g')
  : new RegExp(`(?<![a-z0-9])${esc(norm(p))}(?![a-z0-9])`, 'g');
const anyIn = (text, terms) => terms.some((t) => compile(t).test(text));
const clamp = (x, a = 0, b = 100) => Math.max(a, Math.min(b, x));
const round = (x) => Math.round(x * 10) / 10;

const CONCEPTS = LEX.concepts.map((c) => ({ ...c, rx: c.patterns.map(compile) }));
const ARCHETYPES = ARCH.archetypes.map((a) => ({ ...a, rx: a.title_patterns.map((p) => ({ p, r: compile(p) })) }));
const STATUS = CFG.status_scores;
const LEVEL_W = CFG.level_weights;
const LEVEL_RANK = { noise: -1, desirable: 0, mentioned: 1, duty: 2, mandatory: 3 };
const YEARS_GAP_BLOCKER = CFG.blocking.years_gap_blocker ?? 3;

const STRONG_HEADERS = new Set(['requisitos obrigatorios', 'requisitos', 'pre-requisitos', 'responsabilidades', 'atribuicoes', 'principais atividades',
  'diferenciais', 'desejavel', 'desejaveis', 'qualificacoes', 'beneficios', 'requirements', 'responsibilities', 'key responsibilities', 'qualifications',
  'minimum qualifications', 'basic qualifications', 'preferred qualifications', 'nice to have', 'what you will do', 'o que voce vai fazer',
  'sobre a empresa', 'about us', 'benefits', 'o que oferecemos', 'we offer', 'etapas do processo', 'o que buscamos', 'o que esperamos']);

// ---------------------------------------------------------------- input
function readJobFromArgs(argv) {
  const a = {}; const flags = new Set();
  for (let i = 0; i < argv.length; i++) {
    const k = argv[i];
    if (!k.startsWith('--')) continue;
    const key = k.slice(2);
    if (['ignore-preferences', 'batch-db'].includes(key)) { flags.add(key); continue; }
    a[key] = argv[i + 1]; i++;
  }
  return { a, flags };
}

function toJob(o) {
  if (typeof o === 'string') return { title: '', company: '', location: '', description: o };
  return {
    title: o.title ?? o.titulo ?? o.name ?? '',
    company: o.company ?? o.empresa ?? '',
    location: o.location ?? o.local ?? [o.city, o.state].filter(Boolean).join(', '),
    description: o.description ?? o.descricao ?? o.text ?? '',
    date_posted: o.date_posted ?? o.data_publicacao ?? o.publishedDate ?? '',
    remote_status: o.remote_status ?? o.remote ?? '',
    url: o.url ?? '', id: o.job_id ?? o.source_id ?? o.id ?? '',
    legacy: o.fit !== undefined ? { fit: o.fit, triagem: o.triagem, motivo: o.triagem_motivo, estagio: o.estagio } : undefined,
  };
}

function guessTitle(text) {
  const first = String(text).split(/\r?\n/).map((s) => s.trim()).find((s) => s.length > 3);
  return first && first.length < 140 ? first : '';
}

// ---------------------------------------------------------------- sections / levels
function sectionEvents(t) {
  const ev = [];
  for (const [level, markers] of Object.entries(CFG.section_markers)) {
    for (const m of markers) {
      const r = new RegExp(`(?<![a-z0-9])${esc(m)}(?![a-z0-9])(\\s*(:|\\n|-\\s|\\|))?`, 'g');
      let x;
      while ((x = r.exec(t))) {
        if (x[1] || STRONG_HEADERS.has(m)) ev.push({ pos: x.index, level });
      }
    }
  }
  return ev.sort((p, q) => p.pos - q.pos);
}

function sentenceAt(t, pos) {
  const left = Math.max(t.lastIndexOf('.', pos - 1), t.lastIndexOf(';', pos - 1), t.lastIndexOf('\n', pos - 1), t.lastIndexOf('•', pos - 1), t.lastIndexOf('·', pos - 1), t.lastIndexOf('!', pos - 1), t.lastIndexOf('?', pos - 1));
  const rights = ['.', ';', '\n', '•', '·', '!', '?'].map((c) => t.indexOf(c, pos)).filter((i) => i >= 0);
  const right = rights.length ? Math.min(...rights) : t.length;
  let s = left + 1, e = right;
  if (e - s > 400) { s = Math.max(s, pos - 200); e = Math.min(e, pos + 200); }
  return { s, e, text: t.slice(s, e) };
}

function levelAt(t, events, pos) {
  let sec = 'mentioned';
  for (const e of events) { if (e.pos <= pos) sec = e.level; else break; }
  const sen = sentenceAt(t, pos).text;
  if (anyIn(sen, CFG.inline_markers.desirable)) return { level: 'desirable', explicit: false, sentence: sen };
  if (anyIn(sen, CFG.inline_markers.mandatory)) return { level: sec === 'noise' ? 'noise' : 'mandatory', explicit: true, sentence: sen };
  return { level: sec, explicit: false, sentence: sen };
}

// ---------------------------------------------------------------- archetype
function classify(titleN, descN) {
  const pick = (text) => {
    let best = null;
    for (const a of ARCHETYPES) for (const { p, r } of a.rx) {
      r.lastIndex = 0;
      if (r.test(text)) {
        const cand = { a, p, len: p.length };
        if (!best || a.priority > best.a.priority || (a.priority === best.a.priority && cand.len > best.len)) best = cand;
      }
    }
    return best;
  };
  let hit = titleN ? pick(titleN) : null, source = 'title', base = null;
  if (!hit || hit.a.id === ARCH.fallback) {
    const d = pick(descN.slice(0, 1200));
    if (d && d.a.id !== ARCH.fallback && (!hit || d.a.priority > hit.a.priority)) { hit = d; source = 'description'; base = d.a.base - 10; }
  }
  if (!hit) { hit = { a: ARCHETYPES.find((x) => x.id === ARCH.fallback), p: null }; source = 'fallback'; }
  return { ...hit.a, rx: undefined, matched_pattern: hit.p, source, base: base ?? hit.a.base };
}

// ---------------------------------------------------------------- preferences
function locationScore(job, t) {
  const G = PREF.geography;
  const loc = norm(job.location);
  const remote = /remot|remote|home office|100% home|anywhere/.test(norm(job.remote_status)) || /\b(100% remoto|totalmente remoto|fully remote|trabalho remoto|remote work)\b/.test(t);
  let best = null;
  for (const [k, v] of Object.entries(G.location_scores)) if (loc.includes(k) || (!loc && t.slice(0, 600).includes(k))) best = Math.max(best ?? 0, v);
  if (best === null && G.eu_countries.some((c) => loc.includes(c))) best = G.eu_score;
  if (remote) best = Math.max(best ?? 0, G.remote_score);
  const known = best !== null;
  return { score: known ? best : G.unknown_location_score, known, remote, location: job.location || null };
}

function preferenceFlags(job, titleN, t) {
  const E = PREF.exclusions; const flags = [];
  const comp = norm(job.company);
  const compHit = E.company_terms.find((c) => compile(c).test(comp || t.slice(0, 400)));
  if (compHit) flags.push({ type: 'excluded_company', term: compHit, reason: E.reason });
  const indHit = E.industry_terms_in_title.find((c) => compile(c).test(titleN));
  if (indHit) flags.push({ type: 'excluded_industry', term: indHit, reason: E.reason });
  const titHit = E.title_terms.find((c) => compile(c).test(titleN));
  if (titHit) flags.push({ type: 'excluded_title', term: titHit });
  return flags;
}

function seniority(titleN) {
  const S = PREF.seniority;
  const entry = S.entry_level_terms.some((x) => compile(x).test(titleN)) || /(^|\s)i(\s*$|\s*\(|\s+-)/.test(titleN);
  const tooSenior = S.too_senior_terms.some((x) => compile(x.trim()).test(titleN));
  return { entry, tooSenior };
}

// ---------------------------------------------------------------- years
const YEAR_RX = /(?:(minimo|minima|pelo menos|no minimo|at least|minimum(?: of)?|mais de|acima de|over)\s+(?:de\s+)?)?(\d{1,2})\s*(\+|ou mais|or more)?\s*(?:anos?|years?)\b/g;
const EXP_CUE = /(experiencia|experience|atuacao|vivencia|exercendo|worked|working|na funcao|em cargo|em funcao|de mercado|track record)/;
const DOMAIN_ORDER = ['management_leadership', 'planning_project_controls', 'project_management', 'maintenance', 'quality_management_systems', 'hseq_emergency', 'logistics_supply', 'contracts_procurement', 'oil_gas', 'offshore_marine', 'operations', 'digital_software', 'training_instruction'];
function yearsRequirements(t, events) {
  const out = [];
  let x;
  YEAR_RX.lastIndex = 0;
  while ((x = YEAR_RX.exec(t))) {
    const n = Number(x[2]);
    if (!n || n > 25) continue;
    const lv = levelAt(t, events, x.index);
    if (!EXP_CUE.test(lv.sentence) || lv.level === 'noise') continue;
    let domain = 'total_professional';
    for (const d of DOMAIN_ORDER) if (YEARS.domain_keywords[d]?.some((k) => compile(k.trim()).test(lv.sentence))) { domain = d; break; }
    const have = YEARS.years[domain]?.core ?? YEARS.years.total_professional.core;
    const gap = round(n - have);
    const kind = gap <= 0.5 ? 'ok' : gap <= 1.5 ? 'soft_gap' : 'hard_gap';
    out.push({ required: n, domain, have, gap: Math.max(0, gap), kind, level: lv.level, explicit: lv.explicit || !!x[1], snippet: lv.sentence.trim().slice(0, 220) });
  }
  return out;
}

// ---------------------------------------------------------------- concept matching
function matchConcepts(t, titleN, events) {
  const raw = [];
  const full = `${titleN}\n${t}`;
  const offset = titleN.length + 1;
  for (const c of CONCEPTS) for (const r of c.rx) {
    r.lastIndex = 0; let m;
    while ((m = r.exec(full))) {
      if (!m[0]) { r.lastIndex++; continue; }
      raw.push({ c, start: m.index, end: m.index + m[0].length, inTitle: m.index < titleN.length });
    }
  }
  // longest match wins; ties -> higher weight
  raw.sort((p, q) => (q.end - q.start) - (p.end - p.start) || q.c.weight - p.c.weight);
  const claimed = []; const occ = [];
  for (const h of raw) {
    if (claimed.some(([s, e]) => h.start < e && s < h.end)) continue;
    let lv;
    if (h.inTitle) lv = { level: 'mandatory', explicit: false, sentence: titleN };
    else lv = levelAt(t, events, h.start - offset);
    const degreeSentence = anyIn(lv.sentence, LEX.degree_cues) && /(engenharia|engineering|formacao|graduacao|superior|bacharel|degree|bachelor)/.test(lv.sentence);
    if (h.c.group === 'degree' && !degreeSentence) continue;
    if (h.c.suppress_in_degree_sentence && degreeSentence) continue;
    claimed.push([h.start, h.end]);
    occ.push({ ...h, ...lv });
  }
  // degree alternatives per sentence
  const bySentence = new Map();
  for (const o of occ) if (o.c.group === 'degree') {
    const k = o.sentence; if (!bySentence.has(k)) bySentence.set(k, []); bySentence.get(k).push(o);
  }
  // A degree requirement is satisfied if ANY degree sentence lists a degree he holds or says "afins/related".
  // (Scraped postings often repeat/truncate the same requirement, so one satisfied sentence clears all.)
  let degreeSatisfied = false;
  for (const [sen, list] of bySentence) {
    if (list.some((o) => ['proven', 'adjacent'].includes(o.c.status)) || anyIn(sen, LEX.degree_related_wildcards)) degreeSatisfied = true;
  }
  if (degreeSatisfied) for (const list of bySentence.values()) for (const o of list) if (!['proven', 'adjacent'].includes(o.c.status)) o.alternativeOk = true;
  const degreeViaPostgradOnly = degreeSatisfied && ![...bySentence].some(([sen, list]) => list.some((o) => o.c.status === 'proven') || anyIn(sen, LEX.degree_related_wildcards));
  // aggregate per concept (strongest level)
  const agg = new Map();
  for (const o of occ) {
    const prev = agg.get(o.c.id);
    const better = !prev || LEVEL_RANK[o.level] > LEVEL_RANK[prev.level] || (o.level === prev.level && o.explicit && !prev.explicit);
    if (better) agg.set(o.c.id, { c: o.c, level: o.level, explicit: o.explicit, inTitle: o.inTitle, snippet: o.sentence.trim().slice(0, 220), alternativeOk: o.alternativeOk && (!prev || prev.alternativeOk !== false) });
    else if (prev && !o.alternativeOk) prev.alternativeOk = false;
  }
  const out = [...agg.values()].filter((x) => x.level !== 'noise');
  out.degreeViaPostgradOnly = degreeViaPostgradOnly;
  return out;
}

// ---------------------------------------------------------------- evaluate
export function evaluate(jobIn, opts = {}) {
  const job = toJob(jobIn);
  if (!job.title) job.title = guessTitle(job.description);
  const titleN = norm(job.title).trim();
  const t = norm(job.description);
  const events = sectionEvents(t);

  const arch = classify(titleN, t);
  const hits = matchConcepts(t, titleN, events);
  const yrs = yearsRequirements(t, events);
  const loc = locationScore(job, t);
  const prefFlags = opts.ignorePreferences ? [] : preferenceFlags(job, titleN, t);
  const sen = seniority(titleN);

  const blockers = [], missing = [], actions = [], niceGaps = [], strengths = [], guardrails = new Set();
  let num = 0, den = 0, penalty = 0, bonus = 0;
  const P = CFG.penalties;

  for (const h of hits) {
    const c = h.c;
    if (h.alternativeOk) continue;
    const s = STATUS[c.status] ?? 0;
    const w = (LEVEL_W[h.level] ?? 1) * c.weight;
    num += w * s; den += w;
    if (c.guardrail && s < 1) guardrails.add(c.guardrail);
    const item = { concept: c.id, label: c.label, status: c.status, level: h.level, explicit: h.explicit, snippet: h.snippet };
    if (s >= 0.55) { strengths.push({ ...item, weight: c.weight, evidence_refs: c.evidence_refs, safe_wording: c.safe_wording }); continue; }
    if (h.level === 'mandatory') {
      const eff = c.if_mandatory;
      if (eff === 'blocker' || (eff === 'blocker_if_explicit' && h.explicit)) blockers.push({ type: 'requirement', ...item, guardrail: c.guardrail });
      else if (eff === 'action') { actions.push({ ...item, action: c.action }); penalty += P.renewable_mandatory_each; }
      else if (eff !== 'ok') missing.push({ ...item, action: c.action, guardrail: c.guardrail });
    } else {
      if (c.if_mandatory === 'action') actions.push({ ...item, action: c.action, optional: true });
      else niceGaps.push(item);
    }
  }
  penalty += Math.min(missing.length * P.missing_mandatory_each, P.missing_mandatory_cap);
  // core duties he cannot truthfully own (class/PMS/commissioning/design...) lower the fit even if not "required"
  const hardDuty = niceGaps.filter((g) => g.status === 'hard_gap' && g.level === 'duty').length;
  penalty += Math.min(hardDuty * (P.hard_gap_duty_each ?? 0), P.hard_gap_duty_cap ?? 0);

  let yPen = 0;
  for (const y of yrs) {
    if (y.kind === 'ok') continue;
    if (y.kind === 'soft_gap') yPen += P.years_soft_gap;
    else if (y.level === 'mandatory') {
      yPen += P.years_hard_gap_mandatory;
      if (y.gap >= YEARS_GAP_BLOCKER) blockers.push({ type: 'years', label: `${y.required}+ anos (${y.domain}); tem ${y.have}`, level: y.level, snippet: y.snippet, guardrail: '11_truth/truth_boundaries.json#management_tenure' });
    } else yPen += P.years_hard_gap_desirable;
  }
  penalty += Math.min(yPen, P.years_cap);
  if (sen.entry) penalty += P.entry_level;
  if (sen.tooSenior) penalty += P.too_senior;

  const compN = norm(job.company);
  const dream = PREF.dream_companies.some((d) => compN.includes(norm(d)));
  const priority = PREF.priority_companies.some((d) => compN.includes(norm(d)));
  if (dream) bonus += CFG.bonuses.dream_company; else if (priority) bonus += CFG.bonuses.priority_company;

  // confidence: how much real requirement text was found outside the title
  const bodyHits = hits.filter((h) => !h.inTitle).length;
  const CC = CFG.confidence;
  const confidence = bodyHits >= CC.high_min_body_concepts ? 'high' : bodyHits >= CC.medium_min_body_concepts ? 'medium' : 'low';
  let coverage = den ? num / den : CFG.neutral_coverage_when_no_concepts;
  if (confidence === 'low') coverage = coverage * (1 - CC.low_confidence_blend_to_neutral) + CFG.neutral_coverage_when_no_concepts * CC.low_confidence_blend_to_neutral;

  // industry relevance
  const IND = CFG.industry;
  const ids = new Set(hits.map((h) => h.c.id));
  const industry = priority || dream ? IND.scores.priority_company
    : IND.core_concepts.some((c) => ids.has(c)) ? IND.scores.core
    : IND.adjacent_concepts.some((c) => ids.has(c)) ? IND.scores.adjacent : IND.scores.none;

  const W = CFG.score_weights;
  const raw = W.archetype * arch.base + W.coverage * coverage * 100 + W.location * loc.score + (W.industry ?? 0) * industry;
  const score = round(clamp(raw - penalty + bonus));

  const prefFail = [...prefFlags];
  if (!opts.ignorePreferences && loc.known && loc.score < PREF.geography.min_location_score_for_compatible && !loc.remote) prefFail.push({ type: 'location', reason: `Localização '${job.location}' fora do raio preferido (score ${loc.score}).` });
  if (!opts.ignorePreferences && sen.entry && CFG.blocking.entry_level_is_preference_fail) prefFail.push({ type: 'seniority_entry', reason: 'Vaga de nível de entrada/júnior (senioridade 5/7; ~6 anos de experiência).' });
  const tierBlocked = CFG.blocking.tiers_never_compatible.includes(arch.tier);
  const threshold = opts.threshold ?? (arch.tier === 'C' ? CFG.thresholds.tier_C_min_score : CFG.thresholds.compatible_min_score);
  const compatible = !blockers.length && !prefFail.length && !tierBlocked && score >= threshold;
  const topTier = ['A', 'B'].includes(arch.tier);

  let verdict;
  if (blockers.length) verdict = 'SKIP_BLOCKER';
  else if (prefFail.length) verdict = 'SKIP_PREFERENCE';
  else if (tierBlocked) verdict = 'SKIP_OUT_OF_PROFILE';
  else if (compatible && topTier && confidence !== 'low' && industry >= (CFG.thresholds.apply_priority_min_industry ?? 0)
    && (score >= CFG.thresholds.apply_priority_min_score || (dream && score >= CFG.thresholds.dream_company_priority_min_score))) verdict = 'APPLY_PRIORITY';
  else if (compatible) verdict = 'APPLY';
  else if (score >= CFG.thresholds.stretch_min_score) verdict = 'STRETCH';
  else verdict = 'SKIP_LOW_FIT';

  // language + CV recommendation
  const pad = ` ${t} `;
  const en = CFG.language_detection.en_words.reduce((n, w) => n + (pad.split(w).length - 1), 0);
  const pt = CFG.language_detection.pt_words.reduce((n, w) => n + (pad.split(w).length - 1), 0);
  const lang = en > pt ? 'en' : 'pt';
  const slug = arch.cv?.[lang] ?? arch.cv?.[lang === 'en' ? 'pt' : 'en'] ?? null;
  const cvMeta = CVIDX.find((v) => v.slug === slug);
  const headline = HEADLINES.find((h) => h.id === arch.headline);

  guardrails.add('Tenure: 3+ anos como Superintendente na Van Oord (Jul 2021 - Nov 2024); nunca "5+ anos em gerência similar".');
  guardrails.add('Período Nov/2024-presente = "Professional Development & Independent Projects" (não emprego remunerado).');

  let ageDays = null;
  if (job.date_posted) { const d = new Date(job.date_posted); if (!isNaN(d)) ageDays = Math.floor((Date.now() - d.getTime()) / 86400000); }
  const warnings = [];
  if (ageDays !== null && ageDays > PREF.freshness.max_posting_age_days) warnings.push(`Vaga publicada há ${ageDays} dias (> ${PREF.freshness.max_posting_age_days}).`);
  if (arch.source !== 'title') warnings.push(`Arquétipo inferido pela ${arch.source === 'description' ? 'descrição' : 'regra padrão'}; confira o título.`);
  if (sen.entry) warnings.push('Nível de entrada/júnior: abaixo da senioridade (penalizado).');
  if (sen.tooSenior) warnings.push('Cargo acima do histórico de gestão (penalizado).');
  if (!loc.known) warnings.push('Localização não identificada.');
  const target = PREF.compensation?.target_brl_month;
  if (target) {
    const sal = [...String(job.description).matchAll(/r\$\s*([\d.]+)(?:,(\d{2}))?/gi)].map((m) => Number(m[1].replace(/\./g, ''))).filter((n) => n >= 1500 && n <= 200000);
    if (sal.length && Math.max(...sal) < target) warnings.push(`Salário divulgado (R$ ${Math.max(...sal)}) abaixo da pretensão (R$ ${target}).`);
  }
  if (hits.degreeViaPostgradOnly) warnings.push('Formação exigida atendida só via pós-graduação (Naval/Offshore); graduação é Eng. Civil - confirmar se a vaga aceita.');
  if (confidence === 'low') warnings.push('Descrição com poucos requisitos identificáveis (baixa confiança): leia a vaga completa antes de aplicar.');

  return {
    compatible, verdict, score, confidence,
    job: { title: job.title || null, company: job.company || null, location: job.location || null, language: lang, date_posted: job.date_posted || null, age_days: ageDays, url: job.url || null, id: job.id || null },
    archetype: { id: arch.id, label: arch.label, tier: arch.tier, base: arch.base, matched_pattern: arch.matched_pattern, source: arch.source, note: arch.note },
    blockers, preference_flags: prefFail, missing_mandatory: missing, years_requirements: yrs, actions_required: actions,
    matched_strengths: strengths.sort((p, q) => LEVEL_RANK[q.level] - LEVEL_RANK[p.level] || q.weight - p.weight).slice(0, 15),
    nice_to_have_gaps: niceGaps,
    recommended: {
      cv_variant: slug, cv_file: cvMeta?.file ?? null, cv_status: cvMeta?.status ?? null, cv_profile_260723: arch.cv_profile ?? null,
      headline_id: arch.headline ?? null, headline: headline ? (headline[`headline_${lang}`] ?? headline.headline_en ?? headline.headline_pt) : null,
      lead_with: headline?.lead_with ?? null, interview_stories: arch.stories ?? [],
      build_note: slug ? null : 'Sem CV pronto para este arquétipo/idioma: gerar a partir de 10_career_strategy/cv_profiles_260723.json + 04_experience/cv_bullet_bank.json respeitando 11_truth/.',
    },
    guardrails: [...guardrails],
    warnings,
    score_breakdown: { archetype_base: arch.base, coverage: round(coverage * 100), location: loc.score, industry, penalties: round(penalty), bonuses: bonus, threshold },
    legacy_jobos: job.legacy,
  };
}

// ---------------------------------------------------------------- output
function textReport(r) {
  const L = [];
  L.push(`${r.compatible ? 'COMPATIBLE' : 'NOT COMPATIBLE'}  |  ${r.verdict}  |  score ${r.score}/100  |  confiança ${r.confidence}`);
  L.push(`Vaga: ${r.job.title ?? '?'} - ${r.job.company ?? '?'} - ${r.job.location ?? '?'} [${r.job.language}]`);
  L.push(`Arquétipo: ${r.archetype.label} (tier ${r.archetype.tier}, via ${r.archetype.source})`);
  const sec = (name, arr, f) => { if (arr.length) { L.push(`${name}:`); arr.forEach((x) => L.push(`  - ${f(x)}`)); } };
  sec('Bloqueios', r.blockers, (b) => `${b.label}${b.snippet ? ` <- "${b.snippet.slice(0, 110)}"` : ''}`);
  sec('Preferências', r.preference_flags, (p) => `${p.type}: ${p.term ?? ''} ${p.reason ?? ''}`);
  sec('Faltando (obrigatório)', r.missing_mandatory, (m) => `${m.label} [${m.status}]`);
  sec('Anos exigidos', r.years_requirements, (y) => `${y.required}+ anos ${y.domain} (tem ${y.have}) -> ${y.kind} [${y.level}]`);
  sec('Ações', r.actions_required, (a) => `${a.action ?? a.label}${a.optional ? ' (opcional)' : ''}`);
  sec('Pontos fortes', r.matched_strengths.slice(0, 8), (s) => `${s.label} [${s.status}/${s.level}]`);
  sec('Gaps desejáveis', r.nice_to_have_gaps.slice(0, 6), (g) => `${g.label} [${g.status}]`);
  L.push(`CV: ${r.recommended.cv_variant ?? '(gerar)'}  | headline: ${r.recommended.headline ?? '-'}`);
  sec('Avisos', r.warnings, (w) => w);
  return L.join('\n');
}

function loadBatch(file) {
  const j = JSON.parse(fs.readFileSync(file, 'utf8'));
  if (Array.isArray(j)) return j;
  if (Array.isArray(j.vagas)) return j.vagas;
  if (Array.isArray(j.jobs)) return j.jobs;
  if (j.data?.jobs) return j.data.jobs;
  if (j.data?.vacancies) return j.data.vacancies;
  throw new Error('Formato de batch não reconhecido');
}

function loadBatchDb() {
  const idx = load('13_applications/vacancies_index.json').vacancies;
  const desc = new Map();
  for (const f of fs.readdirSync(path.join(DB, '13_applications/descriptions'))) {
    for (const v of load(`13_applications/descriptions/${f}`).vacancies) desc.set(v.job_id, v.descricao);
  }
  return idx.map((v) => ({ ...v, descricao: desc.get(v.job_id) ?? '' }));
}

async function main() {
  const { a, flags } = readJobFromArgs(process.argv.slice(2));
  const opts = { ignorePreferences: flags.has('ignore-preferences'), threshold: a.threshold ? Number(a.threshold) : undefined };

  if (a.batch || flags.has('batch-db')) {
    const jobs = flags.has('batch-db') ? loadBatchDb() : loadBatch(a.batch);
    const res = jobs.map((j) => evaluate(j, opts));
    if (a.out) fs.writeFileSync(a.out, JSON.stringify(res, null, 2));
    if ((a.format ?? 'text') === 'json') { console.log(JSON.stringify(res, null, 2)); return 0; }
    const rows = res.sort((p, q) => q.score - p.score).map((r) => `${r.compatible ? 'YES' : ' no'}  ${String(r.score).padStart(5)}  ${r.verdict.padEnd(19)} ${r.archetype.tier.padEnd(3)} ${(r.job.company ?? '').slice(0, 16).padEnd(16)} ${(r.job.title ?? '').slice(0, 60)}${r.blockers.length ? '  [' + r.blockers.map((b) => b.label).join('; ').slice(0, 70) + ']' : ''}`);
    console.log(rows.join('\n'));
    console.log(`\n${res.filter((r) => r.compatible).length}/${res.length} compatíveis`);
    return 0;
  }

  let job;
  if (a.json) job = JSON.parse(fs.readFileSync(a.json, 'utf8'));
  else if (a.file) job = { description: fs.readFileSync(a.file, 'utf8') };
  else if (a.text) job = { description: a.text };
  else if (!process.stdin.isTTY) job = { description: fs.readFileSync(0, 'utf8') };
  else { console.error('Uso: node tools/match.mjs --file vaga.txt | --json vaga.json | --text "..." | --batch arquivo.json | --batch-db'); return 3; }
  if (typeof job === 'object' && !Array.isArray(job)) {
    if (a.title) job.title = a.title;
    if (a.company) job.company = a.company;
    if (a.location) job.location = a.location;
  }
  const r = evaluate(job, opts);
  if (a.out) fs.writeFileSync(a.out, JSON.stringify(r, null, 2));
  console.log((a.format ?? 'json') === 'text' ? textReport(r) : JSON.stringify(r, null, 2));
  return r.compatible ? CFG.exit_codes.compatible : CFG.exit_codes.not_compatible;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().then((code) => process.exit(code)).catch((e) => { console.error(e.stack || e.message); process.exit(3); });
}
