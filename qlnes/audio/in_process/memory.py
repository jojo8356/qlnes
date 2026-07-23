"""Memory map for in-process music renders. Architecture step 20.5.

The Memory ABC is what py65's MPU calls into. Concrete subclasses
implement mapper-specific PRG/CHR layouts. The in-process runner currently
ships NROMMemory (mapper 0), UxROMMemory (mapper 2), CNROMMemory
(mapper 3), ColorDreamsMemory (mapper 11), GxROMMemory (mapper 66),
and a conservative MMC1Memory (mapper 1). MMC3Memory (mapper 4) supports
enough PRG/CHR banking for runtime sprite capture on simple boot snapshots.
MMC2Memory (mapper 9) and MMC4Memory (mapper 10) support latch-selected
4 KiB CHR windows for original-color sprite snapshots.
Bandai16Memory (mapper 16) supports Bandai FCG PRG and 1 KiB CHR windows.
Jaleco18Memory (mapper 18) supports SS88006 PRG and 1 KiB CHR windows.
Namco163Memory (mapper 19) supports Namco 129/163 PRG and 1 KiB CHR windows.
MMC5Memory (mapper 5) supports MMC5 PRG modes and CHR windows for sprite capture.
VRC24Memory (mappers 21/22/23/25) supports Konami VRC2/VRC4 PRG and CHR windows.
VRC6Memory (mappers 24/26) supports Konami VRC6 PRG and 1 KiB CHR windows.
VRC7Memory (mapper 85) supports Konami VRC7 PRG and 1 KiB CHR windows.
IremG101Memory (mapper 32) supports G-101 PRG and 1 KiB CHR windows.
Taito33Memory (mapper 33) supports TC0190 PRG and mixed 2/1 KiB CHR windows.
NINA0306Memory (mapper 79) supports AVE NINA-03/NINA-06 PRG/CHR banking.
AxROMMemory (mapper 7) supports 32 KiB PRG switching with CHR-RAM captures.
BNROMNINAMemory (mapper 34) supports BNROM PRG switching and NINA split CHR.
FME7Memory (mapper 69) supports Sunsoft FME-7/5B PRG and 1 KiB CHR windows.
CPROMMemory (mapper 13) supports fixed PRG and switchable 4 KiB CHR-RAM.
Bandai70Memory (mapper 70) supports switchable 16 KiB PRG and 8 KiB CHR-ROM.
CamericaMemory (mapper 71) supports the Codemasters/Camerica UNROM variant.
JF17Memory (mapper 72) supports Jaleco PRG/CHR latch writes.
J87Memory (mapper 87) and JF10Memory (mapper 101) support fixed PRG with
switchable 8 KiB CHR-ROM.
HolyDiverMemory (mapper 78) supports switchable 16 KiB PRG and 8 KiB CHR-ROM.
Namco108Memory (mapper 206) supports MMC3-like PRG/CHR banking without mode bits.
RAMBO1Memory (mapper 64) supports Tengen RAMBO-1 PRG and CHR banking.
Mapper42Memory supports fixed high PRG with switchable 8 KiB PRG/CHR-ROM.

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
    Provides zero-initialized 8 KiB cartridge RAM at $6000-$7FFF. Some NROM
    boards do not physically have PRG-RAM, but many supported mappers do; a
    writable default improves runtime sprite capture for init code that stages
    palette/OAM data there before DMA.
    """

    def __init__(self, prg: bytes) -> None:
        if len(prg) not in (0x4000, 0x8000):
            raise ValueError(
                f"NROM PRG must be 16 or 32 KB; got {len(prg)} bytes"
            )
        self._ram = bytearray(0x800)  # $0000-$07FF, mirrored to $1FFF
        self._prg_ram = bytearray(0x2000)  # $6000-$7FFF cartridge RAM window
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
            if reg == 7:
                return self._read_ppu_data()
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
            return self._prg_ram[addr - 0x6000]
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
        if 0x6000 <= addr < 0x8000:
            self._prg_ram[addr - 0x6000] = v
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

    def _read_ppu_data(self) -> int:
        addr = self._ppu_addr & 0x3FFF
        if 0x0000 <= addr <= 0x1FFF:
            value = self._pattern_table[addr]
        elif 0x3F00 <= addr <= 0x3FFF:
            value = self._palette_ram[self._palette_index(addr)]
        else:
            value = 0
        increment = 32 if (self.ppuctrl & 0x04) else 1
        self._ppu_addr = (self._ppu_addr + increment) & 0x7FFF
        return value

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
        self._prg_ram[:] = b"\x00" * 0x2000
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


class NINA0306Memory(NROMMemory):
    """Mapper-79 AVE NINA-03/NINA-06 memory.

    $8000-$FFFF is a switchable 32 KiB PRG bank and PPU $0000-$1FFF is a
    switchable 8 KiB CHR-ROM bank. The control register is decoded in the
    expansion range, including $4100-$41FF and odd 256-byte pages through
    $5Fxx. Data bits are PCCC: bit 3 selects PRG, bits 0-2 select CHR.
    """

    def __init__(self, prg: bytes, chr_banks: int) -> None:
        if len(prg) % 0x8000 != 0 or len(prg) == 0:
            raise ValueError("Mapper 79 PRG must contain at least one 32 KiB bank")
        super().__init__(prg[:0x8000])
        if chr_banks <= 0:
            raise ValueError("Mapper 79 requires at least one CHR bank")
        self._banks = [prg[i : i + 0x8000] for i in range(0, len(prg), 0x8000)]
        self._prg_bank = 0
        self._chr_bank_count = chr_banks

    def _read_prg(self, addr: int) -> int:
        return self._banks[self._prg_bank][addr - 0x8000]

    def __setitem__(self, addr: int, value: int) -> None:
        if 0x4100 <= addr <= 0x5FFF and (addr & 0x0100):
            self._prg_bank = ((value >> 3) & 0x01) % len(self._banks)
            self.chr_bank = (value & 0x07) % self._chr_bank_count
            return
        if addr >= 0x8000:
            return
        super().__setitem__(addr, value)

    def reset_state(self) -> None:
        super().reset_state()
        self._prg_bank = 0
        self.chr_bank = 0


class Mapper42Memory(NROMMemory):
    """Mapper-42 FDS conversion memory.

    CPU $8000-$FFFF is fixed to the last 32 KiB of PRG-ROM. CPU $6000-$7FFF is
    a switchable 8 KiB PRG-ROM window. PPU $0000-$1FFF selects one 8 KiB
    CHR-ROM bank through register $8000.
    """

    def __init__(self, prg: bytes, chr_banks: int) -> None:
        if len(prg) % 0x2000 != 0 or len(prg) < 0x8000:
            raise ValueError("Mapper 42 PRG must contain at least four 8 KiB banks")
        super().__init__(prg[-0x8000:])
        if chr_banks <= 0:
            raise ValueError("Mapper 42 requires at least one CHR bank")
        self._prg_banks = [prg[i : i + 0x2000] for i in range(0, len(prg), 0x2000)]
        self._prg_6000_bank = 0
        self._chr_bank_count = chr_banks

    def __getitem__(self, addr: int) -> int:
        if 0x6000 <= addr < 0x8000:
            return self._prg_banks[self._prg_6000_bank][addr - 0x6000]
        return super().__getitem__(addr)

    def __setitem__(self, addr: int, value: int) -> None:
        reg = addr & 0xE003
        if reg == 0x8000:
            self.chr_bank = (value & 0x0F) % self._chr_bank_count
            return
        if reg == 0xE000:
            self._prg_6000_bank = (value & 0x0F) % len(self._prg_banks)
            return
        if addr >= 0x8000:
            return
        super().__setitem__(addr, value)

    def reset_state(self) -> None:
        super().reset_state()
        self._prg_6000_bank = 0
        self.chr_bank = 0


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


