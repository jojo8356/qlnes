"""InProcessRunner. Architecture step 20.2.

Runs a ROM's music driver entirely in the Python process via py65 +
NROMMemory. Yields ApuWriteEvent for every APU register write captured
between init and `frames` NMI-driven play() invocations.

The runner does NOT spawn subprocesses. The PyPy-fork performance path
is dispatched at the renderer level (story F.5) — F.3's runner runs
wherever it's called from (CPython or PyPy).

Two run shapes are exposed:

- `run_song(init_addr, play_addr, frames)` — NSF-shaped: explicit
  init/play addresses (the architecture's canonical contract,
  step 20.2). Required for ROMs whose audio driver is data-table-driven
  and whose engine handler returns the addresses (story F.4).

- `run_natural_boot(frames)` — Self-running ROMs: jump to the reset
  vector, let the game's own init code run, then schedule NMIs at the
  60 Hz cadence. Used when no engine handler implements init/play
  (the F.2 spike path; works for Alter Ego).
"""
from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from ...rom import Rom
from ..static.apu_event import ApuWriteEvent
from .memory import (
    AxROMMemory,
    Bandai16Memory,
    Bandai70Memory,
    BNROMNINAMemory,
    CamericaMemory,
    CNROMMemory,
    ColorDreamsMemory,
    CPROMMemory,
    FME7Memory,
    GxROMMemory,
    HolyDiverMemory,
    IremG101Memory,
    Jaleco18Memory,
    JF10Memory,
    JF17Memory,
    J87Memory,
    Mapper42Memory,
    MMC1Memory,
    MMC5Memory,
    MMC2Memory,
    MMC3Memory,
    MMC4Memory,
    Memory,
    Namco108Memory,
    Namco163Memory,
    NINA0306Memory,
    NROMMemory,
    Taito33Memory,
    UxROMMemory,
)
from .nmi import NTSC_CYCLES_PER_FRAME, trigger_nmi, trigger_nmi_to


# When run_natural_boot waits for the game's reset code to settle and
# enable NMI, we cap the wait so a malformed ROM can't hang forever.
INIT_BUDGET_CYCLES = 200_000  # ~6.7 frames at NTSC


@dataclass(frozen=True)
class _RunStats:
    init_cycles: int
    total_cycles: int
    apu_event_count: int


