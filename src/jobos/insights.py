"""Leituras agregadas para o painel: mapa, sinais de contratação e kanban. Somente leitura.

Sinais de contratação são PROXIES públicos: vagas de RH/recrutamento abertas e ritmo de publicação por empresa,
calculados do nosso histórico. Não há dado de contratações reais nem de pessoas (LinkedIn etc.).
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sqlite3
from functools import lru_cache

from jobos.domain.identity import fold, safe_http_url
from jobos.domain.states import application_tag
from jobos.geo import geocode
from jobos.timeutil import BRT, parse_instant, utcnow

HR_TERMS = ["recrutamento", "recrutador", "recrutadora", "recruiter", "recruiting", "talent acquisition", "aquisicao de talentos",
            "atracao de talentos", "recursos humanos", "human resources", "hrbp", "business partner rh", "people partner",
            "gente e gestao", "gente & gestao", "departamento pessoal", "rh ", " rh", "talent partner", "people operations",
            "people &", "hr generalist", "hr analyst", "analista de rh", "analista de gente"]
OPEN = ("active", "missing_unconfirmed")


def is_hr_role(title: str | None) -> bool:
    t = f" {fold(title)} "
    return any(term in t for term in HR_TERMS)


@lru_cache(maxsize=8192)
def _geo(location: str | None, title: str | None) -> tuple:
    g = geocode(location, title)
    return (g["name"], g["uf"], g["lat"], g["lon"], g["ibge"], g["precision"], g["scope"])


def _latest_analysis_join() -> str:
    return """LEFT JOIN analyses a ON a.analysis_id = (SELECT a2.analysis_id FROM analyses a2
              WHERE a2.job_version_id=j.current_version_id ORDER BY a2.created_at DESC LIMIT 1)"""


def map_data(con: sqlite3.Connection, *, include_talent_pool: bool = False, decision: str | None = None) -> dict:
    where = ["j.is_fixture=0", "j.listing_state IN ('active','missing_unconfirmed')"]
    args: list = []
    if not include_talent_pool:
        where.append("j.talent_pool=0")
    if decision:
        where.append("a.decision=?")
        args.append(decision)
    rows = con.execute(f"""SELECT j.job_id, j.title, j.company_name, j.location, j.listing_state, a.decision, a.fit_score,
                             a.priority,
                             (SELECT url FROM source_postings p WHERE p.job_id=j.job_id ORDER BY p.last_seen_at DESC LIMIT 1) url
                           FROM job_records j {_latest_analysis_join()} WHERE {' AND '.join(where)}""", args).fetchall()
    places: dict[str, dict] = {}
    unplaced = {"remote": 0, "abroad": 0, "unknown": 0, "state_only": 0}
    for r in rows:
        name, uf, lat, lon, ibge, precision, scope = _geo(r["location"], r["title"])
        if lat is None:
            key = "state_only" if precision == "state" else scope if scope in unplaced else "unknown"
            unplaced[key] += 1
            continue
        p = places.setdefault(f"{name}|{uf}", {"name": name, "uf": uf, "lat": lat, "lon": lon, "ibge": ibge,
                                               "in_rj": uf == "RJ", "total": 0, "by_decision": {}, "jobs": []})
        p["total"] += 1
        d = r["decision"] or "pending"
        p["by_decision"][d] = p["by_decision"].get(d, 0) + 1
        p["jobs"].append({"job_id": r["job_id"], "title": r["title"], "company": r["company_name"], "decision": d,
                          "fit_score": r["fit_score"], "priority": r["priority"], "url": safe_http_url(r["url"])})
    for p in places.values():
        p["jobs"].sort(key=lambda j: -(j["priority"] or -999))
        p["jobs"] = p["jobs"][:30]
    return {"places": sorted(places.values(), key=lambda p: -p["total"]), "unplaced": unplaced,
            "total_open": len(rows), "geojson": "/painel/data/rj-municipios.geojson",
            "note": "Coordenadas locais (centroide do município ou bairro aproximado); local só do estado não vira ponto."}


def _job_date(r) -> dt.date | None:
    """Data de publicação quando conhecida; senão primeira observação real (não importação/baseline)."""
    if r["published_at"] and r["published_date_precision"] in ("timestamp", "date_only"):
        t = parse_instant(r["published_at"])
        if t:
            return t.astimezone(BRT).date()
        try:
            return dt.date.fromisoformat(r["published_at"][:10])
        except ValueError:
            return None
    if r["first_seen_at"] and not r["is_baseline"]:
        t = parse_instant(r["first_seen_at"])
        return t.astimezone(BRT).date() if t else None
    return None


def signals(con: sqlite3.Connection, *, weeks: int = 12) -> dict:
    today = utcnow().astimezone(BRT).date()
    start = today - dt.timedelta(weeks=weeks)
    week0 = start - dt.timedelta(days=start.weekday())
    week_keys = [(week0 + dt.timedelta(weeks=i)).isoformat() for i in range(weeks + 1)]
    rows = con.execute("""SELECT j.job_id, j.company_id, j.company_name, j.title, j.listing_state, j.published_at,
                            j.published_date_precision, j.first_seen_at, j.is_baseline, j.talent_pool,
                            (SELECT url FROM source_postings p WHERE p.job_id=j.job_id ORDER BY p.last_seen_at DESC LIMIT 1) url
                          FROM job_records j WHERE j.is_fixture=0 AND j.company_id NOT LIKE 'legacy-%'""").fetchall()
    comps: dict[str, dict] = {}
    undated = 0
    for r in rows:
        c = comps.setdefault(r["company_id"], {"company_id": r["company_id"], "name": r["company_name"], "open": 0,
                                              "new_7d": 0, "new_30d": 0, "prev_30d": 0, "hr_open": 0, "hr_recent": [],
                                              "weekly": {k: {"total": 0, "hr": 0} for k in week_keys}})
        hr = is_hr_role(r["title"])
        if r["listing_state"] in OPEN:
            c["open"] += 1
            if hr:
                c["hr_open"] += 1
        d = _job_date(r)
        if d is None:
            undated += 1
            continue
        age = (today - d).days
        if age <= 7:
            c["new_7d"] += 1
        if age <= 30:
            c["new_30d"] += 1
        elif age <= 60:
            c["prev_30d"] += 1
        wk = (d - dt.timedelta(days=d.weekday())).isoformat()
        if wk in c["weekly"]:
            c["weekly"][wk]["total"] += 1
            if hr:
                c["weekly"][wk]["hr"] += 1
        if hr and age <= 120:
            c["hr_recent"].append({"job_id": r["job_id"], "title": r["title"], "date": d.isoformat(),
                                   "listing_state": r["listing_state"], "url": safe_http_url(r["url"])})
    out = []
    for c in comps.values():
        c["momentum"] = c["new_30d"] - c["prev_30d"]
        c["hr_recent"].sort(key=lambda x: x["date"], reverse=True)
        c["weekly"] = [{"week": k, **v} for k, v in c["weekly"].items()]
        c["signal"] = ("forte" if c["hr_open"] and c["momentum"] > 0 else "atenção" if c["hr_open"] or c["momentum"] > 2
                       else "estável" if c["open"] else "sem vagas")
        out.append(c)
    out.sort(key=lambda c: (-(c["hr_open"] > 0), -c["momentum"], -c["new_30d"], -c["open"]))
    return {"weeks": week_keys, "companies": out, "undated_jobs": undated, "hr_terms": HR_TERMS,
            "note": ("Proxy público: vagas de RH/recrutamento e ritmo de publicação por empresa no nosso histórico "
                     "(desde 25/08/2026 no legado). Não mede contratações reais nem usa dados de pessoas.")}


KANBAN_COLUMNS = [
    ("suggested", "Sugestões"), ("shortlisted", "Na mira"), ("preparing", "Preparando"), ("ready", "Pronta para enviar"),
    ("applied", "Aplicado"), ("auto_applied", "Auto aplicado (revisar)"), ("process", "Em processo"), ("closed", "Arquivo"),
]


def kanban(con: sqlite3.Connection, *, suggestions: int = 25) -> dict:
    cols = {k: [] for k, _ in KANBAN_COLUMNS}
    rows = con.execute(f"""SELECT ap.*, j.title, j.company_name, j.location, j.listing_state, a.decision, a.fit_score, a.priority,
                             (SELECT url FROM source_postings p WHERE p.job_id=j.job_id ORDER BY p.last_seen_at DESC LIMIT 1) url
                           FROM applications ap JOIN job_records j ON j.job_id=ap.job_id {_latest_analysis_join()}""").fetchall()
    for r in rows:
        d = dict(r)
        tag = application_tag(d)
        card = {"job_id": d["job_id"], "title": d["title"], "company": d["company_name"], "location": d["location"],
                "listing_state": d["listing_state"], "decision": d["decision"], "fit_score": d["fit_score"],
                "priority": d["priority"], "tag": tag, "stage": d["selection_stage"], "url": safe_http_url(d["url"]),
                "updated_at": d["updated_at"]}
        st = d["prep_state"]
        if d["selection_stage"] not in ("none", None) and d["selection_stage"] not in ("rejected", "withdrawn"):
            cols["process"].append(card)
        elif st == "shortlisted" or st == "discovered":
            cols["shortlisted"].append(card)
        elif st in ("cv_draft", "cv_ready"):
            cols["preparing"].append(card)
        elif st in ("awaiting_review", "submission_unknown"):
            cols["ready"].append(card)
        elif st in ("submitted_manual", "submitted_verified"):
            cols["applied"].append(card)
        elif st == "legacy_needs_review":
            cols["auto_applied"].append(card)
        else:
            cols["closed"].append(card)
    sug = con.execute(f"""SELECT j.job_id, j.title, j.company_name, j.location, j.listing_state, a.decision, a.fit_score,
                            a.priority,
                            (SELECT url FROM source_postings p WHERE p.job_id=j.job_id ORDER BY p.last_seen_at DESC LIMIT 1) url
                          FROM job_records j {_latest_analysis_join()}
                          WHERE j.is_fixture=0 AND j.listing_state='active' AND j.talent_pool=0 AND a.decision='good_fit'
                          AND NOT EXISTS (SELECT 1 FROM applications ap WHERE ap.job_id=j.job_id)
                          ORDER BY a.priority DESC LIMIT ?""", (suggestions,)).fetchall()
    for r in sug:
        cols["suggested"].append({"job_id": r["job_id"], "title": r["title"], "company": r["company_name"],
                                  "location": r["location"], "listing_state": r["listing_state"], "decision": r["decision"],
                                  "fit_score": r["fit_score"], "priority": r["priority"],
                                  "tag": {"code": "suggested", "label": "Sugestão", "tone": "info", "hint": "boa aderência, sem ação ainda",
                                          "counts_as_applied": False}, "stage": "none", "url": safe_http_url(r["url"])})
    for k in cols:
        cols[k].sort(key=lambda c: -(c.get("priority") or -999))
    return {"columns": [{"key": k, "label": label, "cards": cols[k], "count": len(cols[k])} for k, label in KANBAN_COLUMNS]}
