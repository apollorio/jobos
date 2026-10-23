"""Trava de ciclo entre processos (CLI, Agendador, API).

Usa lock do SO sobre um arquivo (`msvcrt.locking` no Windows, `fcntl.flock` no resto):
o SO libera a trava se o processo morrer, então PID antigo não segura o ciclo para sempre.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from jobos.timeutil import iso

if os.name == "nt":
    import msvcrt
else:  # pragma: no cover
    import fcntl


class LockBusy(RuntimeError):
    def __init__(self, owner: dict | None):
        super().__init__("ciclo já em execução")
        self.owner = owner or {}


class CycleLock:
    def __init__(self, path: Path):
        self.path = path
        self.info_path = path.with_suffix(".owner.json")
        self.fd: int | None = None

    def acquire(self, owner: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            if os.name == "nt":
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:  # pragma: no cover
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            raise LockBusy(self.read_owner()) from None
        self.fd = fd
        try:
            self.info_path.write_text(json.dumps({**owner, "pid": os.getpid(), "since": iso()}), encoding="utf-8")
        except OSError:
            pass

    def read_owner(self) -> dict | None:
        try:
            return json.loads(self.info_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def release(self) -> None:
        if self.fd is None:
            return
        try:
            if os.name == "nt":
                os.lseek(self.fd, 0, os.SEEK_SET)
                msvcrt.locking(self.fd, msvcrt.LK_UNLCK, 1)
            else:  # pragma: no cover
                fcntl.flock(self.fd, fcntl.LOCK_UN)
        finally:
            os.close(self.fd)
            self.fd = None
            try:
                self.info_path.unlink()
            except OSError:
                pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()
