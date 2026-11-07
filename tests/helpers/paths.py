"""Repository resources used by developer tests, independent of test depth."""

from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = TESTS_ROOT / "fixtures"
TOOLS = TESTS_ROOT.parent / "tools"
