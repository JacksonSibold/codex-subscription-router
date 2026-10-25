"""Single source of the Relay release version."""
from __future__ import annotations

from pathlib import Path


def _read_version() -> str:
    candidates = (
        Path(__file__).resolve().with_name("VERSION"),
        Path(__file__).resolve().parent.parent / "VERSION",
    )
    for candidate in candidates:
        try:
            value = candidate.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if value:
            return value
    return "1.0.1"


__version__ = _read_version()
