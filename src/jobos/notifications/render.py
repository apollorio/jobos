"""Resumo de execução em texto e HTML. Links oficiais das vagas (localhost não serve no celular)."""
from __future__ import annotations

import html
import json
import sqlite3

from jobos.timeutil import fmt_brt
from jobos.domain.identity import safe_http_url

DECISION_PT = {"good_fit": "boa aderência", "needs_review": "revisar", "weak_fit": "baixa aderência",
               "not_eligible": "lacuna obrigatória", "insufficient_data": "descrição insuficiente"}


def collect_digest(con: sqlite3.Connection, run_id: str, max_items: int) -> dict:
    run = con.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
    items = []
    for ev in con.execute("""SELECT e.kind, e.job_id, j.company_name, j.title, j.location, j.listing_state,
                                (SELECT url FROM source_postings p WHERE p.job_id=j.job_id ORDER BY p.last_seen_at DESC LIMIT 1) url,
                                (SELECT result_json FROM analyses a WHERE a.job_id=j.job_id ORDER BY a.created_at DESC LIMIT 1) analysis
                             FROM job_events e JOIN job_records j ON j.job_id=e.job_id
                             WHERE e.run_id=? AND e.alertable=1 AND j.is_fixture=0""", (run_id,)):
        a = json.loads(ev["analysis"]) if ev["analysis"] else {}
        items.append({"kind": ev["kind"], "job_id": ev["job_id"], "company": ev["company_name"], "title": ev["title"],
                      "location": ev["location"], "url": safe_http_url(ev["url"]), "decision": a.get("decision"),
                      "priority": (a.get("priority") or {}).get("total", 0), "strengths": a.get("strengths", [])[:2],
                      "gaps": a.get("gaps", [])[:2], "unknowns": a.get("unknowns", [])[:1], "next_action": a.get("next_action")})
    items.sort(key=lambda x: -(x["priority"] or 0))
    sources = [dict(r) for r in con.execute("SELECT source_id, status, error_code, error_message FROM source_runs WHERE run_id=?",
                                            (run_id,))]
    runnable = [s for s in sources if s["status"] != "unconfigured"]
    failed = [s for s in runnable if s["status"] not in ("complete", "skipped")]
    pending_review = con.execute("SELECT COUNT(*) FROM applications WHERE prep_state='legacy_needs_review'").fetchone()[0]
    awaiting = con.execute("SELECT COUNT(*) FROM applications WHERE prep_state IN ('awaiting_review','cv_ready')").fetchone()[0]
    return {"run": dict(run) if run else {"run_id": run_id}, "items": items[:max_items], "total_items": len(items),
            "complete_sources": len(runnable) - len(failed), "runnable_sources": len(runnable), "failed": failed,
            "legacy_review": pending_review, "awaiting_review": awaiting}


def subject(d: dict) -> str:
    n = d["total_items"]
    parts = [f"JOBOS: {n} vaga(s) nova(s)/alterada(s) para revisar" if n else "JOBOS: nenhuma vaga nova"]
    if d["failed"]:
        parts.append(f"{len(d['failed'])} fonte(s) com falha")
    return " | ".join(parts)


def render_text(d: dict) -> str:
    run = d["run"]
    lines = [subject(d), "", f"Execução: {fmt_brt(run.get('started_at'))} (Brasília), run {run.get('run_id')}",
             f"Cobertura: {d['complete_sources']}/{d['runnable_sources']} fontes completas", ""]
    for i, it in enumerate(d["items"], 1):
        lines.append(f"{i}. {it['company']} / {it['title']} / {it['location'] or 'local não informado'}")
        lines.append(f"   Evento: {'nova' if it['kind'] == 'job.discovered' else 'alterada' if it['kind'] == 'job.changed' else it['kind']}"
                     f" | análise: {DECISION_PT.get(it['decision'], it['decision'] or 'pendente')}")
        if it["strengths"]:
            lines.append(f"   Evidências: {'; '.join(s[:90] for s in it['strengths'])}")
        if it["gaps"]:
            lines.append(f"   Atenção: {'; '.join(s[:90] for s in it['gaps'])}")
        elif it["unknowns"]:
            lines.append(f"   Desconhecido: {it['unknowns'][0][:110]}")
        lines.append(f"   Próxima ação: {it['next_action'] or 'revisar'}")
        lines.append(f"   Link: {it['url'] or 'sem link oficial'}")
    if d["total_items"] > len(d["items"]):
        lines.append(f"... e mais {d['total_items'] - len(d['items'])} no painel local.")
    if d["failed"]:
        lines += ["", "Fontes com falha:"]
        lines += [f"- {f['source_id']}: {f['status']} {f['error_code'] or ''} {(f['error_message'] or '')[:100]}" for f in d["failed"]]
    lines += ["", f"Pendências: {d['awaiting_review']} candidatura(s) aguardando revisão; "
                  f"{d['legacy_review']} registro(s) legado(s) de procedência a revisar.",
              "A nota é aderência estimada por requisitos, não chance de entrevista.",
              "Diagnóstico completo: painel local (abrir no PC)."]
    return "\n".join(lines)


def render_html(d: dict) -> str:
    e = html.escape
    rows = []
    for it in d["items"]:
        link = f'<a href="{e(it["url"])}">anúncio oficial</a>' if it["url"] else "sem link"
        rows.append(f"<li><b>{e(it['company'])}</b> / {e(it['title'])} / {e(it['location'] or 'local não informado')}<br>"
                    f"<small>{e(DECISION_PT.get(it['decision'], it['decision'] or 'pendente'))} · "
                    f"{e(it['next_action'] or 'revisar')} · {link}</small></li>")
    failed = "".join(f"<li>{e(f['source_id'])}: {e(f['status'])} {e(f['error_code'] or '')}</li>" for f in d["failed"])
    return (f"<!doctype html><html lang=pt-BR><meta charset=utf-8><title>{e(subject(d))}</title>"
            f"<body style='font-family:system-ui,sans-serif;max-width:720px'><h2>{e(subject(d))}</h2>"
            f"<p>Execução {e(fmt_brt(d['run'].get('started_at')))} (Brasília). Cobertura {d['complete_sources']}/"
            f"{d['runnable_sources']} fontes completas.</p><ol>{''.join(rows)}</ol>"
            + (f"<h3>Fontes com falha</h3><ul>{failed}</ul>" if failed else "")
            + f"<p><small>Pendências: {d['awaiting_review']} aguardando revisão; {d['legacy_review']} legado(s) a revisar. "
              "Nota = aderência estimada, não chance de entrevista.</small></p></body></html>")
