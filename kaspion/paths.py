"""Where a household's data lives — always OUTSIDE the installation directory.

An installed copy may sit in a read-only or shared location (/Applications, Program
Files, a zip unpacked anywhere), and two people on one machine must not share a
database. So the DuckDB file, the AES key, the encrypted credentials and the generated
dashboard live in the OS's per-user data directory, never next to the code.

This is also what guarantees a distributed copy carries no data: there is nothing to
carry, because nothing is written into the tree that gets zipped.

These functions do NOT create anything — callers mkdir before writing. Creating
directories at import time would make merely importing kaspion touch the filesystem.

KASPION_DATA_DIR overrides the location (tests, or data on an external disk). Set it
BEFORE importing kaspion: db.py, crypto.py and report.py each resolve their path into a
module-level constant at import time, so changing the variable afterwards has no effect.
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
