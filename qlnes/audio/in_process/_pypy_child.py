"""Subprocess entry point for the PyPy workhorse (story F.5b).

Runs the entire in-process render pipeline (InProcessRunner +
ApuEmulator) inside the PyPy interpreter and writes the resulting
int16 LE PCM bytes to stdout. Both phases are JIT-friendly Python
loops; running the whole thing in PyPy is the only way to get the
F.2 measured 22× speedup end-to-end.

Argv format:
    pypy3 _pypy_child.py <rom_path> <init_hex> <play_hex> <frames>

Stdout binary protocol:
    bytes 0-3:    uint32 LE — PCM byte count (must equal end of buffer)
    bytes 4-7:    uint32 LE — sample rate (44100 for v0.6)
    bytes 8-N:    int16 LE PCM samples (mono)

Stderr is left available for child diagnostics; the parent ignores it
unless `subprocess.run` returns non-zero (CalledProcessError surfaces
stderr in its message).
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 5:
        sys.stderr.write(
            f"usage: {sys.argv[0]} <rom_path> <init_hex> <play_hex> <frames>\n"
        )
        return 2

    # Make the qlnes package importable from the child. The child sits
    # at qlnes/audio/in_process/_pypy_child.py — repo root is 3 levels up.
    repo_root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(repo_root))

    from qlnes.apu import ApuEmulator  # noqa: E402
    from qlnes.audio.engine import CYCLES_PER_FRAME  # noqa: E402
    from qlnes.audio.in_process import InProcessRunner  # noqa: E402
    from qlnes.rom import Rom  # noqa: E402

    rom_path = Path(sys.argv[1])
    init = int(sys.argv[2], 16)
    play = int(sys.argv[3], 16)
    frames = int(sys.argv[4])

    rom = Rom.from_file(rom_path)
    runner = InProcessRunner(rom)
    events = runner.run_song(init, play, frames=frames)

    emu = ApuEmulator()
    last_cycle = 0
    for ev in events:
        emu.write(ev.register, ev.value, ev.cpu_cycle)
        last_cycle = ev.cpu_cycle
    end_cycle = max(last_cycle, int(frames * CYCLES_PER_FRAME))
    pcm = emu.render_until(cycle=end_cycle)

    sample_rate = 44_100
    out = sys.stdout.buffer
    header = struct.pack("<II", len(pcm), sample_rate)
    out.write(header)
    out.write(pcm)
    out.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
