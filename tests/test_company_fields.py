"""COMPANY_FIELDS in crypto.py is a hand-copied subset of israeli-bank-scrapers' own
SCRAPERS export. This catches the copy drifting from the library after `npm update`."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from kaspion.ingest.crypto import COMPANY_FIELDS

SCRAPER_DIR = Path(__file__).resolve().parents[1] / "scraper"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not (SCRAPER_DIR / "node_modules").exists(),
    reason="requires node + scraper/node_modules (npm install)",
)


def _installed_scrapers() -> dict:
    proc = subprocess.run(
        ["node", "-e",
         "import('israeli-bank-scrapers').then(m => "
         "process.stdout.write(JSON.stringify(m.SCRAPERS)))"],
        cwd=SCRAPER_DIR, capture_output=True, text=True, check=True,
    )
    return json.loads(proc.stdout)


def test_company_fields_matches_installed_library():
    installed = _installed_scrapers()
    for company, cfg in COMPANY_FIELDS.items():
        assert company in installed, f"{company} is not a company israeli-bank-scrapers knows"
        assert cfg["fields"] == installed[company]["loginFields"], (
            f"{company}: COMPANY_FIELDS {cfg['fields']} != library "
            f"loginFields {installed[company]['loginFields']}"
        )
