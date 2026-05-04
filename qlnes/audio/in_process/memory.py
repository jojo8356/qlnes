"""Memory map for in-process music renders. Architecture step 20.5.

The Memory ABC is what py65's MPU calls into. Concrete subclasses
implement mapper-specific PRG/CHR layouts; F.3 ships NROMMemory (mapper 0)
and F.8 will add MMC1Memory / MMC3Memory.

The APU observer lives inside __setitem__: when py65 writes to
$4000-$4017, we record an ApuWriteEvent. PPU reads/writes go through
a deliberately minimal stub (vblank=1 always, PPUCTRL bit 7 → NMI
enable) — see arch step 20.7.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..static.apu_event import ApuWriteEvent


class Memory(ABC):
    """64 KB CPU memory bus exposing __getitem__/__setitem__ to py65.

    Subclasses must populate `apu_writes` with ApuWriteEvent on writes
    to $4000-$4017 and maintain `cpu_cycles` (the runner bumps it).
    """

    apu_writes: list[ApuWriteEvent]
    cpu_cycles: int
    nmi_enabled: bool
    vbl_flag: bool

    @abstractmethod
    def __getitem__(self, addr: int) -> int: ...

    @abstractmethod
    def __setitem__(self, addr: int, value: int) -> None: ...

    def __len__(self) -> int:
        return 0x10000


class NROMMemory(Memory):
    """Mapper-0 (NROM) memory. PRG is 16 or 32 KB at $8000-$FFFF.

    16 KB PRG mirrors at $8000 and $C000; 32 KB occupies the full bank.
    No PRG-RAM at $6000-$7FFF (rare for NROM; we stub as zeros).
    """

    def __init__(self, prg: bytes) -> None:
        if len(prg) not in (0x4000, 0x8000):
            raise ValueError(
                f"NROM PRG must be 16 or 32 KB; got {len(prg)} bytes"
            )
        self._ram = bytearray(0x800)  # $0000-$07FF, mirrored to $1FFF
        if len(prg) == 0x4000:
            # 16 KB PRG: mirror so $8000 and $C000 both read it
            self._rom = bytearray(prg) + bytearray(prg)
        else:
            self._rom = bytearray(prg)
        self.apu_writes: list[ApuWriteEvent] = []
        self.cpu_cycles: int = 0
        self.nmi_enabled: bool = False
        self.vbl_flag: bool = False

    def __getitem__(self, addr: int) -> int:
        if addr < 0x2000:
            return self._ram[addr & 0x7FF]
        if addr < 0x4000:
            # PPU regs $2000-$3FFF, mirrored every 8
            reg = (addr - 0x2000) & 7
            if reg == 2:
                # PPUSTATUS: bit 7 = vblank, cleared on read
                v = 0x80 if self.vbl_flag else 0
                self.vbl_flag = False
                return v
            return 0
        if addr < 0x4020:
            # APU/IO read stubs. Real APU would return $4015 channel state
            # and $4016/$4017 controller bits; music drivers don't depend
            # on these for the Alter Ego case (verified in F.2 spike).
            return 0
        if addr < 0x6000:
            return 0  # cartridge expansion (unused in NROM)
        if addr < 0x8000:
            return 0  # PRG-RAM stub
        return self._rom[(addr - 0x8000) & 0x7FFF]

    def __setitem__(self, addr: int, value: int) -> None:
        v = value & 0xFF
        if addr < 0x2000:
            self._ram[addr & 0x7FF] = v
            return
        if addr < 0x4000:
            reg = (addr - 0x2000) & 7
            if reg == 0:  # PPUCTRL — bit 7 is NMI-on-vblank enable
                self.nmi_enabled = bool(v & 0x80)
            return
        if 0x4000 <= addr <= 0x4017:
            self.apu_writes.append(
                ApuWriteEvent(cpu_cycle=self.cpu_cycles, register=addr, value=v)
            )
            return
        # $4018-$401F APU test, $4020+ cart expansion: silently ignored.

    def reset_capture(self) -> None:
        """Clear captured events + cycle counter only.

        Use `reset_state()` for a full power-on reset that also clears
        RAM and PPU/NMI flags. This narrow form is kept for callers
        that want to start a new capture mid-render (rare).
        """
        self.apu_writes.clear()
        self.cpu_cycles = 0

    def reset_state(self) -> None:
        """Power-on-style reset: zero RAM, clear PPU/NMI flags, drop captures.

        Called at the start of every render path so back-to-back runs on
        the same `InProcessRunner` instance produce deterministic,
        independent traces (F.3.CR-10 fix). Real NES has random RAM at
        power-on, but most emulators zero it; well-behaved games
        re-initialize RAM in their reset handler regardless.
        """
        # bytearray.__setitem__(slice, ...) is the fast path for memset
        self._ram[:] = b"\x00" * 0x800
        self.nmi_enabled = False
        self.vbl_flag = False
        self.apu_writes.clear()
        self.cpu_cycles = 0
