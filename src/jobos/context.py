"""Contexto de execução compartilhado por CLI, API e Agendador (mesmo serviço, mesma base)."""
from __future__ import annotations

import shutil
import sqlite3
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from jobos.matching.profile import register_profile
from jobos.paths import Paths, get_paths
from jobos.settings import Registry, Settings, load_registry, load_settings
from jobos.storage import repo
from jobos.storage.db import connect, migrate, open_db, snapshot_bytes, tx


@dataclass
class Context:
    paths: Paths
    settings: Settings
    registry: Registry
    con: sqlite3.Connection
    dry_run: bool = False
    temp_dir: Path | None = None
    profile_state: dict = field(default_factory=dict)

    @property
    def preview_dir(self) -> Path:
        return (self.temp_dir / "outbox-preview") if self.dry_run and self.temp_dir else self.paths.outbox_preview

    @property
    def raw_dir(self) -> Path:
        return (self.temp_dir / "raw") if self.dry_run and self.temp_dir else self.paths.raw

    def close(self) -> None:
        try:
            self.con.close()
        finally:
            if self.temp_dir and self.dry_run:
                shutil.rmtree(self.temp_dir, ignore_errors=True)


def open_context(*, dry_run: bool = False, paths: Paths | None = None, keep_temp: bool = False) -> Context:
    """Dry run: cópia temporária via Backup API; banco real e outbox real ficam intocados (T31)."""
    paths = paths or get_paths()
    paths.ensure()
    settings = load_settings(paths)
    registry = load_registry(paths)
    temp_dir = None
    if dry_run:
        temp_dir = Path(tempfile.mkdtemp(prefix="jobos-dry-"))
        temp_db = temp_dir / "dry-run.sqlite3"
        if paths.db.is_file():
            src = connect(paths.db, readonly=True)
            try:
                temp_db.write_bytes(snapshot_bytes(src))
            finally:
                src.close()
        con = connect(temp_db)
        migrate(con)
    else:
        con = open_db(paths.db)
    with tx(con):
        repo.sync_registry(con, registry)
        repo.relink_postings(con, registry)
    profile_state = register_profile(con, paths.profile_master)
    ctx = Context(paths, settings, registry, con, dry_run, temp_dir if not keep_temp else temp_dir, profile_state)
    return ctx
