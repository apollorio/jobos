"""Acesso explícito aos portais no Edge. Não inspeciona cookies nem infere login."""
import os
from pathlib import Path
import subprocess

from jobos.domain.identity import safe_http_url


def connection_catalog(registry):
    return [{"source_id": s.source_id, "company": s.company_name, "platform": s.platform,
             "url": safe_http_url(s.board_url), "session_status": "not_verified",
             "automatic_submission": False, "collection_enabled": s.enabled}
            for s in registry.sources if s.board_url]


def open_login(registry, source_id):
    source = registry.get(source_id)
    url = safe_http_url(source.board_url)
    if not url or not url.startswith("https://"):
        raise ValueError("Portal HTTPS não configurado")
    candidates = [Path(os.environ.get(key, "C:/")) / "Microsoft/Edge/Application/msedge.exe"
                  for key in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA")]
    edge = next((p for p in candidates if p.is_file()), None)
    if edge is None:
        raise ValueError("Edge não encontrado. Abra o link do portal no Edge já conectado.")
    subprocess.Popen([str(edge), "--new-tab", url], shell=False)
    return {"opened": True, "session_status": "not_verified", "automatic_submission": False}
