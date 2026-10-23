"""Preparo de candidatura a partir do perfil canônico. Não gera CV, não chama IA e não envia nada.

Seleciona textos que já existem no JSON (ponteiro, safe_wording, história) e recusa escolha automática
quando mais de um headline cobre os mesmos domínios.
"""
from __future__ import annotations

from jobos.domain.identity import fold
from jobos.matching.analyze import DOMAIN_TERMS, _has
from jobos.matching.profile import Profile

PUBLIC_PROFILE_URL = "https://rvalle.com.br/rafael.json"
LIMITS = ("Este preparo só reordena fatos já escritos no perfil. Não cria frase de CV, "
          "não envia candidatura e não estima chance de entrevista.")
MAX_STORIES = 4
MAX_CANDIDATES = 4


def build_support(profile: Profile | None, analysis: dict | None, official_url: str | None = None) -> dict:
    base = {"schema_version": 1, "method": "deterministic", "writes_cv": False, "sends_application": False,
            "uses_ai": False, "limits": LIMITS, "public_profile_url": PUBLIC_PROFILE_URL}
    if profile is None:
        return {**base, "available": False, "reason": "Nenhum perfil válido ativo.", "checklist": _checklist(None)}
    if not analysis:
        return {**base, "available": False, "profile_id": profile.profile_id,
                "reason": "Esta vaga ainda não tem análise da versão atual.", "checklist": _checklist(official_url)}
    reqs = [r for r in (analysis.get("requirements") or []) if isinstance(r, dict)]
    domains = _active_domains(reqs)
    headline, candidates, rule = _headlines(profile, domains)
    return {
        **base,
        "available": True,
        "profile_id": profile.profile_id,
        "profile_origin": "config/profile/master.json",
        "display_name": _str(profile.data.get("identity") or {}, "professional_display"),
        "one_liner": _str(profile.data.get("career_summary") or {}, "canonical_one_liner"),
        "decision": analysis.get("decision"),
        "domains": domains,
        "headline": headline,
        "headline_candidates": candidates,
        "headline_rule": rule,
        "use": [_use_row(profile, r) for r in reqs if r.get("status") in ("met", "partial")],
        "do_not_claim": _gaps(reqs),
        "stories": _stories(profile, domains),
        "unknowns": [u for u in (analysis.get("unknowns") or []) if isinstance(u, str)][:8],
        "checklist": _checklist(official_url),
    }


def _str(node: dict, key: str) -> str | None:
    value = node.get(key)
    return value if isinstance(value, str) and value else None


def _active_domains(reqs: list[dict]) -> list[str]:
    found: list[str] = []
    for req in reqs:
        if req.get("status") not in ("met", "partial"):
            continue
        text = fold(req.get("text") if isinstance(req.get("text"), str) else "")
        for domain, terms in DOMAIN_TERMS.items():
            if domain not in found and _has(text, terms):
                found.append(domain)
        for ref in req.get("evidence_refs") or []:
            pointer = ref.get("pointer") if isinstance(ref, dict) else ""
            if isinstance(pointer, str) and pointer.startswith("/domain_tree/"):
                domain = pointer.split("/", 3)[2]
                if domain and domain not in found:
                    found.append(domain)
    return found


def _headlines(profile: Profile, domains: set[str] | list[str]) -> tuple[dict | None, list[dict], str]:
    active = set(domains)
    raw = profile.data.get("positioning_layer") or {}
    items = raw.get("headline_templates") if isinstance(raw, dict) else None
    scored: list[tuple[int, dict]] = []
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("headline_en"), str):
                continue
            tags = [d for d in (item.get("domains") or []) if isinstance(d, str)]
            overlap = len(active.intersection(tags))
            if overlap:
                scored.append((overlap, {"id": item["id"] if isinstance(item.get("id"), str) else None,
                                         "headline_en": item["headline_en"], "domains": tags, "overlap": overlap}))
    scored.sort(key=lambda pair: (-pair[0], str(pair[1].get("id") or "")))
    candidates = [row for _, row in scored[:MAX_CANDIDATES]]
    if not candidates:
        return None, [], "Nenhum headline do perfil compartilha domínio com os requisitos atendidos."
    winner = candidates[0]
    second = candidates[1]["overlap"] if len(candidates) > 1 else 0
    if winner["overlap"] > second:
        rule = "Um headline cobre mais domínios desta vaga do que os demais. A frase é a do perfil, sem edição."
        return winner, candidates, rule
    return None, candidates, ("Mais de um headline cobre estes domínios. Nenhum foi escolhido. "
                              "A escolha fica com você.")


