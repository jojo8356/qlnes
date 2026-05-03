"""Shared pytest fixtures.

A.1 ships only minimal scaffolding here. Later stories extend this file with:
- corpus loader fixture (B.3)
- oracle fixture (FceuxOracle session-scoped) (A.1 phase 7.3 — APU integration phase)
- lameenc-version skip marker (A.2)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_ROOT = REPO_ROOT / "tests" / "fixtures"

# Make `qlnes` importable when running pytest from any cwd.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def fixtures_root() -> Path:
    return FIXTURES_ROOT


@pytest.fixture(autouse=True)
def _isolate_qlnes_env(monkeypatch):
    """Keep QLNES_* env from the host out of every test.

    Without this fixture, a developer with QLNES_AUDIO_FORMAT=mp3 in their shell
    would see config-loader tests behave differently than CI.
    """
    for key in list(os.environ):
        if key.startswith("QLNES_"):
            monkeypatch.delenv(key, raising=False)
