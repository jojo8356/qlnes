"""Invariant: SIGKILL during atomic_writer leaves no partial file (FR35, NFR-REL-4)."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path


def _spawn_slow_writer(target: Path, hold_seconds: float) -> subprocess.Popen:
    """Spawn a child that opens an atomic_writer and holds it open."""
    code = textwrap.dedent(f"""
        import time
        from pathlib import Path
        from qlnes.io.atomic import atomic_writer

        target = Path({str(target)!r})
        with atomic_writer(target, "wb") as f:
            f.write(b"partial-data")
            f.flush()
            time.sleep({hold_seconds})
            f.write(b"more")
    """)
    return subprocess.Popen(
        [sys.executable, "-c", code],
        env={**os.environ, "PYTHONPATH": str(_repo_root())},
    )


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_kill_mid_write_leaves_no_partial(tmp_path):
    target = tmp_path / "out.bin"
    proc = _spawn_slow_writer(target, hold_seconds=5.0)
    time.sleep(0.5)  # let the child enter atomic_writer
    assert not target.exists(), "target must not exist before atomic rename"
    proc.send_signal(signal.SIGKILL)
    proc.wait(timeout=10)
    assert proc.returncode != 0
    # Target file must not exist (rename never happened).
    assert not target.exists()


def test_kill_mid_write_temp_file_remains_but_target_does_not(tmp_path):
    """After SIGKILL the .tmp file may remain (no clean-up handler ran), but the target is intact."""
    target = tmp_path / "out.bin"
    proc = _spawn_slow_writer(target, hold_seconds=5.0)
    time.sleep(0.5)
    proc.send_signal(signal.SIGKILL)
    proc.wait(timeout=10)
    assert not target.exists()
    # Documenting reality: a temp file may remain after SIGKILL because Python's
    # exception handler never runs. atomic_writer's contract is "target is clean";
    # cleaning up orphan .tmp files is not part of that guarantee.
    # (Pre-flight could sweep them; not in MVP scope.)


def test_kill_with_existing_target_keeps_old_bytes(tmp_path):
    target = tmp_path / "out.bin"
    target.write_bytes(b"original")
    proc = _spawn_slow_writer(target, hold_seconds=5.0)
    time.sleep(0.5)
    proc.send_signal(signal.SIGKILL)
    proc.wait(timeout=10)
    assert target.read_bytes() == b"original"
