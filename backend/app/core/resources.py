from __future__ import annotations

import sys
from pathlib import Path


def resource_root() -> Path:
    """Return the source checkout or PyInstaller bundle resource root."""

    frozen_root = getattr(sys, "_MEIPASS", None)
    if isinstance(frozen_root, str):
        return Path(frozen_root)
    return Path(__file__).resolve().parents[3]


def resource_path(*parts: str) -> Path:
    return resource_root().joinpath(*parts)
