"""Índice de evidências do perfil canônico. Cada item aponta um JSON Pointer que resolve de verdade."""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from jobos.domain.identity import fold
from jobos.matching.profile import Profile

SOFTWARE_STATUS_VALUE = {
    "strong/proven": "met", "used/proven": "met", "used/proven independent-project": "partial",
    "applied-operationally": "met", "developing": "partial", "personal-project": "partial",
    "personal-project/developing": "partial", "personal-project/workflow": "partial",
    "listed-needs-context": "partial", "historical-training": "partial", "user-mentioned-unverified": "unknown",
    "do-not-claim": "gap",
}

# Aliases de busca para itens do perfil (minúsculas sem acento). Chave = id do nó.
SOFTWARE_ALIASES = {
    "sw_ms_project": ["ms project", "microsoft project", "ms-project"],
    "sw_primavera_p6": ["primavera", "p6", "oracle primavera"],
    "sw_power_bi": ["power bi", "powerbi"],
    "sw_excel": ["excel", "pacote office", "ms office", "microsoft office", "office 365"],
    "sw_powerpoint": ["powerpoint", "power point"],
    "sw_sap_rt": ["sap rt"],
    "sw_sql": ["sql"],
    "sw_python": ["python"],
    "sw_typescript": ["typescript"],
    "sw_javascript": ["javascript"],
    "sw_amos": ["amos"], "sw_hysys": ["hysys", "pro ii", "pro/ii"], "sw_orcaflex": ["orcaflex"],
    "sw_ansys": ["ansys"], "sw_mathcad": ["mathcad"], "sw_solidworks": ["solidworks"], "sw_smart_3d": ["smart 3d", "s3d"],
    "sw_smart_pid": ["smart p&id", "smartplant p&id"], "sw_skm": ["skm"],
}

# Disciplinas de formação reconhecidas no texto da vaga.
DISCIPLINES = {
    "civil": ["civil"], "mecanica": ["mecanic", "mechanical"], "naval": ["naval", "oceanic", "ocean engineering"],
    "eletrica": ["eletric", "electrical", "eletrotec"], "quimica": ["quimic", "chemical"],
    "producao": ["producao", "production engineering", "industrial engineering", "engenharia industrial"],
    "petroleo": ["petroleo", "petroleum"], "ambiental": ["ambiental", "environmental"],
    "automacao": ["automacao", "controle e automacao", "automation", "mecatronica", "mechatronic"],
    "computacao": ["computacao", "computer", "software", "sistemas de informacao", "ciencia da computacao"],
    "nautica": ["ciencias nauticas", "nautical"], "administracao": ["administracao", "business administration"],
    "economia": ["economia", "economics"], "contabeis": ["contabeis", "accounting"], "direito": ["direito", "law"],
    "geologia": ["geolog", "geophysic", "geofisic"], "logistica": ["logistica", "logistics", "supply chain"],
}


@dataclass
class EvidenceItem:
    pointer: str
    label: str
    status: str            # met | partial | gap | unknown
    qualifier: str = ""
    kind: str = ""


@dataclass
class EvidenceIndex:
    profile: Profile
    software: dict[str, EvidenceItem] = field(default_factory=dict)
    software_terms: list[tuple[str, str]] = field(default_factory=list)   # (alias fold, sw_id)
    education: dict[str, EvidenceItem] = field(default_factory=dict)
    certifications: dict[str, EvidenceItem] = field(default_factory=dict)
    english: EvidenceItem | None = None
    corporate_years: float = 0.0
    management_years: float = 0.0
    boundaries: list[tuple[str, str]] = field(default_factory=list)      # (texto fold, pointer)
    concepts: dict[str, list[EvidenceItem]] = field(default_factory=dict)

    def check(self) -> list[str]:
        """Pointers que não resolvem (deveria ser vazio)."""
        ptrs = [i.pointer for i in self.software.values()] + [i.pointer for i in self.education.values()] + \
               [i.pointer for i in self.certifications.values()] + [p for _, p in self.boundaries]
        return [p for p in ptrs if not self.profile.resolves(p)]


_MONTHS = {"jan": 1, "fev": 2, "feb": 2, "mar": 3, "abr": 4, "apr": 4, "mai": 5, "may": 5, "jun": 6, "jul": 7,
           "ago": 8, "aug": 8, "set": 9, "sep": 9, "out": 10, "oct": 10, "nov": 11, "dez": 12, "dec": 12}


