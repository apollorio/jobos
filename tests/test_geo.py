"""Geocodificação local: cidade antes do estado, bairro, título Cidade/UF, exterior, remoto, desconhecido."""
from jobos.geo import geocode


def test_city_before_state_and_neighborhood():
    assert geocode("Macaé, Rio de Janeiro")["name"] == "Macaé"
    g = geocode("Barra da Tijuca")
    assert g["precision"] == "neighborhood" and g["scope"] == "rj"


def test_title_city_uf_beats_office():
    g = geocode("Brazil - Rio de Janeiro", "Analista de Operações - Híbrido - Santos-SP")
    assert g["name"] == "Santos" and g["scope"] == "br"


def test_abroad_remote_unknown_state():
    assert geocode("Stavanger, Norway")["scope"] == "abroad"
    assert geocode("", "Engenheiro Remoto")["scope"] == "remote"
    assert geocode(None)["scope"] == "unknown"
    s = geocode("RJ")
    assert s["precision"] == "state" and s["lat"] is None  # sem município: não inventa ponto
