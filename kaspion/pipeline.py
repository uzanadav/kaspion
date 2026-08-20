"""The one place dbt gets invoked. Two identical copies previously lived in sync.py and
serve.py; they must not drift, because both the DB path and the profiles dir have to be
passed the same way from both.

Run dbt by hand through this module too, never a bare `dbt`:

    python3 -m kaspion.pipeline build      # or debug / run / test / ...

dbt/profiles.yml reads the database location from KASPION_DB_PATH, which this sets from
kaspion.paths. A bare `dbt` in the dbt/ directory has no such variable and fails to
parse the profile — deliberately, because the alternative (defaulting the path) would
quietly build into the wrong database.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from kaspion.paths import db_path

DBT_DIR = Path(__file__).resolve().parents[1] / "dbt"
# mirrors the installed console script exactly (.venv/bin/dbt is this same two-liner).
# Not a bare "dbt", which is only on PATH when the venv is activated — untrue of the
# double-click launchers; and not `-m dbt.cli.main`, which prints a runpy RuntimeWarning.
_DBT_CLI = "from dbt.cli.main import cli; cli()"


def run_dbt(*args: str) -> None:
    """Defaults to `build -q` — quiet unless something is wrong, failures still raise."""
    env = dict(
        os.environ,
        DBT_PROFILES_DIR=str(DBT_DIR),      # absolute: no longer depends on cwd
        KASPION_DB_PATH=str(db_path()),     # read by dbt/profiles.yml
    )
    subprocess.run(
        [sys.executable, "-c", _DBT_CLI, *(args or ("build", "-q"))],
        cwd=DBT_DIR, env=env, check=True,
    )


if __name__ == "__main__":
    run_dbt(*sys.argv[1:])
