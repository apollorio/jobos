"""HTML de anúncio → texto. Sem execução, sem corte silencioso (A08)."""
from __future__ import annotations

import html as htmllib
import re

MAX_STORED = 60000  # limite de armazenamento; corte é registrado com tamanho original


def html_to_text(s: str | None) -> str:
    s = htmllib.unescape(s or "")
    s = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", s)
    for pat, rep in ((r"(?i)<br\s*/?>", "\n"), (r"(?i)</p>", "\n"), (r"(?i)<li[^>]*>", "\n- "), (r"(?i)</li>", ""),
                     (r"(?i)</h[1-6]>", "\n"), (r"(?i)<h[1-6][^>]*>", "\n"), (r"(?i)</div>", "\n"), (r"(?i)</tr>", "\n")):
        s = re.sub(pat, rep, s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = htmllib.unescape(s)  # Greenhouse escapa duas vezes
    s = s.replace("\xa0", " ").replace("​", "")
    s = re.sub(r"[ \t]{2,}", " ", s)
    s = re.sub(r" *\n *", "\n", s)
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def bounded(text: str) -> tuple[str, str, int | None, str | None]:
    """Retorna (texto, status, tamanho_original, nota). Corte só acima de MAX_STORED e sempre registrado."""
    if not text:
        return "", "missing", None, None
    if len(text) > MAX_STORED:
        return text[:MAX_STORED], "truncated", len(text), f"armazenado {MAX_STORED} de {len(text)} caracteres"
    return text, "full", len(text), None


def clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(s or "")).strip()
