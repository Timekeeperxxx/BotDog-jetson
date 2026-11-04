"""Cross-repository source contracts require an explicit Navigation workspace."""
import os
from pathlib import Path

import pytest


def navigation_workspace() -> Path:
    configured = os.environ.get("BOTDOG_TEST_NAV_WS")
    root = Path(configured) if configured else Path(__file__).resolve().parents[2] / "Navigation"
    if not root.is_dir():
        if configured:
            pytest.fail(f"BOTDOG_TEST_NAV_WS does not exist: {root}")
        pytest.skip("Navigation source contract: set BOTDOG_TEST_NAV_WS to run this integration test")
    return root
