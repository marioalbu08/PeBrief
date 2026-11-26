"""Căile din baza de date, relative la folderul `data/`.

Baza de date păstrează căile fișierelor (logo, video) relativ la `data/`, ca proiectul
să meargă și după ce folderul e mutat sau copiat pe alt calculator. Căile absolute
scrise de versiunile vechi se refac după bucata de după ultimul `data/` din ele.
"""
from __future__ import annotations

import os


def to_stored(path: str | None, data_dir: str) -> str | None:
    """Calea de pus în baza de date: relativă la `data_dir`, cu `/`."""
    if not path:
        return path
    full = os.path.abspath(path)
    try:
        rel = os.path.relpath(full, os.path.abspath(data_dir))
    except ValueError:  # alt disc pe Windows
        return full
    if rel.startswith(".."):
        return full
    return rel.replace(os.sep, "/")


def resolve(stored: str | None, data_dir: str) -> str | None:
    """Calea reală a unui fișier din baza de date (relativă, absolută sau absolută veche)."""
    if not stored:
        return stored
    if not os.path.isabs(stored):
        return os.path.join(data_dir, *stored.split("/"))
    if os.path.exists(stored):
        return stored
    parts = stored.replace("\\", "/").split("/")
    if "data" in parts:
        i = len(parts) - 1 - parts[::-1].index("data")
        moved = os.path.join(data_dir, *parts[i + 1:])
        if os.path.exists(moved):
            return moved
    return stored
