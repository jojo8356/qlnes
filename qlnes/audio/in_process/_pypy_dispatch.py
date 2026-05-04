"""PyPy subprocess workhorse for the in-process music renderer (F.5b).

The F.2 spike measured PyPy 3.11 at 22× the speed of CPython 3.13 on
the qlnes hot loop (3-min Alter Ego: 4.16 s vs 93.2 s). To capture
that speedup end-to-end the *entire* in-process pipeline (CPU
emulator → ApuEmulator → PCM bytes) runs inside the PyPy child;
the parent just reads back the int16 LE PCM and wraps it in a
`PcmStream`.

Why both phases run in PyPy: a 600-frame render on Alter Ego splits
~0.97 s for the CPU loop and ~17.6 s for ApuEmulator under CPython.
Forking only the CPU loop into PyPy turned 23 s → 18 s; forking
both turns it into ~6 s.

If PyPy isn't found, the renderer's caller falls back to the
in-process CPython path with no behavior change (just slower).
"""
from __future__ import annotations

import os
import shutil
import struct
import subprocess
from dataclasses import dataclass
from pathlib import Path

_HEADER = struct.Struct("<II")  # PCM byte count + sample rate


@dataclass(frozen=True)
class PypyRenderResult:
    """Bytes-level PCM produced by the PyPy child + sample rate."""
    pcm: bytes
    sample_rate: int


def find_pypy(*, repo_root: Path | None = None) -> Path | None:
    """Locate a PyPy interpreter in the standard places.

    Resolution order:
      1. `$PYPY_BIN` env var, if set and points to an executable.
      2. `<repo_root>/vendor/pypy/bin/pypy3` — managed install
         provisioned by `scripts/install_audio_deps.sh` (F.10).
      3. `pypy3` on PATH — system or user-shell install.
      4. None — caller must fall back to the in-process CPython path.

    `repo_root` defaults to two levels up from the qlnes package, which
    matches the project layout. Tests can override.
    """
    env = os.environ.get("PYPY_BIN")
    if env:
        p = Path(env)
        if p.is_file() and os.access(p, os.X_OK):
            return p

    if repo_root is None:
        # qlnes/audio/in_process/_pypy_dispatch.py → 3 parents up = repo root
        repo_root = Path(__file__).resolve().parents[3]
    vendored = repo_root / "vendor" / "pypy" / "bin" / "pypy3"
    if vendored.is_file() and os.access(vendored, os.X_OK):
        return vendored

    on_path = shutil.which("pypy3")
    if on_path:
        return Path(on_path)

    return None


def render_song_via_pypy(
    pypy: Path,
    rom_path: Path,
    init_addr: int,
    play_addr: int,
    *,
    frames: int = 600,
    timeout_s: float = 180.0,
) -> PypyRenderResult:
    """Spawn `pypy3 _pypy_child.py ...` and parse its binary stdout.

    The child runs the full pipeline (InProcessRunner + ApuEmulator)
    inside PyPy, then dumps a header (uint32 PCM byte count + uint32
    sample rate) followed by the raw int16 LE PCM bytes.

    Raises subprocess.CalledProcessError if the child exits non-zero.
    Raises subprocess.TimeoutExpired if the child runs past
    `timeout_s` (default 3 min — generous for a 3-min render at PyPy
    speed, ~5 s on the F.2 hardware).
    """
    child_script = Path(__file__).with_name("_pypy_child.py")
    cmd = [
        str(pypy),
        str(child_script),
        str(rom_path),
        f"0x{init_addr:04x}",
        f"0x{play_addr:04x}",
        str(frames),
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        check=True,
        timeout=timeout_s,
    )
    return _decode_pcm(proc.stdout)


def _decode_pcm(raw: bytes) -> PypyRenderResult:
    """Decode the binary protocol produced by `_pypy_child.py`."""
    if len(raw) < _HEADER.size:
        raise ValueError(f"truncated PyPy child output: {len(raw)} bytes")
    pcm_len, sample_rate = _HEADER.unpack_from(raw, 0)
    expected_total = _HEADER.size + pcm_len
    if len(raw) != expected_total:
        raise ValueError(
            f"PyPy child output length {len(raw)} doesn't match "
            f"declared PCM size {pcm_len} (expected {expected_total} bytes)"
        )
    return PypyRenderResult(
        pcm=raw[_HEADER.size:],
        sample_rate=sample_rate,
    )
