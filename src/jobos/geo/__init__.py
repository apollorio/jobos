"""Geocodificação local e determinística (sem serviço externo em tempo de execução).

`places.json` foi gerado uma vez a partir da malha de municípios do RJ do IBGE (centroides por área),
de bairros do Rio com coordenadas aproximadas e de cidades de outros estados citadas em vagas.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from jobos.domain.identity import fold

UFS = {"ac", "al", "ap", "am", "ba", "ce", "df", "es", "go", "ma", "mt", "ms", "mg", "pa", "pb", "pr", "pe", "pi", "rj",
       "rn", "rs", "ro", "rr", "sc", "sp", "se", "to"}
ABROAD = ["norway", "noruega", "united kingdom", "uk", "netherlands", "holanda", "singapore", "malaysia", "usa",
          "united states", "houston", "aberdeen", "stavanger", "bergen", "angola", "guyana", "mexico", "india", "portugal",
          "france", "italy", "spain", "germany", "australia", "nigeria", "ghana", "mozambique", "uae", "dubai", "qatar"]
REMOTE = ["remoto", "remote", "home office", "teletrabalho"]


@lru_cache(maxsize=1)
def places() -> dict:
    return json.loads(Path(__file__).with_name("places.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _pattern() -> re.Pattern:
    keys = sorted(places(), key=len, reverse=True)  # nome mais longo primeiro ("sao goncalo" antes de "goncalo")
    return re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(k) for k in keys) + r")(?![a-z0-9])")


@lru_cache(maxsize=16384)
def _find(text: str) -> dict | None:
    hits = _pattern().findall(text)
    if not hits:
        return None
    return places()[max(hits, key=len)]  # o nome mais específico citado


def geocode(location: str | None, title: str | None = None) -> dict:
    """Retorna {name, uf, lat, lon, ibge, precision, scope}. scope: rj | br | abroad | remote | unknown."""
    loc = fold(location)
    city_part = loc.split(",")[0].strip() if "," in loc else loc
    # "Cidade/UF" no título vence o escritório (Greenhouse usa o escritório como local: "Brazil - Rio" para vaga em Barueri)
    for m in re.finditer(r"([a-z][a-z .']{1,40}?)\s*[/-]\s*([a-z]{2})(?![a-z])", fold(title)):
        if m.group(2) in UFS:
            p = _find(m.group(1).strip())
            if p and p["uf"].lower() == m.group(2):
                return {"name": p["name"], "uf": p["uf"], "lat": p["lat"], "lon": p["lon"], "ibge": p.get("ibge"),
                        "precision": "title_city_uf", "scope": "rj" if p["uf"] == "RJ" else "br"}
    for text, precision in ((city_part, "city"), (loc, "city"), (fold(title), "title")):
        if not text:
            continue
        p = _find(text)
        if p:
            prec = "neighborhood" if p.get("kind") == "bairro" else precision
            return {"name": p["name"], "uf": p["uf"], "lat": p["lat"], "lon": p["lon"], "ibge": p.get("ibge"),
                    "precision": prec, "scope": "rj" if p["uf"] == "RJ" else "br"}
    hay = f"{loc} {fold(title)}"
    if any(re.search(rf"(?<![a-z]){re.escape(r)}(?![a-z])", hay) for r in REMOTE):
        return {"name": "Remoto", "uf": None, "lat": None, "lon": None, "ibge": None, "precision": "none", "scope": "remote"}
    if any(re.search(rf"(?<![a-z]){re.escape(a)}(?![a-z])", loc) for a in ABROAD):
        return {"name": location, "uf": None, "lat": None, "lon": None, "ibge": None, "precision": "country", "scope": "abroad"}
    m = re.search(r"(?:^|[\s,/-])(rj|rio de janeiro)(?:$|[\s,/-])", loc)
    if m:  # só o estado: posição do estado, sem município
        return {"name": "Rio de Janeiro (estado)", "uf": "RJ", "lat": None, "lon": None, "ibge": None,
                "precision": "state", "scope": "rj"}
    return {"name": location or "Local não informado", "uf": None, "lat": None, "lon": None, "ibge": None,
            "precision": "none", "scope": "unknown"}
