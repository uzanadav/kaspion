"""Where a household's data lives — always OUTSIDE the installation directory, so an
installed copy can sit in a read-only or shared location and two people on one machine
never share a database. See "Where things live" in docs/HOW_IT_WORKS.md.

Nothing here creates a directory: callers mkdir before writing, so merely importing
kaspion never touches the filesystem.

KASPION_DATA_DIR overrides the location, but must be set BEFORE importing kaspion —
db.py, crypto.py and report.py each resolve it into a module constant at import time.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def data_dir() -> Path:
    override = os.environ.get("KASPION_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "kaspion"
    if os.name == "nt":
        # LOCALAPPDATA, not APPDATA: machine-local state should not follow a roaming
        # Windows profile between machines
        base = os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
        return Path(base) / "kaspion"
    base = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    return Path(base) / "kaspion"


def db_path() -> Path:
    return data_dir() / "finance.duckdb"


def report_path() -> Path:
    return data_dir() / "dashboard.html"
