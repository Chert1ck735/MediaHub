"""Пауза фонового воркера на время формирования и вручную."""
from __future__ import annotations

_formation_active = 0
_worker_paused = False


def formation_started() -> None:
    global _formation_active
    _formation_active += 1


def formation_finished() -> None:
    global _formation_active
    _formation_active = max(0, _formation_active - 1)


def is_formation_active() -> bool:
    return _formation_active > 0


def pause_worker() -> None:
    global _worker_paused
    _worker_paused = True


def resume_worker() -> None:
    global _worker_paused
    _worker_paused = False


def is_worker_paused() -> bool:
    return _worker_paused


def worker_should_idle() -> bool:
    return is_formation_active() or _worker_paused
