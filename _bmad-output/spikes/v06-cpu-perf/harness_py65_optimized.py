"""F.2 spike — py65 optimized: flat bytearray memory, only APU writes intercepted.

**This file is the F.3 production seed.** F.3's `qlnes/audio/in_process/`
module is structurally a refactor of this script: `FastNROMMemory` →
`qlnes.audio.in_process.memory.NROMMemory`, the manual NMI scheduler →
`qlnes.audio.in_process.nmi.trigger_nmi`, the main loop →
`InProcessRunner.run_natural_boot`.

Replaces ObservableMemory's per-access callback dispatch with a single
__setitem__ override that fast-paths everything except $4000-$4017.

Run on PyPy for the 22× speedup measured in the F.2 decision artifact:
    /tmp/pypy3.11-v7.3.18-linux64/bin/pypy3 \
        _bmad-output/spikes/v06-cpu-perf/harness_py65_optimized.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from py65.devices.mpu6502 import MPU


ROM_PATH = Path("corpus/roms/023ebe61e8a4ba7a439f7fe9f7cbd31b364e5f63853dcbc0f7fa2183f023ef47.nes")
NTSC_CYCLES_PER_FRAME = 29780  # truncated from 29780.5; cumulative drift < 1 cyc/min
# 10800 = 3 min @ 60 Hz — NFR-PERF-80 budget.
# For a 10 s sample, use 600.
TOTAL_FRAMES = 10800
INIT_BUDGET_CYCLES = 200_000  # ~6.7 frames; game settles before phase 2


class FastNROMMemory:
    """Flat 64KB memory with NES address-decoding inlined into __getitem__/__setitem__.

    py65 calls self.memory[addr] for reads and self.memory[addr] = val for writes.
    We override __getitem__/__setitem__ directly — no subscriber dispatch.
    """

    def __init__(self, prg: bytes):
        self.ram = bytearray(0x800)
        rom = bytearray(prg)
        if len(rom) == 0x4000:
            rom = rom + rom
        self.rom = rom  # 32KB at $8000-$FFFF
        self.apu_writes: list[tuple[int, int, int]] = []
        self.cpu_cycles = 0  # bumped by harness loop
        self.nmi_enabled = False
        self.vbl_flag = False

    def __getitem__(self, addr: int) -> int:
        if addr < 0x2000:
            return self.ram[addr & 0x7FF]
        if addr < 0x4000:
            # PPU regs $2000-$3FFF, mirrored every 8
            reg = (addr - 0x2000) & 7
            if reg == 2:
                v = 0x80 if self.vbl_flag else 0
                self.vbl_flag = False
                return v
            return 0
        if addr < 0x4020:
            return 0  # APU/IO reads stubbed
        if addr >= 0x8000:
            return self.rom[(addr - 0x8000) & 0x7FFF]
        return 0

    def __setitem__(self, addr: int, value: int) -> None:
        v = value & 0xFF
        if addr < 0x2000:
            self.ram[addr & 0x7FF] = v
            return
        if addr < 0x4000:
            reg = (addr - 0x2000) & 7
            if reg == 0:
                self.nmi_enabled = bool(v & 0x80)
            return
        if 0x4000 <= addr <= 0x4017:
            self.apu_writes.append((self.cpu_cycles, addr, v))
            return
        # $4018-$401F: ignore. $8000+: ROM, ignore.

    def __len__(self) -> int:
        return 0x10000


def trigger_nmi(mpu: MPU, mem: FastNROMMemory) -> None:
    pc_hi = (mpu.pc >> 8) & 0xFF
    pc_lo = mpu.pc & 0xFF
    p = (mpu.p | 0x20) & ~0x10
    mem[0x0100 + mpu.sp] = pc_hi
    mpu.sp = (mpu.sp - 1) & 0xFF
    mem[0x0100 + mpu.sp] = pc_lo
    mpu.sp = (mpu.sp - 1) & 0xFF
    mem[0x0100 + mpu.sp] = p & 0xFF
    mpu.sp = (mpu.sp - 1) & 0xFF
    mpu.p |= 0x04
    lo = mem[0xFFFA]
    hi = mem[0xFFFB]
    mpu.pc = (hi << 8) | lo
    mpu.processorCycles += 7


def load_rom(path: Path) -> bytes:
    data = path.read_bytes()
    assert data[:4] == b"NES\x1a"
    prg_pages = data[4]
    flags6 = data[6]
    prg_off = 16 + (512 if flags6 & 4 else 0)
    return data[prg_off : prg_off + prg_pages * 16384]


def main() -> None:
    prg = load_rom(ROM_PATH)
    mem = FastNROMMemory(prg)
    mpu = MPU(memory=mem)
    mpu.start_pc = None
    mpu.reset()
    print(f"# post-reset PC=${mpu.pc:04x}", file=sys.stderr)

    t0 = time.perf_counter()
    init_cycles = 0
    while init_cycles < INIT_BUDGET_CYCLES:
        mpu.step()
        init_cycles = mpu.processorCycles
        mem.cpu_cycles = init_cycles
        if mem.nmi_enabled:
            break

    next_nmi_at = init_cycles + NTSC_CYCLES_PER_FRAME
    frames_done = 0
    while frames_done < TOTAL_FRAMES:
        cyc = mpu.processorCycles
        if cyc >= next_nmi_at:
            mem.vbl_flag = True
            if mem.nmi_enabled:
                trigger_nmi(mpu, mem)
            next_nmi_at += NTSC_CYCLES_PER_FRAME
            frames_done += 1
        mpu.step()
        mem.cpu_cycles = mpu.processorCycles

    wall = time.perf_counter() - t0
    print(json.dumps({
        "backend": "py65-fastmem",
        "wall_s": round(wall, 3),
        "frames": TOTAL_FRAMES,
        "init_cycles": init_cycles,
        "total_cycles": mpu.processorCycles,
        "apu_writes": len(mem.apu_writes),
        "first_writes": [[c, f"${r:04x}", f"${v:02x}"] for c, r, v in mem.apu_writes[:10]],
    }))


if __name__ == "__main__":
    main()
