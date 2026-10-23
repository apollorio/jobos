"""Fixtures de teste: diretório de dados temporário (JOBOS_DATA), nunca o banco real."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from jobos.collectors.base import JobObservation, SourceBatch, scope_id
from jobos.settings import SourceConfig

SCHEMA_LEGACY = """
CREATE TABLE jobs (job_id TEXT PRIMARY KEY, source_id TEXT, source TEXT, company TEXT, title TEXT, url TEXT, location TEXT,
  city TEXT, state TEXT, country TEXT, remote_status TEXT, salary TEXT, date_posted TEXT, date_found TEXT, description TEXT,
  fit_score INTEGER, technical_score INTEGER, experience_score INTEGER, seniority_score INTEGER, evidence_score INTEGER,
  interview_prob REAL, effort_hours REAL, decision TEXT, reasons_fit TEXT, reasons_gap TEXT, missing TEXT, priority INTEGER,
  cv_version TEXT, application_status TEXT DEFAULT 'new', application_date TEXT, follow_up_date TEXT, contact TEXT,
  notes TEXT, rejection_reason TEXT, scored_at TEXT, last_seen TEXT, closed INTEGER DEFAULT 0, removed_at TEXT,
  suggested_at TEXT, application_source TEXT, compat_score INTEGER, suggested_run TEXT);
CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT, ts TEXT, kind TEXT, detail TEXT);
CREATE TABLE runs (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, source TEXT, fetched INTEGER, new_jobs INTEGER, errors TEXT);
"""


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "data"
    monkeypatch.setenv("JOBOS_DATA", str(d))
    monkeypatch.delenv("JOBOS_DB", raising=False)
    return d


@pytest.fixture()
def ctx(data_dir):
    from jobos.context import open_context
    c = open_context()
    yield c
    c.close()


@pytest.fixture()
def legacy_db(tmp_path) -> Path:
    """SQLite no formato legado com os casos de risco (rotulado como teste)."""
    p = tmp_path / "legacy-jobs.db"
    con = sqlite3.connect(p)
    con.executescript(SCHEMA_LEGACY)
    rows = [
        # mesmo source_id em duas linhas (título mudou): deve virar UMA vaga com duas versões
        ("h1", "gupy:111", "gupy", "PRIO", "Planner Offshore", "https://prio.gupy.io/jobs/111", "Rio de Janeiro", "2026-08-01",
         "2026-08-02", "Descrição A " * 30, "new", None, None, "2026-08-10T10:00:00+00:00", 0),
        ("h2", "gupy:111", "gupy", "prio", "Planner Offshore Sr", "https://prio.gupy.io/jobs/111", "Rio de Janeiro", "~2026-08-02",
         "2026-08-03", "Descrição B " * 30, "new", None, None, "2026-08-12T10:00:00+00:00", 1),
        # aplicada por consolidação automática
        ("h3", "gupy:222", "gupy", "MODEC", "Engenheiro de Projetos", "https://modec-br.gupy.io/jobs/222", "Rio de Janeiro",
         "Posted Today", "2026-08-05", "", "applied", "auto_sugerida", "2026-08-26", "2026-08-20T10:00:00+00:00", 1),
        # aplicada sem origem (marcação manual)
        ("h4", "web:inhire:OceanPact:abc", "web:inhire", "OceanPact", "Coordenador", "https://oceanpact.inhire.app/vagas/abc",
         "Niterói", "", "2026-08-06", "x", "applied", None, "2026-08-24", "2026-08-20T10:00:00+00:00", 0),
        # mesmo título, IDs diferentes: duas vagas distintas
        ("h5", "gupy:333", "gupy", "PRIO", "Analista", "https://prio.gupy.io/jobs/333", "Rio", "N/A", "2026-08-07", "", "new",
         None, None, "2026-08-20T10:00:00+00:00", 0),
        ("h6", "gupy:334", "gupy", "PRIO", "Analista", "https://prio.gupy.io/jobs/334", "Rio", "2026-08-07", "2026-08-07", "",
         "new", None, None, "2026-08-20T10:00:00+00:00", 0),
    ]
    for r in rows:
        con.execute("""INSERT INTO jobs (job_id, source_id, source, company, title, url, location, date_posted, date_found,
                       description, application_status, application_source, application_date, last_seen, closed)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", r)
    con.execute("UPDATE jobs SET fit_score=95, interview_prob=0.7 WHERE job_id='h1'")
    events = [("h1", "2026-08-02T08:00:00+00:00", "found", "gupy"),
              ("h3", "2026-08-26T09:00:00+00:00", "applied", "consolidada como candidatura: foi sugerida no boletim"),
              ("h4", "2026-08-24T12:00:00+00:00", "applied", "marcado manualmente a pedido do usuario (aplicado em 24/08/2026)"),
              ("orfao", "2026-08-01T00:00:00+00:00", "scored", "")]
    con.executemany("INSERT INTO events (job_id, ts, kind, detail) VALUES (?,?,?,?)", events)
    con.execute("INSERT INTO runs (ts, source, fetched, new_jobs, errors) VALUES ('2026-08-02T08:00:00+00:00','gupy',6,6,'')")
    con.commit()
    con.close()
    return p


def make_source(source_id="prio-gupy", coverage="full_board", params=None, company_id="prio") -> SourceConfig:
    return SourceConfig(source_id=source_id, company_id=company_id, company_name=company_id.upper(), platform="gupy",
                        adapter="gupy_tenant", enabled=True, params=params or {"tenant": "prio"}, coverage=coverage,
                        limits={"max_pages": 3, "max_details": 5, "detail_ttl_days": 7}, priority=1, board_url=None,
                        configuration_origin="test", verification_status="test")


def obs(ext: str, title="Planner Offshore", desc="Requisitos:\n- Graduação em Engenharia\n- Inglês fluente " + "x" * 200,
        **kw) -> JobObservation:
    return JobObservation(platform="gupy", tenant="", external_id=ext, url=f"https://prio.gupy.io/jobs/{ext}", title=title,
                          location=kw.pop("location", "Rio de Janeiro"), description=desc,
                          description_status="full" if desc else "missing", **kw)


def batch(source: SourceConfig, run_id: str, jobs, status="complete", coverage=None) -> SourceBatch:
    b = SourceBatch(run_id=run_id, source_id=source.source_id, adapter="test", adapter_version="test/1", status=status,
                    coverage_kind=coverage or source.coverage, scope_id=scope_id(source),
                    can_infer_absence=(coverage or source.coverage) in ("full_board", "filtered_board"))
    b.jobs = list(jobs)
    b.raw_count = len(b.jobs)
    return b.finish()


def apply(ctx, b, src):
    """Aplica um lote garantindo a execução correspondente em `runs` (FK real do esquema)."""
    from jobos import persistence
    from jobos.timeutil import iso
    ctx.con.execute("INSERT OR IGNORE INTO runs (run_id, trigger, mode, started_at, status) VALUES (?,?,?,?,?)",
                    (b.run_id, "test", "normal", iso(), "running"))
    return persistence.apply_batch(ctx.con, b, src, ctx.settings)
