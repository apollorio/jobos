"""Perfil canônico versionado por hash. Arquivo inválido nunca substitui o último válido (T25)."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from jobos.storage.db import tx
from jobos.timeutil import iso

REQUIRED_MODULES = ("identity", "experience_nodes", "education_tree", "software_systems_tree",
                    "certification_training_tree", "truth_boundaries")


class ProfileError(ValueError):
    pass


@dataclass(frozen=True)
class Profile:
    profile_id: str
    data: dict

    def pointer(self, ptr: str):
        """Resolve JSON Pointer (RFC 6901). Levanta KeyError se não resolver."""
        if ptr == "":
            return self.data
        if not ptr.startswith("/"):
            raise KeyError(ptr)
        cur = self.data
        for raw in ptr[1:].split("/"):
            part = raw.replace("~1", "/").replace("~0", "~")
            if isinstance(cur, list):
                cur = cur[int(part)]
            elif isinstance(cur, dict):
                cur = cur[part]
            else:
                raise KeyError(ptr)
        return cur

    def resolves(self, ptr: str) -> bool:
        try:
            self.pointer(ptr)
            return True
        except (KeyError, IndexError, ValueError):
            return False


def validate(data: dict) -> None:
    if not isinstance(data, dict):
        raise ProfileError("perfil precisa ser objeto JSON")
    missing = [m for m in REQUIRED_MODULES if m not in data]
    if missing:
        raise ProfileError(f"módulos obrigatórios ausentes: {missing}")
    edu = data["education_tree"]
    if not isinstance(edu, dict) or not edu:
        raise ProfileError("education_tree vazio")


def register_profile(con: sqlite3.Connection, path: Path, origin: str = "config/profile/master.json") -> dict:
    """Lê, valida e registra o perfil. Retorna o estado (ativo e eventual erro)."""
    raw = path.read_bytes() if path.is_file() else b""
    digest = hashlib.sha256(raw).hexdigest()
    error = None
    data = None
    try:
        if not raw:
            raise ProfileError(f"arquivo ausente: {path}")
        data = json.loads(raw.decode("utf-8"))
        validate(data)
    except (ValueError, UnicodeDecodeError) as e:
        error = f"{type(e).__name__}: {e}"
    with tx(con):
        exists = con.execute("SELECT profile_id FROM profile_versions WHERE profile_id=?", (digest,)).fetchone()
        if not exists:
            con.execute("""INSERT INTO profile_versions (profile_id, origin, path, received_at, valid, error, content, is_active)
                           VALUES (?,?,?,?,?,?,?,0)""",
                        (digest, origin, str(path), iso(), int(error is None), error,
                         raw.decode("utf-8", errors="replace") if error is None else None))
        if error is None:
            con.execute("UPDATE profile_versions SET is_active = (profile_id = ?)", (digest,))
    active = con.execute("SELECT profile_id FROM profile_versions WHERE is_active=1").fetchone()
    return {"file_sha256": digest, "file_valid": error is None, "error": error,
            "active_profile_id": active["profile_id"] if active else None}


def active_profile(con: sqlite3.Connection) -> Profile | None:
    row = con.execute("SELECT profile_id, content FROM profile_versions WHERE is_active=1").fetchone()
    if not row:
        return None
    return Profile(row["profile_id"], json.loads(row["content"]))
