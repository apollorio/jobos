"""Pacote de CV por vaga (P3.1-R). Determinístico, local, sem IA, sem rede e sem efeito sobre candidaturas.

Cada linha do CV é texto que já existe em `config/profile/master.json` (copiado sem reescrever) e carrega um JSON Pointer
para a evidência e o status (atendido/parcial). Antes de gravar, `validate_cv_data` descarta e registra:
  - T28: número que não consta na evidência apontada (inclui unidade: "5 anos" não é validado por "5 Medevacs");
  - T29: competência de projeto pessoal / em desenvolvimento fora da seção própria e sem qualificador;
  - limites de verdade (BOUNDARY_TERMS, frases `avoid` do safe_wording_bank, "5+ anos em gerência similar").
Gerar o pacote NUNCA marca candidatura como enviada: só a tabela `artifacts` é escrita (e só metadados dos arquivos).

Layout: <data>/artifacts/<job_id>/<input_hash12>/{manifest,cv_data,answers,validation}.json + cv.html.
Arquivos finais são imutáveis (T47): mesmas entradas reutilizam a pasta; perfil novo cria pasta nova.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from jobos.domain.identity import fold
from jobos.matching import cv_render
from jobos.matching.analyze import BOUNDARY_TERMS, _has
from jobos.matching.evidence import SOFTWARE_ALIASES, build_index
from jobos.matching.prepare import _active_domains, build_support
from jobos.matching.profile import Profile, active_profile
from jobos.storage.db import tx
from jobos.timeutil import iso

PACKET_CODE_VERSION = "cv-packet-1"
SCHEMA_VERSION = 1
FILES = ("cv_data.json", "answers.json", "validation.json", "cv.html")
KINDS = {"cv_data.json": "cv_data", "answers.json": "cv_answers", "validation.json": "cv_validation",
         "cv.html": "cv_html", "manifest.json": "cv_manifest"}
STATUS_LABEL = {"met": "atendido", "partial": "parcial"}
VALID_STATUS = ("atendido", "parcial")
SEP = " ¦ "  # separador de campos ao achatar evidência; não é letra nem dígito

# T29: só estes status entram como experiência prática sem qualificador (software_systems_tree.rules.cv_rule).
PROFESSIONAL_STATUS = ("strong/proven", "used/proven")
QUALIFIED_STATUS = {
    "developing": "em desenvolvimento",
    "personal-project": "projeto pessoal",
    "personal-project/developing": "projeto pessoal, em desenvolvimento",
    "personal-project/workflow": "projeto pessoal (fluxo de trabalho)",
    "used/proven independent-project": "uso comprovado em projeto independente",
    "historical-training": "treinamento histórico",
}
QUALIFIER_MARKERS = ("desenvolvimento", "development", "developing", "independen", "pessoal", "personal", "projeto",
                     "project", "aprendizado", "learning", "treinamento", "training")
SKILLS_PRO_MAX, SKILLS_IND_MAX, CERTS_MAX, SUMMARY_MAX, MAX_ITEMS, MAX_LINE_CHARS = 8, 6, 8, 4, 8, 360


class PacketError(ValueError):
    """Pacote não pode ser gerado (sem perfil, sem análise, pasta existente inconsistente...)."""


# ---------------------------------------------------------------------------------------------------------------
# Plano de experiência: (campo no nó, rótulo fixo do CV, domínios que o campo sustenta, máx. de itens por linha).
# O rótulo é só moldura (sem afirmação); os itens são copiados do perfil.
# ---------------------------------------------------------------------------------------------------------------
_NAVAL, _OG, _PM, _PLAN = "naval_marine_offshore", "oil_gas_offshore", "project_management_project_controls", \
    "planning_data_performance"
_MAINT, _LOG, _HSEQ = "maintenance_repairs_asset_readiness", "logistics_materials_suppliers", "hseq_emergency_response"
_QUAL, _COM, _DIG, _IND = "quality_management_systems", "commercial_contract_management", "digital_data_technology", \
    "independent_projects_entrepreneurship"
_TRAIN = "training_communication_leadership"

EXPERIENCE_PLAN = (
    ("exp_professional_development", "independent", 3, (
        ("details", "Atividades", (_DIG, _IND, _PM), MAX_ITEMS),
        ("learning_tracks", "Trilhas de aprendizado", (_DIG, _HSEQ, _IND), MAX_ITEMS))),
    ("exp_vanoord", "corporate", 6, (
        ("formal_job_scope", "Escopo", (), MAX_ITEMS),
        ("marine_operations", "Operações marítimas", (_NAVAL,), MAX_ITEMS),
        ("vessel_shore", "Interface base-embarcação", (_NAVAL, _LOG), MAX_ITEMS),
        ("planning_controls", "Planejamento e controle", (_PLAN, _PM), MAX_ITEMS),
        ("performance_kpis", "Indicadores de desempenho", (_PLAN, _PM), MAX_ITEMS),
        ("survey_and_data_validation", "Levantamentos e validação de dados", (_PLAN, _DIG), MAX_ITEMS),
        ("hseq", "HSEQ", (_HSEQ, _QUAL), MAX_ITEMS),
        ("erc.drills", "Resposta a emergências (simulados)", (_HSEQ,), MAX_ITEMS),
        ("erc.real_response", "Resposta a emergências (casos reais)", (_HSEQ,), MAX_ITEMS),
        ("inspections.activities", "Inspeções", (_HSEQ, _NAVAL, _QUAL), MAX_ITEMS),
        ("maintenance_repairs_readiness", "Manutenção e prontidão", (_MAINT,), MAX_ITEMS),
        ("commercial_contractual", "Contratos, custos e fornecedores", (_COM, _LOG), MAX_ITEMS),
        ("documentation", "Documentação e relatórios", (_QUAL, _PLAN), MAX_ITEMS))),
    ("exp_ctank_analyst", "corporate", 3, (
        ("operations", "Operações", (_OG, _NAVAL, _LOG, _MAINT), MAX_ITEMS),
        ("reporting", "Relatórios", (_PLAN, _PM), MAX_ITEMS),
        ("contract_controls", "Controle contratual", (_COM, _PM), MAX_ITEMS),
        ("quality_process_improvement", "Qualidade e melhoria de processos", (_QUAL,), MAX_ITEMS),
        ("petrobras_processes", "Processos Petrobras", (_OG, _LOG), MAX_ITEMS))),
    ("exp_ctank_assistant", "corporate", 2, (
        ("activities", "Atividades", (_LOG, _OG, _NAVAL), MAX_ITEMS),)),
    ("exp_toolvox", "corporate", 2, (
        ("activities", "Atividades", (_TRAIN, _HSEQ, _NAVAL, _OG), MAX_ITEMS),)),
)

# Tópico do safe_wording_bank -> domínios que o justificam no resumo.
SUMMARY_TOPICS = {
    "ISO / management systems": (_QUAL,),
    "Suppliers": (_LOG, _COM),
    "Maintenance / readiness": (_MAINT,),
    "Planning tools": (_PLAN, _PM),
    "Regulatory": (_HSEQ, _NAVAL),
    "Emergency response": (_HSEQ,),
    "Digital skills": (_DIG,),
    "Dismantle": (_IND,),
}

STOPWORDS = {"experiencia", "conhecimento", "conhecimentos", "desejavel", "obrigatorio", "vivencia", "superior", "ensino",
             "necessario", "requisitos", "diferencial", "preferencial", "sólida", "solida", "atuacao", "area", "areas",
             "desejado", "minimo", "minima", "other", "experience", "knowledge", "required", "years"}


# ---------------------------------------------------------------------------------------------------------------
# Números (T28)
# ---------------------------------------------------------------------------------------------------------------
_NUM = re.compile(r"(?<![\w.,])(\d{1,3}(?:[.,]\d{3})+(?:,\d{1,2})?(?!\d)|\d+(?:[.,]\d+)?)(?![\w])")
_COMPACT = re.compile(r"(?<![\w])(\d+)\s*y(?:ears?)?\s*(\d+)\s*m(?:onths?)?(?![\w])", re.I)
_WORDNUM = {"um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6, "sete": 7, "oito": 8,
            "nove": 9, "dez": 10, "onze": 11, "doze": 12, "quinze": 15, "vinte": 20, "trinta": 30, "one": 1, "two": 2,
            "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twelve": 12,
            "fifteen": 15, "twenty": 20, "thirty": 30}
_WORDNUM_RE = re.compile(r"\b(" + "|".join(_WORDNUM) + r")\s+(anos?|meses|mes|years?|months?)\b")
_UNIT_FAMILY = {"ano": "year", "anos": "year", "year": "year", "years": "year", "yr": "year", "yrs": "year",
                "mes": "month", "meses": "month", "month": "month", "months": "month",
                "dia": "day", "dias": "day", "day": "day", "days": "day"}
_MONEY_WORDS = {"reais", "dolares", "dolar", "euros", "usd", "brl", "eur"}
_MONEY_PREFIX = ("r$", "us$", "$", "€", "£", "usd", "eur", "brl")
_AFTER_WORD = re.compile(r"^\+?\s*[-–]?\s*([A-Za-zÀ-ÿ]+)")


def _norm_num(raw: str) -> str:
    s = raw
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+(?:,\d{1,2})?", s):
        s = s.replace(".", "").replace(",", ".") if "," in s and s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    if "." in s:
        a, b = s.split(".", 1)
        b = b.rstrip("0")
        s = (a.lstrip("0") or "0") + ("." + b if b else "")
    else:
        s = s.lstrip("0") or "0"
    return s


def number_claims(text: str) -> list[tuple[str, str | None, str | None]]:
    """Números do texto como (valor normalizado, família da unidade, radical da palavra seguinte)."""
    out: list[tuple[str, str | None, str | None]] = []
    for m in _NUM.finditer(text):
        before, after = text[:m.start()], text[m.end():]
        fam: str | None = None
        stem: str | None = None
        if after.startswith("%") or after.lstrip().lower().startswith(("por cento", "percent")):
            fam = "pct"
        elif fold(before).rstrip().endswith(_MONEY_PREFIX):
            fam = "money"
        else:
            w = _AFTER_WORD.match(after)
            if w:
                word = fold(w.group(1))
                if word in _UNIT_FAMILY:
                    fam = _UNIT_FAMILY[word]
                elif word in _MONEY_WORDS:
                    fam = "money"
                elif word in ("y", "m") and after.lstrip("+ ").lower().startswith(word):
                    fam = "year" if word == "y" else "month"
                else:
                    fam, stem = "word", word[:4]
        out.append((_norm_num(m.group(1)), fam, stem))
    for m in _COMPACT.finditer(text):
        out.append((_norm_num(m.group(1)), "year", None))
        out.append((_norm_num(m.group(2)), "month", None))
    for m in _WORDNUM_RE.finditer(fold(text)):
        out.append((str(_WORDNUM[m.group(1)]), _UNIT_FAMILY[m.group(2)] if m.group(2) in _UNIT_FAMILY else "year", None))
    return out


def _evidence_numbers(evidence: str) -> tuple[set[tuple[str, str]], set[str]]:
    """(pares valor/família, valores soltos) da evidência, com meses totais derivados de 'X anos e Y meses'."""
    pairs: set[tuple[str, str]] = set()
    values: set[str] = set()
    for val, fam, stem in number_claims(evidence):
        values.add(val)
        pairs.add((val, fam or "none"))
        if fam == "word" and stem:
            pairs.add((val, "word:" + stem))
    years = [v for v, f in pairs if f == "year"]
    months = [v for v, f in pairs if f == "month"]
    for y in years:
        for mo in months:
            try:
                pairs.add((_norm_num(str(int(float(y)) * 12 + int(float(mo)))), "month"))
            except ValueError:
                pass
    return pairs, values


def unsupported_numbers(text: str, evidence: str) -> list[str]:
    """T28: números de `text` que a evidência apontada não sustenta (valor E contexto de unidade)."""
    pairs, values = _evidence_numbers(evidence)
    bad: list[str] = []
    for val, fam, stem in number_claims(text):
        if fam is None:
            ok = val in values
        elif fam == "word":
            ok = (val, "word:" + (stem or "")) in pairs or (val, "none") in pairs
        else:
            ok = (val, fam) in pairs
        if not ok and val not in bad:
            bad.append(val if fam in (None, "word") else f"{val} ({fam})")
    return bad


def evidence_text(value) -> str:
    """Achata um nó do perfil em texto (strings e números) separado por SEP; 'years/months/days' ganham a unidade."""
    parts: list[str] = []

    def walk(v, key=""):
        if isinstance(v, str):
            parts.append(v)
        elif isinstance(v, bool) or v is None:
            return
        elif isinstance(v, (int, float)):
            parts.append(f"{v} {key}" if key in ("years", "months", "days") else str(v))
        elif isinstance(v, list):
            for x in v:
                walk(x, key)
        elif isinstance(v, dict):
            for k, x in v.items():
                walk(x, str(k))
    walk(value)
    return SEP.join(parts)


# ---------------------------------------------------------------------------------------------------------------
# Estado de composição
# ---------------------------------------------------------------------------------------------------------------
@dataclass
class _State:
    profile: Profile
    support: dict
    analysis: dict
    reqs: list[dict]
    active: list[str]
    domain_status: dict[str, str]
    tokens: set[str]
    ev_pointers: dict[str, list[tuple[str, str]]]  # pointer -> [(req_id, status_pt)]
    seq: int = 0
    dropped: list[dict] = field(default_factory=list)

    def line(self, kind: str, text: str, pointer: str, status: str, **extra) -> dict:
        self.seq += 1
        row = {"id": f"L{self.seq:03d}", "kind": kind, "text": text, "pointer": pointer, "status": status}
        row.update({k: v for k, v in extra.items() if v not in (None, "", [], ())})
        return row

    def drop(self, kind: str, text: str, pointer: str, reason: str, detail: str = "") -> None:
        self.dropped.append({"kind": kind, "text": text, "pointer": pointer, "reason": reason, "detail": detail})


def _get(profile: Profile, pointer: str):
    try:
        return profile.pointer(pointer)
    except (KeyError, IndexError, ValueError, TypeError):
        return None


def _str(value) -> str | None:
    return value if isinstance(value, str) and value and "UNKNOWN_NOT_DOCUMENTED" not in value else None


def _domain_status(state_domains: dict[str, str], domains) -> str:
    sts = [state_domains.get(d) for d in domains if d in state_domains]
    return "atendido" if "atendido" in sts else "parcial"


def _prepare_state(profile: Profile, support: dict, analysis: dict) -> _State:
    reqs = [r for r in (analysis.get("requirements") or []) if isinstance(r, dict)]
    used = [r for r in reqs if r.get("status") in STATUS_LABEL]
    dstat: dict[str, str] = {}
    for r in used:
        for d in _active_domains([r]):
            if dstat.get(d) != "atendido":
                dstat[d] = STATUS_LABEL[r["status"]]
    tokens: set[str] = set()
    for r in used:
        for tok in re.findall(r"[a-z0-9]{5,}", fold(r.get("text") if isinstance(r.get("text"), str) else "")):
            if tok not in STOPWORDS:
                tokens.add(tok)
    ev: dict[str, list[tuple[str, str]]] = {}
    for r in used:
        for ref in r.get("evidence_refs") or []:
            ptr = ref.get("pointer") if isinstance(ref, dict) else None
            if isinstance(ptr, str) and ptr:
                ev.setdefault(ptr, []).append((str(r.get("requirement_id") or ""), STATUS_LABEL[r["status"]]))
    return _State(profile, support, analysis, reqs, list(support.get("domains") or []), dstat, tokens, ev)


# ---------------------------------------------------------------------------------------------------------------
# Composição das seções
# ---------------------------------------------------------------------------------------------------------------
def _compose_identity(st: _State) -> dict:
    p = st.profile
    name_ptr = "/identity/professional_name_used_on_cv" if _str(_get(p, "/identity/professional_name_used_on_cv")) \
        else "/identity/professional_display"
    ident = {"name": None, "location": None, "contacts": []}
    for key, ptr in (("name", name_ptr), ("location", "/identity/location")):
        v = _str(_get(p, ptr))
        if v:
            ident[key] = st.line("identity", v, ptr, "atendido")
    for ptr in ("/identity/contacts/email", "/identity/contacts/website", "/identity/links/linkedin"):
        v = _str(_get(p, ptr))
        if v:
            ident["contacts"].append(st.line("contact", v, ptr, "atendido"))
    return ident


def _compose_headline(st: _State, headline_id: str | None) -> tuple[dict | None, list[dict], str]:
    chosen = st.support.get("headline")
    candidates = list(st.support.get("headline_candidates") or [])
    note = st.support.get("headline_rule") or ""
    if headline_id:
        chosen = next((c for c in candidates if c.get("id") == headline_id), None)
        if chosen is None:
            raise PacketError(f"headline_id '{headline_id}' não está entre os candidatos desta vaga: "
                              f"{[c.get('id') for c in candidates]}")
        note = "Headline escolhido explicitamente pelo usuário entre os candidatos do perfil."
    if not chosen:
        return None, candidates, note
    templates = (st.profile.data.get("positioning_layer") or {}).get("headline_templates") or []
    for i, tpl in enumerate(templates):
        if isinstance(tpl, dict) and tpl.get("id") == chosen.get("id") and _str(tpl.get("headline_en")):
            ptr = f"/positioning_layer/headline_templates/{i}/headline_en"
            return (st.line("headline", tpl["headline_en"], ptr, _domain_status(st.domain_status, chosen.get("domains") or []),
                            domains=[d for d in chosen.get("domains") or [] if d in st.active]), candidates, note)
    return None, candidates, note


def _compose_summary(st: _State) -> list[dict]:
    p, out = st.profile, []
    one = _str(_get(p, "/career_summary/canonical_one_liner"))
    if one:
        out.append(st.line("summary", one, "/career_summary/canonical_one_liner", "atendido"))
    bank = (p.data.get("positioning_layer") or {}).get("safe_wording_bank") or []
    ranked = []
    for i, item in enumerate(bank):
        if not isinstance(item, dict) or not _str(item.get("use")):
            continue
        doms = SUMMARY_TOPICS.get(item.get("topic"))
        hit = [d for d in (doms or ()) if d in st.active]
        if hit:
            ranked.append((-len(hit), i, item, hit))
    ranked.sort(key=lambda r: (r[0], r[1]))
    for _, i, item, hit in ranked[:SUMMARY_MAX]:
        out.append(st.line("summary", item["use"], f"/positioning_layer/safe_wording_bank/{i}/use",
                           _domain_status(st.domain_status, hit), domains=hit))
    return out


def _period(st: _State, nid: str, node: dict) -> dict | None:
    per = node.get("period")
    if isinstance(per, dict) and _str(per.get("display")):
        return st.line("period", per["display"], f"/experience_nodes/{nid}/period/display", "atendido")
    if _str(per):
        return st.line("period", per, f"/experience_nodes/{nid}/period", "atendido")
    return None


def _role(st: _State, nid: str, node: dict) -> dict | None:
    variants = node.get("cv_role_variants_allowed")
    if isinstance(variants, list) and variants:
        idx = 3 if (len(variants) > 3 and (_PLAN in st.active or _PM in st.active) and _NAVAL not in st.active) else 0
        if _str(variants[idx]):
            return st.line("role", variants[idx], f"/experience_nodes/{nid}/cv_role_variants_allowed/{idx}", "atendido")
    for key in ("preferred_cv_label_en", "canonical_role", "role", "formal_role"):
        if _str(node.get(key)):
            return st.line("role", node[key], f"/experience_nodes/{nid}/{key}", "atendido")
    return None


def _items(st: _State, node: dict, nid: str, path: str, cap: int) -> tuple[list[str], list[str]]:
    cur = node
    for part in path.split("."):
        cur = cur.get(part) if isinstance(cur, dict) else None
    if not isinstance(cur, list):
        return [], []
    base = f"/experience_nodes/{nid}/" + path.replace(".", "/")
    rows = [(s, f"{base}/{i}") for i, s in enumerate(cur) if _str(s)]
    scored = [(sum(1 for t in st.tokens if t in fold(s)), -i, s, ptr) for i, (s, ptr) in enumerate(rows)]
    scored.sort(key=lambda r: (-r[0], -r[1]))
    pick, total = [], 0
    for _, _, s, ptr in scored:
        if len(pick) >= cap or (pick and total + len(s) > MAX_LINE_CHARS):
            break
        pick.append((s, ptr))
        total += len(s) + 2
    return [s for s, _ in pick], [ptr for _, ptr in pick]


def _compose_experience(st: _State) -> list[dict]:
    entries = []
    exp = st.profile.data.get("experience_nodes") or {}
    for nid, scope, max_bullets, specs in EXPERIENCE_PLAN:
        node = exp.get(nid)
        if not isinstance(node, dict):
            continue
        role, period = _role(st, nid, node), _period(st, nid, node)
        company = None
        for key in ("company", "organization"):
            if _str(node.get(key)) and nid != "exp_professional_development":
                company = st.line("company", node[key], f"/experience_nodes/{nid}/{key}", "atendido")
                break
        scored = []
        for order, (path, label, domains, cap) in enumerate(specs):
            hit = [d for d in domains if d in st.active]
            base = f"/experience_nodes/{nid}/" + path.replace(".", "/")
            boost = any(ptr == base or ptr.startswith(base + "/") for ptr in st.ev_pointers)
            score = len(hit) + (2 if boost else 0)
            if score > 0:
                scored.append((-score, order, path, label, cap, hit))
        scored.sort()
        chosen = scored[:max_bullets] or [(0, 0, specs[0][0], specs[0][1], specs[0][3], [])]
        bullets = []
        for _, _, path, label, cap, hit in chosen:
            texts, ptrs = _items(st, node, nid, path, cap)
            if not texts:
                continue
            base = f"/experience_nodes/{nid}/" + path.replace(".", "/")
            status = _domain_status(st.domain_status, hit) if hit else "atendido"
            req_ids = sorted({rid for ptr, rows in st.ev_pointers.items() if ptr == base or ptr.startswith(base + "/")
                              for rid, _ in rows if rid})
            bullets.append(st.line("bullet", f"{label}: " + "; ".join(texts), base, status, item_pointers=ptrs,
                                   domains=hit, requirement_ids=req_ids))
        entries.append({"id": nid, "scope": scope, "role": role, "company": company, "period": period,
                        "bullets": bullets})
    return entries


def _skill_line(st: _State, ptr: str, req_ids: list[str]) -> dict | None:
    node = _get(st.profile, ptr)
    if not isinstance(node, dict):
        st.drop("skill", ptr, ptr, "ponteiro_nao_resolve")
        return None
    name, status = _str(node.get("name")) or ptr.rsplit("/", 1)[-1], node.get("status")
    if status in PROFESSIONAL_STATUS:
        level = _str(node.get("level"))
        return st.line("skill", f"{name} — {level}" if level else name, ptr, "atendido", requirement_ids=req_ids)
    if status in QUALIFIED_STATUS:
        q = QUALIFIED_STATUS[status]
        return st.line("skill", f"{name} ({q})", ptr, "parcial", qualifier=q, profile_status=status, requirement_ids=req_ids)
    st.drop("skill", name, ptr, "status_nao_alegavel",
            f"status no perfil: {status}; só strong/proven e used/proven entram sem qualificador, e este não tem qualificador permitido")
    return None


def _compose_skills(st: _State) -> dict:
    p = st.profile
    cand: dict[str, list[str]] = {}
    for ptr, rows in st.ev_pointers.items():
        if ptr.startswith("/software_systems_tree/") and p.resolves(ptr):
            cand.setdefault(ptr, []).extend(rid for rid, _ in rows if rid)
    tree = p.data.get("software_systems_tree") or {}
    for group, items in tree.items():
        if group == "rules" or not isinstance(items, dict):
            continue
        for sid, node in items.items():
            if (isinstance(node, dict) and node.get("cv_default") is True and node.get("status") in PROFESSIONAL_STATUS
                    and set(node.get("domain_tags") or []) & set(st.active)):
                cand.setdefault(f"/software_systems_tree/{group}/{sid}", [])
    pro, ind = [], []
    for ptr, rids in cand.items():
        line = _skill_line(st, ptr, sorted(set(rids)))
        if line:
            (ind if line.get("qualifier") else pro).append(line)
    return {"professional": pro[:SKILLS_PRO_MAX], "independent": ind[:SKILLS_IND_MAX]}


def _cert_text(node: dict, name: str) -> tuple[str, str, str]:
    scope = node.get("scope")
    scope = scope if isinstance(scope, str) else ", ".join(s for s in scope if isinstance(s, str)) if isinstance(scope, list) else ""
    wording = _str(node.get("current_safe_wording"))
    hist = node.get("historical_valid_until") or node.get("historical_validity") or node.get("historical_period")
    text = name + (f" ({scope})" if scope else "")
    if wording:
        return text + f" — {wording}", "parcial", wording
    if hist:
        q = f"validade histórica {hist}; validade atual não documentada"
        return text + f" — {q}", "parcial", q
    return text, "atendido", ""


def _compose_credentials(st: _State) -> dict:
    p = st.profile
    idx = build_index(p)
    edu = []
    for eid, node in (p.data.get("education_tree") or {}).items():
        if not isinstance(node, dict) or node.get("cv_default") is not True or not _str(node.get("degree")):
            continue
        ptr = f"/education_tree/{eid}"
        status_raw = node.get("status") if isinstance(node.get("status"), str) else ""
        done = fold(status_raw) == "concluido"
        conflict = bool(node.get("period_source_conflict"))
        period = _str(node.get("period")) if not conflict else None
        text = node["degree"] + (f" — {node['institution']}" if _str(node.get("institution")) else "")
        text += f" ({period})" if period else ""
        if not done and status_raw:
            text += f" ({status_raw})"
        years = re.findall(r"(\d{4})", " ".join(str(node.get(k) or "") for k in ("period", "period_source_1")))
        edu.append((-(int(years[-1]) if years else 0), eid, st.line(
            "education", text, ptr, "atendido" if done else "parcial", qualifier="" if done else status_raw,
            requirement_ids=sorted({rid for rid, _ in st.ev_pointers.get(ptr, []) if rid}))))
    edu.sort(key=lambda r: (r[0], r[1]))
    cert_ids: list[str] = []
    for ptr in st.ev_pointers:
        if ptr.startswith("/certification_training_tree/"):
            cid = ptr.split("/")[2]
            if cid in idx.certifications and cid not in cert_ids:
                cert_ids.append(cid)
    domain_tree = p.data.get("domain_tree") or {}
    for d in st.active:
        refs = ((domain_tree.get(d) or {}).get("refs") or {}).get("certifications") if isinstance(domain_tree.get(d), dict) else None
        for cid in refs or []:
            if cid in idx.certifications and cid not in cert_ids:
                cert_ids.append(cid)
    certs = []
    for cid in cert_ids[:CERTS_MAX]:
        node = (p.data.get("certification_training_tree") or {}).get(cid) or {}
        text, status, qual = _cert_text(node, _str(node.get("name")) or cid)
        ptr = f"/certification_training_tree/{cid}"
        certs.append(st.line("certification", text, ptr, status, qualifier=qual,
                             requirement_ids=sorted({rid for rid, _ in st.ev_pointers.get(ptr, []) if rid})))
    langs = []
    for key, label in (("portuguese", "Português"), ("english", "Inglês")):
        level = _str(_get(p, f"/identity/languages/{key}/level"))
        if level:
            langs.append(st.line("language", f"{label} — {level}", f"/identity/languages/{key}/level", "atendido"))
    regs = []
    if "/identity/crea" in st.ev_pointers and _str(_get(p, "/identity/crea/status")):
        regs.append(st.line("registration", f"CREA — {p.pointer('/identity/crea/status')}", "/identity/crea/status",
                            "atendido"))
    if "/mobility_and_preferences/drivers_license" in st.ev_pointers and _str(_get(p, "/identity/driver_license/value")):
        regs.append(st.line("registration", p.pointer("/identity/driver_license/value"), "/identity/driver_license/value",
                            "atendido"))
    return {"education": [r[2] for r in edu], "certifications": certs, "languages": langs, "registrations": regs}


def compose_cv_data(profile: Profile, analysis: dict, support: dict, *, headline_id: str | None = None) -> tuple[dict, list[dict]]:
    """Seleciona linhas do perfil para a vaga. Retorna (cv_data sem validar, descartes da composição)."""
    st = _prepare_state(profile, support, analysis)
    headline, candidates, note = _compose_headline(st, headline_id)
    cv = {
        "schema_version": SCHEMA_VERSION, "kind": "cv_data", "method": "deterministic", "uses_ai": False,
        "sends_application": False, "changes_application_state": False,
        "language_note": "Textos copiados do perfil como estão (sem tradução ou reescrita).",
        "active_domains": st.active,
        "identity": _compose_identity(st),
        "headline": headline, "headline_candidates": candidates, "headline_note": note,
        "summary": _compose_summary(st),
        "experience": _compose_experience(st),
        "skills": _compose_skills(st),
        "credentials": _compose_credentials(st),
    }
    return cv, st.dropped


# ---------------------------------------------------------------------------------------------------------------
# Validação de claims (T28/T29 + limites de verdade)
# ---------------------------------------------------------------------------------------------------------------
def _avoid_phrases(profile: Profile) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for i, item in enumerate((profile.data.get("positioning_layer") or {}).get("safe_wording_bank") or []):
        if not isinstance(item, dict) or not isinstance(item.get("avoid"), str):
            continue
        for part in item["avoid"].split(";"):
            phrase = fold(re.sub(r"\([^)]*\)", "", part))
            if len(phrase) >= 10 and "'" not in phrase and '"' not in phrase and "opening the" not in phrase:
                out.append((phrase, f"/positioning_layer/safe_wording_bank/{i}/avoid"))
    tenure = (profile.data.get("truth_boundaries") or {}).get("management_tenure")
    if isinstance(tenure, dict) and _str(tenure.get("wrong")):
        out.append((fold(tenure["wrong"]), "/truth_boundaries/management_tenure/wrong"))
    wrong = _str((profile.data.get("career_summary") or {}).get("do_not_round_management_tenure_to"))
    if wrong:
        out.append((fold(wrong), "/career_summary/do_not_round_management_tenure_to"))
    return out


def _qualified_terms(profile: Profile) -> list[str]:
    terms: list[str] = []
    for group, items in (profile.data.get("software_systems_tree") or {}).items():
        if group == "rules" or not isinstance(items, dict):
            continue
        for sid, node in items.items():
            if not isinstance(node, dict) or node.get("status") in PROFESSIONAL_STATUS:
                continue
            names = [node.get("name")] + list(node.get("aliases") or []) + list(SOFTWARE_ALIASES.get(sid, []))
            for n in names:
                f = fold(n) if isinstance(n, str) else ""
                if len(f) >= 3 and f not in terms:
                    terms.append(f)
    return terms


@dataclass
class _Checker:
    profile: Profile
    avoid: list[tuple[str, str]]
    qualified: list[str]

    def check(self, line: dict, scope: str) -> tuple[str, str] | None:
        """None se ok; senão (código, detalhe)."""
        text, ptr = line.get("text"), line.get("pointer")
        if not isinstance(text, str) or not text.strip():
            return "linha_vazia", ""
        if not isinstance(ptr, str) or not ptr or not self.profile.resolves(ptr):
            return "ponteiro_nao_resolve", str(ptr)
        if line.get("status") not in VALID_STATUS:
            return "status_invalido", str(line.get("status"))
        item_ptrs = line.get("item_pointers") or []
        for ip in item_ptrs:
            if not self.profile.resolves(ip):
                return "ponteiro_nao_resolve", ip
        folded = fold(text)
        for terms, bptr, why in BOUNDARY_TERMS:
            if _has(folded, terms) and self.profile.resolves(bptr):
                return "limite_de_verdade", f"{why} ({bptr})"
        for phrase, aptr in self.avoid:
            if phrase in folded:
                return "frase_proibida", f"'{phrase}' ({aptr})"
        ev = SEP.join(evidence_text(self.profile.pointer(p)) for p in (item_ptrs or [ptr]))
        bad = unsupported_numbers(text, ev)
        if bad:
            return "T28_numero_sem_evidencia", f"número(s) {bad} não constam na evidência {ptr}"
        if line.get("kind") == "skill":
            return self._skill(line, scope)
        if scope in ("summary", "experience:corporate", "headline"):
            q = line.get("qualifier")
            if not q and not any(m in folded for m in QUALIFIER_MARKERS):
                for term in self.qualified:
                    if _has(folded, [term]):
                        return "T29_competencia_nao_corporativa", f"'{term}' (projeto pessoal/em desenvolvimento) citada sem qualificador"
        return None

    def _skill(self, line: dict, scope: str) -> tuple[str, str] | None:
        node = self.profile.pointer(line["pointer"])
        status = node.get("status") if isinstance(node, dict) else None
        if status in PROFESSIONAL_STATUS:
            return None if scope == "skills:professional" else ("T29_secao_incorreta", f"{status} fora da seção profissional")
        if status in QUALIFIED_STATUS:
            if scope != "skills:independent":
                return "T29_competencia_nao_corporativa", f"status '{status}' em seção profissional"
            if not line.get("qualifier") or line["qualifier"] not in line["text"]:
                return "T29_qualificador_ausente", f"status '{status}' exige qualificador no texto"
            return None
        return "status_nao_alegavel", f"status no perfil: {status}"


def validate_cv_data(cv: dict, profile: Profile, composition_drops: list[dict] | None = None) -> tuple[dict, dict]:
    """Aplica as checagens e devolve (cv_data apenas com linhas válidas, relatório validation.json)."""
    chk = _Checker(profile, _avoid_phrases(profile), _qualified_terms(profile))
    kept: list[dict] = []
    dropped: list[dict] = [dict(d, stage="composicao") for d in (composition_drops or [])]

    def run(lines, scope):
        ok = []
        for ln in lines:
            res = chk.check(ln, scope)
            if res is None:
                ok.append(ln)
                kept.append({"id": ln["id"], "kind": ln["kind"], "pointer": ln["pointer"], "status": ln["status"],
                             "scope": scope})
            else:
                dropped.append({"stage": "validacao", "line_id": ln.get("id"), "kind": ln.get("kind"),
                                "text": ln.get("text"), "pointer": ln.get("pointer"), "reason": res[0], "detail": res[1]})
        return ok

    out = json.loads(json.dumps(cv))
    ident = out["identity"]
    for key in ("name", "location"):
        if ident.get(key):
            r = run([ident[key]], "identity")
            ident[key] = r[0] if r else None
    ident["contacts"] = run(ident["contacts"], "identity")
    if out.get("headline"):
        r = run([out["headline"]], "headline")
        out["headline"] = r[0] if r else None
    out["summary"] = run(out["summary"], "summary")
    entries = []
    for entry in out["experience"]:
        scope = f"experience:{entry['scope']}"
        head = [entry.get(k) for k in ("role", "company", "period")]
        checked = run([h for h in head if h], scope)
        if len(checked) != len([h for h in head if h]) or not entry.get("role"):
            dropped.append({"stage": "validacao", "line_id": None, "kind": "experience", "text": entry["id"],
                            "pointer": f"/experience_nodes/{entry['id']}", "reason": "entrada_removida",
                            "detail": "linha de cabeçalho (cargo/empresa/período) reprovada"})
            continue
        entry["bullets"] = run(entry["bullets"], scope)
        entries.append(entry)
    out["experience"] = entries
    out["skills"] = {"professional": run(out["skills"]["professional"], "skills:professional"),
                     "independent": run(out["skills"]["independent"], "skills:independent")}
    out["credentials"] = {k: run(v, "credentials") for k, v in out["credentials"].items()}
    if not (ident.get("name")):
        raise PacketError("nome do perfil não validou; pacote não pode ser gerado")
    counts: dict[str, int] = {}
    for d in dropped:
        counts[d["reason"]] = counts.get(d["reason"], 0) + 1
    report = {
        "schema_version": SCHEMA_VERSION, "kind": "cv_validation",
        "checks": ["ponteiro_resolve", "status_atendido_ou_parcial", "limite_de_verdade", "frase_proibida",
                   "T28_numero_na_evidencia", "T29_competencia_nao_corporativa"],
        "summary": {"kept": len(kept), "dropped": len(dropped), "dropped_by_reason": counts},
        "kept": kept, "dropped": dropped,
    }
    return out, report


def iter_lines(cv: dict):
    """Todas as linhas do cv_data (para auditoria: cada uma deve ter `pointer` e `status`)."""
    ident = cv.get("identity") or {}
    for key in ("name", "location"):
        if ident.get(key):
            yield ident[key]
    yield from ident.get("contacts") or []
    if cv.get("headline"):
        yield cv["headline"]
    yield from cv.get("summary") or []
    for e in cv.get("experience") or []:
        for key in ("role", "company", "period"):
            if e.get(key):
                yield e[key]
        yield from e.get("bullets") or []
    for lst in (cv.get("skills") or {}).values():
        yield from lst
    for lst in (cv.get("credentials") or {}).values():
        yield from lst


# ---------------------------------------------------------------------------------------------------------------
# Respostas curtas (answers.json): só o que o perfil afirma diretamente
# ---------------------------------------------------------------------------------------------------------------
ANSWER_SPECS = (
    ("full_name", "Nome completo", "/identity/full_name"),
    ("location", "Cidade/UF atual", "/identity/location"),
    ("email", "E-mail", "/identity/contacts/email"),
    ("website", "Site", "/identity/contacts/website"),
    ("linkedin", "LinkedIn", "/identity/links/linkedin"),
    ("nationality", "Nacionalidade", "/identity/nationalities"),
    ("english_level", "Nível de inglês", "/identity/languages/english/level"),
    ("portuguese_level", "Nível de português", "/identity/languages/portuguese/level"),
    ("drivers_license", "Carteira de habilitação", "/identity/driver_license/value"),
    ("crea_status", "Registro no CREA", "/identity/crea/status"),
    ("availability", "Disponibilidade para início", "/mobility_and_preferences/availability"),
    ("notice_period", "Aviso prévio", "/mobility_and_preferences/notice_period"),
    ("travel_willingness", "Disponibilidade para viagens", "/mobility_and_preferences/travel_willingness"),
    ("offshore_rotation", "Disponibilidade para regime offshore", "/mobility_and_preferences/offshore_rotation_willingness"),
    ("relocation", "Mudança de cidade", "/mobility_and_preferences/relocation"),
    ("salary_expectation", "Pretensão salarial", "/mobility_and_preferences/salary_expectation"),
    ("employment_regime", "Regime de contratação (CLT/PJ)", "/mobility_and_preferences/employment_regime_clt_pj"),
)
OMITTED_ALWAYS = (("work_authorization", "Autorização de trabalho"),)
HEDGES = ("historical", "historic", "not specifically", "prioritizes", "unknown", "to validate")


def build_answers(profile: Profile) -> dict:
    items, omitted = [], []
    for key, question, ptr in ANSWER_SPECS:
        node = _get(profile, ptr)
        if isinstance(node, list) and node and all(isinstance(x, str) and x for x in node):
            answer, pointers = ", ".join(node), [f"{ptr}/{i}" for i in range(len(node))]
        elif isinstance(node, str) and node and "UNKNOWN_NOT_DOCUMENTED" not in node:
            answer, pointers = node, [ptr]
        else:
            omitted.append({"key": key, "question": question, "pointer": ptr, "reason": "não documentado no perfil"})
            continue
        items.append({"key": key, "question": question, "answer": answer, "pointer": ptr, "item_pointers": pointers,
                      "needs_review": any(h in answer.lower() for h in HEDGES)})
    omitted += [{"key": k, "question": q, "pointer": None, "reason": "não documentado no perfil"} for k, q in OMITTED_ALWAYS]
    kept = []
    for it in items:  # mesma regra T28: número da resposta precisa estar na evidência apontada
        ev = SEP.join(evidence_text(profile.pointer(p)) for p in it["item_pointers"])
        bad = unsupported_numbers(it["answer"], ev)
        if bad:
            omitted.append({"key": it["key"], "question": it["question"], "pointer": it["pointer"],
                            "reason": f"T28: número(s) {bad} sem evidência"})
        else:
            kept.append(it)
    return {"schema_version": SCHEMA_VERSION, "kind": "cv_answers", "method": "deterministic", "uses_ai": False,
            "note": "Respostas copiadas do perfil, sem reescrita. Itens com needs_review=true têm ressalva no próprio perfil; "
                    "confira antes de usar. Itens ausentes não constam no perfil: não invente.",
            "items": kept, "omitted": omitted}


# ---------------------------------------------------------------------------------------------------------------
# Pacote em disco
# ---------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class PacketResult:
    job_id: str
    input_hash: str
    directory: Path
    reused: bool
    files: dict[str, str]          # nome -> sha256
    manifest: dict
    kept: int
    dropped: int
    artifact_ids: list[str]
    registered: bool               # linhas gravadas/confirmadas na tabela `artifacts`
    warnings: list[str]


def _dump(obj) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compute_input_hash(version_hash: str, profile_sha: str, policy_version: str, headline_id: str | None = None) -> str:
    payload = {"job_version_hash": version_hash, "profile_sha": profile_sha, "policy_version": policy_version,
               "packet_code_version": PACKET_CODE_VERSION, "renderer": cv_render.renderer_id()}
    if headline_id:
        payload["headline_id"] = headline_id
    return _sha(json.dumps(payload, sort_keys=True).encode("utf-8"))


def _verify_existing(final: Path, input_hash: str) -> dict:
    try:
        manifest = json.loads((final / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("input_hash") != input_hash:
            raise PacketError("manifest com input_hash diferente")
        for name, meta in (manifest.get("files") or {}).items():
            if _sha((final / name).read_bytes()) != meta.get("sha256"):
                raise PacketError(f"{name} difere do SHA-256 do manifest")
        return manifest
    except (OSError, ValueError) as e:
        raise PacketError(f"pasta de pacote existente é inconsistente ({final}): {e}. Nada foi sobrescrito; "
                          "mova a pasta manualmente se quiser regenerar.") from e


def _register(con: sqlite3.Connection, job_id: str, h12: str, manifest: dict, manifest_sha: str) -> tuple[list[str], list[str]]:
    ids, warnings = [], []
    meta = json.dumps({"input_hash": manifest["input_hash"], "profile_id": manifest["profile_id"],
                       "policy_version": manifest["policy_version"], "job_version_id": manifest["job_version_id"],
                       "packet_code_version": manifest["packet_code_version"]}, sort_keys=True)
    rows = []
    shas = {n: i["sha256"] for n, i in manifest["files"].items()}
    shas["manifest.json"] = manifest_sha
    for name, sha in sorted(shas.items()):
        rel = f"{job_id}/{h12}/{name}"
        rows.append(("art-" + _sha(rel.encode("utf-8"))[:32], job_id, rel, sha, KINDS[name], manifest["created_at"], meta))
    try:
        with tx(con):
            for r in rows:
                con.execute("""INSERT OR IGNORE INTO artifacts (artifact_id, job_id, application_id, rel_path, sha256, kind,
                               created_at, meta_json) VALUES (?,?,NULL,?,?,?,?,?)""", r)
        ids = [r[0] for r in rows]
    except sqlite3.Error as e:
        warnings.append(f"registro em `artifacts` falhou ({type(e).__name__}: {e}); arquivos gravados mesmo assim")
    return ids, warnings


def build_packet(ctx, job_id: str, *, out_root: Path | None = None, headline_id: str | None = None) -> PacketResult:
    """Gera (ou reaproveita) o pacote de CV da versão atual da vaga com o perfil ativo. Não altera candidaturas."""
    if not isinstance(job_id, str) or not re.fullmatch(r"[0-9A-Za-z._-]{1,80}", job_id) or job_id in (".", ".."):
        raise PacketError("job_id inválido")
    con = ctx.con
    job = con.execute("SELECT * FROM job_records WHERE job_id=?", (job_id,)).fetchone()
    if job is None or not job["current_version_id"]:
        raise PacketError("vaga não encontrada ou sem versão atual")
    version = con.execute("SELECT * FROM job_versions WHERE version_id=?", (job["current_version_id"],)).fetchone()
    profile = active_profile(con)
    if profile is None:
        raise PacketError("nenhum perfil válido ativo")
    policy = (ctx.settings.matching or {}).get("policy_version", "matching-v1")
    row = con.execute("""SELECT result_json, policy_version FROM analyses WHERE job_version_id=? AND profile_id=?
                         AND method='deterministic' ORDER BY (policy_version=?) DESC, created_at DESC LIMIT 1""",
                      (version["version_id"], profile.profile_id, policy)).fetchone()
    if row is None:
        raise PacketError("esta versão da vaga ainda não tem análise com o perfil ativo; analise primeiro")
    analysis = json.loads(row["result_json"])
    policy = row["policy_version"]
    root = Path(out_root) if out_root is not None else (
        (ctx.temp_dir / "artifacts") if getattr(ctx, "dry_run", False) and getattr(ctx, "temp_dir", None)
        else ctx.paths.artifacts)
    root = root.resolve()
    input_hash = compute_input_hash(version["content_hash"], profile.profile_id, policy, headline_id)
    h12 = input_hash[:12]
    final = root / job_id / h12
    if not final.resolve().is_relative_to(root):
        raise PacketError("caminho de saída fora da raiz de artefatos")

    support = build_support(profile, analysis, None)
    if not support.get("available"):
        raise PacketError(f"preparo indisponível: {support.get('reason')}")

    if final.exists():  # T47: mesmas entradas => mesma pasta, nenhum byte reescrito
        manifest = _verify_existing(final, input_hash)
        msha = _sha((final / "manifest.json").read_bytes())
        ids, warns = _register(con, job_id, h12, manifest, msha)
        val = json.loads((final / "validation.json").read_text(encoding="utf-8"))["summary"]
        return PacketResult(job_id, input_hash, final, True,
                            {**{n: m["sha256"] for n, m in manifest["files"].items()}, "manifest.json": msha}, manifest, val["kept"], val["dropped"], ids, bool(ids), warns)

    cv, drops = compose_cv_data(profile, analysis, support, headline_id=headline_id)
    cv, report = validate_cv_data(cv, profile, drops)
    cv["job"] = {"job_id": job_id, "title": version["title"] or job["title"], "company": job["company_name"],
                 "version_id": version["version_id"], "version_hash": version["content_hash"],
                 "decision": analysis.get("decision")}
    cv["profile"] = {"profile_id": profile.profile_id, "origin": "config/profile/master.json"}
    cv["policy_version"] = policy
    cv["packet_code_version"] = PACKET_CODE_VERSION
    warnings = []
    if analysis.get("decision") in ("not_eligible", "weak_fit", "insufficient_data"):
        warnings.append(f"decisão da análise: {analysis.get('decision')}. O pacote foi gerado mesmo assim; revise antes de usar.")
    report.update({
        "job_id": job_id, "job_version_id": version["version_id"], "profile_id": profile.profile_id, "policy_version": policy,
        "analysis_decision": analysis.get("decision"), "warnings": warnings,
        "headline": {"chosen": (cv["headline"] or {}).get("text"), "note": cv.get("headline_note"),
                     "candidates": cv.get("headline_candidates")},
        "not_claimed": support.get("do_not_claim") or [], "unknowns": support.get("unknowns") or [],
    })
    answers = build_answers(profile)
    html_bytes = cv_render.render_html(cv).encode("utf-8")
    blobs = {"cv_data.json": _dump(cv), "answers.json": _dump(answers), "validation.json": _dump(report), "cv.html": html_bytes}
    manifest = {
        "schema_version": SCHEMA_VERSION, "kind": "cv_packet", "job_id": job_id,
        "job_version_id": version["version_id"], "job_version_hash": version["content_hash"],
        "profile_id": profile.profile_id, "policy_version": policy, "packet_code_version": PACKET_CODE_VERSION,
        "renderer": cv_render.renderer_id(), "input_hash": input_hash, "created_at": iso(),
        "files": {n: {"sha256": _sha(b), "bytes": len(b), "kind": KINDS[n]} for n, b in blobs.items()},
        "uses_ai": False, "sends_application": False, "application_state_changed": False,
        "note": "Gerar este pacote não significa candidatura enviada.",
    }
    blobs["manifest.json"] = _dump(manifest)
    parent = root / job_id
    parent.mkdir(parents=True, exist_ok=True)
    tmp = parent / f".tmp-{h12}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    tmp.mkdir()
    try:
        for name, data in blobs.items():
            (tmp / name).write_bytes(data)
        try:
            os.replace(tmp, final)
        except OSError:
            if final.exists():  # outro processo gerou o mesmo pacote entre a checagem e agora
                shutil.rmtree(tmp, ignore_errors=True)
                manifest = _verify_existing(final, input_hash)
            else:
                raise
    finally:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
    msha = _sha((final / "manifest.json").read_bytes())
    ids, warns = _register(con, job_id, h12, manifest, msha)
    return PacketResult(job_id, input_hash, final, False,
                        {**{n: m["sha256"] for n, m in manifest["files"].items()}, "manifest.json": msha}, manifest, report["summary"]["kept"], report["summary"]["dropped"], ids, bool(ids), warnings + warns)
