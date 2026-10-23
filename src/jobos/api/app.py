"""API local + painel. Loopback, Host/Origin validados, mutações com cabeçalho próprio, estático por allowlist.

Nada roda no import do módulo; GET nunca dispara coleta (POST enfileira; o worker executa).
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field

from jobos.api.worker import Worker, WorkError, enqueue
from jobos.applications import service as appsvc
from jobos.domain.identity import safe_http_url
from jobos.matching.prepare import build_support
from jobos.matching.profile import active_profile
from jobos.domain.states import LISTING_LABELS, PREP_LABELS, TransitionError
from jobos.paths import get_paths
from jobos.settings import load_registry, load_settings
from jobos.status import build_status, source_health
from jobos.storage.db import connect, open_db
from jobos.timeutil import fmt_brt, utcnow

REFRESH_COOLDOWN_MIN = 60
ASSET_EXT = {".js", ".css", ".png", ".svg", ".jpg", ".jpeg", ".webp", ".gif", ".ico", ".woff", ".woff2"}
PANEL_EXT = {".html", ".js", ".css", ".svg", ".png", ".geojson", ".woff2", ".webmanifest"}
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")


class UTF8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"  # clientes como PowerShell 5.1 não presumem UTF-8


class EventIn(BaseModel):
    action: str = Field(pattern="^(transition|stage|note|confirm)$")
    target: str | None = Field(default=None, max_length=40)
    reason: str | None = Field(default=None, max_length=2000)
    date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class WorkIn(BaseModel):
    kind: str = Field(pattern="^(cycle|collect_source|analyze_job)$")
    target: str | None = Field(default=None, max_length=80)


def create_app(*, port: int, worker: bool = True, paths=None) -> FastAPI:
    paths = paths or get_paths()
    settings = load_settings(paths)
    registry = load_registry(paths)
    allowed_hosts = {f"{h}:{port}" for h in (settings.app.get("server") or {}).get("allowed_hosts", ["127.0.0.1", "localhost"])}
    allowed_origins = {f"http://{h}" for h in allowed_hosts}
    workspace = paths.workspace.resolve()
    assets_root = (workspace / "assets").resolve()
    panel_root = (paths.web / "painel").resolve()
    state: dict = {}

    @asynccontextmanager
    async def lifespan(app):
        open_db(paths.db).close()  # migrações aplicadas antes do primeiro request
        if worker:
            from jobos.context import open_context
            w = Worker(lambda: open_context(paths=paths))
            w.start()
            state["worker"] = w
        yield
        if state.get("worker"):
            state["worker"].stop_event.set()

    app = FastAPI(title="JOBOS local", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan,
                  default_response_class=UTF8JSONResponse)

    @app.exception_handler(sqlite3.OperationalError)
    async def db_busy(request: Request, exc: sqlite3.OperationalError):
        return JSONResponse({"error": "banco ocupado por um ciclo em andamento; tente novamente em instantes",
                             "detail": str(exc)[:120]}, status_code=503)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        host = request.headers.get("host", "")
        if host not in allowed_hosts:
            return PlainTextResponse("Host não permitido", status_code=400)
        if request.method in MUTATING:
            origin = request.headers.get("origin")
            site = request.headers.get("sec-fetch-site")
            if request.headers.get("x-jobos") != "1":
                return JSONResponse({"error": "mutação exige cabeçalho X-JOBOS: 1"}, status_code=403)
            if origin is not None and origin not in allowed_origins:
                return JSONResponse({"error": "origem não permitida"}, status_code=403)
            if site is not None and site not in ("same-origin", "none"):
                return JSONResponse({"error": "requisição cross-site recusada"}, status_code=403)
            length = int(request.headers.get("content-length") or 0)
            if length > 64_000:
                return JSONResponse({"error": "payload grande demais"}, status_code=413)
        resp = await call_next(request)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith(("/painel", "/api")):
            resp.headers["Content-Security-Policy"] = ("default-src 'self'; img-src 'self' data: https:; "
                                                       "style-src 'self'; script-src 'self'; frame-ancestors 'none'; "
                                                       "base-uri 'none'; form-action 'self'")
        return resp

    def db():
        con = connect(paths.db)
        try:
            yield con
        finally:
            con.close()

    # ------------------------------------------------------------------ leitura
    @app.get("/api/health")
    def health():
        return {"ok": True, "service": "jobos-local"}

    @app.get("/api/status")
    def status(con=Depends(db)):
        return build_status(con, settings, registry)

    @app.get("/api/sources")
    def sources(con=Depends(db)):
        return {"sources": source_health(con, registry)}

    @app.get("/api/jobs")
    def jobs(con=Depends(db), q: str | None = Query(None, max_length=120),
             state_: str | None = Query(None, alias="state", pattern="^(active|missing_unconfirmed|closed_confirmed|unknown|open)$"),
             decision: str | None = Query(None, pattern="^(good_fit|needs_review|weak_fit|not_eligible|insufficient_data)$"),
             location: str | None = Query(None, pattern="^(preferred|accepted_secondary|review|remote|unknown|outside_preference)$"),
             company: str | None = Query(None, max_length=80), talent_pool: bool | None = None,
             sort: str = Query("priority", pattern="^(priority|recent|published|company)$"),
             page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200)):
        where = ["j.is_fixture=0"]
        args: list = []
        if q:
            where.append("(j.title LIKE ? OR j.company_name LIKE ? OR j.location LIKE ?)")
            args += [f"%{q}%"] * 3
        if state_ == "open":
            where.append("j.listing_state IN ('active','missing_unconfirmed')")
        elif state_:
            where.append("j.listing_state=?")
            args.append(state_)
        if decision:
            where.append("a.decision=?")
            args.append(decision)
        if location:
            where.append("json_extract(a.preference_json,'$.location_label')=?")
            args.append(location)
        if company:
            where.append("j.company_id=?")
            args.append(company)
        if talent_pool is not None:
            where.append("j.talent_pool=?")
            args.append(int(talent_pool))
        order = {"priority": "COALESCE(a.priority,-999) DESC, j.last_seen_at DESC",
                 "recent": "COALESCE(j.first_seen_at, j.imported_at) DESC",
                 "published": "j.published_at DESC", "company": "j.company_name, j.title"}[sort]
        base = f"""FROM job_records j LEFT JOIN analyses a ON a.analysis_id = (
                     SELECT a2.analysis_id FROM analyses a2 WHERE a2.job_version_id=j.current_version_id
                     ORDER BY a2.created_at DESC LIMIT 1)
                   WHERE {' AND '.join(where)}"""
        total = con.execute(f"SELECT COUNT(*) {base}", args).fetchone()[0]
        rows = con.execute(f"""SELECT j.job_id, j.company_id, j.company_name, j.title, j.location, j.workplace, j.listing_state,
                                 j.talent_pool, j.published_at, j.published_date_precision, j.first_seen_at, j.last_seen_at,
                                 j.origin, a.decision, a.fit_score, a.coverage, a.priority, a.preference_json,
                                 (SELECT prep_state FROM applications ap WHERE ap.job_id=j.job_id) prep_state,
                                 (SELECT url FROM source_postings p WHERE p.job_id=j.job_id ORDER BY p.last_seen_at DESC LIMIT 1) url
                               {base} ORDER BY {order} LIMIT ? OFFSET ?""", (*args, page_size, (page - 1) * page_size)).fetchall()
        items = []
        for r in rows:
            d = dict(r)
            prefs = json.loads(d.pop("preference_json") or "{}")
            d.update(url=safe_http_url(d["url"]), listing_label=LISTING_LABELS.get(d["listing_state"]),
                     location_label=prefs.get("location_label"), role_fit=(prefs.get("role_fit") or {}).get("label"),
                     flags=prefs.get("flags", []), published_brt=fmt_brt(d["published_at"], d["published_date_precision"]),
                     prep_label=PREP_LABELS.get(d["prep_state"]) if d["prep_state"] else None)
            items.append(d)
        return {"total": total, "page": page, "page_size": page_size, "items": items}

    @app.get("/api/jobs/{job_id}")
    def job_detail(job_id: str, con=Depends(db)):
        j = con.execute("SELECT * FROM job_records WHERE job_id=?", (job_id,)).fetchone()
        if not j:
            raise HTTPException(404, "vaga não encontrada")
        versions = [dict(v) for v in con.execute(
            """SELECT version_id, observed_at, origin, source_id, title, location, workplace, salary, department,
                      description_status, description_length, original_length, truncation_note, content_hash,
                      CASE WHEN version_id=? THEN description ELSE NULL END AS description
               FROM job_versions WHERE job_id=? ORDER BY observed_at DESC""", (j["current_version_id"], job_id))]
        postings = [dict(p) for p in con.execute(
            """SELECT source_id, platform, tenant, external_id, url, posting_state, first_seen_at, last_seen_at, missing_count,
                      missing_since, origin FROM source_postings WHERE job_id=?""", (job_id,))]
        for p in postings:
            p["url"] = safe_http_url(p["url"])
        events = [dict(e) for e in con.execute(
            "SELECT kind, occurred_at, origin, run_id, payload_json FROM job_events WHERE job_id=? ORDER BY occurred_at DESC LIMIT 100",
            (job_id,))]
        an = con.execute("""SELECT result_json FROM analyses WHERE job_version_id=? ORDER BY created_at DESC LIMIT 1""",
                         (j["current_version_id"],)).fetchone()
        history = [dict(a) for a in con.execute(
            "SELECT analysis_id, job_version_id, policy_version, decision, fit_score, coverage, created_at FROM analyses "
            "WHERE job_id=? ORDER BY created_at DESC", (job_id,))]
        app_row = con.execute("SELECT * FROM applications WHERE job_id=?", (job_id,)).fetchone()
        app_events = [dict(e) for e in con.execute(
            "SELECT * FROM application_events WHERE application_id=? ORDER BY occurred_at, event_id",
            (app_row["application_id"],))] if app_row else []
        legacy = [dict(r) for r in con.execute(
            "SELECT origin, legacy_id, rule FROM legacy_id_map WHERE canonical_job_id=?", (job_id,))]
        relations = [dict(r) for r in con.execute(
            "SELECT * FROM job_relations WHERE a_job_id=? OR b_job_id=?", (job_id, job_id))]
        rec = dict(j)
        rec["listing_label"] = LISTING_LABELS.get(rec["listing_state"])
        rec["published_brt"] = fmt_brt(rec["published_at"], rec["published_date_precision"])
        analysis = json.loads(an["result_json"]) if an else None
        official = next((p["url"] for p in postings if p.get("url")), None)
        return {"job": rec, "versions": versions, "postings": postings, "events": events,
                "analysis": analysis, "support": build_support(active_profile(con), analysis, official),
                "analysis_history": history,
                "application": ({**dict(app_row), "prep_label": PREP_LABELS.get(app_row["prep_state"])} if app_row else None),
                "application_events": app_events, "legacy_refs": legacy, "relations": relations,
                "note": "Texto do anúncio é dado externo; exibido como texto."}

    @app.get("/api/map")
    def map_view(con=Depends(db), talent_pool: bool = False,
                 decision: str | None = Query(None, pattern="^(good_fit|needs_review|weak_fit|not_eligible|insufficient_data)$")):
        from jobos.insights import map_data
        return map_data(con, include_talent_pool=talent_pool, decision=decision)

    @app.get("/api/signals")
    def signals_view(con=Depends(db), weeks: int = Query(12, ge=4, le=52)):
        from jobos.insights import signals
        return signals(con, weeks=weeks)

    @app.get("/api/kanban")
    def kanban_view(con=Depends(db)):
        from jobos.insights import kanban
        return kanban(con)

    @app.get("/api/applications")
    def applications(con=Depends(db)):
        return {"items": appsvc.list_applications(con)}

    @app.get("/api/runs")
    def runs(con=Depends(db), limit: int = Query(30, ge=1, le=200)):
        return {"items": [dict(r) for r in con.execute(
            "SELECT run_id, trigger, mode, started_at, finished_at, stage, status, exit_code, error FROM runs "
            "ORDER BY started_at DESC LIMIT ?", (limit,))]}

    @app.get("/api/runs/{run_id}")
    def run_detail(run_id: str, con=Depends(db)):
        r = con.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if not r:
            raise HTTPException(404, "execução não encontrada")
        return {"run": dict(r), "sources": [dict(s) for s in con.execute(
            "SELECT * FROM source_runs WHERE run_id=? ORDER BY source_id", (run_id,))]}

    @app.get("/api/notifications")
    def notifications(con=Depends(db)):
        return {"sending_enabled": bool(settings.notifications.get("enabled")),
                "recipient_configured": bool(settings.notifications.get("recipient")),
                "items": [dict(r) for r in con.execute(
                    """SELECT notification_id, status, subject, attempts, last_error_code, smtp_accepted_at, created_at,
                              run_id, body_text FROM notification_outbox ORDER BY created_at DESC LIMIT 50""")]}

    @app.get("/api/work-items/{item_id}")
    def work_item(item_id: str, con=Depends(db)):
        r = con.execute("SELECT * FROM work_items WHERE item_id=?", (item_id,)).fetchone()
        if not r:
            raise HTTPException(404, "item não encontrado")
        return dict(r)

    @app.get("/api/artifacts/{artifact_id}")
    def artifact(artifact_id: str, con=Depends(db)):
        r = con.execute("SELECT artifact_id, job_id, kind, sha256, created_at FROM artifacts WHERE artifact_id=?",
                        (artifact_id,)).fetchone()
        if not r:
            raise HTTPException(404, "artefato não encontrado")
        return dict(r)

    @app.get("/api/artifacts/{artifact_id}/download")
    def artifact_download(artifact_id: str, con=Depends(db)):
        r = con.execute("SELECT rel_path FROM artifacts WHERE artifact_id=?", (artifact_id,)).fetchone()
        if not r:
            raise HTTPException(404, "artefato não encontrado")
        root = paths.artifacts.resolve()
        target = (root / r["rel_path"]).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            raise HTTPException(404, "artefato indisponível")
        return FileResponse(target)

    @app.get("/api/book")
    def book():
        return _book()

    def _book():
        from jobos.exports.portal import build_book

        class _Ctx:  # projeção só precisa de con e registry
            pass
        c = _Ctx()
        c.con, c.registry = connect(paths.db), registry
        try:
            return build_book(c)
        finally:
            c.con.close()

    # ------------------------------------------------------------------ mutações
    @app.post("/api/work-items", status_code=202)
    def post_work(body: WorkIn, con=Depends(db)):
        try:
            return enqueue(con, body.kind, body.target, "api", registry)
        except (WorkError, Exception) as e:  # noqa: BLE001  ConfigError de fonte desconhecida inclusive
            raise HTTPException(400, str(e)) from e

    @app.post("/api/applications/{job_id}/events")
    def post_event(job_id: str, body: EventIn, con=Depends(db)):
        try:
            if body.action == "confirm":
                if not body.date:
                    raise HTTPException(422, "data obrigatória (AAAA-MM-DD)")
                return appsvc.confirm_manual(con, job_id, body.date, body.reason)
            if body.action == "transition":
                return appsvc.transition(con, job_id, body.target or "", origin="user_asserted", reason=body.reason)
            if body.action == "stage":
                return appsvc.set_stage(con, job_id, body.target or "", reason=body.reason)
            return appsvc.add_note(con, job_id, body.reason or "")
        except (TransitionError, appsvc.NotFound, ValueError) as e:
            raise HTTPException(409, str(e)) from e

    @app.post("/api/refresh")
    def portal_refresh(con=Depends(db)):
        """Compatível com o portal antigo, que chama este POST a cada abertura: só enfileira um ciclo se não houve
        ciclo iniciado nem enfileirado nos últimos REFRESH_COOLDOWN_MIN minutos. Nunca coleta dentro do request."""
        recent = con.execute(
            """SELECT 1 FROM runs WHERE mode='normal' AND started_at >= ? UNION ALL
               SELECT 1 FROM work_items WHERE kind='cycle' AND created_at >= ? AND status IN ('queued','leased','done')""",
            ((utcnow() - dt.timedelta(minutes=REFRESH_COOLDOWN_MIN)).isoformat(),) * 2).fetchone()
        queued = None
        if not recent:
            queued = enqueue(con, "cycle", None, "portal_refresh")["item_id"]
        b = _book()
        return {"changed": False, "cached": True, "queued": queued, "cooldown_minutes": REFRESH_COOLDOWN_MIN,
                "updatedAt": b["updatedAt"], "book": b}

    # ------------------------------------------------------------------ estático (allowlist)
    def _file(root: Path, rel: str, exts: set[str]) -> FileResponse:
        parts = [p for p in rel.split("/") if p]
        if not parts or any(not SAFE_SEGMENT.match(p) or p.startswith(".") for p in parts):
            raise HTTPException(404)
        target = root.joinpath(*parts).resolve()
        if not target.is_relative_to(root) or target.suffix.lower() not in exts or not target.is_file():
            raise HTTPException(404)
        media = "application/manifest+json" if target.suffix.lower() == ".webmanifest" else None
        extra = {"media_type": media} if media else {}
        return FileResponse(target, headers={"Cache-Control": "no-cache"}, **extra)

    @app.get("/")
    @app.get("/index.html")
    def portal_index():
        return FileResponse(workspace / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/sw.js")
    def sw():
        return FileResponse(workspace / "sw.js", media_type="text/javascript", headers={"Cache-Control": "no-store"})

    @app.get("/manifest.webmanifest")
    def manifest():
        return FileResponse(workspace / "manifest.webmanifest", media_type="application/manifest+json")

    @app.get("/jobs.json")
    def jobs_json():
        return JSONResponse(_book(), headers={"Cache-Control": "no-store"})

    @app.get("/assets/jobs-data.js")
    def jobs_data_js():
        payload = json.dumps(_book(), ensure_ascii=False).replace("</", "<\\/")
        return Response(f"window.JOBOS_BOOK = {payload};\n", media_type="text/javascript",
                        headers={"Cache-Control": "no-store"})

    @app.get("/assets/{rel:path}")
    def assets(rel: str):
        return _file(assets_root, rel, ASSET_EXT)

    @app.get("/painel")
    def panel_redirect():
        return Response(status_code=307, headers={"Location": "/painel/"})

    @app.get("/painel/")
    def panel_index():
        return _file(panel_root, "index.html", PANEL_EXT)

    @app.get("/painel/{rel:path}")
    def panel_files(rel: str):
        return _file(panel_root, rel, PANEL_EXT)

    return app
