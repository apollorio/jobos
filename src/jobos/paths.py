"""Caminhos absolutos a partir da raiz do engine. Nada depende do diretório corrente."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_PACKAGE_ROOT = Path(__file__).resolve().parents[2]  # .../_system


class RootError(RuntimeError):
    pass


def _valid_root(p: Path) -> bool:
    return (p / "pyproject.toml").is_file() and (p / "src" / "jobos").is_dir()


def resolve_root() -> Path:
    """`JOBOS_ROOT` só é aceito se apontar para uma raiz válida do engine."""
    override = os.environ.get("JOBOS_ROOT")
    if override:
        p = Path(override).resolve()
        if not _valid_root(p):
            raise RootError(f"JOBOS_ROOT inválido (sem pyproject.toml/src/jobos): {p}")
        return p
    return _PACKAGE_ROOT


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def workspace(self) -> Path:
        return self.root.parent

    @property
    def config(self) -> Path:
        return self.root / "config"

    @property
    def profile_master(self) -> Path:
        return self.config / "profile" / "master.json"

    @property
    def data(self) -> Path:
        override = os.environ.get("JOBOS_DATA")  # testes e restauração usam diretório separado
        return Path(override).resolve() if override else self.root / "data"

    @property
    def db(self) -> Path:
        override = os.environ.get("JOBOS_DB")
        return Path(override).resolve() if override else self.data / "jobos.sqlite3"

    @property
    def imports(self) -> Path:
        return self.data / "imports"

    @property
    def backups(self) -> Path:
        return self.data / "backups"

    @property
    def logs(self) -> Path:
        return self.data / "logs"

    @property
    def raw(self) -> Path:
        return self.data / "raw"

    @property
    def outbox_preview(self) -> Path:
        return self.data / "outbox-preview"

    @property
    def artifacts(self) -> Path:
        return self.data / "artifacts"

    @property
    def exports(self) -> Path:
        return self.data / "exports"

    @property
    def lock_file(self) -> Path:
        return self.data / "cycle.lock"

    @property
    def web(self) -> Path:
        return self.root / "web"

    @property
    def fixtures(self) -> Path:
        return self.root / "tests" / "fixtures"

    def ensure(self) -> None:
        for d in (self.data, self.imports, self.backups, self.logs, self.raw,
                  self.outbox_preview, self.artifacts, self.exports):
            d.mkdir(parents=True, exist_ok=True)


def get_paths() -> Paths:
    return Paths(resolve_root())
