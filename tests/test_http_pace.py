"""A varredura e a sonda compartilham uma pausa. O intervalo 0 deixa os testes offline instantâneos."""
from jobos.collectors.http import HttpClient, configure_pace


class _Resp:
    status_code = 200
    text = "ok"
    encoding = "utf-8"
    headers: dict = {}


def test_shared_gap_between_requests_from_different_clients():
    slept = []
    configure_pace(2.0, slept.append)
    try:
        a, b = HttpClient(max_attempts=1), HttpClient(max_attempts=1)
        a.session.request = lambda *args, **kwargs: _Resp()
        b.session.request = lambda *args, **kwargs: _Resp()
        a.get_text("https://board.example/jobs")
        b.get_text("https://other.example/jobs")
        assert len(slept) == 1 and abs(slept[0] - 2.0) < 0.05
    finally:
        configure_pace(0)


def test_zero_interval_does_not_sleep():
    slept = []
    configure_pace(0, slept.append)
    try:
        client = HttpClient(max_attempts=1)
        client.session.request = lambda *a, **k: _Resp()
        client.get_text("https://board.example/a")
        client.get_text("https://board.example/b")
        assert slept == []
    finally:
        configure_pace(0)
