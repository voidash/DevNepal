import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

VALIDATOR = Path(__file__).parents[3] / "ops" / "observability" / "validate_dashboards.py"


def _run_validator() -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603 -- fixed argv, no untrusted input
        [sys.executable, str(VALIDATOR)], capture_output=True, text=True, check=False
    )


def test_checked_in_dashboards_pass_validation():
    """NFR-OBS-01: checked-in Grafana dashboards stay well-formed (CI gate)."""
    result = _run_validator()
    assert result.returncode == 0, result.stderr


def test_validator_rejects_a_datasource_typo(tmp_path):
    """NFR-OBS-01: a wrong datasource uid is exactly the mistake this check exists to catch."""
    dashboards_dir = tmp_path / "grafana" / "dashboards"
    dashboards_dir.mkdir(parents=True)
    broken = {
        "uid": "broken",
        "title": "Broken",
        "panels": [
            {
                "id": 1,
                "title": "A panel",
                "datasource": {"uid": "typo'd-uid"},
                "targets": [{"refId": "A", "expr": "up"}],
            }
        ],
    }
    (dashboards_dir / "broken.json").write_text(json.dumps(broken))

    script = tmp_path / "validate_dashboards.py"
    script.write_text(
        VALIDATOR.read_text().replace(
            'DASHBOARDS_DIR = Path(__file__).parent / "grafana" / "dashboards"',
            f"DASHBOARDS_DIR = Path({str(dashboards_dir)!r})",
        )
    )
    result = subprocess.run(  # noqa: S603 -- fixed argv, no untrusted input
        [sys.executable, str(script)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 1
    assert "typo'd-uid" in result.stderr
