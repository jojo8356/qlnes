"""Memory map for in-process music renders. Architecture step 20.5.

The Memory ABC is what py65's MPU calls into. Concrete subclasses
implement mapper-specific PRG/CHR layouts. The in-process runner currently
ships NROMMemory (mapper 0), UxROMMemory (mapper 2), CNROMMemory
(mapper 3), ColorDreamsMemory (mapper 11), GxROMMemory (mapper 66),
and a conservative MMC1Memory (mapper 1). MMC3Memory (mapper 4) supports
enough PRG/CHR banking for runtime sprite capture on simple boot snapshots.
AxROMMemory (mapper 7) supports 32 KiB PRG switching with CHR-RAM captures.
BNROMNINAMemory (mapper 34) supports BNROM PRG switching and NINA split CHR.
FME7Memory (mapper 69) supports Sunsoft FME-7/5B PRG and 1 KiB CHR windows.
CamericaMemory (mapper 71) supports the Codemasters/Camerica UNROM variant.

The APU observer lives inside __setitem__: when py65 writes to
$4000-$4017, we record an ApuWriteEvent. PPU reads/writes go through
a deliberately minimal stub (vblank=1 always, PPUCTRL bit 7 → NMI
enable) — see arch step 20.7.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..static.apu_event import ApuWriteEvent


@dataclass(frozen=True)
class PpuSnapshot:
    ppuctrl: int
    ppumask: int
    palette_ram: bytes
    oam: bytes
    pattern_table: bytes
    chr_bank: int = 0


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
        self.ppuctrl: int = 0
        self.ppumask: int = 0
        self._ppu_addr: int = 0
        self._ppu_addr_latch_high: bool = True
        self._oam_addr: int = 0
        self._palette_ram = bytearray(32)
        self._oam = bytearray(256)
        self._pattern_table = bytearray(0x2000)
        self.chr_bank: int = 0
        self._controller1_state: int = 0
        self._controller1_latch: int = 0
        self._controller1_shift: int = 0
        self._controller_strobe: bool = False

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
                self._ppu_addr_latch_high = True
                return v
            return 0
        if addr < 0x4020:
            if addr == 0x4016:
                return self._read_controller1()
            if addr == 0x4017:
                return 0
            # APU/IO read stubs. Real APU would return $4015 channel state
            # and $4016/$4017 controller bits; music drivers don't depend
            # on these for the Alter Ego case (verified in F.2 spike).
            return 0
        if addr < 0x6000:
            return 0  # cartridge expansion (unused in NROM)
        if addr < 0x8000:
            return 0  # PRG-RAM stub
        return self._read_prg(addr)

    def _read_prg(self, addr: int) -> int:
        return self._rom[(addr - 0x8000) & 0x7FFF]

    def __setitem__(self, addr: int, value: int) -> None:
        v = value & 0xFF
        if addr < 0x2000:
            self._ram[addr & 0x7FF] = v
            return
        if addr < 0x4000:
            reg = (addr - 0x2000) & 7
            if reg == 0:  # PPUCTRL — bit 7 is NMI-on-vblank enable
                self.ppuctrl = v
                self.nmi_enabled = bool(v & 0x80)
            elif reg == 1:  # PPUMASK
                self.ppumask = v
            elif reg == 3:  # OAMADDR
                self._oam_addr = v
            elif reg == 4:  # OAMDATA
                self._oam[self._oam_addr] = v
                self._oam_addr = (self._oam_addr + 1) & 0xFF
            elif reg == 6:  # PPUADDR
                if self._ppu_addr_latch_high:
                    self._ppu_addr = (v & 0x3F) << 8
                    self._ppu_addr_latch_high = False
                else:
                    self._ppu_addr = (self._ppu_addr & 0x3F00) | v
                    self._ppu_addr_latch_high = True
            elif reg == 7:  # PPUDATA
                self._write_ppu_data(v)
            return
        if 0x4000 <= addr <= 0x4017:
            if addr == 0x4016:
                self._write_controller_strobe(v)
            if addr == 0x4014:
                page = v << 8
                for i in range(256):
                    self._oam[(self._oam_addr + i) & 0xFF] = self[page + i]
                self._oam_addr = (self._oam_addr + 256) & 0xFF
            self.apu_writes.append(
                ApuWriteEvent(cpu_cycle=self.cpu_cycles, register=addr, value=v)
            )
            return
        # $4018-$401F APU test, $4020+ cart expansion: silently ignored.

    def set_controller1_state(self, state: int) -> None:
        """Set current controller-1 buttons as NES bitmask A,B,Select,Start,U,D,L,R."""

        self._controller1_state = state & 0xFF
        if self._controller_strobe:
            self._controller1_latch = self._controller1_state
            self._controller1_shift = 0

    def _write_controller_strobe(self, value: int) -> None:
        strobe = bool(value & 0x01)
        if strobe or self._controller_strobe:
            self._controller1_latch = self._controller1_state
            self._controller1_shift = 0
        self._controller_strobe = strobe

    def _read_controller1(self) -> int:
        if self._controller_strobe:
            return self._controller1_state & 0x01
        if self._controller1_shift < 8:
            value = (self._controller1_latch >> self._controller1_shift) & 0x01
            self._controller1_shift += 1
            return value
        return 1

    def reset_capture(self) -> None:
        """Clear captured events + cycle counter only.

        Use `reset_state()` for a full power-on reset that also clears
        RAM and PPU/NMI flags. This narrow form is kept for callers
        that want to start a new capture mid-render (rare).
        """
        self.apu_writes.clear()
        self.cpu_cycles = 0

    def _palette_index(self, addr: int) -> int:
        idx = (addr - 0x3F00) & 0x1F
        # PPU palette mirrors: $3F10/$14/$18/$1C mirror the background
        # universal entries. Store normalized RAM so sprite export sees the
        # same value regardless of which mirror the ROM wrote.
        if idx in (0x10, 0x14, 0x18, 0x1C):
            idx -= 0x10
        return idx

    def _write_ppu_data(self, value: int) -> None:
        addr = self._ppu_addr & 0x3FFF
        if 0x0000 <= addr <= 0x1FFF:
            self._pattern_table[addr] = value & 0xFF
        elif 0x3F00 <= addr <= 0x3FFF:
            self._palette_ram[self._palette_index(addr)] = value & 0x3F
        increment = 32 if (self.ppuctrl & 0x04) else 1
        self._ppu_addr = (self._ppu_addr + increment) & 0x7FFF

    def ppu_snapshot(self) -> PpuSnapshot:
        palette = bytearray(self._palette_ram)
        for src, dst in ((0x00, 0x10), (0x04, 0x14), (0x08, 0x18), (0x0C, 0x1C)):
            palette[dst] = palette[src]
        return PpuSnapshot(
            ppuctrl=self.ppuctrl,
            ppumask=self.ppumask,
            palette_ram=bytes(palette),
            oam=bytes(self._oam),
            pattern_table=bytes(self._pattern_table),
            chr_bank=self.chr_bank,
        )

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
        self.ppuctrl = 0
        self.ppumask = 0
        self._ppu_addr = 0
        self._ppu_addr_latch_high = True
        self._oam_addr = 0
        self._palette_ram[:] = b"\x00" * 32
        self._oam[:] = b"\x00" * 256
        self._pattern_table[:] = b"\x00" * 0x2000
        self.chr_bank = 0
        self._controller1_state = 0
        self._controller1_latch = 0
        self._controller1_shift = 0
        self._controller_strobe = False
        self.apu_writes.clear()
        self.cpu_cycles = 0


class CNROMMemory(NROMMemory):
    """Mapper-3 CNROM memory.

    CPU PRG layout is NROM-like; writes to $8000-$FFFF select an 8 KiB CHR-ROM
    bank. For sprite extraction, tracking that active CHR bank is enough to
    pick the right original tiles for the captured OAM/palette state.
    """

    def __init__(self, prg: bytes, chr_banks: int) -> None:
        super().__init__(prg)
        if chr_banks <= 0:
            raise ValueError("CNROM requires at least one CHR bank")
        self._chr_bank_count = chr_banks

    def __setitem__(self, addr: int, value: int) -> None:
        if addr >= 0x8000:
            self.chr_bank = (value & 0x03) % self._chr_bank_count
            return
        super().__setitem__(addr, value)


class UxROMMemory(NROMMemory):
    """Mapper-2 UxROM memory.

    $8000-$BFFF is a switchable 16 KiB PRG bank, $C000-$FFFF is fixed to the
    last PRG bank. CHR is normally fixed CHR-ROM or CHR-RAM, so sprite export
    only needs CPU bank tracking to let game init reach its palette/OAM writes.
    """

    def __init__(self, prg: bytes) -> None:
        if len(prg) % 0x4000 != 0 or len(prg) < 0x8000:
            raise ValueError("UxROM PRG must contain at least two 16 KiB banks")
        self._banks = [prg[i : i + 0x4000] for i in range(0, len(prg), 0x4000)]
        self._switch_bank = 0
        super().__init__(self._banks[0] + self._banks[-1])

    def _read_prg(self, addr: int) -> int:
        if addr < 0xC000:
            return self._banks[self._switch_bank][addr - 0x8000]
        return self._banks[-1][addr - 0xC000]

    def __setitem__(self, addr: int, value: int) -> None:
        if addr >= 0x8000:
            self._switch_bank = (value & 0x0F) % len(self._banks)
            return
        super().__setitem__(addr, value)

    def reset_state(self) -> None:
        super().reset_state()
        self._switch_bank = 0


class GxROMMemory(NROMMemory):
    """Mapper-66 GxROM/GNROM memory.

    $8000-$FFFF is a switchable 32 KiB PRG bank. The mapper register usually
    uses bits 5-4 for PRG and bits 1-0 for an 8 KiB CHR-ROM bank. Tracking both
    lets simple games reach their init code and lets sprite export select the
    active CHR bank from the captured mapper state.
    """

    def __init__(self, prg: bytes, chr_banks: int) -> None:
        if len(prg) % 0x8000 != 0 or len(prg) == 0:
            raise ValueError("GxROM PRG must contain at least one 32 KiB bank")
        super().__init__(prg[:0x8000])
        self._banks = [prg[i : i + 0x8000] for i in range(0, len(prg), 0x8000)]
        self._prg_bank = 0
        self._chr_bank_count = max(chr_banks, 1)

    def _read_prg(self, addr: int) -> int:
        return self._banks[self._prg_bank][addr - 0x8000]

    def __setitem__(self, addr: int, value: int) -> None:
        if addr >= 0x8000:
            self._prg_bank = ((value >> 4) & 0x03) % len(self._banks)
            self.chr_bank = (value & 0x03) % self._chr_bank_count
            return
        super().__setitem__(addr, value)

    def reset_state(self) -> None:
        super().reset_state()
        self._prg_bank = 0


class ColorDreamsMemory(NROMMemory):
    """Mapper-11 Color Dreams/Wisdom Tree memory.

    $8000-$FFFF is a switchable 32 KiB PRG bank and $0000-$1FFF is a
    switchable 8 KiB CHR-ROM bank. Unlike GxROM, the mapper register layout is
    CCCC LLPP: bits 0-1 select PRG, bits 4-7 select CHR, and bits 2-3 are
    lockout-defeat hardware bits that do not affect emulation here.
    """

    def __init__(self, prg: bytes, chr_banks: int) -> None:
        if len(prg) % 0x8000 != 0 or len(prg) == 0:
            raise ValueError(
                "Color Dreams PRG must contain at least one 32 KiB bank"
            )
        super().__init__(prg[:0x8000])
        self._banks = [prg[i : i + 0x8000] for i in range(0, len(prg), 0x8000)]
        self._prg_bank = 0
        self._chr_bank_count = max(chr_banks, 1)

    def _read_prg(self, addr: int) -> int:
        return self._banks[self._prg_bank][addr - 0x8000]

    def __setitem__(self, addr: int, value: int) -> None:
        if addr >= 0x8000:
            self._prg_bank = (value & 0x03) % len(self._banks)
            self.chr_bank = ((value >> 4) & 0x0F) % self._chr_bank_count
            return
        super().__setitem__(addr, value)

    def reset_state(self) -> None:
        super().reset_state()
        self._prg_bank = 0


class AxROMMemory(NROMMemory):
    """Mapper-7 AxROM memory.

    $8000-$FFFF is a switchable 32 KiB PRG bank. AxROM boards commonly use
    CHR-RAM, which the base PPU write observer already captures through
    PPUADDR/PPUDATA.
    """

    def __init__(self, prg: bytes) -> None:
        if len(prg) % 0x8000 != 0 or len(prg) == 0:
            raise ValueError("AxROM PRG must contain at least one 32 KiB bank")
        super().__init__(prg[:0x8000])
        self._banks = [prg[i : i + 0x8000] for i in range(0, len(prg), 0x8000)]
        self._prg_bank = 0

    def _read_prg(self, addr: int) -> int:
        return self._banks[self._prg_bank][addr - 0x8000]

    def __setitem__(self, addr: int, value: int) -> None:
        if addr >= 0x8000:
            self._prg_bank = (value & 0x07) % len(self._banks)
            return
        super().__setitem__(addr, value)

    def reset_state(self) -> None:
        super().reset_state()
        self._prg_bank = 0


class BNROMNINAMemory(NROMMemory):
    """Mapper-34 BNROM or NINA-001/NINA-002 memory.

    Mapper 34 is historically ambiguous. When CHR-ROM is 0-8 KiB it behaves as
    BNROM: a switchable 32 KiB PRG window and fixed CHR-RAM/CHR-ROM. When CHR
    is larger than 8 KiB, it behaves as NINA: $7FFD switches the 32 KiB PRG
    window and $7FFE/$7FFF switch two 4 KiB CHR windows.
    """

    def __init__(self, prg: bytes, chr_data: bytes) -> None:
        if len(prg) % 0x8000 != 0 or len(prg) == 0:
            raise ValueError("Mapper 34 PRG must contain at least one 32 KiB bank")
        super().__init__(prg[:0x8000])
        self._banks = [prg[i : i + 0x8000] for i in range(0, len(prg), 0x8000)]
        self._prg_bank = 0
        self._chr_rom = bytes(chr_data)
        self._chr_4k_count = max(len(self._chr_rom) // 0x1000, 1)
        self._chr0 = 0
        self._chr1 = 1
        self._prg_ram = bytearray(0x2000)

    def _read_prg(self, addr: int) -> int:
        return self._banks[self._prg_bank][addr - 0x8000]

    def __getitem__(self, addr: int) -> int:
        if 0x6000 <= addr < 0x8000:
            return self._prg_ram[addr - 0x6000]
        return super().__getitem__(addr)

    def __setitem__(self, addr: int, value: int) -> None:
        v = value & 0xFF
        if 0x6000 <= addr < 0x8000:
            self._prg_ram[addr - 0x6000] = v
            if addr == 0x7FFD:
                self._prg_bank = (v & 0x01) % len(self._banks)
            elif addr == 0x7FFE:
                self._chr0 = v & 0x0F
                self.chr_bank = self._dominant_chr_8k_bank()
            elif addr == 0x7FFF:
                self._chr1 = v & 0x0F
                self.chr_bank = self._dominant_chr_8k_bank()
            return
        if addr >= 0x8000:
            self._prg_bank = (v & 0x03) % len(self._banks)
            return
        super().__setitem__(addr, v)

    def _mapped_chr_pattern_table(self) -> bytes:
        if not self._chr_rom:
            return bytes(self._pattern_table)
        if len(self._chr_rom) <= 0x2000:
            return self._chr_rom[:0x2000].ljust(0x2000, b"\x00")
        out = bytearray(0x2000)
        bank0 = self._chr0 % self._chr_4k_count
        bank1 = self._chr1 % self._chr_4k_count
        out[0x0000:0x1000] = self._chr_rom[bank0 * 0x1000 : (bank0 + 1) * 0x1000]
        out[0x1000:0x2000] = self._chr_rom[bank1 * 0x1000 : (bank1 + 1) * 0x1000]
        return bytes(out)

    def _dominant_chr_8k_bank(self) -> int:
        if len(self._chr_rom) <= 0x2000 or self._chr_4k_count < 2:
            return 0
        return (self._chr0 % self._chr_4k_count) // 2

    def ppu_snapshot(self) -> PpuSnapshot:
        snap = super().ppu_snapshot()
        return PpuSnapshot(
            ppuctrl=snap.ppuctrl,
            ppumask=snap.ppumask,
            palette_ram=snap.palette_ram,
            oam=snap.oam,
            pattern_table=self._mapped_chr_pattern_table(),
            chr_bank=self._dominant_chr_8k_bank(),
        )

    def reset_state(self) -> None:
        super().reset_state()
        self._prg_bank = 0
        self._chr0 = 0
        self._chr1 = 1
        self._prg_ram[:] = b"\x00" * 0x2000


class CamericaMemory(UxROMMemory):
    """Mapper-71 Camerica/Codemasters memory.

    Mapper 71 is mostly UNROM: $8000-$BFFF is switchable 16 KiB PRG and
    $C000-$FFFF is fixed to the last bank. Bank select is only on writes to
    $C000-$FFFF; lower writes are mirroring/CIC details ignored by this path.
    """

    def __setitem__(self, addr: int, value: int) -> None:
        if 0xC000 <= addr <= 0xFFFF:
            self._switch_bank = (value & 0x0F) % len(self._banks)
            return
        if addr >= 0x8000:
            return
        super().__setitem__(addr, value)


class MMC1Memory(NROMMemory):
    """Mapper-1 MMC1/SxROM memory for simple runtime sprite capture.

    This implements the serial load register, standard PRG banking modes, and
    CHR-ROM mapping in both 8 KiB and split 4 KiB modes. Many MMC1 board
    variants still remain better handled by an explicit PPU snapshot.
    """

    def __init__(self, prg: bytes, chr_banks: int, chr_data: bytes = b"") -> None:
        if len(prg) % 0x4000 != 0 or len(prg) == 0:
            raise ValueError("MMC1 PRG must contain at least one 16 KiB bank")
        initial = prg if len(prg) in (0x4000, 0x8000) else prg[:0x4000] + prg[-0x4000:]
        super().__init__(initial)
        self._banks = [prg[i : i + 0x4000] for i in range(0, len(prg), 0x4000)]
        self._chr_rom = bytes(chr_data)
        self._chr_bank_count = max(chr_banks, 1)
        self._chr_4k_count = max(len(self._chr_rom) // 0x1000, 1)
        self._shift = 0x10
        self._control = 0x0C
        self._chr0 = 0
        self._chr1 = 0
        self._prg_bank = 0

    def _read_prg(self, addr: int) -> int:
        mode = (self._control >> 2) & 0x03
        if mode in (0, 1):
            bank = (self._prg_bank & 0x0E) % len(self._banks)
            if addr < 0xC000:
                return self._banks[bank][addr - 0x8000]
            return self._banks[(bank + 1) % len(self._banks)][addr - 0xC000]
        if mode == 2:
            if addr < 0xC000:
                return self._banks[0][addr - 0x8000]
            return self._banks[self._prg_bank % len(self._banks)][addr - 0xC000]
        if addr < 0xC000:
            return self._banks[self._prg_bank % len(self._banks)][addr - 0x8000]
        return self._banks[-1][addr - 0xC000]

    def __setitem__(self, addr: int, value: int) -> None:
        if addr >= 0x8000:
            self._write_mapper_register(addr, value & 0xFF)
            return
        super().__setitem__(addr, value)

    def _write_mapper_register(self, addr: int, value: int) -> None:
        if value & 0x80:
            self._shift = 0x10
            self._control |= 0x0C
            return

        complete = bool(self._shift & 0x01)
        self._shift = (self._shift >> 1) | ((value & 0x01) << 4)
        if not complete:
            return

        data = self._shift & 0x1F
        self._shift = 0x10
        register = (addr >> 13) & 0x03
        if register == 0:
            self._control = data
        elif register == 1:
            self._chr0 = data
            if not (self._control & 0x10):
                self.chr_bank = (data >> 1) % self._chr_bank_count
        elif register == 2:
            self._chr1 = data
            if self._control & 0x10:
                self.chr_bank = (self._chr0 // 2) % self._chr_bank_count
        else:
            self._prg_bank = data & 0x0F

    def _mapped_chr_pattern_table(self) -> bytes:
        if not self._chr_rom:
            return bytes(self._pattern_table)
        out = bytearray(0x2000)
        if self._control & 0x10:
            bank0 = self._chr0 % self._chr_4k_count
            bank1 = self._chr1 % self._chr_4k_count
            out[0x0000:0x1000] = self._chr_rom[bank0 * 0x1000 : (bank0 + 1) * 0x1000]
            out[0x1000:0x2000] = self._chr_rom[bank1 * 0x1000 : (bank1 + 1) * 0x1000]
            return bytes(out)
        bank = ((self._chr0 & 0x1E) * 0x1000) % len(self._chr_rom)
        out[:] = self._chr_rom[bank : bank + 0x2000]
        return bytes(out)

    def ppu_snapshot(self) -> PpuSnapshot:
        snap = super().ppu_snapshot()
        return PpuSnapshot(
            ppuctrl=snap.ppuctrl,
            ppumask=snap.ppumask,
            palette_ram=snap.palette_ram,
            oam=snap.oam,
            pattern_table=self._mapped_chr_pattern_table(),
            chr_bank=snap.chr_bank,
        )

    def reset_state(self) -> None:
        super().reset_state()
        self._shift = 0x10
        self._control = 0x0C
        self._chr0 = 0
        self._chr1 = 0
        self._prg_bank = 0


class MMC3Memory(NROMMemory):
    """Mapper-4 MMC3 memory for simple runtime sprite capture.

    This tracks standard MMC3 8 KiB PRG windows and 1/2 KiB CHR windows. IRQ
    timing, mirroring and PRG-RAM protection are intentionally not modeled for
    sprite extraction snapshots.
    """

    def __init__(self, prg: bytes, chr_data: bytes) -> None:
        if len(prg) % 0x2000 != 0 or len(prg) < 0x8000:
            raise ValueError("MMC3 PRG must contain at least four 8 KiB banks")
        initial = prg[:0x4000] + prg[-0x4000:]
        super().__init__(initial)
        self._prg_banks = [prg[i : i + 0x2000] for i in range(0, len(prg), 0x2000)]
        self._chr_rom = bytes(chr_data)
        self._chr_1k_count = max(len(self._chr_rom) // 0x0400, 1)
        self._bank_select = 0
        self._regs = [0, 2, 4, 5, 6, 7, 0, 1]

    def _read_prg(self, addr: int) -> int:
        last = len(self._prg_banks) - 1
        second_last = max(last - 1, 0)
        prg_mode = (self._bank_select >> 6) & 0x01
        r6 = self._regs[6] % len(self._prg_banks)
        r7 = self._regs[7] % len(self._prg_banks)
        if addr < 0xA000:
            bank = second_last if prg_mode else r6
            return self._prg_banks[bank][addr - 0x8000]
        if addr < 0xC000:
            return self._prg_banks[r7][addr - 0xA000]
        if addr < 0xE000:
            bank = r6 if prg_mode else second_last
            return self._prg_banks[bank][addr - 0xC000]
        return self._prg_banks[last][addr - 0xE000]

    def __setitem__(self, addr: int, value: int) -> None:
        if addr >= 0x8000:
            self._write_mapper_register(addr, value & 0xFF)
            return
        super().__setitem__(addr, value)

    def _write_mapper_register(self, addr: int, value: int) -> None:
        if 0x8000 <= addr <= 0x9FFF:
            if addr & 1:
                self._regs[self._bank_select & 0x07] = value
                self.chr_bank = self._dominant_chr_8k_bank()
            else:
                self._bank_select = value
            return
        # Other MMC3 registers affect mirroring, PRG-RAM and IRQs. They are not
        # needed for this PPU/OAM capture path.

    def _chr_bank_1k_for_addr(self, ppu_addr: int) -> int:
        chr_mode = (self._bank_select >> 7) & 0x01
        slot = ppu_addr // 0x0400
        if chr_mode:
            register_by_slot = [2, 3, 4, 5, 0, 0, 1, 1]
        else:
            register_by_slot = [0, 0, 1, 1, 2, 3, 4, 5]
        reg = register_by_slot[slot]
        bank = self._regs[reg]
        if reg in (0, 1):
            bank = (bank & 0xFE) + (slot & 1)
        return bank % self._chr_1k_count

    def _mapped_chr_pattern_table(self) -> bytes:
        if not self._chr_rom:
            return bytes(self._pattern_table)
        out = bytearray(0x2000)
        for slot in range(8):
            bank = self._chr_bank_1k_for_addr(slot * 0x0400)
            start = bank * 0x0400
            out[slot * 0x0400 : (slot + 1) * 0x0400] = self._chr_rom[start : start + 0x0400]
        return bytes(out)

    def _dominant_chr_8k_bank(self) -> int:
        if self._chr_1k_count < 8:
            return 0
        return self._chr_bank_1k_for_addr(0) // 8

    def ppu_snapshot(self) -> PpuSnapshot:
        snap = super().ppu_snapshot()
        return PpuSnapshot(
            ppuctrl=snap.ppuctrl,
            ppumask=snap.ppumask,
            palette_ram=snap.palette_ram,
            oam=snap.oam,
            pattern_table=self._mapped_chr_pattern_table(),
            chr_bank=self._dominant_chr_8k_bank(),
        )

    def reset_state(self) -> None:
        super().reset_state()
        self._bank_select = 0
        self._regs = [0, 2, 4, 5, 6, 7, 0, 1]


class FME7Memory(NROMMemory):
    """Mapper-69 Sunsoft FME-7/5B memory for runtime sprite capture.

    The mapper uses a command register at $8000-$9FFF and a parameter register
    at $A000-$BFFF. Commands 0-7 select eight independent 1 KiB CHR windows;
    commands 9-B select the 8 KiB PRG windows at $8000, $A000 and $C000.
    IRQs, mirroring and 5B expansion audio registers are outside this sprite
    snapshot path.
    """

    def __init__(self, prg: bytes, chr_data: bytes) -> None:
        if len(prg) % 0x2000 != 0 or len(prg) < 0x8000:
            raise ValueError("FME-7 PRG must contain at least four 8 KiB banks")
        initial = prg[:0x6000] + prg[-0x2000:]
        super().__init__(initial)
        self._prg_banks = [prg[i : i + 0x2000] for i in range(0, len(prg), 0x2000)]
        self._chr_rom = bytes(chr_data)
        self._chr_1k_count = max(len(self._chr_rom) // 0x0400, 1)
        self._command = 0
        self._chr_regs = list(range(8))
        self._prg_regs = [0, 1, 2]

    def _read_prg(self, addr: int) -> int:
        if addr < 0xA000:
            bank = self._prg_regs[0] % len(self._prg_banks)
            return self._prg_banks[bank][addr - 0x8000]
        if addr < 0xC000:
            bank = self._prg_regs[1] % len(self._prg_banks)
            return self._prg_banks[bank][addr - 0xA000]
        if addr < 0xE000:
            bank = self._prg_regs[2] % len(self._prg_banks)
            return self._prg_banks[bank][addr - 0xC000]
        return self._prg_banks[-1][addr - 0xE000]

    def __setitem__(self, addr: int, value: int) -> None:
        if 0x8000 <= addr <= 0x9FFF:
            self._command = value & 0x0F
            return
        if 0xA000 <= addr <= 0xBFFF:
            self._write_mapper_parameter(value & 0xFF)
            return
        super().__setitem__(addr, value)

    def _write_mapper_parameter(self, value: int) -> None:
        if 0 <= self._command <= 7:
            self._chr_regs[self._command] = value
            self.chr_bank = self._dominant_chr_8k_bank()
            return
        if 0x09 <= self._command <= 0x0B:
            self._prg_regs[self._command - 0x09] = value & 0x3F

    def _mapped_chr_pattern_table(self) -> bytes:
        if not self._chr_rom:
            return bytes(self._pattern_table)
        out = bytearray(0x2000)
        for slot, reg in enumerate(self._chr_regs):
            bank = reg % self._chr_1k_count
            start = bank * 0x0400
            out[slot * 0x0400 : (slot + 1) * 0x0400] = self._chr_rom[start : start + 0x0400]
        return bytes(out)

    def _dominant_chr_8k_bank(self) -> int:
        if self._chr_1k_count < 8:
            return 0
        return (self._chr_regs[0] % self._chr_1k_count) // 8

    def ppu_snapshot(self) -> PpuSnapshot:
        snap = super().ppu_snapshot()
        return PpuSnapshot(
            ppuctrl=snap.ppuctrl,
            ppumask=snap.ppumask,
            palette_ram=snap.palette_ram,
            oam=snap.oam,
            pattern_table=self._mapped_chr_pattern_table(),
            chr_bank=self._dominant_chr_8k_bank(),
        )

    def reset_state(self) -> None:
        super().reset_state()
        self._command = 0
        self._chr_regs = list(range(8))
        self._prg_regs = [0, 1, 2]
