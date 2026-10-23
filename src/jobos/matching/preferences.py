"""Preferências (política visível) e prioridade operacional. Nenhuma regra esconde vaga."""
from __future__ import annotations

import datetime as dt
import re
import sqlite3

from jobos.domain.identity import fold
from jobos.timeutil import parse_instant, utcnow


def _has(text: str, terms: list[str]) -> str | None:
    for term in terms:
        tt = fold(term)
        if tt.strip() and re.search(rf"(?<![a-z0-9]){re.escape(tt.strip())}(?![a-z0-9])", text):
            return term.strip()
    return None


def evaluate_preferences(job: sqlite3.Row, version: sqlite3.Row, prefs: dict) -> dict:
    loc_cfg = prefs.get("location") or {}
    location = fold(" ".join(x for x in (job["location"] or "", version["location"] or "") if x))
    title = fold(job["title"] or "")
    desc = fold((version["description"] or "")[:200000])
    workplace = (job["workplace"] or version["workplace"] or "").lower()
    out: dict = {"location_label": "unknown", "location_reason": "local não informado", "flags": []}
    hay = f"{location} | {title}"
    if workplace == "remote" or _has(hay, loc_cfg.get("remote_terms") or []):
        out.update(location_label="remote", location_reason="remoto")
    # Cidade antes do estado: "Macaé, Rio de Janeiro" é Macaé (revisar), não Grande Rio.
    city = location.split(",")[0].strip() if "," in location else location
    other_uf = re.search(r"[-/]\s*(sp|mg|ba|pr|rs|sc|pe|ce|go|df|am|pa|rn|pb|al|se|ma|pi|mt|ms|to|ro|ac|ap|rr)\b", title)
    label_hit = None
    for scope_text in (city, hay):
        for label in ("review", "accepted_secondary", "preferred"):
            hit = _has(scope_text, (loc_cfg.get(label) or {}).get("terms") or [])
            if hit:
                label_hit = (label, hit)
                break
        if label_hit:
            break
    if other_uf and (not label_hit or label_hit[0] == "preferred"):
        out.update(location_label="outside_preference",
                   location_reason=f"título indica outra UF ('{other_uf.group(1).upper()}'); escritório pode diferir")
    elif label_hit:
        label, hit = label_hit
        out.update(location_label=label, location_reason=f"'{hit}' ({(loc_cfg.get(label) or {}).get('origin', '')[:80]})")
    elif out["location_label"] == "unknown" and location.strip():
        brazil = any(x in location for x in ("brasil", "brazil", "sao paulo"))
        out.update(location_label="outside_preference",
                   location_reason="outro estado do Brasil" if brazil else "fora das localidades preferidas")
    off = _has(f"{title} {desc[:20000]}", loc_cfg.get("offshore_terms") or [])
    if off:
        out["flags"].append(f"embarque/offshore citado ('{off}'): revisar regime, sem exclusão automática")
    emp = (prefs.get("employers") or {}).get("excluded") or {}
    excluded = _has(fold(job["company_name"] or ""), emp.get("terms") or [])
    out["excluded_employer"] = bool(excluded)
    if excluded:
        out["flags"].append(f"empregador excluído por preferência: {excluded} ({emp.get('origin', '')[:60]})")
    out["talent_pool"] = bool(job["talent_pool"])
    if job["talent_pool"]:
        out["flags"].append("banco de talentos / programa: não é vaga específica")
    out["salary"] = version["salary"] or None
    if not out["salary"]:
        out["flags"].append("salário não informado (sem piso inventado)")
    return out


def priority_score(decision: str, prefs_eval: dict, job: sqlite3.Row, company_priority: int, prefs: dict) -> dict:
    p = prefs.get("priority") or {}
    comp = {
        "decisão": (p.get("decision_weight") or {}).get(decision, 0),
        "local": (p.get("location_weight") or {}).get(prefs_eval["location_label"], 0),
        "empresa": (p.get("company_priority_weight") or {}).get(company_priority, 0),
        "frescor": 0,
        "funcao": {"natural": 10, "off_profile": -20, "off_profile_licensed": -30, "tier_x": -10, "level_below": -10}.get(
            (prefs_eval.get("role_fit") or {}).get("label"), 0),
        "banco_de_talentos": p.get("talent_pool_penalty", 0) if prefs_eval.get("talent_pool") else 0,
        "empregador_excluido": p.get("excluded_employer_penalty", 0) if prefs_eval.get("excluded_employer") else 0,
    }
    if job["published_date_precision"] in ("timestamp", "date_only") and job["published_at"]:
        pub = parse_instant(job["published_at"]) or dt.datetime.fromisoformat(job["published_at"][:10] + "T00:00:00+00:00")
        age = (utcnow() - pub).days
        for days, bonus in sorted((int(k), v) for k, v in (p.get("freshness_days_bonus") or {}).items()):
            if age <= days:
                comp["frescor"] = bonus
                break
        comp_note = f"publicada há {age} dia(s)"
    else:
        comp_note = "data de publicação desconhecida: sem bônus de frescor"
    return {"total": float(sum(comp.values())), "components": comp, "note": comp_note,
            "explanation": "Prioridade operacional; empresa-alvo não aumenta aderência técnica."}
