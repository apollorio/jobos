"""Renderização do CV em HTML imprimível (A4), autocontido: sem fontes externas, CDN ou scripts.

Todo texto vem de `cv_data` (linhas do perfil) e passa por html.escape. URLs aparecem como texto https puro.
"""
from __future__ import annotations

import base64
import hashlib
import html
from pathlib import Path

from jobos.paths import resolve_root

RENDER_VERSION = "render-3"
FORBIDDEN_SECTIONS = {"Competências-Chave", "Competências Principais", "Core Competencies"}
FALLBACK_CSS = ("@page{size:A4;margin:14mm}body{font-family:Arial,Helvetica,sans-serif;font-size:10pt;color:#000;"
                "background:#fff}h1{font-size:18pt}h2{font-size:11pt;border-bottom:1px solid #000}"
                "li{margin:0 0 1mm}.no-print{display:none}@media screen{.no-print{display:block}}")


def css_path() -> Path:
    return resolve_root() / "web" / "painel" / "cv-print.css"


def css_text() -> str:
    try:
        return css_path().read_text(encoding="utf-8")
    except OSError:
        return FALLBACK_CSS


def style_source_hash(css_body: str) -> str:
    """Token CSP do conteúdo exato do elemento style (sha256 em base64, sem o prefixo)."""
    return base64.b64encode(hashlib.sha256(css_body.encode("utf-8")).digest()).decode("ascii")


def renderer_id() -> str:
    """Identifica o renderizador (versão + hash do CSS): muda o hash de entrada do pacote se o visual mudar."""
    return f"cv_render:{RENDER_VERSION}:css-{hashlib.sha256(css_text().encode('utf-8')).hexdigest()[:12]}"


def _e(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _txt(line) -> str:
    return line.get("text", "") if isinstance(line, dict) else ""


def _li(line, cls: str = "") -> str:
    ptr = line.get("pointer", "") if isinstance(line, dict) else ""
    c = f' class="{cls}"' if cls else ""
    return f'<li{c} data-ref="{_e(ptr)}">{_e(_txt(line))}</li>'


def _section(title: str, body: str) -> str:
    if title in FORBIDDEN_SECTIONS:
        raise ValueError("Seção artificial de competências proibida")
    return f"<section>\n<h2>{_e(title)}</h2>\n{body}\n</section>" if body else ""


def _ul(lines, cls: str = "") -> str:
    lines = [ln for ln in lines or [] if ln]
    return "<ul>\n" + "\n".join(_li(ln, cls) for ln in lines) + "\n</ul>" if lines else ""


def render_html(cv_data: dict) -> str:
    ident = cv_data.get("identity") or {}
    job = cv_data.get("job") or {}
    name = _txt(ident.get("name"))
    contact = [_txt(x) for x in [ident.get("location")] + list(ident.get("contacts") or []) if x]
    title_bits = [b for b in (name, "Currículo", job.get("company"), job.get("title")) if b]
    parts = []
    head = [f"<h1>{_e(name)}</h1>"]
    if cv_data.get("headline"):
        head.append(f'<p class="headline">{_e(_txt(cv_data["headline"]))}</p>')
    if contact:
        head.append(f'<p class="contact">{_e(" | ".join(contact))}</p>')
    parts.append('<header class="cv-header">\n' + "\n".join(head) + "\n</header>")

    summary = [ln for ln in cv_data.get("summary") or [] if ln]
    if summary:
        parts.append(_section("Resumo", "\n".join(f'<p data-ref="{_e(ln.get("pointer", ""))}">{_e(_txt(ln))}</p>'
                                                   for ln in summary)))
    exp_html = []
    for e in cv_data.get("experience") or []:
        role, company, period = _txt(e.get("role")), _txt(e.get("company")), _txt(e.get("period"))
        heading = _e(role) + (f" | {_e(company)}" if company else "")
        cls = "job independent" if e.get("scope") == "independent" else "job"
        block = f'<article class="{cls}">\n<h3>{heading}</h3>\n'
        if period:
            block += f'<p class="period">{_e(period)}</p>\n'
        block += _ul(e.get("bullets"))
        exp_html.append(block.rstrip() + "\n</article>")
    parts.append(_section("Experiência", "\n".join(exp_html)))
    skills = cv_data.get("skills") or {}
    sk = _ul(skills.get("professional"))
    if skills.get("independent"):
        sk += ('\n<h3>Em desenvolvimento e projetos independentes</h3>\n' + _ul(skills.get("independent")))
    parts.append(_section("Ferramentas", sk))
    cred = cv_data.get("credentials") or {}
    parts.append(_section("Formação", _ul(cred.get("education"))))
    parts.append(_section("Certificações e treinamentos", _ul(cred.get("certifications"))))
    langreg = _ul(list(cred.get("languages") or []) + list(cred.get("registrations") or []))
    parts.append(_section("Idiomas e registros", langreg))
    body = "\n".join(p for p in parts if p)
    css = css_text().replace("</", "<\\/")
    style_body = f"\n{css}\n"
    token = style_source_hash(style_body)
    return (
        "<!doctype html>\n"
        '<html lang="pt-BR">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta name="robots" content="noindex,nofollow">\n'
        f'<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'none\'; '
        f'style-src \'sha256-{token}\'; img-src data:">\n'
        f"<title>{_e(' - '.join(title_bits))}</title>\n<style>{style_body}</style>\n</head>\n<body>\n"
        f'<main class="cv">\n{body}\n</main>\n</body>\n</html>\n'
    )
