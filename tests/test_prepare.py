"""Preparo determinístico: seleciona textos do perfil e não escolhe headline empatado."""
from jobos.matching.prepare import build_support
from jobos.matching.profile import active_profile


def _analysis():
    return {
        "decision": "needs_review",
        "unknowns": ["NR-10 não consta no perfil canônico; confirmar."],
        "requirements": [
            {"text": "Experiência em operações marítimas offshore", "status": "met", "importance": "mandatory",
             "category": "domain", "explanation": "Domínio relacionado no perfil: naval_marine_offshore.",
             "evidence_refs": [{"pointer": "/domain_tree/naval_marine_offshore", "label": "naval_marine_offshore"}]},
            {"text": "Bacharel em Ciências Náuticas", "status": "gap", "importance": "mandatory",
             "category": "truth_boundary",
             "explanation": "Lacuna: credencial náutica que o perfil declara não possuir.",
             "evidence_refs": [{"pointer": "/truth_boundaries/nautical_credentials", "label": "truth_boundaries"}]},
            {"text": "Conhecimento em Primavera P6", "status": "partial", "importance": "desirable",
             "category": "software", "explanation": "status no perfil: developing",
             "evidence_refs": [{"pointer": "/software_systems_tree/planning/sw_primavera_p6", "label": "Primavera P6",
                                "qualifier": "status no perfil: developing"}]},
        ],
    }


def test_support_copies_profile_text_and_refuses_tied_headline(ctx):
    profile = active_profile(ctx.con)
    packet = build_support(profile, _analysis(), "https://example.com/vaga")
    assert packet["available"] is True
    assert packet["uses_ai"] is False and packet["writes_cv"] is False and packet["sends_application"] is False
    assert packet["headline"] is None
    assert len(packet["headline_candidates"]) >= 2
    assert all("naval_marine_offshore" in row["domains"] for row in packet["headline_candidates"])
    story = next(s for s in packet["stories"] if s["id"] == "fleet_planning")
    assert story["text"] == profile.data["interview_story_bank"]["fleet_planning"]
    assert all(not s["id"].endswith("_long") for s in packet["stories"])
    gap = packet["do_not_claim"][0]
    assert gap["boundary"] is True and "Náuticas" in gap["text"]
    assert gap["explanation"].startswith("Lacuna:")
    assert packet["unknowns"] == ["NR-10 não consta no perfil canônico; confirmar."]
    assert packet["checklist"][0].startswith("Abrir o anúncio oficial")
    assert packet["public_profile_url"] == "https://rvalle.com.br/rafael.json"


def test_support_without_analysis_does_not_invent(ctx):
    packet = build_support(active_profile(ctx.con), None, None)
    assert packet["available"] is False
    assert packet["sends_application"] is False
    assert "stories" not in packet
    assert packet["checklist"][0].startswith("Achar o anúncio oficial")


def test_unknown_wording_is_not_promoted(ctx):
    profile = active_profile(ctx.con)
    packet = build_support(profile, {"decision": "needs_review", "requirements": [
        {"text": "Inglês fluente", "status": "met", "category": "language", "explanation": "Inglês fluente.",
         "evidence_refs": [{"pointer": "/identity/languages/other_languages", "label": "outros idiomas"}]},
    ]}, None)
    evidence = packet["use"][0]["evidence"][0]
    assert "profile_wording" not in evidence


