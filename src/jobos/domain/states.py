"""Três eixos de estado: anúncio, preparação/envio e processo seletivo."""
from __future__ import annotations

LISTING_STATES = ("active", "missing_unconfirmed", "closed_confirmed", "unknown")

PREP_STATES = ("discovered", "shortlisted", "cv_draft", "cv_ready", "awaiting_review", "submission_unknown",
               "submitted_manual", "submitted_verified", "legacy_needs_review", "dismissed")

STAGES = ("none", "screening", "test", "interview", "offer", "rejected", "withdrawn", "hired")

SUBMITTED = ("submitted_manual", "submitted_verified")

# Transições permitidas do eixo de preparação. Nenhuma leva a "enviada" por sugestão, e-mail, clique ou tempo.
PREP_TRANSITIONS: dict[str, set[str]] = {
    "discovered": {"shortlisted", "dismissed", "submitted_manual"},
    "shortlisted": {"cv_draft", "awaiting_review", "dismissed", "submitted_manual", "discovered"},
    "cv_draft": {"cv_ready", "shortlisted", "dismissed"},
    "cv_ready": {"awaiting_review", "cv_draft", "dismissed", "submitted_manual"},
    "awaiting_review": {"submitted_manual", "submitted_verified", "submission_unknown", "shortlisted", "dismissed"},
    "submission_unknown": {"submitted_verified", "submitted_manual", "awaiting_review"},
    "submitted_manual": {"submitted_verified"},
    "submitted_verified": set(),
    "legacy_needs_review": {"submitted_manual", "shortlisted", "dismissed", "discovered"},
    "dismissed": {"shortlisted", "discovered"},
}

# Origem exigida para confirmar envio.
SUBMISSION_ORIGINS = {"submitted_manual": {"user_asserted"},
                      "submitted_verified": {"platform_confirmation"}}

PREP_LABELS = {
    "discovered": "Nova", "shortlisted": "Na mira", "cv_draft": "CV em preparo", "cv_ready": "CV pronto",
    "awaiting_review": "Pronta para enviar", "submission_unknown": "Envio incerto",
    "submitted_manual": "Aplicado", "submitted_verified": "Aplicado ✓ comprovado",
    "legacy_needs_review": "Auto aplicado", "dismissed": "Descartada",
}

LISTING_LABELS = {"active": "Aberta", "missing_unconfirmed": "Sumiu do site (confirmando)",
                  "closed_confirmed": "Encerrada", "unknown": "Não verificada"}


def application_tag(row) -> dict:
    """Etiqueta curta e inequívoca para candidatura: {code, label, tone, hint, counts_as_applied}.

    "Auto aplicado" = marcado pelo sistema antigo sem ação comprovada (não conta como enviada).
    "Aplicado" = envio afirmado por você (inclui a marcação manual original do sistema antigo).
    "Aplicado ✓ comprovado" = prova da plataforma.
    """
    get = (lambda k: row[k] if k in row.keys() else None) if hasattr(row, "keys") else row.get
    state, hint, src = get("prep_state"), get("legacy_hint") or "", get("legacy_source") or ""
    date = (get("submitted_at") or get("legacy_date") or "")[:10]
    if state == "submitted_verified":
        return {"code": "applied_verified", "label": "Aplicado ✓ comprovado", "tone": "ok",
                "hint": f"confirmação da plataforma {date}".strip(), "counts_as_applied": True}
    if state == "submitted_manual":
        manual_original = "legacy_manual_mark_event" in hint
        return {"code": "applied", "label": "Aplicado", "tone": "ok",
                "hint": (f"manual original, sistema antigo, {date}" if manual_original else f"confirmado por você {date}").strip(),
                "counts_as_applied": True}
    if state == "legacy_needs_review":
        if src == "auto_sugerida" or "auto_consolidation" in hint:
            return {"code": "auto_applied", "label": "Auto aplicado", "tone": "warn",
                    "hint": f"o sistema antigo marcou sozinho após sugerir ({date}); sem prova de envio: confirme ou descarte",
                    "counts_as_applied": False}
        if "browser_saved_mark" in hint:
            return {"code": "portal_mark", "label": "Marcado no portal antigo", "tone": "warn",
                    "hint": "marcação do navegador; confirme se enviou", "counts_as_applied": False}
        return {"code": "legacy_review", "label": "Aplicado? (revisar)", "tone": "warn",
                "hint": "registro antigo sem procedência", "counts_as_applied": False}
    tones = {"submission_unknown": "danger", "dismissed": "muted", "awaiting_review": "info", "cv_ready": "info"}
    return {"code": state or "none", "label": PREP_LABELS.get(state, state or "Sem candidatura"),
            "tone": tones.get(state, "neutral"), "hint": "", "counts_as_applied": False}


class TransitionError(ValueError):
    pass


def check_prep_transition(current: str, target: str, origin: str) -> None:
    if target not in PREP_STATES:
        raise TransitionError(f"estado inválido: {target}")
    if target == current:
        raise TransitionError(f"já está em {target}")
    if target not in PREP_TRANSITIONS.get(current, set()):
        raise TransitionError(f"transição não permitida: {current} → {target}")
    allowed = SUBMISSION_ORIGINS.get(target)
    if allowed and origin not in allowed:
        raise TransitionError(f"{target} exige origem {sorted(allowed)}, recebido {origin}")


def check_stage(target: str) -> None:
    if target not in STAGES:
        raise TransitionError(f"estágio inválido: {target}")
