"""Integration test for the F.5b PyPy subprocess workhorse.

Gated on PyPy availability via `find_pypy()`: if no PyPy can be found
(no `PYPY_BIN` env, no `vendor/pypy/`, no `pypy3` on PATH), the entire
file is skipped. The test that benchmarks the speedup is also gated on
the corpus ROM being present.

Verifies AC3 (PyPy result byte-equal to CPython result) and AC7
(end-to-end speedup ≥ 3× on Alter Ego). AC1/AC2/AC4-AC6 are covered by
unit tests (`test_pypy_dispatch.py`).
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from qlnes.audio.engine import SongEntry
from qlnes.audio.engines.famitracker import FamiTrackerEngine
from qlnes.audio.in_process._pypy_dispatch import find_pypy, render_song_via_pypy
from qlnes.rom import Rom

_PYPY = find_pypy()

pytestmark = pytest.mark.skipif(
    _PYPY is None,
    reason="No PyPy interpreter found ($PYPY_BIN / vendor / PATH).",
)

ROM_SHA = "023ebe61e8a4ba7a439f7fe9f7cbd31b364e5f63853dcbc0f7fa2183f023ef47"
ROM_PATH = Path(f"corpus/roms/{ROM_SHA}.nes")


@pytest.fixture(scope="module")
def alter_ego_rom() -> Rom:
    if not ROM_PATH.exists():
        pytest.skip(f"Alter Ego ROM not present at {ROM_PATH}")
    return Rom.from_file(ROM_PATH)


# ---- AC3: byte-equiv between PyPy fork and CPython in-process ------------


def test_pypy_pcm_matches_cpython_pcm_on_alter_ego(alter_ego_rom):
    """AC3 — the PCM bytes from the PyPy child match the CPython
    in-process result byte-for-byte. Both paths run the same Python
    source through the same emulators; the only difference is the
    interpreter."""
    e = FamiTrackerEngine()
    song = SongEntry(index=0)
    init = e.init_addr(alter_ego_rom, song)
    play = e.play_addr(alter_ego_rom, song)

    # PyPy path
    pypy_result = render_song_via_pypy(
        _PYPY, alter_ego_rom.path, init, play, frames=300
    )

    # CPython in-process path (force by hiding PyPy from the resolver).
    # We construct the in-process result directly using the same code
    # the fallback in `_resolve_in_process_pcm` would use, so the
    # comparison is apples-to-apples.
    from qlnes.apu import ApuEmulator
    from qlnes.audio.engine import CYCLES_PER_FRAME
    from qlnes.audio.in_process import InProcessRunner

    runner = InProcessRunner(alter_ego_rom)
    events = runner.run_song(init, play, frames=300)
    emu = ApuEmulator()
    last = 0
    for ev in events:
        emu.write(ev.register, ev.value, ev.cpu_cycle)
        last = ev.cpu_cycle
    end = max(last, int(300 * CYCLES_PER_FRAME))
    cpython_pcm = emu.render_until(cycle=end)

    assert pypy_result.pcm == cpython_pcm
    assert pypy_result.sample_rate == 44_100


# ---- AC7: end-to-end speedup >= 3× on Alter Ego -------------------------


def test_pypy_path_is_at_least_3x_faster_than_cpython_on_alter_ego(
    alter_ego_rom, capsys
):
    """AC7 — full `render_song_in_process` end-to-end (CPU emu +
    ApuEmulator + PCM transfer) is ≥ 3× faster on PyPy than on CPython.

    Uses 300 frames (5 s of audio) for fast test feedback. Records
    both walltimes via capsys so CI logs preserve the numbers
    regardless of pass/fail.
    """
    e = FamiTrackerEngine()
    song = SongEntry(index=0)

    # CPython path: hide PyPy from the resolver
    saved_env = os.environ.pop("PYPY_BIN", None)
    try:
        # Also need to make sure pypy3 isn't on PATH for this run; we
        # can't easily strip PATH for an in-process call, so we
        # monkeypatch find_pypy via the env strip + a saved copy.
        from qlnes.audio.in_process import _pypy_dispatch as pd
        original_find = pd.find_pypy
        pd.find_pypy = lambda **kw: None
        try:
            t0 = time.perf_counter()
            cpython_pcm = e.render_song_in_process(
                alter_ego_rom, song, frames=300
            )
            cpython_wall = time.perf_counter() - t0
        finally:
            pd.find_pypy = original_find
    finally:
        if saved_env is not None:
            os.environ["PYPY_BIN"] = saved_env

    # PyPy path: restore env if it was removed
    if saved_env is None:
        os.environ["PYPY_BIN"] = str(_PYPY)
    t0 = time.perf_counter()
    pypy_pcm = e.render_song_in_process(alter_ego_rom, song, frames=300)
    pypy_wall = time.perf_counter() - t0

    speedup = cpython_wall / pypy_wall
    print(
        f"\nF.5b benchmark (Alter Ego, 300 frames):\n"
        f"  CPython in-process: {cpython_wall:.2f} s\n"
        f"  PyPy fork:          {pypy_wall:.2f} s\n"
        f"  speedup:            {speedup:.2f}×"
    )
    # PCM must still match
    assert cpython_pcm.samples == pypy_pcm.samples
    assert speedup >= 3.0, (
        f"PyPy path delivered only {speedup:.2f}× speedup; "
        f"expected ≥ 3× per F.5b AC7"
    )


# ---- F.5b CR: PyPy failure surfaces as a structured warning -------------


def test_pypy_subprocess_failure_emits_pypy_render_failed_warning(
    alter_ego_rom, capsys, monkeypatch
):
    """F.5b.CR-1 / CR-7 fix: when the PyPy subprocess raises
    CalledProcessError or TimeoutExpired, `_resolve_in_process_pcm`
    emits a `pypy_render_failed` warning and falls back to in-process
    instead of swallowing the failure silently.

    Simulate by making render_song_via_pypy always raise."""
    import subprocess as _sp

    from qlnes.audio.engine import _resolve_in_process_pcm
    from qlnes.audio.in_process import _pypy_dispatch as pd

    def _explode(*args, **kw):
        raise _sp.CalledProcessError(
            returncode=1,
            cmd=["pypy3", "boom"],
            stderr=b"ImportError: No module named 'py65'\n",
        )

    monkeypatch.setattr(pd, "render_song_via_pypy", _explode)
    # Ensure find_pypy "succeeds" so we reach the failure path
    fake_path = Path("/usr/bin/pypy3")
    monkeypatch.setattr(pd, "find_pypy", lambda **kw: fake_path)

    e = FamiTrackerEngine()
    song = SongEntry(index=0)
    init = e.init_addr(alter_ego_rom, song)
    play = e.play_addr(alter_ego_rom, song)

    # Should NOT raise — falls back to in-process
    pcm_bytes, sr = _resolve_in_process_pcm(alter_ego_rom, init, play, 30)
    assert sr == 44_100
    assert len(pcm_bytes) > 0

    captured = capsys.readouterr()
    assert "pypy_render_failed" in captured.err
    assert "CalledProcessError" in captured.err
    assert "No module named" in captured.err


# ---- Recursion guard: PyPy doesn't fork itself --------------------------


def test_pypy_fork_does_not_recurse_when_already_on_pypy(monkeypatch):
    """AC6 — when running under PyPy, `_resolve_in_process_pcm` skips the
    PyPy dispatch path entirely (no fork). We can't actually run this
    test under PyPy from a CPython pytest, so we monkeypatch the
    runtime-detection sentinel and assert find_pypy is never called."""
    if not ROM_PATH.exists():
        pytest.skip("requires Alter Ego")

    from qlnes.audio.engine import _resolve_in_process_pcm
    from qlnes.audio.in_process import _pypy_dispatch as pd

    # Patch sys.implementation.name in a clean way: monkeypatch.setattr
    # on the existing namespace object via a SimpleNamespace proxy.
    import sys
    import types
    fake_impl = types.SimpleNamespace(name="pypy")
    monkeypatch.setattr(sys, "implementation", fake_impl, raising=False)

    # Sentinel: if find_pypy is called, the test fails.
    call_count = 0

    def _spy(**kw):
        nonlocal call_count
        call_count += 1
        return None

    monkeypatch.setattr(pd, "find_pypy", _spy)

    rom = Rom.from_file(ROM_PATH)
    e = FamiTrackerEngine()
    song = SongEntry(index=0)
    init = e.init_addr(rom, song)
    play = e.play_addr(rom, song)
    _ = _resolve_in_process_pcm(rom, init, play, 30)

    assert call_count == 0, "find_pypy was called from a 'pypy' runtime"
