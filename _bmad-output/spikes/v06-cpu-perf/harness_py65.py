"""F.2 spike — py65 backend benchmark on Alter Ego (mapper 0).

**Frozen baseline harness** for the F.2 decision artifact's
"py65 + ObservableMemory" row. The optimized variant
(`harness_py65_optimized.py`) is the one that became the F.3 production
seed. This file is kept as the unoptimized reference: any rerun should
reproduce the F.2 numbers.

Boots the ROM from its reset vector, runs the natural game init, then
drives NMI manually every 29780 cycles for `TOTAL_FRAMES` frames.
Captures every write to $4000-$4017.

Output (stdout, JSON on the last line):
    {"backend":"py65","wall_s":...,"apu_writes":N,"frames":N,
     "first_writes":[[cycle,reg,val], ...10 entries...]}
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from py65.devices.mpu6502 import MPU
from py65.memory import ObservableMemory


ROM_PATH = Path("corpus/roms/023ebe61e8a4ba7a439f7fe9f7cbd31b364e5f63853dcbc0f7fa2183f023ef47.nes")
NTSC_CYCLES_PER_FRAME = 29780  # CPU cycles per NTSC frame (truncated from 29780.5)
# 10800 = 3 min @ 60 Hz — the headline budget for NFR-PERF-80.
# For a 10 s sample (the spike's lenient pass criterion), use 600.
TOTAL_FRAMES = 10800
INIT_BUDGET_CYCLES = 200_000    # ~6.7 frames; game settles before phase 2


def load_rom(path: Path) -> tuple[bytes, bytes]:
    data = path.read_bytes()
    assert data[:4] == b"NES\x1a"
    prg_pages = data[4]
    chr_pages = data[5]
    flags6 = data[6]
    prg_off = 16 + (512 if flags6 & 4 else 0)
    prg = data[prg_off : prg_off + prg_pages * 16384]
    chr_ = data[prg_off + len(prg) : prg_off + len(prg) + chr_pages * 8192]
    return prg, chr_


def build_mem(prg: bytes, apu_writes: list[tuple[int, int, int]], cpu_cycles_ref: list[int]) -> ObservableMemory:
    mem = ObservableMemory()
    # 2KB internal RAM, mirrored $0000-$1FFF
    ram = bytearray(0x800)

    def ram_read(addr):
        return ram[addr & 0x7FF]

    def ram_write(addr, value):
        ram[addr & 0x7FF] = value & 0xFF

    mem.subscribe_to_read(range(0x0000, 0x2000), ram_read)
    mem.subscribe_to_write(range(0x0000, 0x2000), ram_write)

    # PPU regs $2000-$3FFF — stub returns 0, swallows writes (but track NMI enable)
    ppu_state = {"nmi_enabled": False, "vbl_flag": False}

    def ppu_read(addr):
        reg = (addr - 0x2000) & 7
        if reg == 2:  # PPUSTATUS — bit 7 = vblank, then cleared
            v = 0x80 if ppu_state["vbl_flag"] else 0
            ppu_state["vbl_flag"] = False
            return v
        return 0

    def ppu_write(addr, value):
        reg = (addr - 0x2000) & 7
        if reg == 0:  # PPUCTRL
            ppu_state["nmi_enabled"] = bool(value & 0x80)

    mem.subscribe_to_read(range(0x2000, 0x4000), ppu_read)
    mem.subscribe_to_write(range(0x2000, 0x4000), ppu_write)

    # APU + I/O $4000-$401F. Capture writes to $4000-$4017.
    def apu_read(addr):
        if addr == 0x4015:
            return 0  # all channels report idle (stub)
        if addr == 0x4016 or addr == 0x4017:
            return 0  # controllers idle
        return 0

    def apu_write(addr, value):
        if 0x4000 <= addr <= 0x4017:
            apu_writes.append((cpu_cycles_ref[0], addr, value & 0xFF))
        # $4014 OAM DMA: stub — would normally stall CPU for 513 cycles
        # We let the CPU continue, accepting some cycle drift for the spike.

    mem.subscribe_to_read(range(0x4000, 0x4020), apu_read)
    mem.subscribe_to_write(range(0x4000, 0x4020), apu_write)

    # Cartridge ROM at $8000-$FFFF (32KB NROM, no banking)
    rom = bytearray(prg)
    if len(rom) == 0x4000:
        # 16KB PRG mirrored to $8000 + $C000
        rom = rom + rom

    def rom_read(addr):
        return rom[(addr - 0x8000) & 0x7FFF]

    def rom_write(addr, value):
        # NROM has no PRG-RAM and no mapper writes; ignore (debug print if you care)
        pass

    mem.subscribe_to_read(range(0x8000, 0x10000), rom_read)
    mem.subscribe_to_write(range(0x8000, 0x10000), rom_write)
    # (Note: ObservableMemory's `range` arg is start,stop pythonic.)

    return mem, ppu_state


def trigger_nmi(mpu: MPU) -> None:
    """6502 NMI: push PCH, PCL, P (B clear, U set), set I, PC = [$FFFA]."""
    pc_hi = (mpu.pc >> 8) & 0xFF
    pc_lo = mpu.pc & 0xFF
    p = (mpu.p | 0x20) & ~0x10  # U=1, B=0
    # Push to $0100+SP
    mpu.memory[0x0100 + mpu.sp] = pc_hi
    mpu.sp = (mpu.sp - 1) & 0xFF
    mpu.memory[0x0100 + mpu.sp] = pc_lo
    mpu.sp = (mpu.sp - 1) & 0xFF
    mpu.memory[0x0100 + mpu.sp] = p & 0xFF
    mpu.sp = (mpu.sp - 1) & 0xFF
    mpu.p |= 0x04  # I flag
    lo = mpu.memory[0xFFFA]
    hi = mpu.memory[0xFFFB]
    mpu.pc = (hi << 8) | lo
    mpu.processorCycles += 7  # NMI handling cost


def main() -> None:
    prg, _chr = load_rom(ROM_PATH)
    rst = prg[-4] | (prg[-3] << 8)
    nmi = prg[-6] | (prg[-5] << 8)
    print(f"# PRG {len(prg)} bytes, RST=${rst:04x}, NMI=${nmi:04x}", file=sys.stderr)

    apu_writes: list[tuple[int, int, int]] = []
    cyc_ref = [0]
    mem, ppu_state = build_mem(prg, apu_writes, cyc_ref)
    mpu = MPU(memory=mem)
    mpu.start_pc = None  # force reset() to read $FFFC
    mpu.reset()
    print(f"# post-reset PC=${mpu.pc:04x}, SP=${mpu.sp:02x}", file=sys.stderr)

    # Phase 1: run init until INIT_BUDGET_CYCLES OR until NMI is enabled, whichever first
    t0 = time.perf_counter()
    init_cycles = 0
    while init_cycles < INIT_BUDGET_CYCLES:
        mpu.step()
        init_cycles = mpu.processorCycles
        cyc_ref[0] = init_cycles
        if ppu_state["nmi_enabled"]:
            break
    print(f"# init done at {init_cycles} cycles, NMI enabled={ppu_state['nmi_enabled']}", file=sys.stderr)

    # Phase 2: run TOTAL_FRAMES frames, triggering NMI at each frame boundary
    next_nmi_at = init_cycles + NTSC_CYCLES_PER_FRAME
    frames_done = 0
    while frames_done < TOTAL_FRAMES:
        if mpu.processorCycles >= next_nmi_at:
            ppu_state["vbl_flag"] = True
            if ppu_state["nmi_enabled"]:
                trigger_nmi(mpu)
            next_nmi_at += NTSC_CYCLES_PER_FRAME
            frames_done += 1
        mpu.step()
        cyc_ref[0] = mpu.processorCycles

    wall = time.perf_counter() - t0
    result = {
        "backend": "py65",
        "wall_s": round(wall, 3),
        "frames": TOTAL_FRAMES,
        "init_cycles": init_cycles,
        "total_cycles": mpu.processorCycles,
        "apu_writes": len(apu_writes),
        "first_writes": [[c, f"${r:04x}", f"${v:02x}"] for c, r, v in apu_writes[:10]],
    }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