def _parse_period(period) -> tuple[dt.date, dt.date] | None:
    if isinstance(period, dict) and period.get("start") and period.get("end") and period["end"] != "present":
        try:
            s = dt.date.fromisoformat(period["start"][:10] if len(period["start"]) >= 10 else period["start"] + "-01")
            e = dt.date.fromisoformat(period["end"][:10] if len(period["end"]) >= 10 else period["end"] + "-01")
            return s, e
        except ValueError:
            return None
    if isinstance(period, str):
        m = re.findall(r"([A-Za-zç]{3})\w*\s+(\d{4})", period)
        if len(m) == 2:
            try:
                return (dt.date(int(m[0][1]), _MONTHS[m[0][0].lower()[:3]], 1),
                        dt.date(int(m[1][1]), _MONTHS[m[1][0].lower()[:3]], 28))
            except (KeyError, ValueError):
                return None
    return None


def build_index(profile: Profile) -> EvidenceIndex:
    d = profile.data
    idx = EvidenceIndex(profile)
    from jobos.matching.families import profiles, concepts
    # Só campos afirmativos de experiências profissionais. Nunca varrer truth_boundaries/avoid como provas.
    roots = dict.fromkeys(key for f in profiles().values() for key in f["preferred_evidence"])
    for key in roots:
        base = "/experience_nodes/" + key.replace(".", "/")
        if not profile.resolves(base):
            continue
        value = profile.pointer(base)
        for i, fact in enumerate(value if isinstance(value, list) else []):
            if not isinstance(fact, str):
                continue
            for canonical in concepts(fact):
                idx.concepts.setdefault(canonical, []).append(EvidenceItem(
                    f"{base}/{i}", fact, "met", "same_skill_professional; priority=90", "professional_fact"))
    for group, items in (d.get("software_systems_tree") or {}).items():
        if group == "rules" or not isinstance(items, dict):
            continue
        for sid, node in items.items():
            if not isinstance(node, dict):
                continue
            status = SOFTWARE_STATUS_VALUE.get(node.get("status", ""), "unknown")
            qual = "" if status == "met" else f"status no perfil: {node.get('status')}"
            idx.software[sid] = EvidenceItem(f"/software_systems_tree/{group}/{sid}", node.get("name", sid), status, qual,
                                             "software")
            for alias in SOFTWARE_ALIASES.get(sid, [fold(node.get("name", ""))]):
                if alias:
                    idx.software_terms.append((fold(alias), sid))
    idx.software_terms.sort(key=lambda t: -len(t[0]))
    for eid, node in (d.get("education_tree") or {}).items():
        idx.education[eid] = EvidenceItem(f"/education_tree/{eid}", node.get("degree", eid),
                                          "met" if fold(node.get("status", "")).startswith("conclu") else "partial",
                                          node.get("status", ""), "education")
    for cid, node in (d.get("certification_training_tree") or {}).items():
        wording = node.get("current_safe_wording") or ""
        hist = node.get("historical_valid_until") or node.get("historical_validity") or node.get("historical_period")
        status = "partial" if ("reciclagem" in fold(wording) or hist) else "met"
        qual = wording or (f"validade histórica {hist}; validade atual não documentada" if hist else "")
        idx.certifications[cid] = EvidenceItem(f"/certification_training_tree/{cid}", node.get("name", cid), status, qual,
                                               "certification")
    eng = ((d.get("identity") or {}).get("languages") or {}).get("english") or {}
    if eng:
        level = fold(eng.get("level", ""))
        idx.english = EvidenceItem("/identity/languages/english", f"Inglês {eng.get('level')}",
                                   "met" if any(x in level for x in ("fluente", "avancado", "fluent")) else "partial",
                                   eng.get("level", ""), "language")
    total = 0.0
    for eid, node in (d.get("experience_nodes") or {}).items():
        if eid in ("exp_international_research", "exp_professional_development"):
            continue
        per = _parse_period(node.get("period"))
        if per:
            total += max(0.0, (per[1] - per[0]).days / 365.25)
    idx.corporate_years = round(total, 1)
    van = _parse_period(((d.get("experience_nodes") or {}).get("exp_vanoord") or {}).get("period"))
    idx.management_years = round((van[1] - van[0]).days / 365.25, 1) if van else 0.0
    for key, val in (d.get("truth_boundaries") or {}).items():
        if isinstance(val, list):
            for i, text in enumerate(val):
                if isinstance(text, str):
                    idx.boundaries.append((fold(text), f"/truth_boundaries/{key}/{i}"))
    return idx
