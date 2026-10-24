"""W1a: T38 (pasta com espaços e diretório corrente diferente) e códigos de saída 4 e 5 pela CLI.

Processos reais via subprocess usam JOBOS_DATA temporário; nenhum comando aqui toca o banco real."""
import logging
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from jobos import cli, pipeline
from jobos.lock import CycleLock
from jobos.paths import get_paths
from jobos.timeutil import brt_date

SRC = Path(__file__).resolve().parents[1] / "src"
CODIGOS_DOCUMENTADOS = {0, 2, 3, 4, 5}


@pytest.fixture(autouse=True)
def _solta_handlers_de_log():
    yield
    lg = logging.getLogger("jobos")
    for h in list(lg.handlers):
        if isinstance(h, logging.FileHandler):
            lg.removeHandler(h)
            h.close()


def _env(data: Path, **extra) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("JOBOS_ROOT", "JOBOS_DB", "JOBOS_DATA")}
    env.update({"JOBOS_DATA": str(data), "PYTHONPATH": str(SRC), "PYTHONIOENCODING": "utf-8"})
    env.update(extra)
    return env


def _jobos(args, cwd: Path, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "jobos", *args], cwd=cwd, env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=240)


@pytest.fixture()
def cwd_e_dados(tmp_path):
    cwd = tmp_path / "pasta com espaços" / "diretório corrente"
    cwd.mkdir(parents=True)
    return cwd, tmp_path / "dados com espaço" / "data"


# --------------------------------------------------------------------------- T38

@pytest.mark.parametrize("args", [["status"], ["doctor"], ["--json", "status"], ["cycle", "--dry-run", "--fixtures"]])
def test_t38_cli_works_with_spaces_and_other_cwd(cwd_e_dados, args):
    """T38: subcomandos rodam com cwd fora da raiz e JOBOS_DATA com espaços; código documentado, sem traceback."""
    cwd, data = cwd_e_dados
    r = _jobos(args, cwd, _env(data))
    assert r.returncode in CODIGOS_DOCUMENTADOS, r.stderr
    assert "Traceback" not in r.stdout + r.stderr


def test_t38_status_uses_the_data_dir_with_spaces(cwd_e_dados):
    """T38: o banco usado é o do JOBOS_DATA informado (caminho com espaços), não o do diretório corrente."""
    cwd, data = cwd_e_dados
    r = _jobos(["status"], cwd, _env(data))
    assert r.returncode == 0, r.stderr
    assert (data / "jobos.sqlite3").is_file()
    assert not (cwd / "data").exists()
    assert str((data / "jobos.sqlite3").resolve()) in r.stdout


def test_t38_real_process_writes_daily_log_without_console_duplicate(cwd_e_dados):
    """Log diário por processo real: arquivo do dia não vazio, com comando e código final; sem INFO no console."""
    cwd, data = cwd_e_dados
    r = _jobos(["status"], cwd, _env(data))
    assert r.returncode == 0, r.stderr
    arquivo = data / "logs" / f"jobos-{brt_date().isoformat()}.log"
    linhas = arquivo.read_text(encoding="utf-8").splitlines()
    assert any("comando status encerrado: código=0" in ln for ln in linhas)
    assert "INFO" not in r.stderr


# --------------------------------------------------------------------------- código 5

def test_exit_5_invalid_engine_root_via_cli(cwd_e_dados, tmp_path):
    """Código 5: JOBOS_ROOT apontando para pasta sem pyproject/src/jobos é configuração necessária, sem traceback."""
    cwd, data = cwd_e_dados
    r = _jobos(["status"], cwd, _env(data, JOBOS_ROOT=str(tmp_path / "inexistente")))
    assert r.returncode == 5
    assert "JOBOS_ROOT inválido" in r.stderr and "Traceback" not in r.stderr


def test_exit_5_serve_refuses_non_loopback_host(data_dir, capsys):
    """Código 5: o painel só escuta em loopback; pedido para 0.0.0.0 é recusado antes de subir o servidor."""
    assert cli.main(["serve", "--host", "0.0.0.0", "--port", "8797"]) == 5
    assert "loopback" in capsys.readouterr().err


def test_exit_5_serve_refuses_busy_port_without_killing_anything(data_dir, capsys):
    """Código 5: porta ocupada é configuração a corrigir; o processo que a ocupa continua vivo."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    s.listen()
    port = s.getsockname()[1]
    try:
        assert cli.main(["serve", "--host", "127.0.0.1", "--port", str(port)]) == 5
        assert "ocupada" in capsys.readouterr().err
        assert s.fileno() != -1  # socket de quem ocupa a porta segue aberto
    finally:
        s.close()


# --------------------------------------------------------------------------- código 4

def test_exit_4_cycle_skipped_by_overlap_via_cli(data_dir, monkeypatch, capsys):
    """Código 4: ciclo normal com trava de outro processo sai com 4, grava skipped_overlap e não coleta nada."""
    def nao_deve_rodar(*a, **k):
        raise AssertionError("ciclo rodou com a trava ocupada")
    monkeypatch.setattr(pipeline, "_run_locked", nao_deve_rodar)
    lk = CycleLock(get_paths().lock_file)
    lk.acquire({"run_id": "outro-processo"})
    try:
        rc = cli.main(["cycle", "--json"])
    finally:
        lk.release()
    assert rc == 4
    assert "skipped_overlap" in capsys.readouterr().out
