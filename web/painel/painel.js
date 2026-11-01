/* Painel JOBOS (local)
 * Sem frameworks, sem CDN, sem build. Todo o DOM é criado com createElement e textContent.
 * Dados da API (principalmente descrições de vagas) são texto externo não confiável: nunca viram marcação.
 * Leituras usam GET; toda ação usa POST com o cabeçalho X-JOBOS. Um GET nunca dispara coleta.
 */
(() => {
  'use strict';

  /* ======================================================================
   * Tabelas de rótulos: chave -> [texto, símbolo, tom]. O símbolo e o texto
   * sempre acompanham a cor, para o estado não depender só dela.
   * ====================================================================== */
  const LISTING = {
    active: ['Ativa', '✓', 'ok'],
    missing_unconfirmed: ['Ausente não confirmada', '!', 'warn'],
    closed_confirmed: ['Encerrada confirmada', '✗', 'bad'],
    unknown: ['Não verificada', '?', 'mute'],
  };
  const LISTING_ORDER = ['active', 'missing_unconfirmed', 'closed_confirmed', 'unknown'];

  const DECISION = {
    good_fit: ['Boa aderência', '✓', 'ok'],
    needs_review: ['Revisar', '!', 'warn'],
    weak_fit: ['Baixa aderência', '↓', 'mute'],
    not_eligible: ['Lacuna obrigatória', '✗', 'bad'],
    insufficient_data: ['Descrição insuficiente', '?', 'mute'],
  };

  const LOCATION = {
    preferred: ['Grande Rio', '✓', 'ok'],
    accepted_secondary: ['Base secundária', '+', 'info'],
    review: ['Revisar local', '!', 'warn'],
    remote: ['Remoto', '~', 'info'],
    unknown: ['Local desconhecido', '?', 'mute'],
    outside_preference: ['Fora da preferência', '✗', 'bad'],
  };

  const SRC_STATUS = {
    complete: ['Completa', '✓', 'ok'],
    partial: ['Parcial', '!', 'warn'],
    failed: ['Falhou', '✗', 'bad'],
    blocked: ['Bloqueada', '✗', 'bad'],
    unconfigured: ['Sem configuração', '○', 'mute'],
    never_run: ['Nunca executada', '?', 'mute'],
    skipped: ['Ignorada', '○', 'mute'],
  };

  const RUN_STATUS = {
    running: ['Em execução', '…', 'info'],
    complete: ['Completa', '✓', 'ok'],
    partial: ['Parcial', '!', 'warn'],
    failed: ['Falhou', '✗', 'bad'],
    interrupted: ['Interrompida', '✗', 'bad'],
    skipped_overlap: ['Ignorada por sobreposição', '○', 'mute'],
  };

  const WORK_STATUS = {
    queued: ['Na fila', '…', 'info'],
    leased: ['Em execução', '⟳', 'info'],
    done: ['Concluído', '✓', 'ok'],
    failed: ['Falhou', '✗', 'bad'],
    cancelled: ['Cancelado', '○', 'mute'],
  };

  const REQ_STATUS = {
    met: ['Atendido', '✓', 'ok'],
    partial: ['Parcial', '~', 'warn'],
    gap: ['Lacuna', '✗', 'bad'],
    unknown: ['Desconhecido', '?', 'mute'],
  };

  // [texto completo, símbolo, tom, texto curto]
  const NOTIF_STATUS = {
    draft: ['Rascunho (preview)', '○', 'mute', 'Rascunho'],
    queued: ['Na fila', '…', 'info', 'Na fila'],
    sending: ['Enviando', '…', 'info', 'Enviando'],
    accepted: ['Aceito pelo servidor (não é confirmação de entrega)', '✓', 'ok', 'Aceito pelo servidor'],
    unknown: ['Resultado incerto: não reenviar sem reconciliar', '?', 'warn', 'Resultado incerto'],
    failed_transient: ['Falha temporária', '!', 'warn', 'Falha temporária'],
    failed_permanent: ['Falha permanente', '✗', 'bad', 'Falha permanente'],
    cancelled: ['Cancelado', '○', 'mute', 'Cancelado'],
  };

  const PREP = {
    discovered: ['Descoberta', '○', 'mute'],
    shortlisted: ['Selecionada', '+', 'info'],
    cv_draft: ['CV em rascunho', '…', 'info'],
    cv_ready: ['CV pronto', '+', 'info'],
    awaiting_review: ['Aguardando revisão', '…', 'info'],
    submission_unknown: ['Envio incerto', '?', 'warn'],
    submitted_manual: ['Enviada (confirmação do usuário)', '✓', 'ok'],
    submitted_verified: ['Enviada (prova da plataforma)', '✓', 'ok'],
    legacy_needs_review: ['Legado: revisar procedência', '!', 'warn'],
    dismissed: ['Descartada', '✗', 'mute'],
  };
  const PREP_ORDER = ['discovered', 'shortlisted', 'cv_draft', 'cv_ready', 'awaiting_review', 'submission_unknown',
    'submitted_manual', 'submitted_verified', 'legacy_needs_review', 'dismissed'];

  const STAGE = {
    none: ['Sem estágio', '○', 'mute'],
    screening: ['Triagem', '…', 'info'],
    test: ['Teste', '…', 'info'],
    interview: ['Entrevista', '+', 'info'],
    offer: ['Oferta', '✓', 'ok'],
    rejected: ['Rejeitada', '✗', 'bad'],
    withdrawn: ['Retirada', '○', 'mute'],
    hired: ['Contratado', '✓', 'ok'],
  };
  const STAGE_ORDER = ['none', 'screening', 'test', 'interview', 'offer', 'rejected', 'withdrawn', 'hired'];

  const IMPORT_STATUS = {
    complete: ['Completa', '✓', 'ok'],
    running: ['Em andamento', '…', 'info'],
    failed: ['Falhou', '✗', 'bad'],
  };

  // Rótulos simples (texto apenas)
  const PRECISION = { timestamp: 'data e hora', date_only: 'só a data', relative_estimate: 'estimativa relativa', unknown: 'desconhecida' };
  const ORIGIN = {
    observed: 'observada pelo coletor', legacy_sqlite: 'importada do SQLite legado',
    legacy_portal_json: 'importada do JSON do portal legado', fixture: 'dados de teste (fixture)',
    user_asserted: 'declarado pelo usuário', platform_confirmation: 'confirmação da plataforma',
    legacy_import: 'importação legada', system: 'sistema',
  };
  const DESC_STATUS = { full: 'completa', partial: 'parcial', missing: 'ausente', truncated: 'truncada' };
  const WORKPLACE = { onsite: 'presencial', hybrid: 'híbrido', remote: 'remoto', unknown: 'regime não informado' };
  const CONFIDENCE = { high: 'alta', medium: 'média', low: 'baixa' };
  const IMPORTANCE = { mandatory: 'obrigatório', desirable: 'desejável', responsibility: 'responsabilidade', ambiguous: 'ambíguo' };
  const CATEGORY = {
    education: 'Formação', certification: 'Certificação', registration: 'Registro profissional', language: 'Idioma',
    license: 'Habilitação', software: 'Software', experience_years: 'Anos de experiência', domain: 'Domínio',
    truth_boundary: 'Limite de verdade do perfil', student_status: 'Estudante', other: 'Outro',
  };
  const ROLE_FIT = {
    internship: 'Estágio: fora do nível profissional',
    natural: 'Função alinhada', off_profile: 'Função fora do perfil', off_profile_licensed: 'Profissão regulamentada',
    tier_x: 'Função eliminatória', level_below: 'Nível abaixo do perfil', unknown: 'Função não classificada',
  };
  const TRIGGER = { manual: 'Manual', scheduler: 'Agendador', api: 'API (painel)', test: 'Teste', portal_refresh: 'Portal antigo' };
  const MODE = { normal: 'Normal', dry_run: 'Simulação (dry-run)', fixtures: 'Fixtures (dados de teste)' };
  const AXIS = { prep: 'Preparação', stage: 'Estágio', note: 'Nota' };
  const EVENT_KIND = {
    'job.discovered': 'Vaga descoberta', 'job.changed': 'Conteúdo alterado', 'job.closed': 'Vaga encerrada',
    'job.reopened': 'Vaga reaberta', 'job.reappeared': 'Vaga reapareceu na fonte',
    'job.confirmed_active': 'Presença confirmada', 'job.imported': 'Importada do legado',
  };
  const COVERAGE_KIND = {
    full_board: 'Quadro completo', filtered_board: 'Quadro filtrado',
    incremental_query: 'Consulta incremental', single_posting: 'Vaga única',
  };
  const VERIFICATION = { needs_current_probe: 'Precisa de teste atual', legacy_errors: 'Erros no legado', unknown: 'Desconhecida' };
  const IMPORT_KIND = { legacy_sqlite: 'SQLite legado', legacy_portal_json: 'JSON do portal legado', browser_export: 'Exportação do navegador' };
  const PRIORITY_PART = {
    'decisão': 'Decisão', local: 'Local', empresa: 'Empresa', frescor: 'Frescor', funcao: 'Função',
    banco_de_talentos: 'Banco de talentos', empregador_excluido: 'Empregador excluído',
  };

  // Espelho de PREP_TRANSITIONS em jobos/domain/states.py. Serve só para desabilitar opções que o servidor recusaria;
  // quem decide de verdade é a API (um 409 volta com a mensagem e é exibido).
  const PREP_TRANSITIONS = {
    discovered: ['shortlisted', 'dismissed', 'submitted_manual'],
    shortlisted: ['cv_draft', 'awaiting_review', 'dismissed', 'submitted_manual', 'discovered'],
    cv_draft: ['cv_ready', 'shortlisted', 'dismissed'],
    cv_ready: ['awaiting_review', 'cv_draft', 'dismissed', 'submitted_manual'],
    awaiting_review: ['submitted_manual', 'submitted_verified', 'submission_unknown', 'shortlisted', 'dismissed'],
    submission_unknown: ['submitted_verified', 'submitted_manual', 'awaiting_review'],
    submitted_manual: ['submitted_verified'],
    submitted_verified: [],
    legacy_needs_review: ['submitted_manual', 'shortlisted', 'dismissed', 'discovered'],
    dismissed: ['shortlisted', 'discovered'],
  };
  const TRANSITION_TARGETS = ['shortlisted', 'dismissed', 'awaiting_review', 'discovered'];
  const STAGE_TARGETS = ['screening', 'test', 'interview', 'offer', 'rejected', 'withdrawn', 'hired', 'none'];
  const SUBMITTED = ['submitted_manual', 'submitted_verified'];

  const LEGACY_EXPLAIN = 'Registro antigo marcado como aplicado sem prova. Confirme se enviou de verdade (Confirmar envio manual) ou mova para Selecionada/Descartada.';
  const SCORE_NOTE = 'Nota = aderência estimada por requisitos com cobertura; não é chance de entrevista.';

  /* ======================================================================
   * Utilidades
   * ====================================================================== */
  const has = (obj, key) => Object.prototype.hasOwnProperty.call(obj, key);
  const isEmpty = (v) => v === null || v === undefined || v === '';
  const text = (map, key) => (isEmpty(key) ? 'n/d' : has(map, key) ? map[key] : String(key));
  const first = (map, key) => (has(map, key) ? map[key][0] : isEmpty(key) ? 'n/d' : String(key));
  const yesNo = (b) => (b ? 'sim' : 'não');
  const enc = encodeURIComponent;
  const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : 0);

  const NUMBER_FMT = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 1 });
  const fmtNum = (v) => (typeof v === 'number' && Number.isFinite(v) ? NUMBER_FMT.format(v) : 'n/d');
  const fmtPct = (v) => (typeof v === 'number' && Number.isFinite(v) ? Math.round(v * 100) + '%' : 'n/d');

  function truncate(s, n) {
    const t = String(s == null ? '' : s);
    return t.length > n ? t.slice(0, n - 1) + '…' : t;
  }

  function parseJson(s) {
    if (typeof s !== 'string' || !s) return null;
    try { return JSON.parse(s); } catch { return null; }
  }

  function safeDecode(s) {
    try { return decodeURIComponent(s); } catch { return s; }
  }

  // Data do dispositivo (AAAA-MM-DD), usada como padrão do envio manual.
  function todayLocal() {
    const d = new Date();
    const p = (n) => String(n).padStart(2, '0');
    return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate());
  }

  /* ---- datas: strings BRT do servidor passam direto; instantes ISO são formatados em Brasília ---- */
  const DTF = new Intl.DateTimeFormat('pt-BR', { timeZone: 'America/Sao_Paulo', dateStyle: 'short', timeStyle: 'short' });
  const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/;
  const ISO_TIME = /^\d{4}-\d{2}-\d{2}T/;

  function toDate(v) {
    if (isEmpty(v)) return null;
    let s = String(v).trim();
    if (!ISO_TIME.test(s)) return null;
    if (!/(Z|[+-]\d{2}:?\d{2})$/.test(s)) s += 'Z'; // o banco guarda UTC
    const d = new Date(s);
    return Number.isNaN(d.getTime()) ? null : d;
  }

  function fmtDate(v, precision) {
    if (isEmpty(v)) return 'n/d';
    const s = String(v).trim();
    const m = DATE_ONLY.exec(s);
    if (m) return m[3] + '/' + m[2] + '/' + m[1];
    if (precision === 'date_only' && ISO_TIME.test(s)) {
      return s.slice(8, 10) + '/' + s.slice(5, 7) + '/' + s.slice(0, 4);
    }
    const d = toDate(s);
    return d ? DTF.format(d) : s;
  }

  function fmtDuration(a, b) {
    const t0 = toDate(a);
    const t1 = toDate(b);
    if (!t0 || !t1) return 'n/d';
    let s = Math.max(0, Math.round((t1 - t0) / 1000));
    const h = Math.floor(s / 3600);
    s -= h * 3600;
    const m = Math.floor(s / 60);
    s -= m * 60;
    if (h) return h + ' h ' + m + ' min';
    if (m) return m + ' min ' + s + ' s';
    return s + ' s';
  }

  /* ---- URLs vindas de dados: somente http/https ---- */
  function safeUrl(u) {
    if (typeof u !== 'string' || !u.trim()) return null;
    try {
      const p = new URL(u.trim());
      return p.protocol === 'http:' || p.protocol === 'https:' ? p.href : null;
    } catch {
      return null;
    }
  }

  /* ======================================================================
   * DOM: sempre createElement + textContent
   * ====================================================================== */
  const PROP_KEYS = new Set(['value', 'checked', 'disabled', 'selected', 'hidden', 'open']);

  function appendKids(node, kids) {
    for (const k of kids) {
      if (k === null || k === undefined || k === false) continue;
      if (Array.isArray(k)) appendKids(node, k);
      else if (k instanceof Node) node.appendChild(k);
      else node.appendChild(document.createTextNode(String(k)));
    }
  }

  function el(tag, props, ...kids) {
    const n = document.createElement(tag);
    if (props) {
      for (const [k, v] of Object.entries(props)) {
        if (v === null || v === undefined || v === false) continue;
        if (k === 'class') n.className = v;
        else if (k === 'text') n.textContent = v;
        else if (k === 'dataset') Object.assign(n.dataset, v);
        else if (k === 'on') for (const [ev, fn] of Object.entries(v)) n.addEventListener(ev, fn);
        else if (PROP_KEYS.has(k)) n[k] = v;
        else n.setAttribute(k, v === true ? '' : String(v));
      }
    }
    appendKids(n, kids);
    return n;
  }

  function extLink(url, label) {
    const href = safeUrl(url);
    if (!href) return null;
    return el('a', { href, target: '_blank', rel: 'noopener noreferrer' }, label || 'Abrir página oficial', el('span', { class: 'sr-only', text: ' (abre em nova aba)' }));
  }

  function applyHref(data) {
    const apply = (data && data.apply) || {};
    return safeUrl(apply.apply_url) || (data.postings || []).map((p) => safeUrl(p.url)).find(Boolean) || null;
  }

  function badge(map, key, o) {
    const e = has(map, key) ? map[key] : [isEmpty(key) ? 'n/d' : String(key), '?', 'mute'];
    const label = o && o.short && e[3] ? e[3] : e[0];
    return el('span', { class: 'badge badge-' + e[2] + (o && o.wrap ? ' badge-wrap' : '') },
      el('span', { class: 'sym', 'aria-hidden': 'true', text: e[1] }),
      el('span', { text: label }));
  }

  function tagBadge(label, symbol, tone) {
    return el('span', { class: 'badge badge-' + (tone || 'mute') },
      el('span', { class: 'sym', 'aria-hidden': 'true', text: symbol || '' }),
      el('span', { text: label }));
  }

  function callout(tone, symbol, ...kids) {
    const role = tone === 'bad' ? 'alert' : 'status';
    return el('div', { class: 'callout callout-' + tone, role },
      el('span', { class: 'sym', 'aria-hidden': 'true', text: symbol }),
      el('div', null, ...kids));
  }

  function card(title, ...kids) {
    return el('section', { class: 'card' }, title ? el('h3', { text: title }) : null, ...kids);
  }

  function kv(rows, cls) {
    const dl = el('dl', { class: 'kv' + (cls ? ' ' + cls : '') });
    for (const r of rows) {
      if (!r) continue;
      dl.appendChild(el('dt', null, r[0]));
      dl.appendChild(el('dd', null, isEmpty(r[1]) ? 'n/d' : r[1]));
    }
    return dl;
  }

  function code(s) {
    return el('code', { text: isEmpty(s) ? 'n/d' : String(s) });
  }

  function viewHead(title, subtitle, actions) {
    return el('div', { class: 'view-head' },
      el('div', null, el('h2', { tabindex: '-1', text: title }), subtitle ? el('p', { class: 'muted', text: subtitle }) : null),
      actions || null);
  }

  /* ---- tabela: no celular vira lista de cartões (CSS); papéis ARIA explícitos preservam a semântica ---- */
  function makeTable(cols, rows, caption) {
    const head = el('tr', { role: 'row' }, cols.map((c) => el('th', { scope: 'col', role: 'columnheader', class: c.num ? 'num' : null, text: c.label })));
    const body = el('tbody', { role: 'rowgroup' });
    for (const r of rows) {
      const tr = el('tr', { role: 'row' });
      r.forEach((cell, i) => {
        tr.appendChild(el('td', { role: 'cell', class: cols[i].num ? 'num' : null, 'data-label': cols[i].label }, cell));
      });
      body.appendChild(tr);
    }
    const table = el('table', { class: 'rtable', role: 'table', 'aria-label': caption || null },
      el('thead', { role: 'rowgroup' }, head), body);
    return el('div', { class: 'tablewrap', tabindex: '0', role: 'region', 'aria-label': caption || 'Tabela' }, table);
  }

  function field(id, labelText, control, hint) {
    return el('div', { class: 'field' },
      el('label', { for: id, text: labelText }),
      control,
      hint ? el('p', { class: 'hint', id: id + '-hint', text: hint }) : null);
  }

  function select(id, options, value, onChange) {
    const s = el('select', { id });
    for (const o of options) {
      s.appendChild(el('option', { value: o[0], text: o[1], disabled: o[2] === true, selected: o[0] === value }));
    }
    if (onChange) s.addEventListener('change', () => onChange(s.value));
    return s;
  }

  function list(items, cls) {
    return el('ul', { class: cls || 'list-plain' }, items.map((i) => el('li', null, i)));
  }

  /* ---- estados de carregamento, vazio e erro ---- */
  function loadingBox(msg) {
    return el('div', { class: 'state', role: 'status' }, el('span', { class: 'spinner', 'aria-hidden': 'true' }), el('span', { text: msg || 'Carregando...' }));
  }

  function emptyBox(msg) {
    return el('div', { class: 'state' }, el('span', { 'aria-hidden': 'true', text: '○' }), el('span', { text: msg }));
  }

  function errorBox(err, retry) {
    return el('div', { class: 'state state-error', role: 'alert' },
      el('span', { 'aria-hidden': 'true', text: '✗' }),
      el('span', { text: 'Não foi possível carregar: ' + (err && err.message ? err.message : 'erro desconhecido') }),
      retry ? el('button', { type: 'button', class: 'btn btn-sm', on: { click: retry } }, 'Tentar novamente') : null);
  }

  /* ---- anúncio para leitores de tela ---- */
  const liveEl = document.getElementById('live');
  function announce(msg) {
    if (!liveEl) return;
    liveEl.textContent = '';
    setTimeout(() => { liveEl.textContent = msg; }, 40);
  }

  /* ======================================================================
   * API
   * ====================================================================== */
  class ApiError extends Error {
    constructor(message, status) {
      super(message);
      this.status = status;
    }
  }

  async function readBody(res) {
    let raw = '';
    try { raw = await res.text(); } catch { return null; }
    if (!raw) return null;
    try { return JSON.parse(raw); } catch { return raw.slice(0, 300); }
  }

  function errorMessage(body, status) {
    if (body && typeof body === 'object') {
      if (typeof body.detail === 'string') return body.detail;
      if (Array.isArray(body.detail)) {
        return body.detail.map((d) => {
          const where = Array.isArray(d.loc) ? d.loc.filter((x) => x !== 'body' && x !== 'query').join('.') : '';
          return (where ? where + ': ' : '') + (d.msg || 'valor inválido');
        }).join('; ');
      }
      if (typeof body.error === 'string') return body.error;
    }
    if (typeof body === 'string' && body) return body;
    return 'Erro HTTP ' + status;
  }

  const OFFLINE_MSG = 'Sem resposta da API local. Verifique se o servidor do JOBOS está rodando.';

  async function apiGet(path) {
    let res;
    try {
      res = await fetch(path, { method: 'GET', headers: { Accept: 'application/json' }, cache: 'no-store' });
    } catch {
      throw new ApiError(OFFLINE_MSG, 0);
    }
    const body = await readBody(res);
    if (!res.ok) throw new ApiError(errorMessage(body, res.status), res.status);
    return body;
  }

  async function apiPost(path, payload) {
    let res;
    try {
      res = await fetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-JOBOS': '1' },
        body: JSON.stringify(payload),
      });
    } catch {
      throw new ApiError(OFFLINE_MSG, 0);
    }
    const body = await readBody(res);
    if (!res.ok) throw new ApiError(errorMessage(body, res.status), res.status);
    return body;
  }

  // Preenche um contêiner: carregando -> conteúdo ou erro. Ignora respostas de telas já abandonadas.
  function fill(ctx, container, promise, build, retry) {
    container.replaceChildren(loadingBox());
    return promise.then((data) => {
      if (!ctx.alive()) return;
      try {
        container.replaceChildren(...[].concat(build(data)));
      } catch (err) {
        console.error(err);
        container.replaceChildren(errorBox(new Error('falha ao montar a tela (' + err.message + ')'), retry));
      }
    }, (err) => {
      if (!ctx.alive()) return;
      container.replaceChildren(errorBox(err, retry));
    });
  }

  /* ======================================================================
   * Tarefas em segundo plano (fila de work-items) e acompanhamento a cada 3 s
   * ====================================================================== */
  const POLL_MS = 3000;
  const MAX_POLLS = 2400; // cerca de 2 h
  const WORK_KEY = 'jobos.painel.trabalhos';
  const works = [];
  let pollTimer = null;
  let workSignature = '';

  const workPanel = document.getElementById('work-panel');
  const isActive = (w) => w.status === 'queued' || w.status === 'leased';

  function persistWork() {
    try {
      const keep = works.filter((w) => isActive(w) && !w.local).map((w) => ({ id: w.id, kind: w.kind, label: w.label }));
      sessionStorage.setItem(WORK_KEY, JSON.stringify(keep));
    } catch { /* armazenamento indisponível: segue sem persistir */ }
  }

  function restoreWork() {
    try {
      const raw = sessionStorage.getItem(WORK_KEY);
      const saved = raw ? JSON.parse(raw) : [];
      for (const w of Array.isArray(saved) ? saved : []) {
        if (w && typeof w.id === 'string' && /^[\w.-]{1,80}$/.test(w.id) && !works.some((x) => x.id === w.id)) {
          works.push({ id: w.id, kind: String(w.kind || ''), label: String(w.label || 'Tarefa'), status: 'queued', polls: 0 });
        }
      }
    } catch { /* ignora */ }
    if (works.length) {
      renderWork();
      schedulePoll();
    }
  }

  function applyItem(w, item) {
    w.status = item.status;
    w.error = item.error || null;
    w.attempts = item.attempts;
    const result = parseJson(item.result_json);
    w.result = result && typeof result === 'object' ? result : null;
    w.pollError = null;
  }

  async function startWork(kind, target, label) {
    const payload = { kind };
    if (target) payload.target = target;
    try {
      const item = await apiPost('/api/work-items', payload);
      let w = works.find((x) => x.id === item.item_id);
      if (!w) {
        w = { id: item.item_id, kind, label, polls: 0, local: false };
        works.unshift(w);
      }
      w.deduplicated = !!item.deduplicated;
      applyItem(w, item);
      announce(label + ': ' + first(WORK_STATUS, w.status).toLowerCase() + '.');
    } catch (err) {
      works.unshift({ id: 'local-' + Date.now(), kind, label, status: 'failed', error: err.message, local: true });
      announce(label + ': não foi possível enfileirar.');
    }
    persistWork();
    renderWork();
    schedulePoll();
  }

  function schedulePoll() {
    if (pollTimer !== null || !works.some(isActive)) return;
    pollTimer = setTimeout(pollAll, POLL_MS);
  }

  async function pollAll() {
    pollTimer = null;
    const active = works.filter(isActive);
    let settled = false;
    await Promise.all(active.map(async (w) => {
      w.polls = (w.polls || 0) + 1;
      try {
        const item = await apiGet('/api/work-items/' + enc(w.id));
        applyItem(w, item);
      } catch (err) {
        if (err.status === 404) {
          w.status = 'failed';
          w.error = 'Item não encontrado no servidor.';
        } else {
          w.pollError = err.message;
        }
      }
      if (isActive(w) && w.polls >= MAX_POLLS) {
        w.status = 'failed';
        w.error = 'O painel parou de acompanhar este item depois de cerca de 2 horas. Veja a aba Execuções.';
      }
      if (!isActive(w)) {
        settled = true;
        announce(w.label + ': ' + first(WORK_STATUS, w.status).toLowerCase() + '.');
      }
    }));
    persistWork();
    renderWork();
    if (settled) onWorkSettled();
    schedulePoll();
  }

  function workLine(w) {
    const bits = [];
    if (w.deduplicated) bits.push(el('p', { class: 'small muted', text: 'Já havia um item igual na fila; o painel acompanha o existente.' }));
    if (w.status === 'queued') {
      bits.push(el('p', { class: 'small', text: 'Aguardando o worker local pegar o item. O trabalho roda em segundo plano no servidor, não nesta página.' }));
    } else if (w.status === 'leased') {
      bits.push(el('p', { class: 'small', text: 'Rodando em segundo plano no servidor local; pode levar vários minutos. Você pode navegar à vontade. O painel consulta o andamento a cada 3 s.' }));
    } else if (w.status === 'done') {
      const r = w.result;
      if (r && r.run_id) {
        bits.push(el('p', { class: 'small' }, 'Execução ',
          el('a', { href: '#execucoes/' + enc(r.run_id) }, code(r.run_id)),
          ' terminou com status ', badge(RUN_STATUS, r.status),
          isEmpty(r.exit_code) ? null : ' (código de saída ' + r.exit_code + ')'));
        if (r.status === 'skipped_overlap') bits.push(el('p', { class: 'small muted', text: 'Outro ciclo já estava rodando; este foi registrado como ignorado.' }));
      } else {
        bits.push(el('p', { class: 'small', text: 'Concluído.' }));
      }
    } else if (w.status === 'failed') {
      bits.push(el('p', { class: 'small', text: 'Falha: ' + (w.error || 'sem detalhe') }));
    }
    if (w.pollError) bits.push(el('p', { class: 'small', text: 'Não consegui consultar o andamento (' + w.pollError + '). Tentando de novo em 3 s.' }));
    return bits;
  }

  function renderWork() {
    if (!workPanel) return;
    const sig = JSON.stringify(works.map((w) => [w.id, w.status, w.error, w.pollError, w.result, w.deduplicated]));
    syncActionButtons();
    if (sig === workSignature) return;
    workSignature = sig;
    if (!works.length) {
      workPanel.hidden = true;
      workPanel.replaceChildren();
      return;
    }
    workPanel.hidden = false;
    const ul = el('ul', { class: 'work-list' });
    for (const w of works) {
      ul.appendChild(el('li', { class: 'work-item' },
        el('div', { class: 'work-main' },
          el('div', { class: 'tags' }, el('span', { class: 'work-title', text: w.label }), badge(WORK_STATUS, w.status)),
          workLine(w)),
        isActive(w) ? null : el('button', {
          type: 'button', class: 'btn btn-sm',
          on: { click: () => { works.splice(works.indexOf(w), 1); renderWork(); } },
        }, 'Dispensar')));
    }
    workPanel.replaceChildren(el('p', { class: 'label', text: 'Tarefas em segundo plano' }), ul);
  }

  function syncActionButtons() {
    const running = works.some((w) => w.kind === 'cycle' && isActive(w));
    for (const b of document.querySelectorAll('[data-action="cycle"]')) {
      b.disabled = running;
      b.textContent = running ? 'Ciclo em andamento...' : 'Atualizar agora';
    }
  }

  function onWorkSettled() {
    // Só telas de leitura são recarregadas sozinhas; formulários em edição não são tocados.
    if (['visao', 'fontes', 'execucoes', 'diagnostico'].includes(currentTab)) route({ silent: true });
  }

  /* ======================================================================
   * Visão geral
   * ====================================================================== */
  function countRows(obj, order, map) {
    const rows = [];
    const seen = new Set();
    const add = (k) => {
      seen.add(k);
      const n = num((obj || {})[k]);
      if (n > 0) rows.push([has(map, k) ? map[k][0] : String(k), String(n)]);
    };
    order.forEach(add);
    Object.keys(obj || {}).filter((k) => !seen.has(k)).forEach(add);
    return rows;
  }

  function overviewNodes(st) {
    const runs = st.runs || {};
    const jobs = st.jobs || {};
    const apps = st.applications || {};
    const srcs = st.sources || {};
    const outbox = st.outbox || {};
    const prof = st.profile || {};
    const byPrep = apps.by_prep_state || {};
    const out = [];

    if (runs.late) {
      out.push(callout('warn', '!', el('p', null, el('strong', { text: 'Atrasado. ' }),
        'O ciclo agendado mais recente não aparece como concluído. Verifique se o PC estava ligado e use Atualizar agora se precisar.')));
    }
    const fresh = st.freshness || {};
    if (fresh.banner || num(fresh.missed_slots) > 1) {
      const times = Array.isArray(fresh.missed_slot_times) ? fresh.missed_slot_times.slice(0, 4) : [];
      out.push(callout('bad', '!', el('p', null, el('strong', { text: 'Horários perdidos. ' }),
        'O computador não cobriu ' + num(fresh.missed_slots) + ' horário(s) do agendador'
        + (times.length ? ' (' + times.join(', ') + ')' : '') +
        '. Isso acontece quando ele dorme. WakeToRun continua desligado.')));
    }

    const cards = [];

    // Última execução
    const last = runs.last;
    const done = runs.last_completed;
    const cRun = card('Última execução');
    if (!last) {
      cRun.appendChild(el('p', { class: 'muted', text: 'Nenhuma execução registrada ainda.' }));
    } else {
      cRun.appendChild(kv([
        ['Status', badge(RUN_STATUS, last.status)],
        ['Início (Brasília)', last.started_brt || fmtDate(last.started_at)],
        ['Fim (Brasília)', last.finished_brt || (last.status === 'running' ? 'em andamento' : 'n/d')],
        ['Gatilho', text(TRIGGER, last.trigger)],
        ['Etapa', last.stage],
        last.error ? ['Erro', last.error] : null,
      ]));
      if (done && done.run_id !== last.run_id) {
        cRun.appendChild(el('p', { class: 'small muted' }, 'Última concluída: ' + (done.started_brt || fmtDate(done.started_at)) + ' (', first(RUN_STATUS, done.status).toLowerCase(), ').'));
      }
      cRun.appendChild(el('p', { class: 'small' }, el('a', { href: '#execucoes/' + enc(last.run_id) }, 'Ver as fontes desta execução')));
    }
    cards.push(cRun);

    // Próxima execução
    cards.push(card('Próxima execução agendada',
      el('div', { class: 'big', text: runs.next_scheduled_brt || 'n/d' }),
      el('p', { class: 'small muted', text: 'Horário de Brasília (America/Sao_Paulo).' }),
      el('p', null, runs.late ? tagBadge('Atrasado', '!', 'warn') : tagBadge('Em dia', '✓', 'ok'))));

    // Candidaturas: legado a revisar e enviadas comprovadas/afirmadas
    const legacy = num(apps.legacy_needs_review);
    const cApps = card('Candidaturas');
    if (legacy > 0) cApps.classList.add('card-legacy');
    cApps.appendChild(el('div', { class: 'prov-box' },
      el('p', { class: 'label', text: 'Legado a revisar' }),
      el('div', { class: 'big', text: String(legacy) }),
      el('p', { class: 'small', text: legacy > 0 ? LEGACY_EXPLAIN : 'Nenhum registro legado pendente de revisão.' }),
      legacy > 0 ? el('a', { class: 'btn btn-sm', href: '#candidaturas' }, 'Revisar agora') : null));
    cApps.appendChild(el('div', { class: 'prov-box' },
      el('p', { class: 'label', text: 'Enviadas comprovadas ou afirmadas' }),
      el('div', { class: 'big', text: String(num(apps.proven_submitted)) }),
      kv([
        ['Prova da plataforma', String(num(byPrep.submitted_verified))],
        ['Confirmadas por você (declaradas)', String(num(byPrep.submitted_manual))],
      ], 'kv-tight'),
      el('p', { class: 'small muted', text: 'Só conta como enviada o que tem confirmação sua ou prova da plataforma. Legado e envio incerto não contam.' })));
    const prepRows = countRows(byPrep, PREP_ORDER, PREP);
    const stageRows = countRows(apps.by_stage, STAGE_ORDER, STAGE);
    cApps.appendChild(el('details', null, el('summary', { text: 'Todos os estados e estágios' }),
      el('h4', { text: 'Preparação' }), prepRows.length ? kv(prepRows, 'kv-tight') : el('p', { class: 'muted', text: 'Nenhuma candidatura registrada.' }),
      el('h4', { text: 'Estágio seletivo' }), stageRows.length ? kv(stageRows, 'kv-tight') : el('p', { class: 'muted', text: 'Nenhum estágio registrado.' })));
    cards.push(cApps);

    const pend = st.pendencias || {};
    const pendItems = Array.isArray(pend.good_fit_without_application) ? pend.good_fit_without_application : [];
    cards.push(card('Pendências',
      kv([
        ['Boa aderência sem envio', String(num(pend.good_fit_without_application_count))],
        ['CV aguardando a sua revisão', String(num(pend.cv_awaiting_review))],
        ['Legado a revisar', String(num(pend.legacy_to_review))],
      ], 'kv-tight'),
      el('p', { class: 'small muted', text: 'Gerar o currículo não envia a candidatura. Você envia no site oficial e confirma aqui.' }),
      pendItems.length
        ? el('ul', { class: 'list-bare' }, pendItems.map((j) => el('li', null,
          el('a', { href: '#vaga/' + enc(j.job_id) }, (j.company_name || 'Empresa') + ' — ' + (j.title || '(sem título)')))))
        : el('p', { class: 'muted', text: 'Nenhuma vaga de boa aderência sem envio nesta lista.' }),
      num(pend.legacy_to_review) > 0 ? el('p', { class: 'small' }, el('a', { href: '#candidaturas' }, 'Revisar o legado')) : null));

    // Vagas
    const byListing = jobs.by_listing_state || {};
    const listingRows = LISTING_ORDER.map((k) => [el('span', null, el('span', { 'aria-hidden': 'true', text: LISTING[k][1] + ' ' }), LISTING[k][0]), String(num(byListing[k]))]);
    Object.keys(byListing).filter((k) => !has(LISTING, k)).forEach((k) => listingRows.push([k, String(num(byListing[k]))]));
    cards.push(card('Vagas por situação do anúncio',
      kv(listingRows, 'kv-tight'),
      el('p', { class: 'label', text: 'Total e outros' }),
      kv([
        ['Total (sem fixtures)', String(num(jobs.total))],
        ['Banco de talentos', String(num(jobs.talent_pool))],
        ['Fixtures excluídas da contagem', String(num(jobs.fixtures_excluded))],
      ], 'kv-tight'),
      el('p', { class: 'label', text: 'Alertáveis nas últimas 24 h' }),
      kv([
        ['Novas', String(num(jobs.alertable_new_24h))],
        ['Alteradas', String(num(jobs.alertable_changed_24h))],
      ], 'kv-tight'),
      el('p', { class: 'small' }, el('a', { href: '#vagas' }, 'Abrir a lista de vagas'))));

    // Fontes
    const bySrc = srcs.by_last_status || {};
    const srcRows = Object.keys(SRC_STATUS).concat(Object.keys(bySrc).filter((k) => !has(SRC_STATUS, k)))
      .filter((k) => num(bySrc[k]) > 0)
      .map((k) => [badge(SRC_STATUS, k), String(num(bySrc[k]))]);
    cards.push(card('Fontes pela última coleta',
      el('div', { class: 'big', text: String(num(srcs.total)) }),
      el('p', { class: 'small muted', text: 'fontes cadastradas' }),
      srcRows.length ? kv(srcRows, 'kv-tight') : el('p', { class: 'muted', text: 'Nenhuma fonte cadastrada.' }),
      el('p', { class: 'small' }, el('a', { href: '#fontes' }, 'Ver detalhes das fontes'))));

    // Fila de notificações
    const outRows = Object.keys(outbox.by_status || {}).filter((k) => num(outbox.by_status[k]) > 0)
      .map((k) => [badge(NOTIF_STATUS, k, { short: true }), String(num(outbox.by_status[k]))]);
    cards.push(card('Notificações (fila de saída)',
      outbox.sending_enabled
        ? el('p', null, tagBadge('Envio ligado', '!', 'warn'), ' ', outbox.recipient_configured ? 'Destinatário configurado.' : 'Sem destinatário configurado.')
        : el('p', null, tagBadge('Envio desligado: apenas preview', '○', 'mute')),
      outRows.length ? kv(outRows, 'kv-tight') : el('p', { class: 'muted', text: 'Fila vazia.' }),
      el('p', { class: 'small' }, el('a', { href: '#notificacoes' }, 'Ver mensagens'))));

    // Perfil e importações
    const pid = prof.active_profile_id;
    cards.push(card('Perfil ativo',
      pid ? el('p', null, code(String(pid).slice(0, 12)), el('span', { class: 'small muted', text: '  (início do identificador)' }))
        : callout('warn', '!', el('p', { text: 'Nenhum perfil válido ativo. A análise de aderência não roda sem perfil.' })),
      prof.last_invalid ? el('p', { class: 'small', text: 'Há um perfil inválido registrado. Veja o Diagnóstico.' }) : null));

    const imports = Array.isArray(st.imports) ? st.imports : [];
    cards.push(card('Importações do legado',
      imports.length
        ? el('ul', { class: 'list-bare' }, imports.map((i) => el('li', null,
          el('div', { class: 'tags' }, el('strong', { text: text(IMPORT_KIND, i.kind) }), badge(IMPORT_STATUS, i.status)),
          el('div', { class: 'small muted' }, 'Fim: ' + fmtDate(i.finished_at) + ' · hash ', code(String(i.sha256 || '').slice(0, 12))))))
        : el('p', { class: 'muted', text: 'Nenhuma importação registrada.' })));

    out.push(el('div', { class: 'grid' }, cards));
    out.push(el('p', { class: 'small muted', text: 'Dados gerados em ' + fmtDate(st.generated_at) + ' (Brasília).' }));
    return out;
  }

  function renderVisao(root, arg, ctx) {
    const body = el('div', { class: 'stack' });
    const cycleBtn = el('button', {
      type: 'button', class: 'btn btn-primary', dataset: { action: 'cycle' },
      on: { click: () => startWork('cycle', null, 'Ciclo completo de coleta') },
    }, 'Atualizar agora');
    const reloadBtn = el('button', { type: 'button', class: 'btn', on: { click: load } }, 'Recarregar dados');
    root.append(
      viewHead('Visão geral', 'Seu espaço para avaliar vagas e acompanhar candidaturas.', el('div', { class: 'tags' }, cycleBtn, reloadBtn)),
      el('nav', { class: 'apollo-workflow', 'aria-label': 'Ações principais' },
        ...[['01', 'Avaliar vagas', 'Compare os requisitos com a sua experiência.', '#vagas'],
          ['02', 'Entrar nas plataformas', 'Abra a conta da empresa pelo Edge.', '#logins'],
          ['03', 'Acompanhar envios', 'Consulte candidaturas e etapas de seleção.', '#candidaturas']].map(([n, title, help, href]) =>
          el('a', { href }, el('span', { class: 'apollo-step', text: n }), el('span', { class: 'apollo-action', text: title }), el('span', { text: help })))),
      body);
    syncActionButtons();
    load();
    function load() { fill(ctx, body, apiGet('/api/status'), overviewNodes, load); }
  }

  /* ======================================================================
   * Fontes
   * ====================================================================== */
  let fontesFilter = 'all';
  let fontesSort = 'health';

  // Saúde da fonte (derivada no servidor: jobos/status.py::derive_health). O texto do chip diz o nível; cor e símbolo só reforçam.
  const SRC_HEALTH = {
    failure: ['Falha', '✗', 'bad'],
    attention: ['Atenção', '!', 'warn'],
    never_run: ['Nunca rodou', '?', 'mute'],
    no_reader: ['Sem leitor', '○', 'mute'],
    ok: ['Ok', '✓', 'ok'],
  };
  const HEALTH_ORDER = ['failure', 'attention', 'never_run', 'no_reader', 'ok'];  // falhas primeiro
  const healthOf = (s) => (has(SRC_HEALTH, s.health) ? s.health : 'attention');
  const healthRank = (s) => HEALTH_ORDER.indexOf(healthOf(s));
  const byCompany = (a, b) => String(a.company_name || '').localeCompare(String(b.company_name || ''), 'pt-BR');
  const SORTS = {
    health: ['Saúde (falhas primeiro)', (a, b) => healthRank(a) - healthRank(b) || num(b.failure_streak) - num(a.failure_streak) || byCompany(a, b)],
    company: ['Empresa (A–Z)', byCompany],
    recent: ['Última coleta (mais recente)', (a, b) => String(b.last_run_at || '').localeCompare(String(a.last_run_at || '')) || byCompany(a, b)],
  };

  function scopeCell(s) {
    const ev = s.scope_evidence;
    const kids = [];
    if (!ev) {
      kids.push(el('span', { class: 'muted', text: 'sem leitura' }));
    } else {
      const pages = ev.pages_expected ? ev.pages_received + ' de ' + ev.pages_expected + ' página(s)' : ev.pages_received + ' página(s)';
      kids.push(el('span', { text: ev.ok ? 'Completa, escopo comprovado' : 'Sem prova de escopo completo' }));
      kids.push(el('span', { class: 'cell-sub', text: text(COVERAGE_KIND, ev.coverage_kind || s.coverage) + '; ' + pages }));
    }
    kids.push(el('span', { class: 'cell-sub', text: 'Verificação: ' + text(VERIFICATION, s.verification_status) }));
    return el('div', null, ...kids);
  }

  function sourceRow(s) {
    const runnable = !!s.adapter && s.enabled !== false;
    const full = s.last_error ? String(s.last_error) : '';
    const err = s.last_error_short || truncate(full, 160);
    const warnings = Array.isArray(s.last_warnings) ? s.last_warnings : [];
    const streak = num(s.failure_streak);

    const btn = el('button', { type: 'button', class: 'btn btn-sm', 'aria-label': 'Coletar ' + s.company_name }, 'Coletar');
    btn.addEventListener('click', async () => {
      btn.disabled = true;
      await startWork('collect_source', s.source_id, 'Coleta: ' + s.company_name);
      btn.disabled = false;
    });

    return [
      [el('span', { class: 'cell-title', text: s.company_name }), el('span', { class: 'cell-sub mono', text: s.source_id })],
      el('div', null, badge(SRC_HEALTH, healthOf(s)), s.health_reason ? el('span', { class: 'cell-sub', text: s.health_reason }) : null),
      el('div', null, el('span', { text: s.platform }),
        s.adapter ? el('span', { class: 'cell-sub' }, code(s.adapter)) : el('span', { class: 'cell-sub muted', text: 'sem leitor' }),
        s.enabled === false ? tagBadge('desativada', '○', 'mute') : null),
      el('div', null,
        badge(SRC_STATUS, s.last_status),
        s.last_run_at ? el('span', { class: 'cell-sub', text: 'em ' + fmtDate(s.last_run_at) }) : null),
      s.last_success_at ? fmtDate(s.last_success_at) : 'nunca',
      isEmpty(s.last_success_count) ? 'n/d' : String(s.last_success_count),
      String(streak),
      scopeCell(s),
      el('div', null,
        err ? el('span', { title: full || err, text: err }) : el('span', { class: 'muted', text: 'nenhum' }),
        full && full.length > err.length ? el('details', null, el('summary', { text: 'texto completo' }), el('p', { class: 'small', text: full })) : null,
        err && s.last_error_at ? el('span', { class: 'cell-sub', text: 'em ' + fmtDate(s.last_error_at) }) : null,
        warnings.length ? el('details', null, el('summary', { text: warnings.length + ' aviso(s) na última coleta' }),
          list(warnings.map((w) => (typeof w === 'string' ? w : JSON.stringify(w))))) : null),
      yesNo(s.absence_applied),
      String(num(s.active_jobs)),
      s.note ? s.note : el('span', { class: 'muted', text: 'sem observação' }),
      runnable ? btn : el('span', { class: 'muted', text: s.adapter ? 'desativada' : 'sem leitor' }),
    ];
  }

  const SOURCE_COLS = [
    { label: 'Empresa' }, { label: 'Saúde' }, { label: 'Plataforma e leitor' }, { label: 'Última coleta' },
    { label: 'Última leitura completa' }, { label: 'Vagas na leitura completa', num: true }, { label: 'Falhas seguidas', num: true },
    { label: 'Escopo da leitura' }, { label: 'Último erro' }, { label: 'Ausência aplicada' },
    { label: 'Vagas ativas', num: true }, { label: 'Observação' }, { label: 'Ação' },
  ];

  function sourcesNodes(list) {
    const count = (k) => list.filter((s) => healthOf(s) === k).length;
    const filters = [['all', 'Todas', () => true]].concat(HEALTH_ORDER.map((k) => [k, SRC_HEALTH[k][0], (s) => healthOf(s) === k]));
    const holder = el('div');
    const chips = el('div', { class: 'chips', role: 'group', 'aria-label': 'Filtrar fontes por saúde' });
    const buttons = filters.map(([key, label, fn]) => {
      const b = el('button', { type: 'button', class: 'chip' }, label + ' (' + list.filter(fn).length + ')');
      b.addEventListener('click', () => { fontesFilter = key; draw(); });
      chips.appendChild(b);
      return b;
    });
    const sortSel = select('fontes-sort', Object.keys(SORTS).map((k) => [k, SORTS[k][0]]), fontesSort, (v) => { fontesSort = v; draw(); });

    function draw() {
      const def = filters.find((f) => f[0] === fontesFilter) || filters[0];
      buttons.forEach((b, i) => b.setAttribute('aria-pressed', String(filters[i][0] === def[0])));
      const cmp = (SORTS[fontesSort] || SORTS.health)[1];
      const rows = list.filter(def[2]).sort(cmp);
      if (!rows.length) {
        holder.replaceChildren(emptyBox('Nenhuma fonte neste filtro.'));
      } else {
        holder.replaceChildren(
          el('p', { class: 'small muted', text: rows.length + ' de ' + list.length + ' fonte(s).' }),
          makeTable(SOURCE_COLS, rows.map(sourceRow), 'Matriz de saúde das fontes de vagas'));
      }
      announce(rows.length + ' fonte(s) no filtro ' + def[1] + '.');
    }
    draw();

    const sum = el('ul', { class: 'health-summary', 'aria-label': 'Resumo por nível de saúde' },
      HEALTH_ORDER.map((k) => el('li', null, badge(SRC_HEALTH, k), el('span', { class: 'health-count', text: String(count(k)) }))));

    return [
      el('p', { class: 'small', text: list.length + ' fonte(s) cadastrada(s): ' + HEALTH_ORDER.map((k) => count(k) + ' ' + SRC_HEALTH[k][0].toLowerCase()).join(', ') + '.' }),
      sum,
      callout('info', 'i', el('p', { text: 'Falha não encerra vagas: fonte que falhou, foi bloqueada ou leu só em parte nunca fecha anúncios. Só leitura completa no mesmo escopo, duas vezes e com intervalo, pode indicar ausência. Zero vagas só é "ok" quando a leitura foi completa e com escopo comprovado.' })),
      el('div', { class: 'field fontes-sort' }, el('label', { for: 'fontes-sort', text: 'Ordenar por' }), sortSel),
      chips, holder,
    ];
  }

  function renderLogins(root, arg, ctx) {
    const body = el('div', { class: 'stack' });
    root.append(viewHead('Logins e candidaturas', 'Entre nas plataformas pelo Edge e acompanhe o que o JOBOS consegue executar.'),
      callout('info', 'i', el('p', { text: '1. Abra o portal no Edge. 2. Entre na sua conta (Candidato / Entrar / Sign in). 3. Volte a Vagas, confira a compatibilidade e gere o CV. 4. Envie na plataforma e registre a confirmação em Candidaturas.' })),
      callout('warn', '!', el('p', { text: 'Envio automático: não implementado neste motor. Sessão do Edge: não verificada pelo JOBOS. Abrir o portal não comprova login nem candidatura. SuccessFactors pode exigir uma conta por empresa; entrar na SBM não confirma acesso às demais.' })), body);
    fill(ctx, body, apiGet('/api/connections'), (data) => (data.connections || []).map((item) => {
      const message = el('p', { class: 'small', role: 'status' });
      const button = el('button', { class: 'btn', type: 'button', text: 'Entrar pelo Edge — ' + item.company });
      button.addEventListener('click', async () => {
        button.disabled = true;
        try {
          await apiPost('/api/connections/' + enc(item.source_id) + '/open', {});
          message.textContent = 'Portal aberto. Faça o login na janela do Edge; a sessão não é verificada automaticamente.';
        } catch (err) { message.textContent = err.message; }
        finally { button.disabled = false; }
      });
      return el('section', { class: 'section' }, el('h3', { text: item.company }),
        el('p', { text: item.platform + ' · sessão não verificada · envio pela plataforma' }),
        el('div', { class: 'actions' }, button, extLink(item.url, 'Abrir portal no navegador')), message);
    }), () => { root.replaceChildren(); renderLogins(root, arg, ctx); });
  }

  function renderFontes(root, arg, ctx) {
    const body = el('div', { class: 'stack' });
    root.append(viewHead('Fontes', 'Saúde e resultado da última coleta de cada empresa cadastrada.'), body);
    load();
    function load() { fill(ctx, body, apiGet('/api/sources'), (d) => sourcesNodes(d.sources || []), load); }
  }

  /* ======================================================================
   * Vagas (lista)
   * ====================================================================== */
  const JOB_DEFAULTS = { q: '', state: 'open', decision: '', location: '', talent: false, sort: 'priority', page: 1 };
  const jobsFilter = Object.assign({}, JOB_DEFAULTS);
  const PAGE_SIZE = 50;
  let jobsScroll = null;

  function jobCard(j) {
    const analyzed = !isEmpty(j.decision);
    const published = (j.published_brt || 'desconhecida') + (j.published_date_precision === 'relative_estimate' ? ' (estimada)' : '');
    const link = extLink(j.url, 'Anúncio oficial');
    const flags = Array.isArray(j.flags) ? j.flags : [];
    const score = el('details', { class: 'score-audit' });
    const auditBody = el('div', { class: 'score-audit-body' });
    score.append(el('summary', { text: 'Compatibilidade: ' + (isEmpty(j.fit_score) ? 'sem nota' : fmtNum(j.fit_score) + '%') + ' · ver critérios' }), auditBody);
    let loaded = false;
    score.addEventListener('toggle', async () => {
      if (!score.open || loaded) return;
      loaded = true;
      auditBody.replaceChildren(el('p', { text: 'Carregando critérios e evidências…' }));
      try {
        const detail = await apiGet('/api/jobs/' + enc(j.job_id));
        auditBody.replaceChildren(analysisSection(detail));
      } catch (err) {
        loaded = false;
        auditBody.replaceChildren(el('p', { text: 'Não foi possível carregar: ' + err.message + '. Feche e abra para tentar novamente.' }));
      }
    });

    const titleLink = el('a', { class: 'job-title', href: '#vaga/' + enc(j.job_id) }, j.title || '(sem título)');
    titleLink.addEventListener('click', () => { jobsScroll = window.scrollY; });

    return el('li', { class: 'job' },
      el('div', { class: 'job-top' },
        el('div', { class: 'job-main' }, el('div', { class: 'job-co', text: j.company_name }), titleLink),
        el('span', { class: 'small muted', text: 'cobertura ' + fmtPct(j.coverage) })),
      score,
      el('div', { class: 'tags' },
        analyzed ? badge(DECISION, j.decision) : tagBadge('Sem análise', '?', 'mute'),
        badge(LISTING, j.listing_state),
        j.location_label ? badge(LOCATION, j.location_label) : null,
        j.prep_label ? tagBadge(j.prep_label, '+', 'info') : null,
        j.talent_pool ? tagBadge('Banco de talentos', '○', 'mute') : null,
        j.role_fit && j.role_fit !== 'natural' ? tagBadge(text(ROLE_FIT, j.role_fit), '!', 'mute') : null,
        j.origin && j.origin !== 'observed' ? tagBadge('Origem: ' + text(ORIGIN, j.origin), '○', 'mute') : null),
      el('div', { class: 'meta-line' },
        el('span', { text: 'Local: ' + (j.location || 'não informado') + (j.workplace ? ' (' + text(WORKPLACE, j.workplace) + ')' : '') }),
        el('span', { text: 'Publicada: ' + published }),
        el('span', { text: 'Prioridade: ' + (isEmpty(j.priority) ? 'n/d' : fmtNum(j.priority)) }),
        link ? el('span', null, link) : null),
      flags.length ? el('ul', { class: 'flags', 'aria-label': 'Alertas desta vaga' }, flags.map((f) => el('li', { text: f }))) : null);
  }

  function renderVagas(root, arg, ctx) {
    const f = jobsFilter;
    const results = el('div', { class: 'stack' });
    let timer = null;
    let seq = 0;

    const q = el('input', {
      type: 'search', id: 'f-q', value: f.q, placeholder: 'Título, empresa ou local', autocomplete: 'off', maxlength: '120',
    });
    q.addEventListener('input', () => {
      f.q = q.value;
      clearTimeout(timer);
      timer = setTimeout(() => { if (ctx.alive()) { f.page = 1; load(); } }, 300);
    });

    const change = (key) => (v) => { f[key] = v; f.page = 1; load(); };
    const sState = select('f-state', [
      ['open', 'Abertas (ativas e ausentes)'], ['active', 'Ativas'], ['missing_unconfirmed', 'Ausentes não confirmadas'],
      ['closed_confirmed', 'Encerradas confirmadas'], ['unknown', 'Não verificadas'], ['all', 'Todas'],
    ], f.state, change('state'));
    const sDecision = select('f-decision', [
      ['', 'Todas as decisões'], ['good_fit', 'Boa aderência'], ['needs_review', 'Revisar'], ['weak_fit', 'Baixa aderência'],
      ['not_eligible', 'Lacuna obrigatória'], ['insufficient_data', 'Descrição insuficiente'],
    ], f.decision, change('decision'));
    const sLocation = select('f-location', [
      ['', 'Todos os locais'], ['preferred', 'Grande Rio'], ['accepted_secondary', 'Base secundária'], ['review', 'Revisar local'],
      ['remote', 'Remoto'], ['unknown', 'Local desconhecido'], ['outside_preference', 'Fora da preferência'],
    ], f.location, change('location'));
    const sSort = select('f-sort', [
      ['priority', 'Prioridade'], ['recent', 'Mais recentes (primeira observação)'], ['published', 'Data de publicação'], ['company', 'Empresa'],
    ], f.sort, change('sort'));
    const talent = el('input', { type: 'checkbox', id: 'f-talent', checked: f.talent });
    talent.addEventListener('change', () => { f.talent = talent.checked; f.page = 1; load(); });

    const reset = el('button', {
      type: 'button', class: 'btn',
      on: { click: () => { Object.assign(f, JOB_DEFAULTS); root.replaceChildren(); renderVagas(root, arg, ctx); } },
    }, 'Limpar filtros');

    const form = el('form', { class: 'filters', role: 'search', 'aria-label': 'Filtrar vagas', on: { submit: (e) => e.preventDefault() } },
      el('div', { class: 'field wide' }, el('label', { for: 'f-q', text: 'Buscar' }), q),
      field('f-state', 'Situação do anúncio', sState),
      field('f-decision', 'Decisão', sDecision),
      field('f-location', 'Local', sLocation),
      field('f-sort', 'Ordenar por', sSort),
      el('div', { class: 'check' }, talent, el('label', { for: 'f-talent', text: 'Incluir banco de talentos' })),
      el('div', null, reset));

    root.append(viewHead('Vagas', 'Vagas observadas, com a análise de aderência ao perfil.'), form, results);

    function pager(data, pages) {
      const go = (delta) => () => { f.page = Math.min(pages, Math.max(1, f.page + delta)); window.scrollTo(0, 0); load(); };
      return el('div', { class: 'pager' },
        el('button', { type: 'button', class: 'btn', disabled: data.page <= 1, on: { click: go(-1) } }, '← Anterior'),
        el('span', { class: 'small', text: 'Página ' + data.page + ' de ' + pages }),
        el('button', { type: 'button', class: 'btn', disabled: data.page >= pages, on: { click: go(1) } }, 'Próxima →'));
    }

    function jobsNodes(data, pages) {
      const items = Array.isArray(data.items) ? data.items : [];
      if (!items.length) {
        return [emptyBox('Nenhuma vaga com estes filtros. Tente "Todas" em situação do anúncio ou marque o banco de talentos.'),
          el('p', { class: 'footnote', text: SCORE_NOTE })];
      }
      return [
        el('p', { class: 'small muted', text: data.total + ' vaga(s) encontrada(s), ' + PAGE_SIZE + ' por página.' }),
        pager(data, pages),
        el('ul', { class: 'joblist' }, items.map(jobCard)),
        pager(data, pages),
        el('p', { class: 'footnote', text: SCORE_NOTE }),
      ];
    }

    function load() {
      const mine = ++seq;
      results.replaceChildren(loadingBox('Carregando vagas...'));
      const p = new URLSearchParams();
      if (f.q.trim()) p.set('q', f.q.trim().slice(0, 120));
      if (f.state !== 'all') p.set('state', f.state);
      if (f.decision) p.set('decision', f.decision);
      if (f.location) p.set('location', f.location);
      if (!f.talent) p.set('talent_pool', 'false'); // padrão: sem banco de talentos
      p.set('sort', f.sort);
      p.set('page', String(f.page));
      p.set('page_size', String(PAGE_SIZE));
      apiGet('/api/jobs?' + p.toString()).then((data) => {
        if (!ctx.alive() || mine !== seq) return;
        const pages = Math.max(1, Math.ceil(num(data.total) / (data.page_size || PAGE_SIZE)));
        if (num(data.total) > 0 && !(data.items || []).length && f.page > pages) {
          f.page = pages;
          load();
          return;
        }
        results.replaceChildren(...jobsNodes(data, pages));
        announce(num(data.total) + ' vaga(s) encontrada(s).');
        if (jobsScroll !== null) {
          const y = jobsScroll;
          jobsScroll = null;
          window.scrollTo(0, y);
        }
      }, (err) => {
        if (!ctx.alive() || mine !== seq) return;
        results.replaceChildren(errorBox(err, load));
      });
    }
    load();
  }

  /* ======================================================================
   * Detalhe da vaga
   * ====================================================================== */
  function listingBadge(state) { return badge(LISTING, state); }

  // Rótulo de um estado de evento conforme o eixo (preparação ou estágio).
  function axisState(axis, s) {
    if (isEmpty(s)) return null;
    if (axis === 'prep') return first(PREP, s);
    if (axis === 'stage') return first(STAGE, s);
    return String(s);
  }

  function eventsTimeline(events) {
    if (!events.length) return el('p', { class: 'muted', text: 'Sem eventos.' });
    return el('ol', { class: 'timeline' }, events.map((e) => {
      const from = axisState(e.axis, e.from_state);
      const to = axisState(e.axis, e.to_state);
      return el('li', null,
        el('div', { class: 'tl-head' },
          el('strong', { text: text(AXIS, e.axis) }),
          to ? el('span', { text: (from ? from + ' → ' : '→ ') + to }) : null,
          el('span', { class: 'tl-when', text: fmtDate(e.occurred_at) + ' · ' + text(ORIGIN, e.origin) })),
        e.reason ? el('p', { class: 'tl-reason', text: e.reason }) : null,
        e.proof ? el('p', { class: 'small muted', text: 'Prova: ' + e.proof }) : null);
    }));
  }

  function appFacts(app) {
    return kv([
      ['Preparação', badge(PREP, app.prep_state)],
      ['Conta como enviada', SUBMITTED.includes(app.prep_state)
        ? tagBadge('sim: ' + (app.prep_state === 'submitted_verified' ? 'prova da plataforma' : 'confirmação sua'), '✓', 'ok')
        : tagBadge('não', '✗', 'mute')],
      ['Estágio seletivo', badge(STAGE, app.selection_stage)],
      ['Procedência', text(ORIGIN, app.provenance)],
      app.submitted_at ? ['Data de envio', fmtDate(app.submitted_at, app.submitted_precision)] : null,
      app.legacy_status ? ['Status no legado', app.legacy_status] : null,
      app.legacy_source ? ['Fonte no legado', app.legacy_source] : null,
      app.legacy_date ? ['Data no legado', fmtDate(app.legacy_date)] : null,
      app.legacy_hint ? ['Pista no legado', app.legacy_hint] : null,
      app.notes ? ['Notas', app.notes] : null,
      ['Atualizada em', fmtDate(app.updated_at)],
    ]);
  }

  function applicationSection(data, flash, hooks) {
    const jobId = data.job.job_id;
    const app = data.application;
    const cur = app ? app.prep_state : 'discovered';
    const submitted = SUBMITTED.includes(cur);
    const events = data.application_events || [];
    const section = el('section', { class: 'section', 'aria-labelledby': 'sec-app' }, el('h3', { id: 'sec-app', text: 'Candidatura' }));

    if (data.duplicate_warning) {
      section.appendChild(callout('warn', '!', el('p', { text: data.duplicate_warning + ' O registro não é bloqueado.' })));
    }
    if (cur === 'legacy_needs_review') section.appendChild(callout('warn', '!', el('p', { text: LEGACY_EXPLAIN })));
    if (!app) {
      section.appendChild(el('p', { class: 'muted', text: 'Esta vaga ainda não tem registro de candidatura. A primeira ação registrada cria o registro a partir do estado Descoberta.' }));
    } else {
      section.appendChild(appFacts(app));
    }
    if (flash) {
      section.appendChild(el('p', { class: 'form-msg form-msg-ok', role: 'status', tabindex: '-1', text: flash }));
    }

    /* Ações: todas via POST com X-JOBOS (apiPost). O estado final vem sempre do servidor. */
    const errText = (err) => (err.status === 409 ? 'Recusado pelo servidor (409): ' : '') + err.message;

    function makeAction(o) {
      const msg = el('p', { class: 'form-msg form-msg-bad', role: 'alert', hidden: true });
      const show = (t) => { msg.textContent = t; msg.hidden = false; };
      const btn = el('button', { type: 'submit', class: 'btn btn-primary', disabled: !!o.disabled }, o.submitText);
      const form = el('form', { class: 'action', novalidate: '', 'aria-label': o.title },
        el('h4', { text: o.title }),
        o.intro ? el('p', { class: 'hint', text: o.intro }) : null,
        o.fields,
        o.note ? el('p', { class: 'hint', text: o.note }) : null,
        btn, msg);
      form.addEventListener('submit', async (ev) => {
        ev.preventDefault();
        msg.hidden = true;
        const payload = o.build();
        if (typeof payload === 'string') { show(payload); return; }
        if (o.confirmText && !window.confirm(o.confirmText(payload))) return;
        btn.disabled = true;
        try {
          await apiPost('/api/applications/' + enc(jobId) + '/events', payload);
        } catch (err) {
          show(errText(err));
          btn.disabled = false;
          return;
        }
        try {
          await hooks.reload(o.success);
        } catch (err) {
          show('A ação foi registrada, mas não consegui recarregar os dados: ' + err.message);
          btn.disabled = false;
        }
      });
      return form;
    }

    // 1) Confirmar envio manual
    const dateIn = el('input', { type: 'date', id: 'act-date', value: todayLocal(), max: todayLocal() });
    const confNote = el('textarea', { id: 'act-conf-note', rows: '2', maxlength: '2000' });
    const packets = Array.isArray(data.cv_packets) ? data.cv_packets : [];
    const htmlArt = packets.find((p) => p.kind === 'cv_html');
    const shaIn = el('input', { type: 'text', id: 'act-sha', maxlength: '64', autocomplete: 'off', spellcheck: 'false',
      value: htmlArt && htmlArt.sha256 ? String(htmlArt.sha256) : '' });
    const proofIn = el('textarea', { id: 'act-proof', rows: '2', maxlength: '500' });
    const confirmForm = makeAction({
      title: 'Registrar envio',
      intro: 'Use depois de enviar no site oficial. O registro fica como declaração sua, sem prova da plataforma.',
      fields: [
        field('act-date', 'Data do envio', dateIn),
        field('act-conf-note', 'Observação (opcional)', confNote),
        field('act-sha', 'SHA-256 do currículo usado (opcional)', shaIn, '64 caracteres hexadecimais do cv.html que você anexou. O painel liga esse arquivo a este envio.'),
        field('act-proof', 'Texto de confirmação da plataforma (opcional)', proofIn, 'Código ou frase que o site mostrou depois do envio. O painel grava só o hash desse texto.'),
      ],
      note: !submitted && !(PREP_TRANSITIONS[cur] || []).includes('submitted_manual')
        ? 'Pelas regras atuais, o estado ' + first(PREP, cur) + ' não permite confirmar envio; o servidor deve recusar. Mude o estado antes.' : null,
      submitText: 'Registrar envio',
      disabled: submitted,
      build: () => {
        if (!dateIn.value) return 'Informe a data do envio.';
        const body = { action: 'confirm', date: dateIn.value };
        if (confNote.value.trim()) body.reason = confNote.value.trim();
        const sha = shaIn.value.trim().toLowerCase();
        if (sha) {
          if (!/^[0-9a-f]{64}$/.test(sha)) return 'O SHA do currículo precisa ter 64 caracteres hexadecimais.';
          body.artifact_sha256 = sha;
        }
        if (proofIn.value.trim()) body.confirmation = proofIn.value.trim();
        return body;
      },
      confirmText: (p) => 'Confirmar que você enviou esta candidatura em ' + fmtDate(p.date) + '? Será registrado como declaração sua, não como prova da plataforma.',
      success: 'Envio manual registrado como declaração sua (sem prova da plataforma).',
    });
    if (submitted) {
      confirmForm.appendChild(el('p', { class: 'hint', text: 'Esta candidatura já consta como enviada (' + first(PREP, cur) + ').' }));
    }

    // 2) Mudar estado
    const targetOpts = [['', 'Selecione o novo estado']].concat(TRANSITION_TARGETS.map((t) => {
      const allowed = (PREP_TRANSITIONS[cur] || []).includes(t);
      return [t, first(PREP, t) + (t === cur ? ' (estado atual)' : allowed ? '' : ' (não permitido agora)'), !allowed];
    }));
    const trSel = select('act-target', targetOpts, '');
    const trReason = el('textarea', { id: 'act-tr-reason', rows: '2', maxlength: '2000' });
    const transitionForm = makeAction({
      title: 'Mudar estado',
      fields: [field('act-target', 'Novo estado', trSel), field('act-tr-reason', 'Motivo (obrigatório)', trReason)],
      submitText: 'Mudar estado',
      build: () => {
        if (!trSel.value) return 'Escolha o novo estado.';
        if (!trReason.value.trim()) return 'Informe o motivo da mudança.';
        return { action: 'transition', target: trSel.value, reason: trReason.value.trim() };
      },
      success: 'Estado alterado.',
    });

    // 3) Estágio seletivo
    const stSel = select('act-stage', [['', 'Selecione o estágio']].concat(STAGE_TARGETS.map((s) => [s, s === 'none' ? 'Nenhum (limpar o estágio)' : first(STAGE, s)])), '');
    const stReason = el('input', { type: 'text', id: 'act-st-reason', maxlength: '2000', autocomplete: 'off' });
    const stageForm = makeAction({
      title: 'Estágio seletivo',
      intro: 'Etapa do processo seletivo. Independe de a candidatura estar enviada.',
      fields: [field('act-stage', 'Estágio', stSel), field('act-st-reason', 'Observação (opcional)', stReason)],
      submitText: 'Registrar estágio',
      build: () => {
        if (!stSel.value) return 'Escolha o estágio.';
        const body = { action: 'stage', target: stSel.value };
        if (stReason.value.trim()) body.reason = stReason.value.trim();
        return body;
      },
      success: 'Estágio registrado.',
    });

    // 4) Nota
    const noteIn = el('textarea', { id: 'act-note', rows: '3', maxlength: '2000' });
    const noteForm = makeAction({
      title: 'Nota',
      fields: [field('act-note', 'Texto da nota', noteIn)],
      submitText: 'Registrar nota',
      build: () => (noteIn.value.trim() ? { action: 'note', reason: noteIn.value.trim() } : 'Escreva a nota.'),
      success: 'Nota registrada.',
    });

    section.appendChild(el('div', { class: 'actions' }, confirmForm, transitionForm, stageForm, noteForm));
    section.appendChild(el('h4', { text: 'Histórico da candidatura' }));
    section.appendChild(eventsTimeline(events));
    return section;
  }

  function supportSection(data) {
    const section = el('section', { class: 'section', 'aria-labelledby': 'sec-prep' },
      el('h3', { id: 'sec-prep', text: 'Preparo para esta vaga' }));
    const mount = window.JobosPreparo && typeof window.JobosPreparo.mount === 'function'
      ? window.JobosPreparo.mount : null;
    if (!data.support || !mount) {
      section.appendChild(el('p', { class: 'muted', text: 'Preparo indisponível neste carregamento.' }));
      return section;
    }
    mount(section, data.support);
    return section;
  }

  function analysisSection(data) {
    const section = el('section', { class: 'section', 'aria-label': 'Análise de aderência' }, el('h3', { text: 'Análise de aderência' }));
    const an = data.analysis;
    if (!an) {
      section.appendChild(el('p', { class: 'muted', text: 'Sem análise para a versão atual desta vaga.' }));
      return section;
    }
    const prefs = an.preferences || {};
    const prio = an.priority || {};
    const reqs = Array.isArray(an.requirements) ? an.requirements : [];

    section.appendChild(el('div', { class: 'tags' }, badge(DECISION, an.decision, { wrap: true }), el('span', { text: an.decision_reason || '' })));
    section.appendChild(kv([
      ['Nota', isEmpty(an.fit_score) ? 'sem nota (cobertura insuficiente)' : fmtNum(an.fit_score)],
      ['Cobertura', fmtPct(an.coverage)],
      ['Nota só dos itens avaliáveis', isEmpty(an.known_items_score) ? 'n/d' : fmtNum(an.known_items_score) + ' (informativa, sem cobertura mínima)'],
      ['Confiança', text(CONFIDENCE, an.confidence)],
      ['Política e método', (an.policy_version || 'n/d') + ' · ' + (an.method || 'n/d')],
      an.extraction ? ['Extração de requisitos', (an.extraction.method || 'n/d') + ', ' + reqs.length + ' requisito(s)'] : null,
    ]));
    section.appendChild(el('p', { class: 'footnote', text: SCORE_NOTE }));
    const audit = an.score_audit;
    if (audit) section.appendChild(kv([
      ['Fórmula', audit.formula], ['Pontos obtidos / peso total', fmtNum(audit.earned_points) + ' / ' + fmtNum(audit.total_weight)],
      ['Antes dos bloqueios', isEmpty(audit.before_gates) ? 'sem nota' : fmtNum(audit.before_gates) + '%'],
      ['Teto aplicado', isEmpty(audit.cap) ? 'nenhum' : fmtNum(audit.cap) + '%'],
      ['Motivo da decisão', audit.gate_reason],
      ['Família principal / secundária', an.family ? (an.family.primary || 'fora das famílias') + ' / ' + (an.family.secondary || 'nenhuma') : 'não classificada'],
      ['Regra de evidência', 'Atendido = 1; parcial = 0,5; lacuna/desconhecido = 0. Domínio relacionado não comprova experiência integral.'],
    ]));

    // Preferências
    section.appendChild(el('h4', { text: 'Preferências' }));
    const rf = prefs.role_fit || {};
    section.appendChild(kv([
      ['Local', el('div', null, has(LOCATION, prefs.location_label) ? badge(LOCATION, prefs.location_label) : 'n/d', prefs.location_reason ? el('div', { class: 'small muted', text: prefs.location_reason }) : null)],
      ['Função', el('div', null, text(ROLE_FIT, rf.label), rf.reason ? el('div', { class: 'small muted', text: rf.reason }) : null)],
      ['Salário', prefs.salary || 'não informado'],
      ['Banco de talentos', yesNo(prefs.talent_pool)],
      ['Empregador excluído por preferência', yesNo(prefs.excluded_employer)],
    ]));
    const flags = Array.isArray(prefs.flags) ? prefs.flags : [];
    section.appendChild(flags.length ? list(flags) : el('p', { class: 'muted', text: 'Sem alertas de preferência.' }));

    // Prioridade
    section.appendChild(el('h4', { text: 'Prioridade operacional' }));
    const comps = prio.components && typeof prio.components === 'object' ? prio.components : {};
    section.appendChild(kv([['Total', fmtNum(prio.total)]].concat(Object.keys(comps).map((k) => [
      text(PRIORITY_PART, k), (comps[k] > 0 ? '+' : '') + fmtNum(comps[k])])), 'kv-tight'));
    if (prio.note) section.appendChild(el('p', { class: 'small muted', text: prio.note }));
    if (prio.explanation) section.appendChild(el('p', { class: 'small muted', text: prio.explanation }));

    // Requisitos
    section.appendChild(el('h4', { text: 'Requisitos (' + reqs.length + ')' }));
    if (!reqs.length) {
      section.appendChild(el('p', { class: 'muted', text: 'Nenhum requisito extraído automaticamente.' }));
    } else {
      section.appendChild(makeTable([
        { label: 'Requisito' }, { label: 'Importância' }, { label: 'Categoria' }, { label: 'Status' },
        { label: 'Peso × valor = pontos' }, { label: 'Explicação' }, { label: 'Evidências' },
      ], reqs.map((r) => [
        el('span', { text: r.text || '' }),
        text(IMPORTANCE, r.importance),
        text(CATEGORY, r.category),
        badge(REQ_STATUS, r.status),
        isEmpty(r.weight) ? 'n/d' : r.weight + ' × ' + r.value + ' = ' + (r.weight * r.value).toFixed(3),
        r.explanation || 'n/d',
        Array.isArray(r.evidence_refs) && r.evidence_refs.length
          ? el('ul', { class: 'list-bare' }, r.evidence_refs.map((e) => el('li', null,
            code(e.pointer), e.label ? el('span', { class: 'small muted', text: ' ' + e.label + (e.qualifier ? ' (' + e.qualifier + ')' : '') }) : null)))
          : el('span', { class: 'muted', text: 'sem evidência' }),
      ]), 'Requisitos da vaga e situação de cada um'));
    }

    // Pontos fortes, lacunas e desconhecidos
    const bucket = (title, items) => el('div', null, el('h4', { text: title }),
      Array.isArray(items) && items.length ? list(items) : el('p', { class: 'muted', text: 'Nenhum.' }));
    section.appendChild(el('div', { class: 'cols' }, bucket('Pontos fortes', an.strengths), bucket('Lacunas', an.gaps), bucket('Desconhecidos', an.unknowns)));

    section.appendChild(el('h4', { text: 'Próxima ação sugerida' }));
    section.appendChild(el('p', { text: an.next_action || 'n/d' }));
    section.appendChild(el('p', { class: 'small muted', text: an.limitations || '' }));

    const hist = Array.isArray(data.analysis_history) ? data.analysis_history : [];
    if (hist.length > 1) {
      section.appendChild(el('details', null,
        el('summary', { text: 'Histórico de análises (' + hist.length + ')' }),
        makeTable([{ label: 'Criada em' }, { label: 'Decisão' }, { label: 'Nota', num: true }, { label: 'Cobertura', num: true }, { label: 'Política' }],
          hist.map((h) => [fmtDate(h.created_at), badge(DECISION, h.decision), isEmpty(h.fit_score) ? 'sem nota' : fmtNum(h.fit_score), fmtPct(h.coverage), h.policy_version || 'n/d']),
          'Histórico de análises')));
    }
    return section;
  }

  function datesSection(job) {
    return el('section', { class: 'section', 'aria-labelledby': 'sec-dates' },
      el('h3', { id: 'sec-dates', text: 'Datas e origem' }),
      kv([
        ['Publicada', job.published_brt || 'desconhecida'],
        ['Precisão da data de publicação', text(PRECISION, job.published_date_precision)],
        ['Fonte da data de publicação', job.published_date_source || 'n/d'],
        ['Texto original da data', isEmpty(job.published_raw) ? 'n/d' : code(job.published_raw)],
        ['Primeira observação', fmtDate(job.first_seen_at, job.first_seen_precision)],
        ['Precisão da primeira observação', text(PRECISION, job.first_seen_precision)],
        ['Fonte da primeira observação', job.first_seen_source || 'n/d'],
        ['Última observação', fmtDate(job.last_seen_at)],
        ['Importada em', fmtDate(job.imported_at)],
        job.content_changed_at ? ['Conteúdo alterado em', fmtDate(job.content_changed_at)] : null,
        job.closed_at ? ['Encerrada em', fmtDate(job.closed_at) + (job.close_reason ? ' (' + job.close_reason + ')' : '')] : null,
        ['Origem do registro', text(ORIGIN, job.origin)],
      ]));
  }

  function postingsSection(postings) {
    const sec = el('section', { class: 'section', 'aria-labelledby': 'sec-post' }, el('h3', { id: 'sec-post', text: 'Anúncios nas fontes' }));
    if (!postings.length) {
      sec.appendChild(el('p', { class: 'muted', text: 'Nenhum anúncio de fonte vinculado (vaga importada do legado).' }));
      return sec;
    }
    sec.appendChild(makeTable([
      { label: 'Fonte' }, { label: 'Plataforma' }, { label: 'ID externo' }, { label: 'Estado' },
      { label: 'Primeira vez' }, { label: 'Última vez' }, { label: 'Ausências' }, { label: 'Página oficial' },
    ], postings.map((p) => [
      p.source_id, p.platform, p.external_id ? code(p.external_id) : 'n/d', listingBadge(p.posting_state),
      fmtDate(p.first_seen_at), fmtDate(p.last_seen_at),
      num(p.missing_count) ? p.missing_count + ' desde ' + fmtDate(p.missing_since) : '0',
      extLink(p.url, 'Abrir página oficial') || el('span', { class: 'muted', text: 'sem link válido' }),
    ]), 'Anúncios da vaga nas fontes'));
    return sec;
  }

  function descriptionSection(data) {
    const job = data.job;
    const cur = (data.versions || []).find((v) => v.version_id === job.current_version_id) || null;
    const sec = el('section', { class: 'section', 'aria-labelledby': 'sec-desc' }, el('h3', { id: 'sec-desc', text: 'Descrição atual do anúncio' }));
    if (!cur) {
      sec.appendChild(el('p', { class: 'muted', text: 'Sem versão atual registrada.' }));
      return sec;
    }
    sec.appendChild(kv([
      ['Estado da descrição', text(DESC_STATUS, cur.description_status)],
      ['Tamanho', num(cur.description_length) + ' caracteres' + (cur.original_length && cur.original_length !== cur.description_length ? ' (original: ' + cur.original_length + ')' : '')],
      cur.truncation_note ? ['Nota de truncamento', cur.truncation_note] : null,
      ['Versão observada em', fmtDate(cur.observed_at)],
    ]));
    if (cur.description_status && cur.description_status !== 'full') {
      sec.appendChild(callout('warn', '!', el('p', { text: 'A descrição não está completa. Confira o anúncio oficial antes de decidir.' })));
    }
    sec.appendChild(el('p', { class: 'small muted', text: 'O texto abaixo vem do anúncio (dado externo) e é exibido como texto simples.' }));
    if (cur.description) {
      sec.appendChild(el('pre', { class: 'desc', tabindex: '0', 'aria-label': 'Texto da descrição da vaga', text: cur.description }));
    } else {
      sec.appendChild(el('p', { class: 'muted', text: 'Esta versão não tem texto de descrição.' }));
    }
    return sec;
  }

  function versionsSection(data) {
    const versions = data.versions || [];
    const sec = el('section', { class: 'section', 'aria-labelledby': 'sec-ver' }, el('h3', { id: 'sec-ver', text: 'Versões do anúncio (' + versions.length + ')' }));
    if (!versions.length) {
      sec.appendChild(el('p', { class: 'muted', text: 'Nenhuma versão registrada.' }));
      return sec;
    }
    sec.appendChild(makeTable([
      { label: 'Observada em' }, { label: 'Origem' }, { label: 'Fonte' }, { label: 'Título' },
      { label: 'Descrição' }, { label: 'Tamanho', num: true }, { label: 'Situação' },
    ], versions.map((v) => [
      fmtDate(v.observed_at), text(ORIGIN, v.origin), v.source_id || 'n/d', v.title || 'n/d',
      text(DESC_STATUS, v.description_status), String(num(v.description_length)),
      v.version_id === data.job.current_version_id ? tagBadge('atual', '✓', 'ok') : el('span', { class: 'muted', text: 'anterior' }),
    ]), 'Versões do anúncio'));
    return sec;
  }

  function jobEventsSection(events) {
    const sec = el('section', { class: 'section', 'aria-labelledby': 'sec-ev' }, el('h3', { id: 'sec-ev', text: 'Eventos da vaga (' + events.length + ')' }));
    if (!events.length) {
      sec.appendChild(el('p', { class: 'muted', text: 'Nenhum evento.' }));
      return sec;
    }
    sec.appendChild(el('ol', { class: 'timeline' }, events.map((e) => {
      const payload = parseJson(e.payload_json);
      return el('li', null,
        el('div', { class: 'tl-head' },
          el('strong', { text: text(EVENT_KIND, e.kind) }),
          el('span', { class: 'tl-when', text: fmtDate(e.occurred_at) + ' · ' + text(ORIGIN, e.origin) }),
          e.run_id ? el('a', { class: 'small', href: '#execucoes/' + enc(e.run_id) }, 'execução ', code(String(e.run_id).slice(0, 12))) : null),
        payload && typeof payload === 'object' && Object.keys(payload).length
          ? el('details', null, el('summary', { text: 'Dados do evento' }), el('pre', { class: 'code', text: JSON.stringify(payload, null, 2) })) : null);
    })));
    return sec;
  }

  function legacySection(data) {
    const refs = data.legacy_refs || [];
    const rels = data.relations || [];
    if (!refs.length && !rels.length) return null;
    const sec = el('section', { class: 'section', 'aria-labelledby': 'sec-leg' }, el('h3', { id: 'sec-leg', text: 'Referências legadas e relações' }));
    if (refs.length) {
      sec.appendChild(makeTable([{ label: 'Origem' }, { label: 'ID no legado' }, { label: 'Regra de vínculo' }],
        refs.map((r) => [text(ORIGIN, r.origin), code(r.legacy_id), r.rule || 'n/d']), 'Referências legadas'));
    }
    if (rels.length) {
      sec.appendChild(el('h4', { text: 'Possíveis repetições (sugeridas pelo sistema)' }));
      sec.appendChild(el('ul', { class: 'list-bare' }, rels.map((r) => {
        const other = r.a_job_id === data.job.job_id ? r.b_job_id : r.a_job_id;
        return el('li', null,
          el('a', { href: '#vaga/' + enc(other) }, 'Ver a outra vaga ', code(String(other).slice(0, 8))),
          ' · ' + (r.kind === 'possible_repost' ? 'possível republicação' : 'possível duplicata') + ' · status: ' + r.status,
          r.reason ? el('div', { class: 'small muted', text: r.reason }) : null);
      })));
    }
    return sec;
  }

  const CV_KIND = { cv_html: 'Currículo (HTML)', cv_data: 'Dados do currículo', cv_validation: 'Validação de fatos', cv_answers: 'Respostas', cv_coverage: 'Auditoria ATS: requisito → evidência → trecho do CV' };

  function applyBadges(apply) {
    const a = apply || {};
    const out = [];
    if (a.quick_apply === true) out.push(tagBadge('Gupy: candidatura rápida', '○', 'info'));
    else if (a.quick_apply === false) out.push(tagBadge('Gupy: formulário completo', '○', 'mute'));
    if (a.apply_mode && a.apply_mode !== 'unknown') out.push(tagBadge('Candidatura: ' + a.apply_mode, '○', 'info'));
    if (a.whatsapp === true) out.push(tagBadge('WhatsApp no anúncio', '!', 'warn'));
    (Array.isArray(a.apply_options) ? a.apply_options : []).forEach((opt) => {
      if (opt && opt !== 'unknown' && opt !== 'apply_now') out.push(tagBadge(String(opt), '○', 'mute'));
    });
    return out;
  }

  function cvSection(data, onGenerate) {
    const packets = Array.isArray(data.cv_packets) ? data.cv_packets : [];
    const section = el('section', { class: 'section', 'aria-labelledby': 'sec-cv' },
      el('h3', { id: 'sec-cv', text: 'Currículo' }));
    section.appendChild(callout('info', 'i', el('p', { text: 'Revise o currículo. Candidatar abre o formulário oficial no seu navegador. Quem envia é você. Depois use Registrar envio.' })));
    const kc = data.keyword_coverage;
    if (kc) {
      section.appendChild(el('p', { text: 'Termos do anúncio já no currículo: ' + num(kc.present_count) +
        '. No perfil e não escolhidos: ' + num(kc.available_not_chosen_count) +
        '. Ausentes do perfil: ' + num(kc.absent_from_profile_count) + '. ' + (kc.note || 'Nada foi inserido.') }));
    }
    if (packets.length) {
      section.appendChild(el('ul', { class: 'list-bare' }, packets.map((p) => el('li', null,
        el('a', { href: '/api/artifacts/' + enc(p.artifact_id) + '/download', target: '_blank', rel: 'noopener noreferrer' },
          CV_KIND[p.kind] || p.kind),
        el('span', { class: 'small muted', text: ' · ' + String(p.sha256 || '').slice(0, 12) })))));
    } else {
      section.appendChild(el('p', { class: 'muted', text: 'Nenhum currículo gerado para esta vaga.' }));
    }
    const msg = el('p', { class: 'form-msg', role: 'status', hidden: true });
    const href = applyHref(data);
    const applyBtn = href
      ? el('a', { class: 'btn btn-primary', href, target: '_blank', rel: 'noopener noreferrer' }, 'Candidatar',
        el('span', { class: 'sr-only', text: ' (abre o formulário oficial em nova aba)' }))
      : el('span', { class: 'muted', text: 'Esta vaga não tem link de candidatura.' });
    const btn = el('button', { type: 'button', class: 'btn' }, 'Gerar currículo');
    btn.addEventListener('click', async () => {
      msg.hidden = true;
      btn.disabled = true;
      btn.textContent = 'Gerando...';
      try {
        await onGenerate();
      } catch (err) {
        msg.className = 'form-msg form-msg-bad';
        msg.textContent = err && err.message ? err.message : 'Não foi possível gerar o currículo.';
        msg.hidden = false;
        btn.disabled = false;
        btn.textContent = 'Gerar currículo';
      }
    });
    section.appendChild(el('div', { class: 'actions' }, applyBtn, btn, msg));
    return section;
  }

  function renderVaga(root, jobId, ctx) {
    if (!jobId) { location.hash = '#vagas'; return; }
    const backHash = lastListHash || '#vagas';
    const backText = backHash.startsWith('#candidaturas') ? '← Voltar às candidaturas'
      : backHash.startsWith('#vagas') ? '← Voltar às vagas' : '← Voltar';
    const title = el('h2', { tabindex: '-1', text: 'Detalhe da vaga' });
    const head = el('div', { class: 'detail-head' },
      el('div', null, el('a', { class: 'btn btn-sm', href: backHash }, backText)),
      title);
    const body = el('div', { class: 'stack' });
    root.append(head, body);
    load();

    function load() {
      fill(ctx, body, apiGet('/api/jobs/' + enc(jobId)), build, load);
    }

    function build(data) {
      const job = data.job;
      title.textContent = job.title || '(sem título)';
      document.title = 'Painel JOBOS | ' + (job.title || 'Vaga');
      const official = (data.postings || []).map((p) => extLink(p.url, 'Abrir página oficial')).find(Boolean);
      const apply = data.apply || {};
      const applyLink = extLink(apply.apply_url, 'Abrir candidatura');

      while (head.children.length > 2) head.removeChild(head.lastChild);
      head.appendChild(el('p', { class: 'muted', text: [job.company_name, job.location, job.workplace ? text(WORKPLACE, job.workplace) : null].filter(Boolean).join(' · ') }));
      head.appendChild(el('div', { class: 'tags' },
        listingBadge(job.listing_state),
        job.talent_pool ? tagBadge('Banco de talentos', '○', 'mute') : null,
        job.is_fixture ? tagBadge('Dado de teste (fixture)', '!', 'warn') : null,
        ...applyBadges(apply),
        official || null,
        applyLink || null));

      const hooks = {
        reload: async (flash) => {
          const fresh = await apiGet('/api/jobs/' + enc(jobId));
          if (!ctx.alive()) return;
          const next = applicationSection(fresh, flash, hooks);
          appSlot.replaceWith(next);
          appSlot = next;
          announce(flash);
          const f = next.querySelector('.form-msg-ok');
          if (f) f.focus();
        },
      };
      let appSlot = applicationSection(data, null, hooks);

      async function generateCv() {
        const res = await apiPost('/api/jobs/' + enc(job.job_id) + '/cv', {});
        const html = (Array.isArray(res.artifacts) ? res.artifacts : []).find((a) => a.kind === 'cv_html');
        if (html) {
          const a = el('a', { href: '/api/artifacts/' + enc(html.artifact_id) + '/download', target: '_blank', rel: 'noopener noreferrer' });
          document.body.appendChild(a);
          a.click();
          a.remove();
        }
        const kc = res.keyword_coverage;
        announce('Currículo gerado. A candidatura não foi enviada.' + (kc
          ? ' Termos já no currículo: ' + num(kc.present_count) + '. No perfil e não escolhidos: ' + num(kc.available_not_chosen_count) + '. Ausentes do perfil: ' + num(kc.absent_from_profile_count) + '.'
          : ''));
        load();
      }

      return [cvSection(data, generateCv), appSlot, supportSection(data), analysisSection(data), datesSection(job),
        postingsSection(data.postings || []), descriptionSection(data), versionsSection(data),
        jobEventsSection(data.events || []), legacySection(data)].filter(Boolean);
    }
  }

  /* ======================================================================
   * Candidaturas
   * ====================================================================== */
  function applicationCard(a) {
    const events = Array.isArray(a.events) ? a.events : [];
    return el('li', { class: 'job' },
      el('div', { class: 'job-top' },
        el('div', { class: 'job-main' },
          el('div', { class: 'job-co', text: a.company_name }),
          el('a', { class: 'job-title', href: '#vaga/' + enc(a.job_id) }, a.title || '(sem título)')),
        el('a', { class: 'btn btn-sm', href: '#vaga/' + enc(a.job_id) }, a.prep_state === 'legacy_needs_review' ? 'Abrir e decidir' : 'Abrir detalhe')),
      el('div', { class: 'tags' },
        badge(PREP, a.prep_state),
        badge(STAGE, a.selection_stage),
        a.counts_as_submitted ? tagBadge('Conta como enviada', '✓', 'ok') : tagBadge('Não conta como enviada', '✗', 'mute'),
        badge(LISTING, a.listing_state)),
      kv([
        ['Procedência', text(ORIGIN, a.provenance)],
        a.submitted_at ? ['Data de envio', fmtDate(a.submitted_at, a.submitted_precision)] : null,
        a.legacy_source ? ['Fonte no legado', a.legacy_source] : null,
        a.legacy_date ? ['Data no legado', fmtDate(a.legacy_date)] : null,
        a.legacy_hint ? ['Pista no legado', a.legacy_hint] : null,
        a.location ? ['Local', a.location] : null,
      ]),
      a.url && safeUrl(a.url) ? el('p', { class: 'small' }, extLink(a.url, 'Anúncio oficial')) : null,
      events.length
        ? el('details', null, el('summary', { text: 'Histórico (' + events.length + ')' }), eventsTimeline(events))
        : el('p', { class: 'small muted', text: 'Sem eventos registrados.' }));
  }

  function applicationsNodes(data) {
    const items = Array.isArray(data.items) ? data.items : [];
    const legacy = items.filter((a) => a.prep_state === 'legacy_needs_review');
    const others = items.filter((a) => a.prep_state !== 'legacy_needs_review');
    const out = [];
    if (legacy.length) {
      out.push(el('section', { class: 'card card-legacy', 'aria-labelledby': 'sec-legacy' },
        el('h3', { id: 'sec-legacy', text: 'Procedência legada a revisar (' + legacy.length + ')' }),
        el('p', { text: LEGACY_EXPLAIN }),
        el('ul', { class: 'joblist' }, legacy.map(applicationCard))));
    } else if (items.length) {
      out.push(callout('ok', '✓', el('p', { text: 'Nenhum registro legado aguardando revisão de procedência.' })));
    }
    out.push(el('section', { 'aria-labelledby': 'sec-apps' },
      el('h3', { id: 'sec-apps', text: 'Candidaturas (' + others.length + ')' }),
      others.length ? el('ul', { class: 'joblist' }, others.map(applicationCard))
        : emptyBox(items.length ? 'Nenhuma outra candidatura além das legadas.' : 'Nenhuma candidatura registrada ainda. Abra uma vaga e use Mudar estado ou Confirmar envio manual.')));
    return out;
  }

  function renderCandidaturas(root, arg, ctx) {
    const body = el('div', { class: 'stack' });
    root.append(viewHead('Candidaturas', 'Só conta como enviada o que você confirmou ou o que a plataforma comprovou.'), body);
    load();
    function load() { fill(ctx, body, apiGet('/api/applications'), applicationsNodes, load); }
  }

  /* ======================================================================
   * Execuções
   * ====================================================================== */
  const RUN_COLS = [
    { label: 'Início (Brasília)' }, { label: 'Gatilho' }, { label: 'Modo' }, { label: 'Etapa' },
    { label: 'Status' }, { label: 'Duração' }, { label: 'Erro' }, { label: 'Detalhe' },
  ];

  function modeBadge(mode) {
    if (mode === 'fixtures') return tagBadge('Fixtures: dados de teste', '!', 'warn');
    if (mode === 'dry_run') return tagBadge('Simulação (dry-run)', '○', 'info');
    return el('span', { text: text(MODE, mode) });
  }

  function runDetailNodes(d, runId) {
    const run = d.run || {};
    const sources = Array.isArray(d.sources) ? d.sources : [];
    const counts = parseJson(run.counts_json);
    const nodes = [
      kv([
        ['Execução', code(run.run_id)],
        ['Status', badge(RUN_STATUS, run.status)],
        ['Gatilho', text(TRIGGER, run.trigger)],
        ['Modo', modeBadge(run.mode)],
        ['Início (Brasília)', fmtDate(run.started_at)],
        ['Fim (Brasília)', run.finished_at ? fmtDate(run.finished_at) : 'em andamento ou sem registro'],
        ['Duração', fmtDuration(run.started_at, run.finished_at)],
        ['Etapa', run.stage],
        ['Código de saída', isEmpty(run.exit_code) ? 'n/d' : String(run.exit_code)],
        run.error ? ['Erro', run.error] : null,
      ]),
    ];
    if (counts && typeof counts === 'object') {
      nodes.push(el('details', null, el('summary', { text: 'Contagens da execução' }), el('pre', { class: 'code', text: JSON.stringify(counts, null, 2) })));
    }
    nodes.push(el('h4', { text: 'Fontes desta execução (' + sources.length + ')' }));
    if (!sources.length) {
      nodes.push(emptyBox('Nenhuma fonte registrada nesta execução.'));
    } else {
      nodes.push(makeTable([
        { label: 'Fonte' }, { label: 'Status' }, { label: 'Itens', num: true }, { label: 'Novas', num: true },
        { label: 'Alteradas', num: true }, { label: 'Ausentes', num: true }, { label: 'Encerradas', num: true },
        { label: 'Ausência aplicada' }, { label: 'Páginas' }, { label: 'Erro' }, { label: 'Avisos' },
      ], sources.map((s) => {
        const warnings = parseJson(s.warnings_json);
        const wl = Array.isArray(warnings) ? warnings : warnings ? [warnings] : [];
        return [
          [el('span', { class: 'cell-title', text: s.source_id }), el('span', { class: 'cell-sub', text: (s.adapter || 'sem leitor') + (s.coverage_kind ? ' · ' + text(COVERAGE_KIND, s.coverage_kind) : '') })],
          badge(SRC_STATUS, s.status),
          String(num(s.normalized_count)), String(num(s.new_count)), String(num(s.changed_count)),
          String(num(s.missing_count)), String(num(s.closed_count)),
          yesNo(s.absence_applied),
          isEmpty(s.pages_expected) ? 'n/d' : num(s.pages_received) + ' de ' + s.pages_expected,
          s.error_code || s.error_message
            ? el('span', null, el('strong', { text: s.error_code || '' }), s.error_code && s.error_message ? ': ' : '', s.error_message || '')
            : el('span', { class: 'muted', text: 'nenhum' }),
          wl.length ? list(wl.map((w) => (typeof w === 'string' ? w : JSON.stringify(w)))) : el('span', { class: 'muted', text: 'nenhum' }),
        ];
      }), 'Fontes da execução ' + runId));
    }
    return nodes;
  }

  function renderExecucoes(root, runId, ctx) {
    const detail = el('div', { class: 'stack' });
    const listHolder = el('div', { class: 'stack' });
    const children = [viewHead('Execuções', 'Ciclos de coleta mais recentes, com o resultado por fonte.')];
    if (runId) {
      children.push(el('section', { class: 'section', 'aria-labelledby': 'sec-run' },
        el('div', { class: 'card-title-row' }, el('h3', { id: 'sec-run', text: 'Detalhe da execução' }),
          el('a', { class: 'btn btn-sm', href: '#execucoes' }, 'Fechar detalhe')),
        detail));
    }
    children.push(listHolder);
    root.append(...children);

    if (runId) loadDetail();
    loadList();

    function loadDetail() {
      fill(ctx, detail, apiGet('/api/runs/' + enc(runId)), (d) => runDetailNodes(d, runId), loadDetail);
    }
    function loadList() {
      fill(ctx, listHolder, apiGet('/api/runs'), (d) => {
        const items = Array.isArray(d.items) ? d.items : [];
        if (!items.length) return emptyBox('Nenhuma execução registrada ainda.');
        return [
          callout('info', 'i', el('p', { text: 'Execuções em modo Fixtures ou Simulação não usam vagas reais.' })),
          makeTable(RUN_COLS, items.map((r) => [
            fmtDate(r.started_at), text(TRIGGER, r.trigger), modeBadge(r.mode), r.stage || 'n/d', badge(RUN_STATUS, r.status),
            fmtDuration(r.started_at, r.finished_at),
            r.error ? el('span', { title: r.error, text: truncate(r.error, 80) }) : el('span', { class: 'muted', text: 'nenhum' }),
            el('a', { class: 'btn btn-sm', href: '#execucoes/' + enc(r.run_id), 'aria-current': r.run_id === runId ? 'true' : null, 'aria-label': 'Ver fontes da execução de ' + fmtDate(r.started_at) }, 'Ver fontes'),
          ]), 'Execuções recentes'),
        ];
      }, loadList);
    }
  }

  /* ======================================================================
   * Notificações
   * ====================================================================== */
  function notificationsNodes(d) {
    const items = Array.isArray(d.items) ? d.items : [];
    const out = [];
    out.push(d.sending_enabled
      ? callout('warn', '!', el('p', { text: 'Envio ligado. As mensagens da fila podem ser enviadas por e-mail.' }))
      : callout('info', '○', el('p', null, el('strong', { text: 'Envio desligado: apenas preview. ' }), 'Nada é enviado por e-mail; as mensagens ficam como rascunho para você conferir.')));
    out.push(d.recipient_configured
      ? callout('ok', '✓', el('p', { text: 'Destinatário configurado.' }))
      : callout('warn', '!', el('p', { text: 'Destinatário não configurado. Sem ele o envio não acontece, mesmo se for ligado.' })));
    if (!items.length) {
      out.push(emptyBox('Nenhuma notificação na fila.'));
      return out;
    }
    out.push(el('ul', { class: 'joblist' }, items.map((n) => el('li', { class: 'job' },
      el('div', { class: 'job-top' },
        el('div', { class: 'job-main' },
          el('div', { class: 'job-co', text: 'Criada em ' + fmtDate(n.created_at) }),
          el('strong', { class: 'job-title', text: n.subject || '(sem assunto)' })),
        badge(NOTIF_STATUS, n.status, { wrap: true })),
      el('div', { class: 'meta-line' },
        el('span', { text: 'Tentativas: ' + num(n.attempts) }),
        n.smtp_accepted_at ? el('span', { text: 'Aceito pelo servidor em ' + fmtDate(n.smtp_accepted_at) }) : null,
        n.last_error_code ? el('span', { text: 'Último erro: ' + n.last_error_code }) : null,
        n.run_id ? el('span', null, el('a', { href: '#execucoes/' + enc(n.run_id) }, 'Execução de origem')) : null),
      el('details', null,
        el('summary', { text: 'Ver mensagem' }),
        el('pre', { class: 'desc', tabindex: '0', 'aria-label': 'Texto da mensagem', text: n.body_text || '' }))))));
    return out;
  }

  function renderNotificacoes(root, arg, ctx) {
    const body = el('div', { class: 'stack' });
    root.append(viewHead('Notificações', 'Fila de saída de e-mails (rascunhos e envios).'), body);
    load();
    function load() { fill(ctx, body, apiGet('/api/notifications'), notificationsNodes, load); }
  }

  /* ======================================================================
   * Diagnóstico
   * ====================================================================== */
  const CLI_COMMANDS = [
    ['Verifica ambiente, banco e configuração', '.\\.venv\\Scripts\\python.exe -m jobos doctor'],
    ['Mostra o estado do sistema no terminal', '.\\.venv\\Scripts\\python.exe -m jobos status'],
    ['Simula um ciclo com dados de teste (fixtures), sem coletar vagas reais', '.\\.venv\\Scripts\\python.exe -m jobos cycle --dry-run --fixtures'],
  ];

  function diagnosticNodes(res) {
    const st = res.status;
    const prof = st.profile || {};
    const inv = prof.last_invalid;
    const health = res.health;
    return [
      el('div', { class: 'grid' },
        card('API local', health && health.ok
          ? el('p', null, tagBadge('Respondendo', '✓', 'ok'), ' ', code(health.service || 'jobos-local'))
          : el('p', null, tagBadge('Sem resposta de /api/health', '✗', 'bad'))),
        card('Banco de dados', kv([
          ['Arquivo', code(st.database)],
          ['Versão do esquema', isEmpty(st.schema_version) ? 'n/d' : String(st.schema_version)],
          ['Estado gerado em', fmtDate(st.generated_at)],
        ])),
        card('Perfil', kv([
          ['Perfil ativo', prof.active_profile_id ? code(String(prof.active_profile_id).slice(0, 12)) : tagBadge('nenhum', '!', 'warn')],
          ['Último perfil inválido', inv
            ? el('div', null, tagBadge('há registro', '!', 'warn'), el('div', { class: 'small', text: inv.error || 'sem mensagem' }), el('div', { class: 'small muted', text: 'recebido em ' + fmtDate(inv.received_at) }))
            : tagBadge('nenhum', '✓', 'ok')],
        ])),
        card('Recursos', kv([
          ['IA habilitada', (st.ai || {}).enabled ? tagBadge('sim', '!', 'warn') : tagBadge('não (análise por regras)', '○', 'mute')],
          ['Relações sugeridas pendentes', String(num(st.relations_suggested))],
          ['Fixtures fora da contagem', String(num((st.jobs || {}).fixtures_excluded))],
        ]))),
      card('Comandos de linha de comando',
        el('p', { class: 'muted', text: 'Rode na pasta _system, no PowerShell. A CLI e o painel usam o mesmo serviço e o mesmo banco.' }),
        el('div', { class: 'stack' }, CLI_COMMANDS.map(([what, cmd]) => el('div', null,
          el('p', { class: 'small', text: what }),
          el('pre', { class: 'code', tabindex: '0' }, el('code', { text: cmd })))))),
    ];
  }

  function renderDiagnostico(root, arg, ctx) {
    const body = el('div', { class: 'stack' });
    root.append(viewHead('Diagnóstico', 'Dados técnicos para conferir o ambiente.'), body);
    load();
    function load() {
      const both = Promise.all([apiGet('/api/status'), apiGet('/api/health').catch(() => null)])
        .then(([status, health]) => ({ status, health }));
      fill(ctx, body, both, diagnosticNodes, load);
    }
  }

  /* ======================================================================
   * Roteamento por hash
   * ====================================================================== */
  const VIEWS = {
    logins: ['Logins e candidaturas', renderLogins],
    visao: ['Visão geral', renderVisao],
    fontes: ['Fontes', renderFontes],
    vagas: ['Vagas', renderVagas],
    vaga: ['Detalhe da vaga', renderVaga],
    candidaturas: ['Candidaturas', renderCandidaturas],
    execucoes: ['Execuções', renderExecucoes],
    notificacoes: ['Notificações', renderNotificacoes],
    diagnostico: ['Diagnóstico', renderDiagnostico],
  };

  const mainEl = document.getElementById('principal');
  const tabButtons = Array.from(document.querySelectorAll('.tab'));
  let routeToken = 0;
  let currentTab = 'visao';
  let lastListHash = '#vagas';

  function parseHash() {
    const raw = location.hash.replace(/^#\/?/, '');
    const parts = raw.split('/');
    const tab = has(VIEWS, parts[0]) ? parts[0] : 'visao';
    const arg = parts.length > 1 ? safeDecode(parts.slice(1).join('/')) : null;
    return { tab, arg: arg || null };
  }

  function route(opts) {
    const o = opts || {};
    const { tab, arg } = parseHash();
    const token = ++routeToken;
    const ctx = { alive: () => token === routeToken };
    currentTab = tab;
    if (tab !== 'vaga') lastListHash = location.hash || '#visao';
    if (tab !== 'vaga' && tab !== 'vagas') jobsScroll = null; // posição da lista só vale na ida e volta do detalhe

    for (const b of tabButtons) {
      const here = b.dataset.tab === tab;
      if (here) b.setAttribute('aria-current', 'page');
      else b.removeAttribute('aria-current');
      if (b.dataset.tab === 'vaga') b.hidden = tab !== 'vaga';
    }
    const active = tabButtons.find((b) => b.dataset.tab === tab);
    if (active && active.scrollIntoView) active.scrollIntoView({ block: 'nearest', inline: 'nearest' });

    document.title = 'Painel JOBOS | ' + VIEWS[tab][0];
    mainEl.replaceChildren();
    try {
      VIEWS[tab][1](mainEl, arg, ctx);
    } catch (err) {
      console.error(err);
      mainEl.replaceChildren(errorBox(err, () => route({ silent: true })));
    }
    syncActionButtons();

    if (!o.silent) {
      window.scrollTo(0, 0);
      if (o.focus) {
        const h = mainEl.querySelector('h2');
        if (h) h.focus({ preventScroll: true });
      }
    }
  }

  function go(tab) {
    if (tab === 'vaga') { route({ focus: true }); return; }
    const target = '#' + tab;
    if (location.hash === target) route({ focus: true });
    else location.hash = target;
  }

  for (const b of tabButtons) b.addEventListener('click', () => go(b.dataset.tab));
  window.addEventListener('hashchange', () => route({ focus: true }));

  const skip = document.getElementById('skip-link');
  if (skip) {
    skip.addEventListener('click', (ev) => {
      ev.preventDefault(); // mantém o hash de roteamento intacto
      mainEl.focus();
    });
  }

  if (location.protocol === 'file:') {
    document.title = 'JOBOS local';
    mainEl.replaceChildren(el('div', { class: 'state state-error', role: 'alert' },
      el('span', { 'aria-hidden': 'true', text: '✗' }),
      el('span', { text: 'Este arquivo não é o aplicativo. Dê duplo clique em JOBOS.cmd, na pasta _system. O painel só abre em http://127.0.0.1:8776/painel/.' })));
  } else {
    restoreWork();
    route({ focus: false });
  }
})();