def _wording(node: object) -> str | None:
    if not isinstance(node, dict):
        return None
    for key in ("current_safe_wording", "safe_wording"):
        value = node.get(key)
        if isinstance(value, str) and value and value != "UNKNOWN_NOT_DOCUMENTED":
            return value
    return None


def _use_row(profile: Profile, req: dict) -> dict:
    evidence = []
    for ref in req.get("evidence_refs") or []:
        if not isinstance(ref, dict):
            continue
        pointer = ref.get("pointer") if isinstance(ref.get("pointer"), str) else ""
        item = {"pointer": pointer, "label": ref.get("label") if isinstance(ref.get("label"), str) else "",
                "qualifier": ref.get("qualifier") if isinstance(ref.get("qualifier"), str) else ""}
        if pointer and profile.resolves(pointer):
            wording = _wording(profile.pointer(pointer))
            if wording:
                item["profile_wording"] = wording
        evidence.append(item)
    return {"text": req.get("text") if isinstance(req.get("text"), str) else "",
            "status": req.get("status"), "explanation": req.get("explanation") if isinstance(req.get("explanation"), str) else "",
            "evidence": evidence}


def _gaps(reqs: list[dict]) -> list[dict]:
    out = []
    for req in reqs:
        if req.get("status") != "gap":
            continue
        pointers = [ref.get("pointer") for ref in (req.get("evidence_refs") or [])
                    if isinstance(ref, dict) and isinstance(ref.get("pointer"), str)]
        boundary = req.get("category") == "truth_boundary" or any(p.startswith("/truth_boundaries/") for p in pointers)
        if not boundary and req.get("category") not in ("education", "license", "experience_years", "software"):
            continue
        out.append({"text": req.get("text") if isinstance(req.get("text"), str) else "",
                    "explanation": req.get("explanation") if isinstance(req.get("explanation"), str) else "",
                    "pointers": pointers, "boundary": boundary})
    return out


def _stories(profile: Profile, domains: list[str]) -> list[dict]:
    active = set(domains)
    bank = profile.data.get("interview_story_bank")
    if not isinstance(bank, dict):
        return []
    meta = bank.get("_story_meta") if isinstance(bank.get("_story_meta"), dict) else {}
    by_domain: dict[str, set[str]] = {}
    tree = profile.data.get("domain_tree")
    if isinstance(tree, dict):
        for domain, node in tree.items():
            refs = node.get("refs") if isinstance(node, dict) else None
            stories = refs.get("stories") if isinstance(refs, dict) else None
            if isinstance(stories, list):
                for sid in stories:
                    if isinstance(sid, str):
                        by_domain.setdefault(sid, set()).add(domain)
    ranked: list[tuple[int, str, str, list[str]]] = []
    for sid, text in bank.items():
        if not isinstance(sid, str) or sid.startswith("_") or sid.endswith("_long") or not isinstance(text, str):
            continue
        info = meta.get(sid) if isinstance(meta, dict) else None
        tags = set(info.get("domain_tags") or []) if isinstance(info, dict) else set()
        tags.update(by_domain.get(sid, set()))
        overlap = sorted(active.intersection(tags))
        if overlap:
            ranked.append((len(overlap), sid, text, overlap))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    return [{"id": sid, "text": text, "domains": tags} for _, sid, text, tags in ranked[:MAX_STORIES]]


def _checklist(official_url: str | None) -> list[str]:
    steps = []
    if official_url:
        steps.append("Abrir o anúncio oficial e reler a descrição antes de usar qualquer frase.")
    else:
        steps.append("Achar o anúncio oficial. Este preparo não tem URL segura para abrir.")
    steps.append("Usar só os textos citados abaixo. Se o ponteiro não está aqui, a frase não entra.")
    steps.append("Onde houver reciclagem pendente ou status parcial, escrever isso. Não atualizar a validade.")
    steps.append("Não marcar candidatura no JOBOS até você mesmo enviar na plataforma.")
    return steps
