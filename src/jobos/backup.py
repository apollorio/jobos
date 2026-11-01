"""Backup consistente (Backup API) + verificação de restauração em diretório separado."""
from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
from pathlib import Path

from jobos.context import Context
from jobos.storage.db import connect, sha256_file, table_counts, write_snapshot
from jobos.timeutil import iso

KEY_TABLES = ["job_records", "source_postings", "job_versions", "job_events", "applications", "application_events",
              "legacy_id_map", "legacy_events", "runs", "source_runs", "notification_outbox", "analyses"]


def make_backup(ctx: Context, dest_root: Path | None = None, label: str = "manual") -> dict:
    stamp = iso().replace(":", "").replace("-", "")[:15]
    dest = (dest_root or ctx.paths.backups) / f"{stamp}-{label}"
    dest.mkdir(parents=True, exist_ok=False)
    snap = write_snapshot(ctx.con, dest / "jobos.sqlite3")
    cfg_dir = dest / "config"
    shutil.copytree(ctx.paths.config, cfg_dir)
    files = {str(p.relative_to(dest)).replace("\\", "/"): sha256_file(p) for p in cfg_dir.rglob("*") if p.is_file()}
    artifact_files: dict[str, str] = {}
    art = ctx.paths.artifacts
    if art.is_dir():
        dest_art = dest / "artifacts"
        shutil.copytree(art, dest_art)
        artifact_files = {str(p.relative_to(dest)).replace("\\", "/"): sha256_file(p)
                          for p in dest_art.rglob("*") if p.is_file()}
    live_counts = table_counts(ctx.con, KEY_TABLES)
    verify = verify_restore(dest / "jobos.sqlite3", live_counts)
    manifest = {"created_at": iso(), "label": label, "database": snap, "config_files": files,
                "artifact_files": artifact_files, "live_counts": live_counts, "restore_check": verify,
                "note": "data/artifacts vai junto, com SHA-256 por arquivo"}
    (dest / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"path": str(dest), **manifest}


def verify_restore(backup_db: Path, expected: dict | None = None) -> dict:
    """Restaura numa pasta temporária (nunca sobre a base ativa) e confere integridade e contagens."""
    tmp = Path(tempfile.mkdtemp(prefix="jobos-restore-"))
    try:
        target = tmp / "restored.sqlite3"
        shutil.copyfile(backup_db, target)  # arquivo de backup é fechado e sem WAL
        con = connect(target)
        try:
            ic = con.execute("PRAGMA integrity_check").fetchone()[0]
            fk = len(con.execute("PRAGMA foreign_key_check").fetchall())
            counts = table_counts(con, KEY_TABLES)
        finally:
            con.close()
        mismatch = {k: (v, counts.get(k)) for k, v in (expected or {}).items() if counts.get(k) != v}
        return {"integrity_check": ic, "foreign_key_violations": fk, "counts": counts, "mismatch": mismatch,
                "ok": ic == "ok" and fk == 0 and not mismatch}
    except sqlite3.Error as e:
        return {"ok": False, "error": str(e)}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
