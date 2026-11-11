import os
import subprocess
import sys
from pathlib import Path


def test_alembic_upgrade_on_fresh_database(tmp_path: Path):
    """start.sh runs the migrations before the app exists, so they must work on an empty DB."""
    env = os.environ.copy()
    env["SQLITE_URL"] = f"sqlite+aiosqlite:///{tmp_path / 'fresh.db'}"

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
