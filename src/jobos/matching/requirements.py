"""Extração de requisitos do texto COMPLETO do anúncio (sem corte silencioso, A08).

Distingue obrigatório, desejável e ambíguo por seção e por pistas na própria frase.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass

from jobos.domain.identity import fold

MAX_REQUIREMENTS = 60

H_MANDATORY = ["requisitos", "requisito", "qualificacoes", "qualificacao", "requirements", "required", "qualifications",
               "must have", "o que buscamos", "o que esperamos", "pre-requisitos", "pre requisitos", "perfil desejado",
               "o que voce precisa", "what you need", "what we are looking for", "what we're looking for",
               "minimum qualifications", "basic qualifications", "formacao", "experiencia necessaria", "competencias",
               "skills", "your profile", "seu perfil", "perfil", "knowledge, skills", "requisitos obrigatorios",
               "requisitos e qualificacoes", "esperamos que voce tenha", "about you"]
H_DESIRABLE = ["desejavel", "desejaveis", "diferenciais", "diferencial", "sera um diferencial", "nice to have",
               "preferred", "preferable", "bonus", "plus", "preferred qualifications", "requisitos desejaveis",
               "sera um plus", "it would be great"]
H_RESP = ["responsabilidades", "atividades", "atribuicoes", "responsibilities", "what you'll do", "what you will do",
          "principais atividades", "o que voce vai fazer", "duties", "descricao da vaga", "job description",
          "sobre a vaga", "your role", "the role", "key accountabilities", "accountabilities", "main activities"]
H_OTHER = ["beneficios", "benefits", "sobre a empresa", "about us", "sobre nos", "informacoes adicionais",
           "etapas do processo", "local de trabalho", "about the company", "what we offer", "o que oferecemos",
           "additional information", "equal opportunity", "jornada", "regime de contratacao"]

DESIRABLE_CUES = ["desirable", "a plus", "differential", "nice-to-have", "preferable", "competitive edge", "desejavel", "diferencial", "preferencialmente", "sera um plus", "e um plus", "nice to have",
                  "preferred", "preferably", "is a plus", "is an advantage", "nao obrigatorio", "not required",
                  "advantageous", "beneficial", "would be a plus"]
MANDATORY_CUES = ["obrigatorio", "obrigatoria", "imprescindivel", "indispensavel", "must", "required", "mandatory",
                  "exigido", "exigida", "essencial", "essential", "necessario", "necessaria"]
REQUIREMENT_CUES = ["experiencia", "experience", "conhecimento", "knowledge", "formacao", "graduacao", "graduado",
                    "bacharel", "degree", "engenharia", "engineering", "ingles", "english", "espanhol", "spanish",
                    "certificacao", "certificado", "certification", "cnh", "habilitacao", "crea", "nr-", "nr ",
                    "cbsp", "bosiet", "huet", "stcw", "pmp", "dominio", "proficiency", "fluente", "fluent",
                    "anos", "years", "curso", "superior completo", "tecnico", "pacote office", "excel", "sap",
                    "disponibilidade para", "availability to"]


@dataclass
class Requirement:
    text: str
    importance: str        # mandatory | desirable | ambiguous
    source: str            # description:<seção>


def _header_kind(line: str) -> str | None:
    if line.lstrip().startswith(("-", "•", "*", "·", "▪", "●", "–")):
        return None  # item de lista nunca é cabeçalho ("- BOSIET desejável")
    t = fold(line).strip(" :-–•*#").rstrip(":")
    if not t or len(t) > 70:
        return None
    looks_header = line.strip().endswith(":") or len(t.split()) <= 6
    if not looks_header:
        return None
    for kind, words in (("desirable", H_DESIRABLE), ("mandatory", H_MANDATORY), ("responsibilities", H_RESP),
                        ("other", H_OTHER)):
        if any(t == w or t.startswith(w + " ") or t.startswith(w + ":") for w in words):
            return kind
    return None


def _cue_importance(text: str, default: str) -> str:
    t = fold(text)
    if any(c in t for c in DESIRABLE_CUES):
        return "desirable"
    if any(re.search(rf"\b{re.escape(c)}\b", t) for c in MANDATORY_CUES):
        return "mandatory"
    return default


def _split_items(block: str) -> list[str]:
    parts = []
    for line in block.splitlines():
        line = line.strip(" \t-•*·▪●–")
        if not line or line.startswith("#") or line.count("#") >= 3:
            continue  # hashtags de divulgação não são requisitos
        pieces = [x.strip() for x in line.split(";")] if line.count(";") >= 1 else [line]
        for piece in pieces:
            if len(piece) > 160:  # parágrafo longo: quebra em frases
                parts += [x.strip() for x in re.split(r"(?<=[.!?])\s+(?=[A-ZÀ-Ý])", piece) if len(x.strip()) > 3]
            elif len(piece) > 3:
                parts.append(piece)
    return parts


def extract(description: str) -> tuple[list[Requirement], dict]:
    """Retorna (requisitos, metadados da extração)."""
    meta = {"description_length": len(description or ""), "sections_found": [], "method": "sections",
            "truncated_requirements": 0}
    if not description or len(description.strip()) < 40:
        meta["method"] = "none"
        return [], meta
    description = html.unescape(description).replace("\xa0", " ")  # legado guardava &nbsp;/&amp;
    lines = description.splitlines()
    current = None
    sections: dict[str, list[str]] = {}
    for line in lines:
        kind = _header_kind(line)
        if kind:
            current = kind
            meta["sections_found"].append(kind)
            rest = line.split(":", 1)[1].strip() if ":" in line and line.index(":") < len(line) - 1 else ""
            if rest:
                sections.setdefault(current, []).append(rest)
            continue
        if current:
            sections.setdefault(current, []).append(line)
    reqs: list[Requirement] = []
    for kind in ("mandatory", "desirable"):
        for item in _split_items("\n".join(sections.get(kind, []))):
            if len(item) < 4:
                continue
            reqs.append(Requirement(item, _cue_importance(item, kind), f"description:{kind}"))
    if not reqs:
        meta["method"] = "cue_scan"
        for item in _split_items(description):
            t = fold(item)
            if any(c in t for c in REQUIREMENT_CUES) and len(item) < 300:
                reqs.append(Requirement(item, _cue_importance(item, "ambiguous"), "description:sem_secao"))
    if len(reqs) > MAX_REQUIREMENTS:
        meta["truncated_requirements"] = len(reqs) - MAX_REQUIREMENTS
        reqs = reqs[:MAX_REQUIREMENTS]
    return reqs, meta
