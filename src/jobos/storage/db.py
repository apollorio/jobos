"""Conexão SQLite, migrações versionadas e backup consistente."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from jobos.timeutil import iso

MIGRATIONS_DIR = Path(__file__).with_name("migrations")


class SchemaError(RuntimeError):
    pass


def connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    """WAL + synchronous=NORMAL: no D: deste PC cada fsync custa ~1,5 s (AUDIT §1)."""
    if readonly:
        con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=30,
                              isolation_level=None, check_same_thread=False)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(path), timeout=30, isolation_level=None, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA busy_timeout = 30000")
    if not readonly:
        con.execute("PRAGMA journal_mode = WAL")
        con.execute("PRAGMA synchronous = NORMAL")
    return con


@contextmanager
def tx(con: sqlite3.Connection, *, immediate: bool = True) -> Iterator[sqlite3.Connection]:
    """Transação curta explícita (a conexão está em autocommit)."""
    con.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    try:
        yield con
    except BaseException:
        con.execute("ROLLBACK")
        raise
    else:
        con.execute("COMMIT")


def _migrations() -> list[tuple[int, str, str, str]]:
    out = []
    for p in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = int(p.name.split("_", 1)[0])
        sql = p.read_text(encoding="utf-8")
        out.append((version, p.name, hashlib.sha256(sql.encode("utf-8")).hexdigest(), sql))
    return out


def migrate(con: sqlite3.Connection) -> list[str]:
    con.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY, name TEXT NOT NULL, sha256 TEXT NOT NULL, applied_at TEXT NOT NULL)""")
    applied = {r["version"]: r for r in con.execute("SELECT * FROM schema_migrations")}
    done = []
    for version, name, digest, sql in _migrations():
        if version in applied:
            if applied[version]["sha256"] != digest:
                raise SchemaError(f"migração {name} alterada depois de aplicada (hash diferente)")
            continue
        con.execute("BEGIN IMMEDIATE")
        try:
            for stmt in _split_sql(sql):
                con.execute(stmt)
            con.execute("INSERT INTO schema_migrations VALUES (?,?,?,?)", (version, name, digest, iso()))
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise
        done.append(name)
    return done


def _split_sql(sql: str) -> list[str]:
    lines = [ln for ln in sql.splitlines() if not ln.strip().startswith("--")]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]


def open_db(path: Path) -> sqlite3.Connection:
    con = connect(path)
    migrate(con)
    return con


def integrity(con: sqlite3.Connection) -> dict:
    ic = con.execute("PRAGMA integrity_check").fetchone()[0]
    fk = [tuple(r) for r in con.execute("PRAGMA foreign_key_check").fetchall()]
    return {"integrity_check": ic, "foreign_key_violations": len(fk)}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot_bytes(src: sqlite3.Connection) -> bytes:
    """Cópia consistente via Backup API para memória (funciona com WAL ativo)."""
    mem = sqlite3.connect(":memory:")
    try:
        src.backup(mem)
        return mem.serialize()
    finally:
        mem.close()


def write_snapshot(src: sqlite3.Connection, dest: Path) -> dict:
    data = snapshot_bytes(src)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, dest)
    chk = sqlite3.connect(f"file:{dest.as_posix()}?mode=ro", uri=True)
    try:
        result = chk.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        chk.close()
    return {"path": str(dest), "bytes": len(data), "sha256": sha256_file(dest), "integrity_check": result}


def table_counts(con: sqlite3.Connection, tables: list[str] | None = None) -> dict[str, int]:
    names = tables or [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    return {t: con.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0] for t in names}


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
