"""NFR-MNT-01: enforce traceable SRS citations in applicable pytest functions."""

import ast
import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SRS_PATH = REPOSITORY_ROOT / "docs" / "srs-v0.9.txt"
TEST_PATTERNS = (
    "apps/*/tests/test_*.py",
    "tests/test_*.py",
    "tests/acceptance/test_*.py",
    "tests/accessibility/test_*.py",
)
EXCLUDED_PATHS = {REPOSITORY_ROOT / "tests" / "test_scaffold.py"}
SRS_ID_PATTERN = re.compile(r"\b(?:[A-Z]+(?:-[A-Z0-9]+)*-\d{2,3})\b")


def test_app_acceptance_and_accessibility_tests_cite_srs_requirements():
    """NFR-MNT-01: each applicable test function cites a requirement defined by the SRS."""
    srs_ids = set(SRS_ID_PATTERN.findall(SRS_PATH.read_text()))
    missing_citations = []

    for pattern in TEST_PATTERNS:
        for path in REPOSITORY_ROOT.glob(pattern):
            if path in EXCLUDED_PATHS:
                continue
            module = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(module):
                if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                    continue
                if not node.name.startswith("test_"):
                    continue
                citations = set(SRS_ID_PATTERN.findall(ast.get_docstring(node) or ""))
                if not citations.intersection(srs_ids):
                    missing_citations.append(f"{path.relative_to(REPOSITORY_ROOT)}:{node.name}")

    assert not missing_citations, "Missing SRS requirement citation(s):\n" + "\n".join(
        missing_citations
    )