class InProcessRunner:
    """Execute a ROM's music driver in-process and yield APU writes."""

    def __init__(self, rom: Rom, *, cpu_backend: str = "py65") -> None:
        if cpu_backend != "py65":
            # F.11 may add "native" via a Cython port or cynes-fork; not now.
            raise ValueError(
                f"unknown cpu_backend {cpu_backend!r}; only 'py65' is implemented"
            )
        self.rom = rom
        self._cpu_backend = cpu_backend
        self._mem = self._build_memory(rom)
        self._mpu = self._build_mpu(self._mem)
        # Last run's stats — set by run_song / run_natural_boot
        self.last_stats: _RunStats | None = None

    @staticmethod
    def _build_memory(rom: Rom) -> Memory:
        mapper = rom.mapper
        if mapper not in (0, 1, 2, 3, 4, 5, 7, 9, 10, 11, 13, 16, 18, 19, 32, 33, 34, 42, 66, 69, 70, 71, 72, 78, 79, 87, 101, 206, None):
            raise ValueError(
                f"InProcessRunner currently supports mapper 0, 1, 2, 3, 4, 5, 7, 9, 10, 11, 13, 16, 18, 19, 32, 33, 34, 42, 66, 69, 70, 71, 72, 78, 79, 87, 101 and 206 only; "
                f"got mapper {mapper}."
            )
        prg = rom.prg if rom.header is not None else rom.raw
        if mapper == 1 and rom.header is not None:
            return MMC1Memory(prg, rom.header.chr_banks, InProcessRunner._chr_rom(rom))
        if mapper == 2:
            return UxROMMemory(prg)
        if mapper == 3 and rom.header is not None:
            return CNROMMemory(prg, rom.header.chr_banks)
        if mapper == 4 and rom.header is not None:
            return MMC3Memory(prg, InProcessRunner._chr_rom(rom))
        if mapper == 5 and rom.header is not None:
            return MMC5Memory(prg, InProcessRunner._chr_rom(rom))
        if mapper == 7:
            return AxROMMemory(prg)
        if mapper == 9 and rom.header is not None:
            return MMC2Memory(prg, InProcessRunner._chr_rom(rom))
        if mapper == 10 and rom.header is not None:
            return MMC4Memory(prg, InProcessRunner._chr_rom(rom))
        if mapper == 11 and rom.header is not None:
            return ColorDreamsMemory(prg, rom.header.chr_banks)
        if mapper == 13:
            return CPROMMemory(prg)
        if mapper == 16 and rom.header is not None:
            return Bandai16Memory(prg, InProcessRunner._chr_rom(rom))
        if mapper == 18 and rom.header is not None:
            return Jaleco18Memory(prg, InProcessRunner._chr_rom(rom))
        if mapper == 19 and rom.header is not None:
            return Namco163Memory(prg, InProcessRunner._chr_rom(rom))
        if mapper == 32 and rom.header is not None:
            return IremG101Memory(prg, InProcessRunner._chr_rom(rom))
        if mapper == 33 and rom.header is not None:
            return Taito33Memory(prg, InProcessRunner._chr_rom(rom))
        if mapper == 34 and rom.header is not None:
            return BNROMNINAMemory(prg, InProcessRunner._chr_rom(rom))
        if mapper == 42 and rom.header is not None:
            return Mapper42Memory(prg, rom.header.chr_banks)
        if mapper == 66 and rom.header is not None:
            return GxROMMemory(prg, rom.header.chr_banks)
        if mapper == 69 and rom.header is not None:
            return FME7Memory(prg, InProcessRunner._chr_rom(rom))
        if mapper == 70 and rom.header is not None:
            return Bandai70Memory(prg, rom.header.chr_banks)
        if mapper == 71:
            return CamericaMemory(prg)
        if mapper == 72 and rom.header is not None:
            return JF17Memory(prg, rom.header.chr_banks)
        if mapper == 78 and rom.header is not None:
            return HolyDiverMemory(prg, rom.header.chr_banks)
        if mapper == 79 and rom.header is not None:
            return NINA0306Memory(prg, rom.header.chr_banks)
        if mapper == 87 and rom.header is not None:
            return J87Memory(prg, rom.header.chr_banks)
        if mapper == 101 and rom.header is not None:
            return JF10Memory(prg, rom.header.chr_banks)
        if mapper == 206 and rom.header is not None:
            return Namco108Memory(prg, InProcessRunner._chr_rom(rom))
        return NROMMemory(prg)

    @staticmethod
    def _chr_rom(rom: Rom) -> bytes:
        if rom.header is None:
            return b""
        offset = 16 + (512 if rom.header.has_trainer else 0) + rom.header.prg_size
        return rom.raw[offset : offset + rom.header.chr_size]

    @staticmethod
    def _build_mpu(mem: Memory):
        from py65.devices.mpu6502 import MPU

        mpu = MPU(memory=mem)
        mpu.start_pc = None  # tells reset() to read $FFFC
        mpu.reset()
        return mpu

    def run_song(
        self,
        init_addr: int,
        play_addr: int,
        *,
        frames: int = 600,
        init_a: int | None = None,
    ) -> Iterator[ApuWriteEvent]:
        """NSF-shaped run: jump to init, then NMI=play 60×/s for `frames`.

        Sets PC = init_addr with a sentinel return address pushed so an
        RTS at the end of init lands us at $FFFF (the loop exits when
        PC reaches that sentinel, OR when INIT_BUDGET_CYCLES elapses).
        Then for `frames` frames, an NMI is injected directly to
        play_addr (bypassing the ROM's $FFFA-$FFFB vector).

        Unlike `run_natural_boot`, this does NOT gate on
        `mem.nmi_enabled` — the engine has explicitly told us where to
        run play, so we trust it. PPUCTRL bit-7 may not be set on
        every ROM (e.g. NSF-style data-driven ROMs).

        The MPU is reset at the start of every call so back-to-back
        runs on the same `InProcessRunner` instance produce
        deterministic, independent traces.
        """
        mem = self._mem
        mpu = self._mpu
        # Power-on-style reset (CPU + memory) so back-to-back runs on the
        # same runner produce deterministic, independent traces.
        mpu.start_pc = None
        mpu.reset()
        mem.reset_state()

        # Run init: set PC to init_addr, optionally seed A with the song
        # selector (NSF-shaped drivers), and push a sentinel return address.
        # We push (sentinel - 1) on the stack; an RTS at the end of init
        # pops + 1 = sentinel, so PC lands at $FFFF and we exit phase 1.
        mpu.pc = init_addr
        if init_a is not None:
            mpu.a = init_a & 0xFF
        # Push high byte then low byte of (sentinel - 1) per RTS semantics
        sentinel = 0xFFFF
        ret = sentinel - 1
        mem[0x0100 + mpu.sp] = (ret >> 8) & 0xFF
        mpu.sp = (mpu.sp - 1) & 0xFF
        mem[0x0100 + mpu.sp] = ret & 0xFF
        mpu.sp = (mpu.sp - 1) & 0xFF

        init_start_cycles = mpu.processorCycles
        budget_end = init_start_cycles + INIT_BUDGET_CYCLES
        while mpu.processorCycles < budget_end:
            mpu.step()
            mem.cpu_cycles = mpu.processorCycles
            if mpu.pc == sentinel:
                break
        init_done_cycles = mpu.processorCycles

        # Phase 2: NMI-driven play loop, using the explicit play_addr.
        next_nmi_at = init_done_cycles + NTSC_CYCLES_PER_FRAME
        frames_done = 0
        while frames_done < frames:
            if mpu.processorCycles >= next_nmi_at:
                mem.vbl_flag = True
                trigger_nmi_to(mpu, mem, play_addr)
                next_nmi_at += NTSC_CYCLES_PER_FRAME
                frames_done += 1
            mpu.step()
            mem.cpu_cycles = mpu.processorCycles

        self.last_stats = _RunStats(
            init_cycles=init_done_cycles - init_start_cycles,
            total_cycles=mpu.processorCycles,
            apu_event_count=len(mem.apu_writes),
        )
        return iter(list(mem.apu_writes))

    def run_natural_boot(
        self,
        *,
        frames: int = 600,
        controller1_frames: Sequence[int] | None = None,
    ) -> Iterator[ApuWriteEvent]:
        """Self-running ROM: boot from reset vector, then drive NMIs.

        The ROM's own reset handler runs game-init (including audio init),
        we wait until either NMI gets enabled or INIT_BUDGET_CYCLES elapses,
        then schedule NMIs at the NTSC cadence for `frames` frames.

        This is what the F.2 spike used and what works for Alter Ego.
        """
        mem = self._mem
        mpu = self._mpu
        # Power-on-style reset (CPU + memory): py65's reset() ran in
        # __init__, but a 2nd run on the same runner needs fresh state.
        mpu.start_pc = None
        mpu.reset()
        mem.reset_state()

        # Phase 1: let game init settle until NMI is enabled or budget elapses
        init_cap = INIT_BUDGET_CYCLES
        while mpu.processorCycles < init_cap:
            mpu.step()
            mem.cpu_cycles = mpu.processorCycles
            if mem.nmi_enabled:
                break
        init_cycles = mpu.processorCycles

        # Phase 2: NMI cadence
        next_nmi_at = init_cycles + NTSC_CYCLES_PER_FRAME
        frames_done = 0
        while frames_done < frames:
            if mpu.processorCycles >= next_nmi_at:
                if controller1_frames is not None:
                    self._set_controller1_state_for_frame(controller1_frames, frames_done + 1)
                mem.vbl_flag = True
                if mem.nmi_enabled:
                    trigger_nmi(mpu, mem)
                next_nmi_at += NTSC_CYCLES_PER_FRAME
                frames_done += 1
            mpu.step()
            mem.cpu_cycles = mpu.processorCycles

        self.last_stats = _RunStats(
            init_cycles=init_cycles,
            total_cycles=mpu.processorCycles,
            apu_event_count=len(mem.apu_writes),
        )
        return iter(list(mem.apu_writes))

    def _set_controller1_state_for_frame(
        self,
        controller1_frames: Sequence[int],
        frame: int,
    ) -> None:
        if not controller1_frames:
            return
        setter = getattr(self._mem, "set_controller1_state", None)
        if setter is None:
            return
        idx = min(max(frame, 1), len(controller1_frames)) - 1
        setter(int(controller1_frames[idx]) & 0xFF)

    def ppu_snapshot(self):
        """Return the current PPU/OAM snapshot when the memory backend supports it."""

        snap = getattr(self._mem, "ppu_snapshot", None)
        if snap is None:
            raise ValueError("memory backend does not expose PPU snapshots")
        return snap()


def render_rom(
    rom_path: Path | str, *, frames: int = 600
) -> list[ApuWriteEvent]:
    """Convenience: load ROM from path and run natural boot. Returns a list."""
    rom = Rom.from_file(rom_path)
    runner = InProcessRunner(rom)
    return list(runner.run_natural_boot(frames=frames))
