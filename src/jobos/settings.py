"""Leitura validada das configurações YAML (loader seguro)."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from jobos.paths import Paths

COVERAGE_KINDS = ("full_board", "filtered_board", "incremental_query", "single_posting")


class ConfigError(ValueError):
    pass


def load_yaml(path: Path) -> dict:
    if not path.is_file():
        raise ConfigError(f"arquivo de configuração ausente: {path}")
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path.name}: raiz precisa ser um mapa")
    return data


@dataclass(frozen=True)
class SourceConfig:
    source_id: str
    company_id: str
    company_name: str
    platform: str
    adapter: str | None
    enabled: bool
    params: dict
    coverage: str
    limits: dict
    priority: int
    board_url: str | None
    configuration_origin: str
    verification_status: str
    note: str | None = None
    fallback_adapters: tuple = field(default_factory=tuple)

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


@dataclass(frozen=True)
class Registry:
    sources: tuple[SourceConfig, ...]
    sha256: str
    content: str

    def get(self, source_id: str) -> SourceConfig:
        for s in self.sources:
            if s.source_id == source_id:
                return s
        raise ConfigError(f"fonte desconhecida: {source_id}")

    def runnable(self) -> list[SourceConfig]:
        return [s for s in self.sources if s.enabled and s.adapter]


def load_registry(paths: Paths) -> Registry:
    path = paths.config / "sources.yaml"
    content = path.read_text(encoding="utf-8")
    data = yaml.safe_load(content) or {}
    if data.get("schema_version") != 1:
        raise ConfigError("sources.yaml: schema_version 1 esperado")
    defaults = data.get("defaults") or {}
    seen: set[str] = set()
    out = []
    for i, raw in enumerate(data.get("sources") or []):
        if not isinstance(raw, dict):
            raise ConfigError(f"sources.yaml: item {i} inválido")
        for req in ("source_id", "company_id", "company_name", "platform"):
            if not raw.get(req):
                raise ConfigError(f"sources.yaml: item {i} sem {req}")
        sid = str(raw["source_id"])
        if sid in seen:
            raise ConfigError(f"sources.yaml: source_id duplicado {sid}")
        seen.add(sid)
        coverage = raw.get("coverage", "full_board")
        if coverage not in COVERAGE_KINDS:
            raise ConfigError(f"sources.yaml: {sid} coverage inválido {coverage}")
        limits = {**(defaults.get("limits") or {}), **(raw.get("limits") or {})}
        out.append(SourceConfig(
            source_id=sid,
            company_id=str(raw["company_id"]),
            company_name=str(raw["company_name"]),
            platform=str(raw["platform"]),
            adapter=raw.get("primary_adapter"),
            enabled=bool(raw.get("enabled", defaults.get("enabled", True))),
            params=dict(raw.get("params") or {}),
            coverage=coverage,
            limits=limits,
            priority=int(raw.get("priority", 3)),
            board_url=raw.get("board_url"),
            configuration_origin=str(raw.get("configuration_origin", "unknown")),
            verification_status=str(raw.get("verification_status", defaults.get("verification_status", "unknown"))),
            note=raw.get("note"),
            fallback_adapters=tuple(raw.get("fallback_adapters") or ()),
        ))
    return Registry(tuple(out), hashlib.sha256(content.encode("utf-8")).hexdigest(), content)


@dataclass(frozen=True)
class Settings:
    paths: Paths
    app: dict
    preferences: dict
    matching: dict
    notifications: dict

    def legacy_path(self, key: str) -> Path:
        rel = (self.app.get("legacy") or {}).get(key)
        if not rel:
            raise ConfigError(f"app.yaml legacy.{key} ausente")
        return (self.paths.root / rel).resolve()


def load_settings(paths: Paths) -> Settings:
    return Settings(
        paths=paths,
        app=load_yaml(paths.config / "app.yaml"),
        preferences=load_yaml(paths.config / "preferences.yaml"),
        matching=load_yaml(paths.config / "matching.yaml"),
        notifications=load_yaml(paths.config / "notifications.yaml"),
    )


def get(d: dict, dotted: str, default: Any = None) -> Any:
    cur: Any = d
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur
