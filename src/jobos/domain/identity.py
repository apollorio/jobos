"""Identidade de anúncio, URL canônica, normalização e hash de conteúdo.

Identidade forte: (platform, tenant, external_id). Fallback: URL canônica.
O hash legado empresa+título+local NÃO é identidade (A02).
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

NORMALIZATION_VERSION = "norm-v2"  # v2: ignora caixa, acentos, pontuação e marcadores

# Somente parâmetros de rastreamento conhecidos. Parâmetros que identificam a vaga ficam.
TRACKING_PARAMS = {"gclid", "fbclid", "mc_cid", "mc_eid", "jobboardsource", "_ga", "trk", "ref_src"}


def fold(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s.lower()).strip()


def canonical_url(url: str | None) -> str | None:
    if not url:
        return None
    try:
        p = urlsplit(url.strip())
    except ValueError:
        return None
    if p.scheme not in ("http", "https") or not p.netloc:
        return None
    query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS]
    path = p.path or "/"
    return urlunsplit(("https", p.netloc.lower(), path, urlencode(query), p.fragment))


def safe_http_url(url: str | None) -> str | None:
    """Só http/https; o painel nunca usa javascript:/data: vindos de anúncio."""
    if not url:
        return None
    try:
        p = urlsplit(url.strip())
    except ValueError:
        return None
    return url.strip() if p.scheme in ("http", "https") and p.netloc else None


def workday_req_id(segment: str) -> str:
    """'Title-Slug_R111671-1' → 'R111671-1'. O slug muda com o título; a requisição não."""
    seg = unquote(segment.rstrip("/").rsplit("/", 1)[-1])
    m = re.search(r"_([A-Za-z]{0,4}-?\d[\w-]*)$", seg)
    return m.group(1) if m else seg


def j2w_id(url_or_path: str) -> str | None:
    """SAP J2W: '/job/<slug>/<id>/' → '<id>'."""
    m = re.search(r"/job/[^/]+/(\d+)/?", url_or_path or "")
    return m.group(1) if m else None


def totvs_number(url: str) -> str | None:
    m = re.search(r"/(?:job-opportunity/)?(\d+)(?:/|$)", urlsplit(url or "").path)
    return m.group(1) if m else None


def host_label(url: str | None) -> str:
    try:
        return urlsplit(url or "").netloc.split(".")[0].lower()
    except ValueError:
        return ""


def norm_text(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def semantic_text(s: str | None) -> str:
    """Só palavras: formatação (marcadores, espaços, &nbsp;, caixa, acentos) não é mudança de conteúdo."""
    return re.sub(r"[\W_]+", " ", fold(s)).strip()


def content_hash(fields: dict) -> str:
    """Conteúdo significativo apenas (sem timestamps de coleta, ordem de cards, rastreamento ou formatação)."""
    keys = ("title", "description", "location", "workplace", "salary", "department", "deadline")
    blob = "\x1f".join(f"{k}={semantic_text(fields.get(k))}" for k in keys)
    return hashlib.sha256(f"{NORMALIZATION_VERSION}\x1e{blob}".encode("utf-8")).hexdigest()


def is_talent_pool(title: str, terms: list[str]) -> bool:
    t = fold(title)
    return any(fold(term) in t for term in terms)


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", fold(s)).strip("-") or "sem-nome"
