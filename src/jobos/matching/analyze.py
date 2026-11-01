"""Análise determinística por requisito com evidências (DEC-008).

Quatro respostas por requisito: met, partial, gap (lacuna comprovada pelo perfil), unknown.
Nota numérica só com cobertura suficiente; nunca é probabilidade. Prioridade é separada e transparente.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field

from jobos.domain.identity import fold
from jobos.matching.evidence import DISCIPLINES, EvidenceIndex, EvidenceItem, build_index
from jobos.matching.preferences import evaluate_preferences, priority_score
from jobos.matching.profile import active_profile
from jobos.matching.requirements import Requirement, extract
from jobos.storage import repo
from jobos.storage.db import tx
from jobos.timeutil import iso

MIN_DESCRIPTION = 200
CHUNK = 100

# Pistas de requisito → domínio do perfil (domain_tree). Domínio só vira "met" com prioridade alta no perfil.
DOMAIN_TERMS = {
    "naval_marine_offshore": ["operacoes maritimas", "marine operations", "maritim", "embarcac", "vessel", "navio",
                              "offshore", "naval", "portuari", "port ", "osv", "rebocador", "dp ", "marine"],
    "oil_gas_offshore": ["oleo e gas", "oil and gas", "oil & gas", "o&g", "petroleo", "fpso", "pre-sal", "upstream",
                         "drilling", "sonda"],
    "project_management_project_controls": ["gestao de projetos", "gerenciamento de projetos", "project management",
                                            "project controls", "controle de projetos", "pmbok", "pmi"],
    "planning_data_performance": ["planejamento", "planning", "cronograma", "schedule", "kpi", "indicadores",
                                  "look-ahead", "forecast", "curva s", "s-curve"],
    "maintenance_repairs_asset_readiness": ["manutencao", "maintenance", "reparo", "repair"],
    "logistics_materials_suppliers": ["logistica", "logistics", "suprimentos", "supply", "materiais", "fornecedores",
                                      "crew change", "mobilizacao"],
    "hseq_emergency_response": ["hse", "hsse", "qhse", "sms ", "seguranca do trabalho", "emergencia", "emergency",
                                "safety"],
    "quality_management_systems": ["qualidade", "quality", "iso 9001", "controle documental"],
    "commercial_contract_management": ["contratos", "contract", "medicao", "medicoes", "custos", "claims"],
}
HIGH_DOMAINS = {"naval_marine_offshore", "oil_gas_offshore", "project_management_project_controls",
                "planning_data_performance", "maintenance_repairs_asset_readiness", "logistics_materials_suppliers",
                "hseq_emergency_response"}

CERT_TERMS = {
    "cbsp": ["cbsp"], "bosiet": ["bosiet"], "huet": ["huet"], "thuet": ["t-huet", "thuet", "t huet"],
    "nr35": ["nr-35", "nr 35", "nr35"], "nr33": ["nr-33", "nr 33", "nr33"], "nr34": ["nr-34", "nr 34", "nr34"],
    "nr30": ["nr-30", "nr 30", "nr30"], "nr17": ["nr-17", "nr 17", "nr17"],
}
UNLISTED_CERTS = ["nr-10", "nr 10", "nr-12", "nr 12", "nr-13", "nr 13", "nr-20", "nr 20", "nr-37", "nr 37", "gwo",
                  "opito", "irata", "cswip", "nebosh", "iosh", "csp", "lead auditor", "auditor lider", "pmp", "pmi-sp",
                  "prince2", "cfa", "cpa", "oab", "cra"]
BOUNDARY_TERMS = [
    (["ciencias nauticas", "nautical science", "master mariner", "chief mate", "chief officer",
      "oficial de nautica", "oficial de quarto", "ccl", "ccb", "stcw ii/2", "stcw management", "watchkeeping",
      "capitao de longo curso", "capitao de cabotagem"],
     "/truth_boundaries/nautical_credentials", "credencial náutica que o perfil declara não possuir"),
    (["hysys", "pro ii", "process simulation", "simulacao de processo"], "/truth_boundaries/engineering_design/2",
     "simulação de processo não faz parte da experiência"),
    (["orcaflex", "ansys", "mathcad", "solidworks", "fea", "elementos finitos"], "/truth_boundaries/engineering_design/1",
     "ferramenta/competência de projeto declarada como não alegável"),
    (["subsea controls", "controles submarinos"], "/truth_boundaries/engineering_design/3", "subsea controls fora do perfil"),
    (["lead auditor", "auditor lider", "auditor iso"], "/truth_boundaries/quality/1", "auditoria formal não alegável"),
    (["production operator", "operador de producao", "fpso production operations", "operacao de producao de fpso"],
     "/truth_boundaries/fpso_production_and_commissioning/0", "operação de produção de FPSO não alegável"),
    (["amos"], "/truth_boundaries/vessel_technical_management/5", "AMOS declarado como não alegável"),
]


ROLE_LICENSED = ["enfermeir", "enfermagem", "nurse", "medico do trabalho", "medico", "physician", "advogad", "lawyer",
                 "attorney", "farmaceutic", "pharmacist", "psicolog", "dentist", "odontolog", "fisioterap", "nutricionist"]
ROLE_OFF = ["desenvolvedor", "developer", "programador", "software engineer", "engenheiro de software", "engenheira de software",
            "data scientist", "cientista de dados", "designer", "vendedor", "vendas", "sales", "account executive",
            "account manager", "recepcionista", "cozinheir", "taifeiro", "motorista", "eletricista", "soldador", "welder",
            "caldeireiro", "pintor industrial", "marinheiro", "moco de convés", "contas a pagar",
            "contas a receber", "contabil", "contador", "fiscal tributario", "tributari", "recrutador", "recruiter",
            "talent acquisition", "marketing", "juridico", "piloto de rov", "rov pilot", "operador de rov", "tecnico de rov",
            "backend", "back-end", "frontend", "front-end", "full stack", "fullstack", "devops", "sap consultant",
            "consultor sap", "consultant", "consultor", "auditor fiscal", "advisory", "economist", "economista",
            "tesouraria", "treasury", "payroll", "folha de pagamento", "comprador", "assistente administrativo"]
# Área explícita fora da trajetória vence palavras genéricas como "planejamento" ("Planejamento Financeiro").
ROLE_OFF_STRONG = ["financeir", "fp&a", "contabil", "contador", "controladoria", "tributari", "fiscal", "juridic",
                   "advog", "marketing", "vendas", "comercial", "recursos humanos", "folha de pagamento", "tesouraria",
                   "credito", "cobranca", "desenvolvedor", "developer", "software", "investimentos", "auditoria interna"]
ROLE_NATURAL = ["operations engineer", "engenheiro de operacoes", "engenheira de operacoes", "operacoes maritimas",
                "marine operations", "offshore operations", "planejamento", "planner", "planning", "project controls",
                "controle de projetos", "project engineer", "engenheiro de projetos", "engenheira de projetos",
                "coordenador de projetos", "coordenadora de projetos", "logistica", "logistics", "shorebase",
                "base de apoio", "vessel", "embarcac", "superintend", "qhse", "hsse", "sms", "qualidade", "quality",
                "coordenador de operacoes", "coordenadora de operacoes", "operations coordinator", "fleet", "frota",
                "package coordinator", "coordenador de pacotes", "readiness", "subcontract", "supplier", "fornecedores",
                "maritim", "operacoes offshore", "emergency response", "resposta a emergencia"]
ROLE_TIER_X = ["master mariner", "captain", "comandante", "chief mate", "imediato", "fpso production", "operador de producao",
               "process engineer", "engenheiro de processo", "subsea controls", "structural", "estrutural", "fea"]


ROLE_LEVEL_BELOW = ["technician", "tecnico", "tecnica", "tech", "operator", "operador", "operadora", "inspector",
                    "inspetor", "inspetora", "assistente", "assistant", "auxiliar", "expeditor", "trainee", "estagi",
                    "aprendiz", "jovem", "intern", "junior", "jr", "analista i", "analyst i"]


def _prefix(t: str, terms) -> bool:
    return any(re.search(rf"(?<![a-z0-9]){re.escape(x)}", t) for x in terms)


def role_fit(title: str) -> dict:
    t = fold(title)
    if re.search(r"\b(?:estagio|estagiari[oa]s?|internship|intern|interns|aprendiz|apprentice)\b", t):
        return {"label": "internship", "reason": "estágio/aprendizagem fora do nível profissional do perfil; excluído da seleção automática"}
    if _prefix(t, ROLE_LICENSED):
        return {"label": "off_profile_licensed", "reason": "profissão regulamentada fora da formação do perfil"}
    if _prefix(t, ROLE_TIER_X):
        return {"label": "tier_x", "reason": "função listada em role_fit_tree.tier_X (eliminatória se obrigatória)"}
    if _prefix(t, ROLE_OFF_STRONG):
        return {"label": "off_profile", "reason": "área da função fora da trajetória documentada no perfil"}
    natural = _prefix(t, ROLE_NATURAL)
    if _prefix(t, ROLE_OFF) and not natural:
        return {"label": "off_profile", "reason": "função fora da trajetória documentada no perfil"}
    if _has(t, ROLE_LEVEL_BELOW):
        return {"label": "level_below", "reason": "nível técnico/operacional/júnior abaixo da trajetória documentada"}
    if natural:
        return {"label": "natural", "reason": "título alinhado a role_fit_tree (tiers A/B)"}
    return {"label": "unknown", "reason": "função não classificada automaticamente"}


@dataclass
class Evaluated:
    req: Requirement
    category: str
    status: str
    evidence: list[dict] = field(default_factory=list)
    explanation: str = ""


def _ev(item: EvidenceItem) -> dict:
    return {"pointer": item.pointer, "label": item.label, "qualifier": item.qualifier}


def _has(t: str, terms) -> bool:
    return any(re.search(rf"(?<![a-z0-9]){re.escape(x)}(?![a-z0-9])", t) for x in terms)


def evaluate(req: Requirement, idx: EvidenceIndex) -> Evaluated:
    t = fold(req.text)
    # 1) limites de verdade: lacuna comprovada
    for terms, ptr, why in BOUNDARY_TERMS:
        if _has(t, terms) and idx.profile.resolves(ptr):
            return Evaluated(req, "truth_boundary", "gap", [{"pointer": ptr, "label": "truth_boundaries"}],
                             f"Lacuna: {why}.")
    # 2) formação (só com pista de grau; "engenharia de software" sozinha não é formação)
    if _has(t, ["cursando", "estudante", "enrolled", "currently studying", "matriculado", "formatura prevista"]):
        return Evaluated(req, "student_status", "gap", [],
                         "Matrícula atual exigida não comprovada; graduação concluída não comprova vínculo de estudante.")
    if _has(t, ["graduacao", "graduado", "graduada", "formacao", "formado", "formada", "bacharel", "bacharelado",
                "bachelor", "bachelor's", "degree", "ensino superior", "nivel superior", "superior completo",
                "curso superior", "curso tecnico", "formacao tecnica", "tecnico em", "tecnologo", "graduate in",
                "graduation"]) and not _has(t, ["experiencia", "experience", "anos", "years"]):
        return _education(req, t, idx)
    # 3) certificações
    for cid, terms in CERT_TERMS.items():
        if _has(t, terms) and cid in idx.certifications:
            item = idx.certifications[cid]
            return Evaluated(req, "certification", item.status, [_ev(item)],
                             f"{item.label}: {item.qualifier or 'registrado'}. Validade atual não é declarada."
                             if item.status == "partial" else f"{item.label} registrado no perfil.")
    if _has(t, UNLISTED_CERTS):
        return Evaluated(req, "certification", "unknown", [], "Certificação não consta no perfil canônico; confirmar.")
    if _has(t, ["crea", "registro profissional", "conselho de classe"]):
        crea = idx.profile.data.get("identity", {}).get("crea") or {}
        if fold(crea.get("status", "")) == "ativo":
            return Evaluated(req, "registration", "met", [{"pointer": "/identity/crea", "label": "CREA ativo"}],
                             "CREA ativo segundo o perfil (atribuição profissional não inferida).")
    # 4) idiomas
    if _has(t, ["ingles", "english"]):
        if idx.english:
            return Evaluated(req, "language", idx.english.status, [_ev(idx.english)], f"{idx.english.label}.")
    if _has(t, ["espanhol", "spanish", "frances", "french", "alemao", "german", "italiano", "italian",
                "noruegues", "norwegian", "mandarim", "chinese"]):
        return Evaluated(req, "language", "unknown", [{"pointer": "/identity/languages/other_languages",
                                                        "label": "outros idiomas"}],
                         "Outros idiomas não documentados no perfil.")
    # 5) CNH
    if _has(t, ["cnh", "habilitacao", "driver"]):
        cat = re.search(r"\b(?:categoria|cat\.?)\s*([a-e]{1,2})\b", t)
        if cat and cat.group(1) not in ("b", "ab"):
            return Evaluated(req, "license", "gap", [{"pointer": "/mobility_and_preferences/drivers_license",
                                                       "label": "CNH B"}], f"Perfil registra CNH B; vaga pede {cat.group(1).upper()}.")
        return Evaluated(req, "license", "met", [{"pointer": "/mobility_and_preferences/drivers_license", "label": "CNH B"}],
                         "CNH B registrada.")
    # 7) anos de experiência
    m = re.search(r"(\d{1,2})\s*\+?\s*(?:anos|years|ano|year)", t)
    if m and _has(t, ["experiencia", "experience", "atuacao", "vivencia"]):
        need = int(m.group(1))
        if _has(t, ["gestao", "gerencia", "lideranca", "coordenacao", "management", "leadership", "gerente", "manager",
                    "supervisao", "supervisor", "superintend"]):
            have, ptr = idx.management_years, "/truth_boundaries/management_tenure"
            if need <= have:
                return Evaluated(req, "experience_years", "met", [{"pointer": ptr, "label": "gestão"}],
                                 f"Pede {need} anos de gestão; perfil documenta {have:.1f} (Superintendente Van Oord).")
            return Evaluated(req, "experience_years", "gap", [{"pointer": ptr, "label": "gestão"}],
                             f"Pede {need} anos de gestão; perfil documenta {have:.1f}. Não arredondar (truth_boundaries).")
        domains = [k for k, terms in DOMAIN_TERMS.items() if _has(t, terms)]
        have = idx.corporate_years
        ptr = "/experience_nodes"
        if need > have:
            return Evaluated(req, "experience_years", "gap", [{"pointer": ptr, "label": "experiência corporativa"}],
                             f"Pede {need} anos; experiência corporativa documentada ≈ {have:.1f} anos.")
        if domains and any(d in HIGH_DOMAINS for d in domains):
            return Evaluated(req, "experience_years", "partial",
                             [{"pointer": f"/domain_tree/{d}", "label": d} for d in domains],
                             f"{have:.1f} anos corporativos totais; tempo específico no domínio solicitado não comprovado automaticamente.")
        return Evaluated(req, "experience_years", "partial", [{"pointer": ptr, "label": "experiência corporativa"}],
                         f"Tempo atendido ({have:.1f} anos), mas o domínio exigido não foi verificado automaticamente.")
    # 6) software
    if _has(t, ["sap ps", "sap modulo ps", "sap module ps", "primavera risk analysis"]):
        return Evaluated(req, "software", "unknown", [],
                         "Ferramenta específica não comprovada; SAP RT não equivale a SAP PS, P6 não equivale a Risk Analysis.")
    found = []
    for alias, sid in idx.software_terms:
        if len(alias) >= 2 and _has(t, [alias]) and sid not in [f[0] for f in found]:
            found.append((sid, idx.software[sid]))
    if found:
        statuses = [f[1].status for f in found]
        order = {"gap": 0, "unknown": 1, "partial": 2, "met": 3}
        any_of = _has(t, ["ou", "or"]) or "/" in req.text
        status = max(statuses, key=order.get) if any_of else min(statuses, key=order.get)
        expl = "; ".join(f"{f[1].label}: {f[1].qualifier or 'uso profissional comprovado'}" for f in found)
        return Evaluated(req, "software", status, [_ev(f[1]) for f in found], expl)
    # 8) domínio
    from jobos.matching.families import concepts, ALIASES
    canonical = concepts(req.text)
    matched = {c: idx.concepts[c][0] for c in canonical if c in idx.concepts}
    if matched:
        residue = t
        for c in canonical:
            for alias in sorted(ALIASES[c], key=len, reverse=True):
                residue = re.sub(r"(?<![a-z0-9])" + re.escape(fold(alias)) + r"(?![a-z0-9])", " ", residue)
        residue = re.sub(r"\b(experiencia|experience|conhecimento|knowledge|em|in|with|com|e|and|de|do|da|the|required|obrigatorio)\b", " ", residue)
        atomic = not re.search(r"[a-z0-9]", residue)
        complete = len(matched) == len(canonical) and atomic
        return Evaluated(req, "professional_fact", "met" if complete else "partial",
                         [_ev(item) for item in matched.values()],
                         "Fatos profissionais encontrados: " + "; ".join(item.label for item in matched.values()) +
                         ("." if complete else ". Escopo restante não comprovado automaticamente."))
    domains = [k for k, terms in DOMAIN_TERMS.items() if _has(t, terms)]
    if domains and idx.profile.resolves(f"/domain_tree/{domains[0]}"):
        high = [d for d in domains if d in HIGH_DOMAINS]
        status = "partial"  # afinidade de domínio não comprova o escopo integral de uma frase
        return Evaluated(req, "domain", status, [{"pointer": f"/domain_tree/{d}", "label": d} for d in domains],
                         f"Domínio relacionado no perfil: {', '.join(domains)}." +
                         ("" if status == "met" else " Verificar o escopo exato do requisito."))
    return Evaluated(req, "other", "unknown", [], "Sem regra determinística para este requisito; revisar.")


def _education(req: Requirement, t: str, idx: EvidenceIndex) -> Evaluated:
    civil = idx.education.get("edu_civil")
    ev = [_ev(civil)] if civil else []
    if _has(t, ["mba", "pos-graduacao", "pos graduacao", "especializacao", "postgraduate"]) and \
            _has(t, ["projetos", "project"]) and "edu_mba_pm" in idx.education:
        return Evaluated(req, "education", "met", [_ev(idx.education["edu_mba_pm"])], "MBA em Gestão de Projetos.")
    named = [k for k, terms in DISCIPLINES.items() if any(x in t for x in terms)]
    technical = _has(t, ["curso tecnico", "formacao tecnica", "tecnico em", "nivel tecnico"]) and \
        not _has(t, ["superior", "graduacao", "bacharel", "engenharia", "degree"])
    if technical:
        ports = idx.education.get("edu_ports")
        if ports and _has(t, ["portos", "portuario", "logistica"]):
            return Evaluated(req, "education", "met", [_ev(ports)], "Técnico em Portos (concluído).")
        return Evaluated(req, "education", "gap" if named else "unknown", [_ev(ports)] if ports else [],
                         f"Vaga pede formação técnica{' em ' + ', '.join(named) if named else ''}; perfil tem Técnico em "
                         "Portos e Engenharia Civil." + (" Não equivalente." if named else ""))
    if "nautica" in named:
        return Evaluated(req, "education", "gap", [{"pointer": "/truth_boundaries/nautical_credentials/0",
                                                    "label": "Ciências Náuticas"}], "Perfil não possui Ciências Náuticas.")
    related = _has(t, ["afins", "correlatas", "relacionadas", "related", "similar", "equivalent", "equivalente",
                       "areas correlatas", "engenharias"])
    if not named:
        if _has(t, ["engenharia", "engineering", "engenheiro", "engineer", "superior", "graduacao", "degree", "bacharel"]):
            return Evaluated(req, "education", "met", ev,
                             "Formação exigida genérica; perfil: Bacharelado em Engenharia Civil (concluído).")
        return Evaluated(req, "education", "unknown", ev, "Formação não identificada com clareza.")
    if "civil" in named:
        return Evaluated(req, "education", "met", ev, "Engenharia Civil está entre as formações aceitas.")
    if related:
        return Evaluated(req, "education", "partial", ev,
                         f"Vaga cita {', '.join(named)} ou áreas afins; perfil é Engenharia Civil. Aceitação depende do recrutador.")
    return Evaluated(req, "education", "gap", ev,
                     f"Vaga exige formação em {', '.join(named)}; perfil registra Engenharia Civil (não equivalente).")


def score(evals: list[Evaluated], cfg: dict) -> dict:
    w = cfg.get("weights") or {}
    vals = cfg.get("status_values") or {"met": 1.0, "partial": 0.5, "gap": 0.0}
    total = evaluable = points = 0.0
    for e in evals:
        weight = float(w.get(e.req.importance, 1))
        total += weight
        if e.status in vals:
            evaluable += weight
            points += weight * float(vals[e.status])
    coverage = round(evaluable / total, 3) if total else 0.0
    raw = (points / evaluable * 100) if evaluable else None
    fit = round(points / total * 100, 1) if total and coverage >= float(cfg.get("min_coverage_for_score", 0.6)) else None
    return {"coverage": coverage, "fit_score": fit, "known_items_score": round(raw, 1) if raw is not None else None,
            "audit": {"total_weight": total, "evaluated_weight": evaluable, "earned_points": points,
                      "weights": w, "status_values": {**vals, "unknown": 0.0},
                      "formula": "100 × soma(peso × valor) / soma de TODOS os pesos; desconhecido vale zero",
                      "minimum_coverage": float(cfg.get("min_coverage_for_score", 0.6))}}


def analyze_version(con: sqlite3.Connection, job: sqlite3.Row, version: sqlite3.Row, profile, idx: EvidenceIndex,
                    settings, source_priority: int) -> dict:
    cfg = settings.matching
    description = version["description"] or ""
    reqs, meta = extract(description) if len(description) >= MIN_DESCRIPTION else ([], {"method": "none",
                                                                                       "description_length": len(description)})
    evals = [evaluate(r, idx) for r in reqs]
    sc = score(evals, cfg)
    hard_gap = [e for e in evals if e.req.importance == "mandatory" and e.status == "gap"
                and e.category in ("education", "truth_boundary", "license", "certification", "student_status")]
    th = cfg.get("decision_thresholds") or {}
    if len(description) < MIN_DESCRIPTION:
        decision, why = "insufficient_data", "Descrição ausente ou curta; análise parcial."
    elif hard_gap:
        decision, why = "not_eligible", f"Requisito obrigatório com lacuna comprovada: {hard_gap[0].req.text[:120]}"
    elif not reqs:
        decision, why = "needs_review", "Nenhum requisito extraído automaticamente."
    elif sc["fit_score"] is None:
        decision, why = "needs_review", f"Cobertura {sc['coverage']:.0%} abaixo do mínimo para nota."
    elif sc["fit_score"] >= float(th.get("good_fit", 70)):
        decision, why = "good_fit", "Boa aderência nos requisitos avaliáveis."
    elif sc["fit_score"] < float(th.get("weak_fit", 40)):
        decision, why = "weak_fit", "Baixa aderência nos requisitos avaliáveis."
    else:
        decision, why = "needs_review", "Aderência intermediária."
    role = role_fit(job["title"] or "")
    uncapped_score = sc["fit_score"]
    if role["label"] == "internship":
        decision, why = "not_eligible", role["reason"]
        sc["fit_score"] = 0.0
    if role["label"] == "off_profile_licensed":
        decision, why = "not_eligible", f"Função: {role['reason']}."
    elif role["label"] == "off_profile" and decision in ("good_fit", "needs_review", "insufficient_data"):
        decision, why = "weak_fit", f"Função: {role['reason']} (requisitos genéricos não compensam)."
    elif role["label"] in ("tier_x", "level_below") and decision == "good_fit":
        decision, why = "needs_review", f"Função: {role['reason']}."
    cap = {"not_eligible": 0, "weak_fit": 39}.get(decision)
    if role["label"] in ("tier_x", "level_below"):
        cap = min(cap if cap is not None else 59, 59)
    if cap is not None and sc["fit_score"] is not None:
        sc["fit_score"] = min(sc["fit_score"], cap)
    if decision == "good_fit" and any(e.req.importance == "mandatory" and e.status != "met" for e in evals):
        decision, why = "needs_review", "Há requisito obrigatório parcial, desconhecido ou não atendido; revisão necessária."
    from jobos.matching.families import classify
    family = classify(job["title"] or "", [r.text for r in reqs])
    confidence = "high" if sc["coverage"] >= 0.8 and len(reqs) >= 5 else "medium" if sc["coverage"] >= 0.6 else "low"
    prefs = evaluate_preferences(job, version, settings.preferences)
    prefs["role_fit"] = role
    prio = priority_score(decision, prefs, job, source_priority, settings.preferences)
    unknowns = [e.req.text for e in evals if e.status == "unknown"][:10]
    if meta.get("truncated_requirements"):
        unknowns.append(f"{meta['truncated_requirements']} requisitos além do limite de {len(reqs)} não avaliados")
    if version["description_status"] in ("partial", "truncated"):
        unknowns.append(f"Descrição {version['description_status']}: {version['truncation_note'] or 'texto incompleto'}")
    result = {
        "schema_version": 1, "job_version_id": version["version_id"], "profile_version_id": profile.profile_id,
        "policy_version": cfg.get("policy_version", "matching-v1"), "method": "deterministic",
        "decision": decision, "decision_reason": why, "fit_score": sc["fit_score"], "coverage": sc["coverage"],
        "known_items_score": sc["known_items_score"], "confidence": confidence, "extraction": meta,
        "family": family, "eligibility": {"eligible": decision != "not_eligible", "requires_review": decision != "good_fit",
                                          "hard_gaps": [e.req.text for e in hard_gap]},
        "score_audit": {**sc["audit"], "before_gates": uncapped_score, "cap": cap,
                        "gate_reason": why, "final_score": sc["fit_score"]},
        "requirements": [{"requirement_id": f"req-{i + 1}", "text": e.req.text, "importance": e.req.importance,
                          "category": e.category, "requirement_source": e.req.source, "status": e.status,
                          "weight": float((cfg.get("weights") or {}).get(e.req.importance, 1)),
                          "value": float((cfg.get("status_values") or {}).get(e.status, 0)),
                          "evidence_refs": e.evidence, "explanation": e.explanation} for i, e in enumerate(evals)],
        "strengths": [e.req.text for e in evals if e.status == "met"][:8],
        "gaps": [e.req.text for e in evals if e.status == "gap"][:8],
        "unknowns": unknowns, "preferences": prefs, "priority": prio,
        "next_action": _next_action(decision, prefs),
        "limitations": "Análise determinística por regras; não é probabilidade de entrevista ou contratação.",
    }
    analysis_id = repo.new_id("an-")
    con.execute("""INSERT INTO analyses (analysis_id, job_id, job_version_id, profile_id, policy_version, method, decision,
                     fit_score, coverage, confidence, priority, preference_json, result_json, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (analysis_id, job["job_id"], version["version_id"], profile.profile_id, result["policy_version"],
                 "deterministic", decision, sc["fit_score"], sc["coverage"], confidence, prio["total"],
                 repo.dumps(prefs), repo.dumps(result), iso()))
    for i, e in enumerate(evals):
        con.execute("""INSERT INTO requirements (requirement_id, analysis_id, ord, text, category, importance,
                         requirement_source, status, evidence_json, explanation) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (f"{analysis_id}:{i + 1}", analysis_id, i + 1, e.req.text, e.category, e.req.importance, e.req.source,
                     e.status, repo.dumps(e.evidence), e.explanation))
    return {"analysis_id": analysis_id, "decision": decision, "fit_score": sc["fit_score"], "coverage": sc["coverage"]}


def _next_action(decision: str, prefs: dict) -> str:
    if prefs.get("excluded_employer"):
        return "Empregador excluído por preferência; manter só como histórico."
    return {"good_fit": "Revisar descrição e preparar currículo.",
            "needs_review": "Revisar requisitos desconhecidos/obrigatórios.",
            "weak_fit": "Provavelmente descartar; confirmar lacunas.",
            "not_eligible": "Lacuna obrigatória comprovada; descartar salvo exceção.",
            "insufficient_data": "Abrir o anúncio oficial; descrição ausente."}.get(decision, "Revisar.")


def _pending_query(policy: str, profile_id: str, job_id: str | None = None):
    sql = """SELECT j.*, v.version_id AS v_id FROM job_records j JOIN job_versions v ON v.version_id=j.current_version_id
             WHERE NOT EXISTS (SELECT 1 FROM analyses a WHERE a.job_version_id=v.version_id AND a.profile_id=?
                               AND a.policy_version=? AND a.method='deterministic')"""
    args: list = [profile_id, policy]
    if job_id:
        sql += " AND j.job_id=?"
        args.append(job_id)
    return sql, args


def analyze_pending(ctx, job_ids: list[str] | None = None) -> dict:
    profile = active_profile(ctx.con)
    if profile is None:
        return {"analyzed": 0, "error": "nenhum perfil válido ativo"}
    idx = build_index(profile)
    policy = ctx.settings.matching.get("policy_version", "matching-v1")
    sql, args = _pending_query(policy, profile.profile_id)
    rows = ctx.con.execute(sql, args).fetchall()
    prio = {s.company_id: s.priority for s in ctx.registry.sources}
    counts: dict[str, int] = {}
    todo = [j for j in rows if not job_ids or j["job_id"] in job_ids]
    for start in range(0, len(todo), CHUNK):  # transações curtas: API e CLI não ficam bloqueadas
        with tx(ctx.con):
            for job in todo[start:start + CHUNK]:
                if ctx.con.execute("""SELECT 1 FROM analyses WHERE job_version_id=? AND profile_id=? AND policy_version=?
                                      AND method='deterministic'""", (job["v_id"], profile.profile_id, policy)).fetchone():
                    continue  # outro processo (CLI/API/ciclo) analisou entre a consulta e a transação
                version = ctx.con.execute("SELECT * FROM job_versions WHERE version_id=?", (job["v_id"],)).fetchone()
                out = analyze_version(ctx.con, job, version, profile, idx, ctx.settings, prio.get(job["company_id"], 3))
                counts[out["decision"]] = counts.get(out["decision"], 0) + 1
    return {"analyzed": sum(counts.values()), "by_decision": counts, "profile_id": profile.profile_id[:16],
            "policy_version": policy}


def analyze_job(ctx, job_id: str, force: bool = False) -> dict:
    profile = active_profile(ctx.con)
    if profile is None:
        return {"error": "nenhum perfil válido ativo"}
    job = ctx.con.execute("SELECT * FROM job_records WHERE job_id=?", (job_id,)).fetchone()
    version = ctx.con.execute("SELECT * FROM job_versions WHERE version_id=?", (job["current_version_id"],)).fetchone()
    policy = ctx.settings.matching.get("policy_version", "matching-v1")
    existing = ctx.con.execute("""SELECT result_json FROM analyses WHERE job_version_id=? AND profile_id=? AND policy_version=?
                                  AND method='deterministic'""", (version["version_id"], profile.profile_id, policy)).fetchone()
    if existing and not force:
        import json
        return json.loads(existing["result_json"])
    prio = {s.company_id: s.priority for s in ctx.registry.sources}
    with tx(ctx.con):
        if existing:
            ids = [r[0] for r in ctx.con.execute("""SELECT analysis_id FROM analyses WHERE job_version_id=? AND profile_id=?
                                                    AND policy_version=? AND method='deterministic'""",
                                                 (version["version_id"], profile.profile_id, policy))]
            for aid in ids:  # reanálise forçada da MESMA versão substitui; versões anteriores ficam preservadas
                ctx.con.execute("DELETE FROM requirements WHERE analysis_id=?", (aid,))
                ctx.con.execute("DELETE FROM analyses WHERE analysis_id=?", (aid,))
        out = analyze_version(ctx.con, job, version, profile, build_index(profile), ctx.settings,
                              prio.get(job["company_id"], 3))
    return out
