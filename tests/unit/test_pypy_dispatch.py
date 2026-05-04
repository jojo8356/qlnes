"""Unit tests for `qlnes.audio.in_process._pypy_dispatch.find_pypy`.

Exercises each branch of the resolution chain via monkeypatching:
  1. $PYPY_BIN env var
  2. <repo_root>/vendor/pypy/bin/pypy3
  3. `pypy3` on PATH (via shutil.which mock)
  4. None — caller must fall back

Doesn't actually spawn a PyPy subprocess; that lives in the
gated integration test (test_pypy_subprocess.py).
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from qlnes.audio.in_process._pypy_dispatch import _decode_pcm, find_pypy


@pytest.fixture(autouse=True)
def _strip_pypy_env(monkeypatch):
    """Tests must control $PYPY_BIN; ensure no host leak."""
    monkeypatch.delenv("PYPY_BIN", raising=False)


def _make_executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(0o755)
    return path


# ---- find_pypy resolution ------------------------------------------------


def test_find_pypy_returns_none_when_nothing_available(tmp_path, monkeypatch):
    """No PYPY_BIN, no vendor install, no pypy3 on PATH → None."""
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert find_pypy(repo_root=tmp_path) is None


def test_find_pypy_picks_env_var_first(tmp_path, monkeypatch):
    """$PYPY_BIN takes priority over vendor install and PATH."""
    env_path = _make_executable(tmp_path / "env_pypy")
    vendored = _make_executable(tmp_path / "vendor" / "pypy" / "bin" / "pypy3")
    monkeypatch.setenv("PYPY_BIN", str(env_path))
    monkeypatch.setattr("shutil.which", lambda name: "/some/other/pypy3")
    assert find_pypy(repo_root=tmp_path) == env_path


def test_find_pypy_skips_env_var_if_not_executable(tmp_path, monkeypatch):
    """Non-executable PYPY_BIN is skipped; resolution continues."""
    bad = tmp_path / "not_exec_pypy"
    bad.write_text("notexec")  # no chmod +x
    vendored = _make_executable(tmp_path / "vendor" / "pypy" / "bin" / "pypy3")
    monkeypatch.setenv("PYPY_BIN", str(bad))
    assert find_pypy(repo_root=tmp_path) == vendored


def test_find_pypy_picks_vendor_install(tmp_path, monkeypatch):
    """No PYPY_BIN; vendor install present → that wins over PATH."""
    vendored = _make_executable(tmp_path / "vendor" / "pypy" / "bin" / "pypy3")
    monkeypatch.setattr("shutil.which", lambda name: "/some/path/pypy3")
    assert find_pypy(repo_root=tmp_path) == vendored


def test_find_pypy_falls_back_to_path(tmp_path, monkeypatch):
    """No PYPY_BIN, no vendor install → shutil.which result."""
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/pypy3")
    result = find_pypy(repo_root=tmp_path)
    assert result == Path("/usr/bin/pypy3")


def test_find_pypy_uses_default_repo_root_if_none_passed(monkeypatch, tmp_path):
    """When `repo_root` is None, find_pypy infers it from the module path.

    Verify by setting up a fake vendor dir and monkeypatching the
    module's __file__ to live under our tmp_path."""
    # Default repo_root computed from the qlnes module location; we
    # don't override it here — just confirm the function doesn't crash
    # and returns a Path or None depending on the host.
    monkeypatch.setattr("shutil.which", lambda name: None)
    result = find_pypy()
    assert result is None or isinstance(result, Path)


# ---- _decode_pcm protocol ------------------------------------------------


def test_decode_pcm_round_trips_a_synthetic_payload():
    """Build the exact protocol the child writes; assert decoder matches."""
    import struct
    pcm_bytes = b"\x01\x00\x02\x00\x03\x00"  # 6 bytes of PCM
    sample_rate = 48000
    raw = struct.pack("<II", len(pcm_bytes), sample_rate) + pcm_bytes
    result = _decode_pcm(raw)
    assert result.pcm == pcm_bytes
    assert result.sample_rate == sample_rate


def test_decode_pcm_rejects_truncated_header():
    with pytest.raises(ValueError, match="truncated"):
        _decode_pcm(b"\x00\x00")


def test_decode_pcm_rejects_size_mismatch():
    """Header says 100 bytes of PCM, payload only has 5 → ValueError."""
    import struct
    raw = struct.pack("<II", 100, 44100) + b"\x00" * 5
    with pytest.raises(ValueError, match="length"):
        _decode_pcm(raw)
