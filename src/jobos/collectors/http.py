"""HTTP de coleta: timeout por requisição, retry com backoff exponencial + jitter, Retry-After.

401/403 → Blocked (sem retry, sem troca de identidade). 404/410 → SourceFailure('not_found').
Conteúdo inesperado é validado pelo adapter (FormatChanged).
"""
from __future__ import annotations

import random
import time

import requests

from jobos import __version__
from jobos.collectors.base import Blocked, FormatChanged, SourceFailure

UA = (f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      f"Chrome/128.0 Safari/537.36 jobos-local/{__version__}")
TRANSIENT = {408, 425, 429, 500, 502, 503, 504}


class HttpClient:
    def __init__(self, *, timeout: float = 25, max_attempts: int = 3, base_delay: float = 1.0,
                 max_delay: float = 20.0, sleep=time.sleep):
        self.timeout = timeout
        self.max_attempts = max(1, max_attempts)
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.sleep = sleep
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"})
        self.requests_made = 0

    def _request(self, method: str, url: str, **kw) -> requests.Response:
        last_exc: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                self.requests_made += 1
                r = self.session.request(method, url, timeout=self.timeout, **kw)
            except (requests.ConnectionError, requests.Timeout) as e:
                last_exc = e
                if attempt == self.max_attempts:
                    raise SourceFailure("network", f"{type(e).__name__}: {str(e)[:160]}") from e
                self._backoff(attempt, None)
                continue
            if r.status_code in (401, 403):
                raise Blocked(f"HTTP {r.status_code} em {url}")
            if r.status_code in (404, 410):
                raise SourceFailure("not_found", f"HTTP {r.status_code} em {url}")
            if r.status_code in TRANSIENT:
                if attempt == self.max_attempts:
                    raise SourceFailure(f"http_{r.status_code}", f"HTTP {r.status_code} em {url} após {attempt} tentativas")
                self._backoff(attempt, r.headers.get("Retry-After"))
                continue
            if r.status_code >= 400:
                raise SourceFailure(f"http_{r.status_code}", f"HTTP {r.status_code} em {url}")
            return r
        raise SourceFailure("network", str(last_exc))

    def _backoff(self, attempt: int, retry_after: str | None) -> None:
        delay = None
        if retry_after:
            try:
                delay = float(retry_after)
            except ValueError:
                delay = None
        if delay is None:
            delay = min(self.max_delay, self.base_delay * (2 ** (attempt - 1)))
            delay += random.uniform(0, delay / 2)
        self.sleep(min(delay, 60.0))

    def get_text(self, url: str, *, headers: dict | None = None, params: dict | None = None) -> tuple[int, str]:
        r = self._request("GET", url, headers=headers, params=params)
        r.encoding = r.encoding or "utf-8"
        return r.status_code, r.text

    def get_json(self, url: str, *, headers: dict | None = None, params: dict | None = None):
        h = {"Accept": "application/json", **(headers or {})}
        r = self._request("GET", url, headers=h, params=params)
        return _json(r, url)

    def post_json(self, url: str, body: dict, *, headers: dict | None = None):
        h = {"Accept": "application/json", "Content-Type": "application/json", **(headers or {})}
        r = self._request("POST", url, headers=h, json=body)
        return _json(r, url)


def _json(r: requests.Response, url: str):
    ctype = r.headers.get("Content-Type", "")
    text = r.text.lstrip()
    if not text.startswith(("{", "[")):
        raise FormatChanged(f"resposta não-JSON ({ctype or 'sem content-type'}) em {url}: {text[:80]!r}")
    try:
        return r.json()
    except ValueError as e:
        raise FormatChanged(f"JSON inválido em {url}: {e}") from e
