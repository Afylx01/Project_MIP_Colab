"""Session-wide test isolation for tracked scanner deliverables.

Several integration tests run the real scanner against the project root. The
scanner always refreshes reconciliation metadata and the quality report, even
when report export is disabled, so a completed suite would otherwise leave
tracked files modified. These files are part of the repository's evidence, not
test output: snapshot them before the session and restore them afterwards.

This fixture only restores bytes; it never hides a failing assertion, because
assertions run while the test is executing and see the live values.
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Tracked deliverables rewritten by scanner/backtest integration tests.
PRESERVED = (
    ROOT / "data" / "constituent_snapshots.json",
    ROOT / "reports" / "scan_quality.md",
)


@pytest.fixture(scope="session", autouse=True)
def preserve_tracked_deliverables():
    backups = {path: path.read_bytes() for path in PRESERVED if path.exists()}
    yield
    for path, payload in backups.items():
        path.write_bytes(payload)