class MMC2Memory(NROMMemory):
    """Mapper-9 MMC2/PxROM memory.

    CPU $8000-$9FFF is one switchable 8 KiB PRG bank and $A000-$FFFF is fixed
    to the last three 8 KiB PRG banks. PPU $0000-$0FFF and $1000-$1FFF are two
    latch-selected 4 KiB CHR-ROM windows. The full PPU latch timing is not
    rendered here, but the selected latch registers are mapped into the runtime
    pattern-table snapshot so OAM sprite PNGs use the active original tiles.
    """

    def __init__(self, prg: bytes, chr_data: bytes) -> None:
        if len(prg) % 0x2000 != 0 or len(prg) < 0x8000:
            raise ValueError("MMC2 PRG must contain at least four 8 KiB banks")
        self._prg_banks = [prg[i : i + 0x2000] for i in range(0, len(prg), 0x2000)]
        initial = self._prg_banks[0] + self._prg_banks[-3] + self._prg_banks[-2] + self._prg_banks[-1]
        super().__init__(initial)
        if not chr_data:
            raise ValueError("MMC2 requires CHR-ROM data")
        self._chr_rom = bytes(chr_data)
        self._chr_4k_count = max(len(self._chr_rom) // 0x1000, 1)
        self._prg_bank = 0
        self._chr_regs = [0, 0, 0, 0]
        self._chr_latches = [0xFD, 0xFD]

    def _read_prg(self, addr: int) -> int:
        if addr < 0xA000:
            return self._prg_banks[self._prg_bank % len(self._prg_banks)][addr - 0x8000]
        if addr < 0xC000:
            return self._prg_banks[-3][addr - 0xA000]
        if addr < 0xE000:
            return self._prg_banks[-2][addr - 0xC000]
        return self._prg_banks[-1][addr - 0xE000]

    def __setitem__(self, addr: int, value: int) -> None:
        if addr >= 0x8000:
            self._write_mapper_register(addr, value & 0xFF)
            return
        super().__setitem__(addr, value)

    def _write_mapper_register(self, addr: int, value: int) -> None:
        reg = addr & 0xF000
        if reg == 0xA000:
            self._prg_bank = value & 0x0F
        elif reg == 0xB000:
            self._chr_regs[0] = value & 0x1F
        elif reg == 0xC000:
            self._chr_regs[1] = value & 0x1F
        elif reg == 0xD000:
            self._chr_regs[2] = value & 0x1F
        elif reg == 0xE000:
            self._chr_regs[3] = value & 0x1F
        # $F000 mirroring writes do not affect sprite extraction.

    def _mapped_chr_pattern_table(self) -> bytes:
        out = bytearray(0x2000)
        reg0 = 0 if self._chr_latches[0] == 0xFD else 1
        reg1 = 2 if self._chr_latches[1] == 0xFD else 3
        bank0 = self._chr_regs[reg0] % self._chr_4k_count
        bank1 = self._chr_regs[reg1] % self._chr_4k_count
        out[0x0000:0x1000] = self._chr_rom[bank0 * 0x1000 : (bank0 + 1) * 0x1000]
        out[0x1000:0x2000] = self._chr_rom[bank1 * 0x1000 : (bank1 + 1) * 0x1000]
        return bytes(out)

    def _read_ppu_data(self) -> int:
        addr = self._ppu_addr & 0x3FFF
        if 0x0FD8 <= addr <= 0x0FDF:
            self._chr_latches[0] = 0xFD
        elif 0x0FE8 <= addr <= 0x0FEF:
            self._chr_latches[0] = 0xFE
        elif 0x1FD8 <= addr <= 0x1FDF:
            self._chr_latches[1] = 0xFD
        elif 0x1FE8 <= addr <= 0x1FEF:
            self._chr_latches[1] = 0xFE

        if 0x0000 <= addr <= 0x1FFF:
            value = self._mapped_chr_pattern_table()[addr]
        elif 0x3F00 <= addr <= 0x3FFF:
            value = self._palette_ram[self._palette_index(addr)]
        else:
            value = 0
        increment = 32 if (self.ppuctrl & 0x04) else 1
        self._ppu_addr = (self._ppu_addr + increment) & 0x7FFF
        return value

    def ppu_snapshot(self) -> PpuSnapshot:
        snap = super().ppu_snapshot()
        return PpuSnapshot(
            ppuctrl=snap.ppuctrl,
            ppumask=snap.ppumask,
            palette_ram=snap.palette_ram,
            oam=snap.oam,
            pattern_table=self._mapped_chr_pattern_table(),
            chr_bank=(self._chr_regs[0] % self._chr_4k_count) // 2,
        )

    def reset_state(self) -> None:
        super().reset_state()
        self._prg_bank = 0
        self._chr_regs = [0, 0, 0, 0]
        self._chr_latches = [0xFD, 0xFD]


class MMC4Memory(MMC2Memory):
    """Mapper-10 MMC4/FxROM memory.

    MMC4 keeps the same 4 KiB latch-selected CHR register layout as MMC2, but
    CPU PRG uses a switchable 16 KiB bank at $8000-$BFFF and a fixed last
    16 KiB bank at $C000-$FFFF.
    """

    def __init__(self, prg: bytes, chr_data: bytes) -> None:
        if len(prg) % 0x4000 != 0 or len(prg) < 0x8000:
            raise ValueError("MMC4 PRG must contain at least two 16 KiB banks")
        self._prg16_banks = [prg[i : i + 0x4000] for i in range(0, len(prg), 0x4000)]
        super().__init__(self._prg16_banks[0] + self._prg16_banks[-1], chr_data)

    def _read_prg(self, addr: int) -> int:
        if addr < 0xC000:
            return self._prg16_banks[self._prg_bank % len(self._prg16_banks)][addr - 0x8000]
        return self._prg16_banks[-1][addr - 0xC000]


class Bandai16Memory(NROMMemory):
    """Mapper-16 Bandai FCG memory.

    CPU $8000-$BFFF is a switchable 16 KiB PRG bank and $C000-$FFFF is fixed
    to the last PRG bank. Registers at `$6000-$6008` or `$8000-$8008` select
    eight 1 KiB CHR-ROM windows and the low PRG bank. IRQ, mirroring and EEPROM
    registers are outside this sprite snapshot path.
    """

    def __init__(self, prg: bytes, chr_data: bytes) -> None:
        if len(prg) % 0x4000 != 0 or len(prg) < 0x8000:
            raise ValueError("Mapper 16 PRG must contain at least two 16 KiB banks")
        self._banks = [prg[i : i + 0x4000] for i in range(0, len(prg), 0x4000)]
        super().__init__(self._banks[0] + self._banks[-1])
        if not chr_data:
            raise ValueError("Mapper 16 requires CHR-ROM data")
        self._chr_rom = bytes(chr_data)
        self._chr_1k_count = max(len(self._chr_rom) // 0x0400, 1)
        self._switch_bank = 0
        self._chr_regs = list(range(8))

    def _read_prg(self, addr: int) -> int:
        if addr < 0xC000:
            return self._banks[self._switch_bank][addr - 0x8000]
        return self._banks[-1][addr - 0xC000]

    def __setitem__(self, addr: int, value: int) -> None:
        if 0x6000 <= addr <= 0x600F or 0x8000 <= addr <= 0x800F:
            self._write_mapper_register(addr, value & 0xFF)
            return
        if addr >= 0x8000:
            return
        super().__setitem__(addr, value)

    def _write_mapper_register(self, addr: int, value: int) -> None:
        reg = addr & 0x000F
        if 0 <= reg <= 7:
            self._chr_regs[reg] = value
            self.chr_bank = self._dominant_chr_8k_bank()
        elif reg == 8:
            self._switch_bank = value % len(self._banks)
        # $9 mirroring, $A-$C IRQ and $D EEPROM are ignored here.

    def _mapped_chr_pattern_table(self) -> bytes:
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
        self._switch_bank = 0
        self._chr_regs = list(range(8))


class Jaleco18Memory(NROMMemory):
    """Mapper-18 Jaleco SS88006 memory.

    CPU $8000/$A000/$C000 are switchable 8 KiB PRG banks and $E000-$FFFF is
    fixed to the last PRG bank. CHR uses eight switchable 1 KiB windows. Bank
    numbers are split across low/high nibble register pairs. IRQ, mirroring and
    ADPCM registers are intentionally ignored for sprite snapshot export.
    """

    def __init__(self, prg: bytes, chr_data: bytes) -> None:
        if len(prg) % 0x2000 != 0 or len(prg) < 0x8000:
            raise ValueError("Mapper 18 PRG must contain at least four 8 KiB banks")
        initial = prg[:0x6000] + prg[-0x2000:]
        super().__init__(initial)
        if not chr_data:
            raise ValueError("Mapper 18 requires CHR-ROM data")
        self._prg_banks = [prg[i : i + 0x2000] for i in range(0, len(prg), 0x2000)]
        self._chr_rom = bytes(chr_data)
        self._chr_1k_count = max(len(self._chr_rom) // 0x0400, 1)
        self._prg_regs = [0, 1, 2]
        self._chr_regs = list(range(8))

    def _read_prg(self, addr: int) -> int:
        if addr < 0xA000:
            return self._prg_banks[self._prg_regs[0] % len(self._prg_banks)][addr - 0x8000]
        if addr < 0xC000:
            return self._prg_banks[self._prg_regs[1] % len(self._prg_banks)][addr - 0xA000]
        if addr < 0xE000:
            return self._prg_banks[self._prg_regs[2] % len(self._prg_banks)][addr - 0xC000]
        return self._prg_banks[-1][addr - 0xE000]

    def __setitem__(self, addr: int, value: int) -> None:
        if addr >= 0x8000:
            self._write_mapper_register(addr, value & 0x0F)
            return
        super().__setitem__(addr, value)

    def _write_mapper_register(self, addr: int, value: int) -> None:
        reg = addr & 0xF003
        prg_pairs = {
            0x8000: (0, False),
            0x8001: (0, True),
            0x8002: (1, False),
            0x8003: (1, True),
            0x9000: (2, False),
            0x9001: (2, True),
        }
        if reg in prg_pairs:
            slot, high = prg_pairs[reg]
            if high:
                self._prg_regs[slot] = (self._prg_regs[slot] & 0x0F) | ((value & 0x03) << 4)
            else:
                self._prg_regs[slot] = (self._prg_regs[slot] & 0x30) | value
            return

        chr_pairs = {
            0xA000: (0, False),
            0xA001: (0, True),
            0xA002: (1, False),
            0xA003: (1, True),
            0xB000: (2, False),
            0xB001: (2, True),
            0xB002: (3, False),
            0xB003: (3, True),
            0xC000: (4, False),
            0xC001: (4, True),
            0xC002: (5, False),
            0xC003: (5, True),
            0xD000: (6, False),
            0xD001: (6, True),
            0xD002: (7, False),
            0xD003: (7, True),
        }
        if reg in chr_pairs:
            slot, high = chr_pairs[reg]
            if high:
                self._chr_regs[slot] = (self._chr_regs[slot] & 0x0F) | (value << 4)
            else:
                self._chr_regs[slot] = (self._chr_regs[slot] & 0xF0) | value
            self.chr_bank = self._dominant_chr_8k_bank()

    def _mapped_chr_pattern_table(self) -> bytes:
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
        self._prg_regs = [0, 1, 2]
        self._chr_regs = list(range(8))


class Namco163Memory(NROMMemory):
    """Mapper-19 Namco 129/163 memory.

    CPU $8000/$A000/$C000 are switchable 8 KiB PRG banks and $E000-$FFFF is
    fixed to the last PRG bank. PPU pattern tables use eight 1 KiB CHR windows
    selected through `$8000-$BFFF` in 0x800-byte register ranges. IRQ,
    expansion audio and nametable-source banking are outside this sprite path.
    """

    def __init__(self, prg: bytes, chr_data: bytes) -> None:
        if len(prg) % 0x2000 != 0 or len(prg) < 0x8000:
            raise ValueError("Namco 163 PRG must contain at least four 8 KiB banks")
        initial = prg[:0x6000] + prg[-0x2000:]
        super().__init__(initial)
        if not chr_data:
            raise ValueError("Namco 163 requires CHR-ROM data")
        self._prg_banks = [prg[i : i + 0x2000] for i in range(0, len(prg), 0x2000)]
        self._chr_rom = bytes(chr_data)
        self._chr_1k_count = max(len(self._chr_rom) // 0x0400, 1)
        self._prg_regs = [0, 1, 2]
        self._chr_regs = list(range(8))
        self._chip_ram = bytearray(0x80)
        self._chip_ram_addr = 0

    def _read_prg(self, addr: int) -> int:
        if addr < 0xA000:
            return self._prg_banks[self._prg_regs[0] % len(self._prg_banks)][addr - 0x8000]
        if addr < 0xC000:
            return self._prg_banks[self._prg_regs[1] % len(self._prg_banks)][addr - 0xA000]
        if addr < 0xE000:
            return self._prg_banks[self._prg_regs[2] % len(self._prg_banks)][addr - 0xC000]
        return self._prg_banks[-1][addr - 0xE000]

    def __getitem__(self, addr: int) -> int:
        if 0x4800 <= addr <= 0x4FFF:
            return self._chip_ram[self._chip_ram_addr & 0x7F]
        return super().__getitem__(addr)

    def __setitem__(self, addr: int, value: int) -> None:
        v = value & 0xFF
        if 0x4800 <= addr <= 0x4FFF:
            self._chip_ram[self._chip_ram_addr & 0x7F] = v
            return
        if 0xF800 <= addr <= 0xFFFF:
            self._chip_ram_addr = v & 0x7F
            return
        if 0x8000 <= addr <= 0xFFFF:
            self._write_mapper_register(addr, v)
            return
        super().__setitem__(addr, v)

    def _write_mapper_register(self, addr: int, value: int) -> None:
        if 0x8000 <= addr <= 0xBFFF:
            slot = (addr - 0x8000) // 0x0800
            self._chr_regs[slot] = value
            self.chr_bank = self._dominant_chr_8k_bank()
            return
        if 0xE000 <= addr <= 0xE7FF:
            self._prg_regs[0] = value & 0x3F
        elif 0xE800 <= addr <= 0xEFFF:
            self._prg_regs[1] = value & 0x3F
        elif 0xF000 <= addr <= 0xF7FF:
            self._prg_regs[2] = value & 0x3F

    def _mapped_chr_pattern_table(self) -> bytes:
        out = bytearray(0x2000)
        for slot, reg in enumerate(self._chr_regs):
            if reg >= 0xE0:
                continue
            bank = reg % self._chr_1k_count
            start = bank * 0x0400
            out[slot * 0x0400 : (slot + 1) * 0x0400] = self._chr_rom[start : start + 0x0400]
        return bytes(out)

    def _dominant_chr_8k_bank(self) -> int:
        if self._chr_1k_count < 8:
            return 0
        first = self._chr_regs[0]
        if first >= 0xE0:
            return 0
        return (first % self._chr_1k_count) // 8

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
        self._prg_regs = [0, 1, 2]
        self._chr_regs = list(range(8))
        self._chip_ram[:] = b"\x00" * 0x80
        self._chip_ram_addr = 0


class MMC5Memory(NROMMemory):
    """Mapper-5 MMC5 memory for runtime sprite capture.

    This tracks PRG mode `$5100`, CHR mode `$5101`, PRG registers
    `$5114-$5117`, upper CHR bits `$5130`, and CHR select registers
    `$5120-$512B`. IRQs, MMC5 audio, ExRAM, split screen and extended
    attributes are outside this sprite snapshot path.
    """

    def __init__(self, prg: bytes, chr_data: bytes) -> None:
        if len(prg) % 0x2000 != 0 or len(prg) < 0x8000:
            raise ValueError("MMC5 PRG must contain at least four 8 KiB banks")
        super().__init__(prg[-0x8000:])
        self._prg_banks = [prg[i : i + 0x2000] for i in range(0, len(prg), 0x2000)]
        self._chr_rom = bytes(chr_data)
        self._chr_1k_count = max(len(self._chr_rom) // 0x0400, 1)
        self._prg_mode = 3
        self._chr_mode = 3
        last = len(self._prg_banks) - 1
        self._prg_regs = [max(last - 3, 0), max(last - 2, 0), max(last - 1, 0), 0xFF]
        self._chr_regs = list(range(12))
        self._chr_upper = 0

    def _read_prg_bank(self, bank: int, offset: int) -> int:
        return self._prg_banks[bank % len(self._prg_banks)][offset]

    def _read_prg(self, addr: int) -> int:
        mode = self._prg_mode & 0x03
        if mode == 0:
            base = ((self._prg_regs[3] & 0x7F) & ~0x03) % len(self._prg_banks)
            return self._read_prg_bank(base + ((addr - 0x8000) // 0x2000), (addr - 0x8000) & 0x1FFF)
        if mode == 1:
            if addr < 0xC000:
                base = ((self._prg_regs[1] & 0x7F) & ~0x01) % len(self._prg_banks)
                return self._read_prg_bank(base + ((addr - 0x8000) // 0x2000), (addr - 0x8000) & 0x1FFF)
            base = ((self._prg_regs[3] & 0x7F) & ~0x01) % len(self._prg_banks)
            return self._read_prg_bank(base + ((addr - 0xC000) // 0x2000), (addr - 0xC000) & 0x1FFF)
        if mode == 2:
            if addr < 0xC000:
                base = ((self._prg_regs[1] & 0x7F) & ~0x01) % len(self._prg_banks)
                return self._read_prg_bank(base + ((addr - 0x8000) // 0x2000), (addr - 0x8000) & 0x1FFF)
            if addr < 0xE000:
                return self._read_prg_bank(self._prg_regs[2] & 0x7F, addr - 0xC000)
            return self._read_prg_bank(self._prg_regs[3] & 0x7F, addr - 0xE000)
        if addr < 0xA000:
            return self._read_prg_bank(self._prg_regs[0] & 0x7F, addr - 0x8000)
        if addr < 0xC000:
            return self._read_prg_bank(self._prg_regs[1] & 0x7F, addr - 0xA000)
        if addr < 0xE000:
            return self._read_prg_bank(self._prg_regs[2] & 0x7F, addr - 0xC000)
        return self._read_prg_bank(self._prg_regs[3] & 0x7F, addr - 0xE000)

    def __setitem__(self, addr: int, value: int) -> None:
        v = value & 0xFF
        if 0x5000 <= addr <= 0x5FFF:
            self._write_mapper_register(addr, v)
            return
        super().__setitem__(addr, v)

    def _write_mapper_register(self, addr: int, value: int) -> None:
        if addr == 0x5100:
            self._prg_mode = value & 0x03
        elif addr == 0x5101:
            self._chr_mode = value & 0x03
            self.chr_bank = self._dominant_chr_8k_bank()
        elif 0x5114 <= addr <= 0x5117:
            self._prg_regs[addr - 0x5114] = value
        elif 0x5120 <= addr <= 0x512B:
            self._chr_regs[addr - 0x5120] = ((self._chr_upper & 0x03) << 8) | value
            self.chr_bank = self._dominant_chr_8k_bank()
        elif addr == 0x5130:
            self._chr_upper = value & 0x03

    def _copy_chr_bank(self, out: bytearray, dst: int, bank: int, size: int) -> None:
        if not self._chr_rom:
            out[dst : dst + size] = self._pattern_table[dst : dst + size]
            return
        unit_count = max(len(self._chr_rom) // size, 1)
        start = (bank % unit_count) * size
        out[dst : dst + size] = self._chr_rom[start : start + size]

    def _mapped_chr_pattern_table(self) -> bytes:
        out = bytearray(0x2000)
        mode = self._chr_mode & 0x03
        if mode == 0:
            self._copy_chr_bank(out, 0x0000, self._chr_regs[7], 0x2000)
        elif mode == 1:
            self._copy_chr_bank(out, 0x0000, self._chr_regs[3], 0x1000)
            self._copy_chr_bank(out, 0x1000, self._chr_regs[7], 0x1000)
        elif mode == 2:
            for dst, reg in ((0x0000, 1), (0x0800, 3), (0x1000, 5), (0x1800, 7)):
                self._copy_chr_bank(out, dst, self._chr_regs[reg], 0x0800)
        else:
            for slot in range(8):
                self._copy_chr_bank(out, slot * 0x0400, self._chr_regs[slot], 0x0400)
        return bytes(out)

    def _dominant_chr_8k_bank(self) -> int:
        if self._chr_1k_count < 8:
            return 0
        mode = self._chr_mode & 0x03
        if mode == 0:
            return self._chr_regs[7] % max(self._chr_1k_count // 8, 1)
        if mode == 1:
            return (self._chr_regs[3] * 4 % self._chr_1k_count) // 8
        if mode == 2:
            return (self._chr_regs[1] * 2 % self._chr_1k_count) // 8
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
        last = len(self._prg_banks) - 1
        self._prg_mode = 3
        self._chr_mode = 3
        self._prg_regs = [max(last - 3, 0), max(last - 2, 0), max(last - 1, 0), 0xFF]
        self._chr_regs = list(range(12))
        self._chr_upper = 0


class VRC6Memory(NROMMemory):
    """Mapper-24/26 Konami VRC6 memory for runtime sprite capture.

    Mapper 24 uses direct `$x000/$x001/$x002/$x003` register decoding. Mapper
    26 swaps A0 and A1, so `$x001` and `$x002` exchange roles. This model
    tracks the 16 KiB PRG window at `$8000`, the 8 KiB PRG window at `$C000`,
    and the eight 1 KiB CHR windows used by normal VRC6 sprite snapshots.
    IRQs, VRC6 expansion audio and ROM nametable banking are outside this path.
    """

    def __init__(self, prg: bytes, chr_data: bytes, *, mapper: int = 24) -> None:
        if len(prg) % 0x2000 != 0 or len(prg) < 0x8000:
            raise ValueError("VRC6 PRG must contain at least four 8 KiB banks")
        initial = prg[:0x4000] + prg[:0x2000] + prg[-0x2000:]
        super().__init__(initial)
        self._mapper = mapper
        self._prg = bytes(prg)
        self._prg_16k_count = max(len(self._prg) // 0x4000, 1)
        self._prg_8k_banks = [prg[i : i + 0x2000] for i in range(0, len(prg), 0x2000)]
        self._chr_rom = bytes(chr_data)
        self._chr_1k_count = max(len(self._chr_rom) // 0x0400, 1)
        self._prg_16k = 0
        self._prg_8k = 0
        self._chr_regs = list(range(8))
        self._banking_style = 0

    def _normal_register(self, addr: int) -> int:
        reg = addr & 0xF003
        if self._mapper == 26:
            low = reg & 0x0003
            if low == 0x0001:
                reg = (reg & ~0x0003) | 0x0002
            elif low == 0x0002:
                reg = (reg & ~0x0003) | 0x0001
        return reg

    def _read_prg(self, addr: int) -> int:
        if addr < 0xC000:
            bank = self._prg_16k % self._prg_16k_count
            start = bank * 0x4000
            return self._prg[start + addr - 0x8000]
        if addr < 0xE000:
            return self._prg_8k_banks[self._prg_8k % len(self._prg_8k_banks)][addr - 0xC000]
        return self._prg_8k_banks[-1][addr - 0xE000]

    def __setitem__(self, addr: int, value: int) -> None:
        if 0x8000 <= addr <= 0xFFFF:
            self._write_mapper_register(addr, value & 0xFF)
            return
        super().__setitem__(addr, value)

    def _write_mapper_register(self, addr: int, value: int) -> None:
        reg = self._normal_register(addr)
        if 0x8000 <= reg <= 0x8003:
            self._prg_16k = value & 0x0F
            return
        if reg == 0xB003:
            self._banking_style = value & 0x07
            self.chr_bank = self._dominant_chr_8k_bank()
            return
        if 0xC000 <= reg <= 0xC003:
            self._prg_8k = value & 0x1F
            return
        if 0xD000 <= reg <= 0xD003:
            self._chr_regs[reg & 0x03] = value
            self.chr_bank = self._dominant_chr_8k_bank()
            return
        if 0xE000 <= reg <= 0xE003:
            self._chr_regs[4 + (reg & 0x03)] = value
            self.chr_bank = self._dominant_chr_8k_bank()

    def _chr_register_for_slot(self, slot: int) -> int:
        mode = self._banking_style & 0x03
        if mode == 1:
            return [0, 1, 1, 3, 2, 5, 3, 7][slot]
        if mode in (2, 3):
            return [0, 1, 2, 3, 4, 5, 5, 7][slot]
        return slot

    def _mapped_chr_pattern_table(self) -> bytes:
        if not self._chr_rom:
            return bytes(self._pattern_table)
        out = bytearray(0x2000)
        for slot in range(8):
            reg = self._chr_register_for_slot(slot)
            bank = self._chr_regs[reg] % self._chr_1k_count
            start = bank * 0x0400
            out[slot * 0x0400 : (slot + 1) * 0x0400] = self._chr_rom[start : start + 0x0400]
        return bytes(out)

    def _dominant_chr_8k_bank(self) -> int:
        if self._chr_1k_count < 8:
            return 0
        bank = self._chr_regs[self._chr_register_for_slot(0)] % self._chr_1k_count
        return bank // 8

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
        self._prg_16k = 0
        self._prg_8k = 0
        self._chr_regs = list(range(8))
        self._banking_style = 0


class VRC24Memory(NROMMemory):
    """Mappers 21/22/23/25 Konami VRC2/VRC4 memory for sprite capture.

    VRC2/VRC4 boards wire low CPU address lines differently. This model accepts
    the known iNES addressing permutations for each mapper and observes the PRG
    and CHR registers needed to compose a runtime pattern-table snapshot.
    Mirroring, IRQ and the VRC2 1-bit latch are outside this sprite path.
    """

    _PORT_OFFSETS: dict[int, tuple[tuple[int, int, int, int], ...]] = {
        21: ((0x000, 0x002, 0x004, 0x006), (0x000, 0x040, 0x080, 0x0C0)),
        22: ((0x000, 0x002, 0x001, 0x003),),
        23: ((0x000, 0x001, 0x002, 0x003), (0x000, 0x004, 0x008, 0x00C)),
        25: ((0x000, 0x002, 0x001, 0x003), (0x000, 0x008, 0x004, 0x00C)),
    }

    def __init__(self, prg: bytes, chr_data: bytes, *, mapper: int) -> None:
        if len(prg) % 0x2000 != 0 or len(prg) < 0x8000:
            raise ValueError("VRC2/VRC4 PRG must contain at least four 8 KiB banks")
        initial = prg[:0x4000] + prg[-0x4000:]
        super().__init__(initial)
        self._mapper = mapper
        self._prg_banks = [prg[i : i + 0x2000] for i in range(0, len(prg), 0x2000)]
        self._chr_rom = bytes(chr_data)
        self._chr_1k_count = max(len(self._chr_rom) // 0x0400, 1)
        self._prg0 = 0
        self._prg1 = 1
        self._swap_mode = False
        self._chr_regs = list(range(8))

    def _normal_register(self, addr: int) -> int | None:
        group = addr & 0xF000
        offset = addr & 0x0FF
        for ports in self._PORT_OFFSETS.get(self._mapper, ()):
            if offset in ports:
                return group | ports.index(offset)
        return None

    def _read_prg(self, addr: int) -> int:
        second_last = max(len(self._prg_banks) - 2, 0)
        if self._mapper == 22:
            if addr < 0xA000:
                return self._prg_banks[self._prg0 % len(self._prg_banks)][addr - 0x8000]
            if addr < 0xC000:
                return self._prg_banks[self._prg1 % len(self._prg_banks)][addr - 0xA000]
            if addr < 0xE000:
                return self._prg_banks[second_last][addr - 0xC000]
            return self._prg_banks[-1][addr - 0xE000]
        if addr < 0xA000:
            bank = second_last if self._swap_mode else self._prg0
            return self._prg_banks[bank % len(self._prg_banks)][addr - 0x8000]
        if addr < 0xC000:
            return self._prg_banks[self._prg1 % len(self._prg_banks)][addr - 0xA000]
        if addr < 0xE000:
            bank = self._prg0 if self._swap_mode else second_last
            return self._prg_banks[bank % len(self._prg_banks)][addr - 0xC000]
        return self._prg_banks[-1][addr - 0xE000]

    def __setitem__(self, addr: int, value: int) -> None:
        if 0x8000 <= addr <= 0xFFFF:
            self._write_mapper_register(addr, value & 0xFF)
            return
        super().__setitem__(addr, value)

    def _write_mapper_register(self, addr: int, value: int) -> None:
        reg = self._normal_register(addr)
        if reg is None:
            return
        if 0x8000 <= reg <= 0x8003:
            self._prg0 = value & 0x1F
            return
        if 0x9000 <= reg <= 0x9003:
            if (reg & 0x0003) == 0x02 and self._mapper != 22:
                self._swap_mode = bool(value & 0x02)
            return
        if 0xA000 <= reg <= 0xA003:
            self._prg1 = value & 0x1F
            return
        chr_slot_pair = {
            0xB000: (0, False),
            0xB001: (0, True),
            0xB002: (1, False),
            0xB003: (1, True),
            0xC000: (2, False),
            0xC001: (2, True),
            0xC002: (3, False),
            0xC003: (3, True),
            0xD000: (4, False),
            0xD001: (4, True),
            0xD002: (5, False),
            0xD003: (5, True),
            0xE000: (6, False),
            0xE001: (6, True),
            0xE002: (7, False),
            0xE003: (7, True),
        }.get(reg)
        if chr_slot_pair is None:
            return
        slot, high = chr_slot_pair
        if high:
            self._chr_regs[slot] = (self._chr_regs[slot] & 0x0F) | ((value & 0x1F) << 4)
        else:
            self._chr_regs[slot] = (self._chr_regs[slot] & 0x1F0) | (value & 0x0F)
        self.chr_bank = self._dominant_chr_8k_bank()

    def _chr_bank_for_slot(self, slot: int) -> int:
        bank = self._chr_regs[slot]
        if self._mapper == 22:
            bank >>= 1
        return bank % self._chr_1k_count

    def _mapped_chr_pattern_table(self) -> bytes:
        if not self._chr_rom:
            return bytes(self._pattern_table)
        out = bytearray(0x2000)
        for slot in range(8):
            bank = self._chr_bank_for_slot(slot)
            start = bank * 0x0400
            out[slot * 0x0400 : (slot + 1) * 0x0400] = self._chr_rom[start : start + 0x0400]
        return bytes(out)

    def _dominant_chr_8k_bank(self) -> int:
        if self._chr_1k_count < 8:
            return 0
        return self._chr_bank_for_slot(0) // 8

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
        self._prg0 = 0
        self._prg1 = 1
        self._swap_mode = False
        self._chr_regs = list(range(8))


class VRC7Memory(NROMMemory):
    """Mapper-85 Konami VRC7 memory for runtime sprite capture.

    VRC7 has two board variants: one selects secondary registers with A3
    (`$x008`), the other with A4 (`$x010`). This model accepts both aliases for
    PRG and CHR banking, and ignores IRQ, mirroring, WRAM protection and FM
    audio because they are not required for sprite PNG snapshots.
    """

    def __init__(self, prg: bytes, chr_data: bytes) -> None:
        if len(prg) % 0x2000 != 0 or len(prg) < 0x8000:
            raise ValueError("VRC7 PRG must contain at least four 8 KiB banks")
        initial = prg[:0x6000] + prg[-0x2000:]
        super().__init__(initial)
        self._prg_banks = [prg[i : i + 0x2000] for i in range(0, len(prg), 0x2000)]
        self._chr_rom = bytes(chr_data)
        self._chr_1k_count = max(len(self._chr_rom) // 0x0400, 1)
        self._prg_regs = [0, 1, 2]
        self._chr_regs = list(range(8))

    def _read_prg(self, addr: int) -> int:
        if addr < 0xA000:
            return self._prg_banks[self._prg_regs[0] % len(self._prg_banks)][addr - 0x8000]
        if addr < 0xC000:
            return self._prg_banks[self._prg_regs[1] % len(self._prg_banks)][addr - 0xA000]
        if addr < 0xE000:
            return self._prg_banks[self._prg_regs[2] % len(self._prg_banks)][addr - 0xC000]
        return self._prg_banks[-1][addr - 0xE000]

    def __setitem__(self, addr: int, value: int) -> None:
        if 0x8000 <= addr <= 0xFFFF:
            self._write_mapper_register(addr, value & 0xFF)
            return
        super().__setitem__(addr, value)

    def _write_mapper_register(self, addr: int, value: int) -> None:
        reg = addr & 0xF018
        if reg == 0x8000:
            self._prg_regs[0] = value & 0x3F
        elif reg in (0x8008, 0x8010, 0x8018):
            self._prg_regs[1] = value & 0x3F
        elif reg == 0x9000:
            self._prg_regs[2] = value & 0x3F
        elif reg == 0xA000:
            self._set_chr_reg(0, value)
        elif reg in (0xA008, 0xA010, 0xA018):
            self._set_chr_reg(1, value)
        elif reg == 0xB000:
            self._set_chr_reg(2, value)
        elif reg in (0xB008, 0xB010, 0xB018):
            self._set_chr_reg(3, value)
        elif reg == 0xC000:
            self._set_chr_reg(4, value)
        elif reg in (0xC008, 0xC010, 0xC018):
            self._set_chr_reg(5, value)
        elif reg == 0xD000:
            self._set_chr_reg(6, value)
        elif reg in (0xD008, 0xD010, 0xD018):
            self._set_chr_reg(7, value)

    def _set_chr_reg(self, slot: int, value: int) -> None:
        self._chr_regs[slot] = value
        self.chr_bank = self._dominant_chr_8k_bank()

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
        self._prg_regs = [0, 1, 2]
        self._chr_regs = list(range(8))


class IremG101Memory(NROMMemory):
    """Mapper-32 Irem G-101 memory.

    CPU $A000-$BFFF is a switchable 8 KiB PRG bank, $E000-$FFFF is fixed to
    the last bank, and $8000/$C000 swap one switchable bank with the fixed
    second-last bank depending on PRG mode. CHR uses eight switchable 1 KiB
    windows selected at `$B000-$B007`. Mirroring is ignored for sprite export.
    """

    def __init__(self, prg: bytes, chr_data: bytes) -> None:
        if len(prg) % 0x2000 != 0 or len(prg) < 0x8000:
            raise ValueError("Irem G-101 PRG must contain at least four 8 KiB banks")
        initial = prg[:0x4000] + prg[-0x4000:]
        super().__init__(initial)
        if not chr_data:
            raise ValueError("Irem G-101 requires CHR-ROM data")
        self._prg_banks = [prg[i : i + 0x2000] for i in range(0, len(prg), 0x2000)]
        self._chr_rom = bytes(chr_data)
        self._chr_1k_count = max(len(self._chr_rom) // 0x0400, 1)
        self._prg0 = 0
        self._prg1 = 1
        self._prg_mode = 0
        self._chr_regs = list(range(8))

    def _read_prg(self, addr: int) -> int:
        second_last = max(len(self._prg_banks) - 2, 0)
        if addr < 0xA000:
            bank = second_last if self._prg_mode else self._prg0
            return self._prg_banks[bank % len(self._prg_banks)][addr - 0x8000]
        if addr < 0xC000:
            return self._prg_banks[self._prg1 % len(self._prg_banks)][addr - 0xA000]
        if addr < 0xE000:
            bank = self._prg0 if self._prg_mode else second_last
            return self._prg_banks[bank % len(self._prg_banks)][addr - 0xC000]
        return self._prg_banks[-1][addr - 0xE000]

    def __setitem__(self, addr: int, value: int) -> None:
        if addr >= 0x8000:
            self._write_mapper_register(addr, value & 0xFF)
            return
        super().__setitem__(addr, value)

    def _write_mapper_register(self, addr: int, value: int) -> None:
        reg = addr & 0xF007
        if 0x8000 <= reg <= 0x8007:
            self._prg0 = value & 0x1F
            return
        if 0x9000 <= reg <= 0x9007:
            self._prg_mode = (value >> 1) & 0x01
            return
        if 0xA000 <= reg <= 0xA007:
            self._prg1 = value & 0x1F
            return
        if 0xB000 <= reg <= 0xB007:
            self._chr_regs[reg & 0x07] = value
            self.chr_bank = self._dominant_chr_8k_bank()

    def _mapped_chr_pattern_table(self) -> bytes:
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
        self._prg0 = 0
        self._prg1 = 1
        self._prg_mode = 0
        self._chr_regs = list(range(8))


class Taito33Memory(NROMMemory):
    """Mapper-33 Taito TC0190 memory.

    CPU $8000/$A000 are switchable 8 KiB PRG banks and $C000/$E000 are fixed
    to the last two banks. CHR has two 2 KiB windows at `$0000/$0800` and four
    1 KiB windows at `$1000-$1FFF`. IRQ and alternate mapper-48 behavior are
    intentionally outside this mapper-33 sprite snapshot path.
    """

    def __init__(self, prg: bytes, chr_data: bytes) -> None:
        if len(prg) % 0x2000 != 0 or len(prg) < 0x8000:
            raise ValueError("Mapper 33 PRG must contain at least four 8 KiB banks")
        initial = prg[:0x4000] + prg[-0x4000:]
        super().__init__(initial)
        if not chr_data:
            raise ValueError("Mapper 33 requires CHR-ROM data")
        self._prg_banks = [prg[i : i + 0x2000] for i in range(0, len(prg), 0x2000)]
        self._chr_rom = bytes(chr_data)
        self._chr_1k_count = max(len(self._chr_rom) // 0x0400, 1)
        self._prg0 = 0
        self._prg1 = 1
        self._chr2k_regs = [0, 2]
        self._chr1k_regs = [4, 5, 6, 7]

    def _read_prg(self, addr: int) -> int:
        if addr < 0xA000:
            return self._prg_banks[self._prg0 % len(self._prg_banks)][addr - 0x8000]
        if addr < 0xC000:
            return self._prg_banks[self._prg1 % len(self._prg_banks)][addr - 0xA000]
        if addr < 0xE000:
            return self._prg_banks[-2][addr - 0xC000]
        return self._prg_banks[-1][addr - 0xE000]

    def __setitem__(self, addr: int, value: int) -> None:
        if 0x8000 <= addr <= 0xBFFF:
            self._write_mapper_register(addr, value & 0xFF)
            return
        if addr >= 0x8000:
            return
        super().__setitem__(addr, value)

    def _write_mapper_register(self, addr: int, value: int) -> None:
        reg = addr & 0xA003
        if reg == 0x8000:
            self._prg0 = value & 0x3F
        elif reg == 0x8001:
            self._prg1 = value & 0x3F
        elif reg == 0x8002:
            self._chr2k_regs[0] = value
            self.chr_bank = self._dominant_chr_8k_bank()
        elif reg == 0x8003:
            self._chr2k_regs[1] = value
            self.chr_bank = self._dominant_chr_8k_bank()
        elif 0xA000 <= reg <= 0xA003:
            self._chr1k_regs[reg & 0x03] = value
            self.chr_bank = self._dominant_chr_8k_bank()

    def _mapped_chr_pattern_table(self) -> bytes:
        out = bytearray(0x2000)
        for slot, reg in enumerate(self._chr2k_regs):
            bank = reg % max(self._chr_1k_count // 2, 1)
            start = bank * 0x0800
            out[slot * 0x0800 : (slot + 1) * 0x0800] = self._chr_rom[start : start + 0x0800]
        for slot, reg in enumerate(self._chr1k_regs):
            bank = reg % self._chr_1k_count
            start = bank * 0x0400
            dst = 0x1000 + slot * 0x0400
            out[dst : dst + 0x0400] = self._chr_rom[start : start + 0x0400]
        return bytes(out)

    def _dominant_chr_8k_bank(self) -> int:
        if self._chr_1k_count < 8:
            return 0
        return ((self._chr2k_regs[0] * 2) % self._chr_1k_count) // 8

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
        self._prg0 = 0
        self._prg1 = 1
        self._chr2k_regs = [0, 2]
        self._chr1k_regs = [4, 5, 6, 7]


class CPROMMemory(NROMMemory):
    """Mapper-13 CPROM memory.

    PRG is fixed like NROM. PPU $0000-$0FFF maps fixed CHR-RAM page 0 and
    PPU $1000-$1FFF maps one of four 4 KiB CHR-RAM pages selected by writes to
    $8000-$FFFF.
    """

    def __init__(self, prg: bytes) -> None:
        super().__init__(prg)
        self._chr_ram_4k = [bytearray(0x1000) for _ in range(4)]
        self._chr_ram_bank = 0

    def __setitem__(self, addr: int, value: int) -> None:
        if addr >= 0x8000:
            self._chr_ram_bank = value & 0x03
            self.chr_bank = self._chr_ram_bank
            return
        super().__setitem__(addr, value)

    def _write_ppu_data(self, value: int) -> None:
        addr = self._ppu_addr & 0x3FFF
        if 0x0000 <= addr <= 0x0FFF:
            self._chr_ram_4k[0][addr] = value & 0xFF
        elif 0x1000 <= addr <= 0x1FFF:
            self._chr_ram_4k[self._chr_ram_bank][addr - 0x1000] = value & 0xFF
        else:
            super()._write_ppu_data(value)
            return
        increment = 32 if (self.ppuctrl & 0x04) else 1
        self._ppu_addr = (self._ppu_addr + increment) & 0x7FFF

    def ppu_snapshot(self) -> PpuSnapshot:
        snap = super().ppu_snapshot()
        pattern_table = bytes(self._chr_ram_4k[0] + self._chr_ram_4k[self._chr_ram_bank])
        return PpuSnapshot(
            ppuctrl=snap.ppuctrl,
            ppumask=snap.ppumask,
            palette_ram=snap.palette_ram,
            oam=snap.oam,
            pattern_table=pattern_table,
            chr_bank=self._chr_ram_bank,
        )

    def reset_state(self) -> None:
        super().reset_state()
        for bank in self._chr_ram_4k:
            bank[:] = b"\x00" * 0x1000
        self._chr_ram_bank = 0


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


class Bandai70Memory(UxROMMemory):
    """Mapper-70 Bandai memory.

    $8000-$BFFF is a switchable 16 KiB PRG bank and $C000-$FFFF is fixed to the
    last PRG bank. Writes to $8000-$FFFF use PPPP CCCC: bits 4-7 select PRG and
    bits 0-3 select the active 8 KiB CHR-ROM bank.
    """

    def __init__(self, prg: bytes, chr_banks: int) -> None:
        super().__init__(prg)
        if chr_banks <= 0:
            raise ValueError("Mapper 70 requires at least one CHR bank")
        self._chr_bank_count = chr_banks

    def __setitem__(self, addr: int, value: int) -> None:
        if addr >= 0x8000:
            self._switch_bank = ((value >> 4) & 0x0F) % len(self._banks)
            self.chr_bank = (value & 0x0F) % self._chr_bank_count
            return
        super().__setitem__(addr, value)

    def reset_state(self) -> None:
        super().reset_state()
        self.chr_bank = 0


class HolyDiverMemory(UxROMMemory):
    """Mapper-78 Holy Diver / Cosmo Carrier memory.

    $8000-$BFFF is a switchable 16 KiB PRG bank and $C000-$FFFF is fixed to the
    last bank. Writes to $8000-$FFFF use bits 0-2 for PRG and bits 4-7 for the
    8 KiB CHR-ROM bank. Mirroring bit 3 is not relevant to sprite extraction.
    """

    def __init__(self, prg: bytes, chr_banks: int) -> None:
        super().__init__(prg)
        if chr_banks <= 0:
            raise ValueError("Mapper 78 requires at least one CHR bank")
        self._chr_bank_count = chr_banks

    def __setitem__(self, addr: int, value: int) -> None:
        if addr >= 0x8000:
            self._switch_bank = (value & 0x07) % len(self._banks)
            self.chr_bank = ((value >> 4) & 0x0F) % self._chr_bank_count
            return
        super().__setitem__(addr, value)

    def reset_state(self) -> None:
        super().reset_state()
        self.chr_bank = 0


class JF17Memory(UxROMMemory):
    """Mapper-72 Jaleco JF-17 memory.

    $8000-$BFFF is a switchable 16 KiB PRG bank and $C000-$FFFF is fixed to the
    last PRG bank. Writes to $8000-$FFFF use command bits in the written value:
    bit 7 rising selects the PRG bank from bits 0-3, and bit 6 rising selects
    the 8 KiB CHR-ROM bank from bits 0-3.
    """

    def __init__(self, prg: bytes, chr_banks: int) -> None:
        super().__init__(prg)
        if chr_banks <= 0:
            raise ValueError("Mapper 72 requires at least one CHR bank")
        self._chr_bank_count = chr_banks
        self._last_command_bits = 0

    def __setitem__(self, addr: int, value: int) -> None:
        if addr >= 0x8000:
            command = value & 0xC0
            bank = value & 0x0F
            if (command & 0x80) and not (self._last_command_bits & 0x80):
                self._switch_bank = bank % len(self._banks)
            if (command & 0x40) and not (self._last_command_bits & 0x40):
                self.chr_bank = bank % self._chr_bank_count
            self._last_command_bits = command
            return
        super().__setitem__(addr, value)

    def reset_state(self) -> None:
        super().reset_state()
        self._last_command_bits = 0
        self.chr_bank = 0


class J87Memory(NROMMemory):
    """Mapper-87 J87 memory.

    PRG is fixed like NROM. Writes to $6000-$7FFF select an 8 KiB CHR-ROM bank
    with swapped low/high bits: register bit 0 is CHR bit 1 and register bit 1
    is CHR bit 0.
    """

    def __init__(self, prg: bytes, chr_banks: int) -> None:
        super().__init__(prg)
        if chr_banks <= 0:
            raise ValueError("J87 requires at least one CHR bank")
        self._chr_bank_count = chr_banks

    def __setitem__(self, addr: int, value: int) -> None:
        if 0x6000 <= addr <= 0x7FFF:
            v = value & 0x03
            self.chr_bank = (((v & 0x01) << 1) | ((v & 0x02) >> 1)) % self._chr_bank_count
            return
        super().__setitem__(addr, value)


class JF10Memory(NROMMemory):
    """Mapper-101 JF-10 memory.

    Mapper 101 describes a dump variant of the same J87 family, but the
    CHR-ROM bank bits at $6000-$7FFF are in normal order.
    """

    def __init__(self, prg: bytes, chr_banks: int) -> None:
        super().__init__(prg)
        if chr_banks <= 0:
            raise ValueError("JF-10 requires at least one CHR bank")
        self._chr_bank_count = chr_banks

    def __setitem__(self, addr: int, value: int) -> None:
        if 0x6000 <= addr <= 0x7FFF:
            self.chr_bank = (value & 0xFF) % self._chr_bank_count
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


class Namco108Memory(MMC3Memory):
    """Mapper-206 Namco 108/109/118/MIMIC-1 memory.

    This is MMC3-like for the sprite capture path but without PRG/CHR mode
    control bits. The last two 8 KiB PRG banks stay fixed and the CHR layout is
    always two 2 KiB banks at $0000-$0FFF plus four 1 KiB banks at
    $1000-$1FFF.
    """

    def _write_mapper_register(self, addr: int, value: int) -> None:
        if 0x8000 <= addr <= 0x9FFF:
            if addr & 1:
                self._regs[self._bank_select & 0x07] = value
                self.chr_bank = self._dominant_chr_8k_bank()
            else:
                self._bank_select = value & 0x07


class RAMBO1Memory(NROMMemory):
    """Mapper-64 Tengen RAMBO-1 memory for runtime sprite capture.

    RAMBO-1 is MMC3-like but adds a third switchable PRG register, optional
    full 1 KiB CHR banking for the paired 2 KiB windows, and CHR A12 inversion.
    IRQ and mirroring are outside this sprite snapshot path.
    """

    def __init__(self, prg: bytes, chr_data: bytes) -> None:
        if len(prg) % 0x2000 != 0 or len(prg) < 0x8000:
            raise ValueError("RAMBO-1 PRG must contain at least four 8 KiB banks")
        initial = prg[:0x6000] + prg[-0x2000:]
        super().__init__(initial)
        self._prg_banks = [prg[i : i + 0x2000] for i in range(0, len(prg), 0x2000)]
        self._chr_rom = bytes(chr_data)
        self._chr_1k_count = max(len(self._chr_rom) // 0x0400, 1)
        self._bank_select = 0
        second_last = max(len(self._prg_banks) - 2, 0)
        self._regs = [0, 2, 4, 5, 6, 7, 0, 1, 1, 3, 0, 0, 0, 0, 0, second_last]

    def _read_prg(self, addr: int) -> int:
        prg_mode = bool(self._bank_select & 0x40)
        r6 = self._regs[6] % len(self._prg_banks)
        r7 = self._regs[7] % len(self._prg_banks)
        rf = self._regs[0x0F] % len(self._prg_banks)
        if addr < 0xA000:
            bank = rf if prg_mode else r6
            return self._prg_banks[bank][addr - 0x8000]
        if addr < 0xC000:
            return self._prg_banks[r7][addr - 0xA000]
        if addr < 0xE000:
            bank = r6 if prg_mode else rf
            return self._prg_banks[bank][addr - 0xC000]
        return self._prg_banks[-1][addr - 0xE000]

    def __setitem__(self, addr: int, value: int) -> None:
        if 0x8000 <= addr <= 0xFFFF:
            self._write_mapper_register(addr, value & 0xFF)
            return
        super().__setitem__(addr, value)

    def _write_mapper_register(self, addr: int, value: int) -> None:
        if 0x8000 <= addr <= 0x9FFF:
            if addr & 1:
                reg = self._bank_select & 0x0F
                self._regs[reg] = value
                self.chr_bank = self._dominant_chr_8k_bank()
            else:
                self._bank_select = value
                self.chr_bank = self._dominant_chr_8k_bank()
            return
        # $A000/$C000/$E000 pairs control mirroring and IRQs. They are not
        # needed to snapshot sprite palette/OAM/CHR state.

    def _chr_reg_for_slot(self, slot: int) -> int:
        chr_inversion = bool(self._bank_select & 0x80)
        full_1k = bool(self._bank_select & 0x20)
        if chr_inversion:
            register_by_slot = [2, 3, 4, 5, 0, 8 if full_1k else 0, 1, 9 if full_1k else 1]
        else:
            register_by_slot = [0, 8 if full_1k else 0, 1, 9 if full_1k else 1, 2, 3, 4, 5]
        return register_by_slot[slot]

    def _chr_bank_1k_for_slot(self, slot: int) -> int:
        reg = self._chr_reg_for_slot(slot)
        bank = self._regs[reg]
        if reg in (0, 1) and not (self._bank_select & 0x20):
            bank = (bank & 0xFE) + (slot & 1)
        return bank % self._chr_1k_count

    def _mapped_chr_pattern_table(self) -> bytes:
        if not self._chr_rom:
            return bytes(self._pattern_table)
        out = bytearray(0x2000)
        for slot in range(8):
            bank = self._chr_bank_1k_for_slot(slot)
            start = bank * 0x0400
            out[slot * 0x0400 : (slot + 1) * 0x0400] = self._chr_rom[start : start + 0x0400]
        return bytes(out)

    def _dominant_chr_8k_bank(self) -> int:
        if self._chr_1k_count < 8:
            return 0
        return self._chr_bank_1k_for_slot(0) // 8

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
        second_last = max(len(self._prg_banks) - 2, 0)
        self._bank_select = 0
        self._regs = [0, 2, 4, 5, 6, 7, 0, 1, 1, 3, 0, 0, 0, 0, 0, second_last]


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
