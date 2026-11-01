"""Vocabulário e narrativa por família; não é um segundo motor de aderência."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from functools import lru_cache

import yaml

from jobos.domain.identity import fold

CONFIG = Path(__file__).resolve().parents[3] / "config" / "family_profiles.yaml"
ALIASES = {
    "schedule": ["cronograma", "cronogramas", "schedule", "scheduling", "planejamento físico"],
    "baseline": ["baseline", "linha de base"],
    "critical_path": ["caminho crítico", "critical path", "cpm"],
    "wbs": ["eap", "wbs", "estrutura analítica do projeto", "work breakdown structure"],
    "physical_progress": ["avanço físico", "progresso físico", "physical progress", "progress tracking"],
    "physical_financial_progress": ["físico-financeiro", "físico e financeiro", "physical-financial"],
    "plan_vs_actual": ["planejado x realizado", "planned vs actual", "plan vs actual"],
    "forecast": ["forecast", "forecasting", "previsão", "tendência de conclusão"],
    "lookahead": ["look-ahead", "lookahead", "look ahead"],
    "s_curve": ["curva s", "s-curve"], "kpi": ["kpi", "kpis", "indicadores"],
    "deviation": ["desvios", "deviation", "deviations"], "risk": ["riscos", "risk", "risks"],
    "action_followup": ["follow-up", "follow up"], "cost": ["custos", "cost", "costs"],
    "measurement": ["medições", "medição", "measurements"],
    "reporting": ["reporting", "relatórios", "reports"],
    "ms_project": ["ms project", "microsoft project", "ms-project"],
    "excel": ["excel"], "power_bi": ["power bi", "powerbi"],
    "primavera_p6": ["primavera p6", "oracle primavera", "p6"],
    "primavera_risk_analysis": ["primavera risk analysis"], "sap_ps": ["sap ps", "sap módulo ps"],
    "offshore_operations": ["operações offshore", "offshore operations"],
    "marine_operations": ["operações marítimas", "marine operations"],
    "vessel_shore": ["vessel-shore", "ship-shore", "base-embarcação", "shorebase interface"],
    "operational_readiness": ["prontidão", "readiness"],
    "resource_coordination": ["recursos", "resources"], "mobilization": ["mobilização", "mobilization"],
    "logistics": ["logística", "logistics"], "materials": ["materiais", "materials"],
    "suppliers": ["fornecedores", "suppliers", "vendors"], "simops": ["simops"],
    "hseq": ["hseq", "qsms", "hse", "qhse"], "procedures": ["procedimentos", "procedures"],
    "inspections": ["inspeções", "inspections"],
    "incident_response": ["resposta a emergências", "emergency response"],
    "corrective_actions": ["ações corretivas", "corrective actions"], "downtime": ["downtime"],
    "client_interface": ["interface com cliente", "client interface"],
    "vessel_master_interface": ["comandante", "vessel master"],
    "scope": ["escopo", "scope"], "stakeholders": ["stakeholders", "partes interessadas"],
    "engineering_deliverables": ["engineering deliverables", "entregáveis de engenharia"],
    "multidisciplinary_interfaces": ["interfaces multidisciplinares", "multidisciplinary interfaces"],
    "subcontractors": ["subcontratados", "subcontractors"],
    "change_management": ["gestão de mudanças", "change management"], "claims": ["claims", "pleitos"],
    "project_lifecycle": ["ciclo de vida", "project lifecycle"], "closeout": ["closeout", "encerramento"],
}


def profiles():
    return _profiles(CONFIG.stat().st_mtime_ns)


@lru_cache(maxsize=4)
def _profiles(version):
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def config_hash():
    return hashlib.sha256(CONFIG.read_bytes()).hexdigest()


EXACT_ALIASES = {fold(a): k for k, words in ALIASES.items() for a in words}
CONCEPT_PATTERN = re.compile(r"(?<![a-z0-9])(?:" + "|".join(
    re.escape(a) for a in sorted(EXACT_ALIASES, key=len, reverse=True)) + r")(?![a-z0-9])")


@lru_cache(maxsize=8192)
def concepts(text):
    return frozenset(EXACT_ALIASES[m.group()] for m in CONCEPT_PATTERN.finditer(fold(text)))


def classify(title, requirements):
    title = fold(title)
    excluded = bool(re.search(r"\b(quality|qualidade|reliability|confiabilidade|rotating|rotativos|process engineer|engenheiro de processos?|estagio|estagiari[oa]|internship)\b", title))
    found = set().union(*(concepts(t) for t in requirements)) if requirements else set()
    scores = {}
    for name, cfg in profiles().items():
        title_hit = any(re.search(r"\b" + re.escape(fold(t)) + r"\b", title) for t in cfg["title_terms"])
        overlap = found & set(cfg["core_concepts"])
        scores[name] = round(min(1, (0.55 if title_hit else 0) + 0.45 * len(overlap) / len(cfg["core_concepts"])), 3)
    ranked = sorted(scores, key=lambda k: (-scores[k], k))
    primary = ranked[0] if not excluded and scores[ranked[0]] >= 0.15 else None
    secondary = ranked[1] if primary and scores[ranked[1]] >= 0.15 else None
    return {"primary": primary, "secondary": secondary, "scores": scores,
            "out_of_scope": excluded or primary is None, "concepts": sorted(found),
            "method": "title 55% + canonical core concepts 45%; non-exclusive; not eligibility"}
