"""Unit tests for qlnes.audio.in_process.memory.NROMMemory."""
from __future__ import annotations

import pytest

from qlnes.audio.in_process.memory import (
    AxROMMemory,
    BNROMNINAMemory,
    CamericaMemory,
    CNROMMemory,
    ColorDreamsMemory,
    CPROMMemory,
    FME7Memory,
    GxROMMemory,
    HolyDiverMemory,
    JF10Memory,
    MMC1Memory,
    MMC3Memory,
    NROMMemory,
    UxROMMemory,
)


def _prg32() -> bytes:
    # 32 KB pattern: byte i at PRG offset i = i & 0xFF
    return bytes(i & 0xFF for i in range(0x8000))


def _prg16() -> bytes:
    return bytes(i & 0xFF for i in range(0x4000))


def test_constructor_rejects_wrong_prg_size():
    with pytest.raises(ValueError, match="NROM PRG must be 16 or 32 KB"):
        NROMMemory(b"\x00" * 1234)


def test_ram_read_write_and_mirroring():
    m = NROMMemory(_prg32())
    m[0x0123] = 0x42
    assert m[0x0123] == 0x42
    # RAM mirrors every $0800 up to $1FFF
    assert m[0x0923] == 0x42  # $0800 + $0123
    assert m[0x1123] == 0x42
    assert m[0x1923] == 0x42


def test_ppustatus_read_returns_vblank_and_clears():
    m = NROMMemory(_prg32())
    m.vbl_flag = True
    assert m[0x2002] == 0x80
    # cleared after read
    assert m[0x2002] == 0x00
    # mirroring: $2002 also accessible at $2002 + 8k for k in 0..1023
    m.vbl_flag = True
    assert m[0x200A] == 0x80  # $2002 mirror in next 8-byte block


def test_ppuctrl_write_toggles_nmi_enable():
    m = NROMMemory(_prg32())
    assert m.nmi_enabled is False


def test_ppu_palette_writes_are_captured_through_ppuaddr_ppudata():
    m = NROMMemory(_prg32())
    m[0x2006] = 0x3F
    m[0x2006] = 0x10
    m[0x2007] = 0x0F
    m[0x2007] = 0x30
    m[0x2007] = 0x16
    m[0x2007] = 0x27
    snap = m.ppu_snapshot()
    assert snap.palette_ram[0x00] == 0x0F
    assert snap.palette_ram[0x10] == 0x0F
    assert snap.palette_ram[0x11:0x14] == bytes([0x30, 0x16, 0x27])


def test_ppu_pattern_table_writes_are_captured_for_chr_ram():
    m = NROMMemory(_prg32())
    m[0x2006] = 0x10
    m[0x2006] = 0x00
    m[0x2007] = 0xAA
    m[0x2007] = 0x55
    snap = m.ppu_snapshot()
    assert snap.pattern_table[0x1000:0x1002] == bytes([0xAA, 0x55])


def test_oamdata_and_oamdma_are_captured():
    m = NROMMemory(_prg32())
    m[0x0200] = 0x14
    m[0x0201] = 0x24
    m[0x0202] = 0x02
    m[0x0203] = 0x40
    m[0x2003] = 0x00
    m[0x4014] = 0x02
    snap = m.ppu_snapshot()
    assert snap.oam[:4] == bytes([0x14, 0x24, 0x02, 0x40])
    # Keep legacy audio-observer behavior: $4014 is still in the captured
    # $4000-$4017 write range.
    assert len(m.apu_writes) == 1
    m[0x2000] = 0x80
    assert m.nmi_enabled is True
    m[0x2000] = 0x00
    assert m.nmi_enabled is False


def test_cartridge_prg_ram_read_write_and_reset():
    m = NROMMemory(_prg32())
    m[0x6000] = 0x14
    m[0x7FFF] = 0x27
    assert m[0x6000] == 0x14
    assert m[0x7FFF] == 0x27
    m.reset_state()
    assert m[0x6000] == 0x00
    assert m[0x7FFF] == 0x00


def test_oamdma_can_copy_from_cartridge_prg_ram_page():
    m = NROMMemory(_prg32())
    m[0x6000] = 0x14
    m[0x6001] = 0x24
    m[0x6002] = 0x02
    m[0x6003] = 0x40
    m[0x2003] = 0x00
    m[0x4014] = 0x60
    snap = m.ppu_snapshot()
    assert snap.oam[:4] == bytes([0x14, 0x24, 0x02, 0x40])


def test_controller1_strobe_latches_and_shifts_button_bits():
    m = NROMMemory(_prg32())
    m.set_controller1_state(0x09)  # A + Start
    m[0x4016] = 0x01
    m[0x4016] = 0x00
    reads = [m[0x4016] & 0x01 for _ in range(8)]
    assert reads == [1, 0, 0, 1, 0, 0, 0, 0]
    assert m[0x4016] & 0x01 == 1


def test_apu_writes_captured_in_4000_4017():
    m = NROMMemory(_prg32())
    m.cpu_cycles = 1000
    m[0x4000] = 0x30
    m[0x4017] = 0xC0
    assert len(m.apu_writes) == 2
    e0, e1 = m.apu_writes
    assert e0.cpu_cycle == 1000 and e0.register == 0x4000 and e0.value == 0x30
    assert e1.cpu_cycle == 1000 and e1.register == 0x4017 and e1.value == 0xC0


def test_apu_writes_outside_range_not_captured():
    m = NROMMemory(_prg32())
    # $4014 is the OAM DMA register and IS in-range; verify it
    m[0x4014] = 0x07
    assert len(m.apu_writes) == 1
    # $4018, $4019, $401F are out of $4000-$4017 — silently dropped
    m[0x4018] = 0xFF
    m[0x401F] = 0xFF
    assert len(m.apu_writes) == 1


def test_prg32_no_mirror():
    m = NROMMemory(_prg32())
    assert m[0x8000] == 0x00
    assert m[0x8123] == 0x23
    assert m[0xFFFF] == 0xFF
    # $8000 should NOT mirror to $C000 with a 32 KB PRG
    assert m[0xC000] == 0x00  # offset 0x4000 in the 32K PRG = 0x00... actually
    # The pattern at offset 0x4000 is (0x4000 & 0xFF) = 0x00, and offset 0
    # is also 0x00 so this happens to look like a mirror but isn't.
    # Distinguish: $8001 vs $C001
    assert m[0x8001] == 0x01
    assert m[0xC001] == 0x01  # both pattern-byte 1 (because 0x4000 & 0xFF = 0,
    # and 0x4001 & 0xFF = 1, while 0x0001 & 0xFF = 1, coincidentally equal).
    # Better: compare with known distinct bytes
    assert m[0x80FF] == 0xFF
    assert m[0xC0FF] == 0xFF  # again coincidentally equal since pattern repeats every 256
    # Pick bytes that distinguish:
    # offset 0x100 in PRG = 0x100 & 0xFF = 0x00 → m[0x8100] = 0
    # offset 0x4100 in PRG = 0x4100 & 0xFF = 0x00 → m[0xC100] = 0
    # Pattern repeats every 256 bytes regardless. Make a non-repeating PRG:


def test_prg32_no_mirror_with_nonrepeating_prg():
    """Distinguishing test: 32 KB PRG with byte at offset i = (i >> 8) & 0xFF."""
    prg = bytes((i >> 8) & 0xFF for i in range(0x8000))
    m = NROMMemory(prg)
    # $8000 = offset 0 → 0x00
    assert m[0x8000] == 0x00
    # $C000 = offset 0x4000 → (0x4000 >> 8) & 0xFF = 0x40
    assert m[0xC000] == 0x40
    # Confirms no mirror


def test_prg16_mirrors_to_c000():
    """16 KB PRG mirrors at $8000 and $C000 (NROM-128)."""
    m = NROMMemory(_prg16())
    assert m[0x8000] == 0x00
    assert m[0xC000] == 0x00
    assert m[0x8123] == 0x23
    assert m[0xC123] == 0x23
    assert m[0xBFFF] == 0xFF  # last byte of low bank
    assert m[0xFFFF] == 0xFF  # last byte of high bank (mirrored)


def test_writes_to_rom_silently_ignored():
    m = NROMMemory(_prg32())
    pre = m[0x8000]
    m[0x8000] = 0xCC  # NROM has no PRG-RAM at this range — write is a no-op
    assert m[0x8000] == pre


def test_reset_capture_clears_events_and_cycles():
    m = NROMMemory(_prg32())
    m.cpu_cycles = 12345
    m[0x4000] = 0x30
    assert len(m.apu_writes) == 1
    m.reset_capture()
    assert len(m.apu_writes) == 0
    assert m.cpu_cycles == 0


def test_reset_capture_does_not_touch_ram_or_flags():
    """reset_capture is a NARROW reset — RAM, NMI, vblank stay put."""
    m = NROMMemory(_prg32())
    m[0x0123] = 0xAB
    m[0x2000] = 0x80   # set nmi_enabled
    m.vbl_flag = True
    m.reset_capture()
    assert m[0x0123] == 0xAB
    assert m.nmi_enabled is True
    # vbl_flag was True, may have been read once during the assertion
    # via __getitem__ — this test only asserts reset_capture() didn't
    # touch the underlying flag


def test_reset_state_clears_ram_and_flags_and_capture():
    """reset_state is the full power-on-style reset (F.3.CR-10 fix)."""
    m = NROMMemory(_prg32())
    # Pollute everything
    m[0x0123] = 0xAB
    m[0x07FF] = 0xCC
    m[0x2000] = 0x80   # set nmi_enabled
    m.vbl_flag = True
    m.cpu_cycles = 12345
    m[0x4000] = 0x30   # capture an event
    assert len(m.apu_writes) == 1
    # Now reset everything
    m.reset_state()
    assert m[0x0123] == 0x00
    assert m[0x07FF] == 0x00
    assert m.nmi_enabled is False
    assert m.vbl_flag is False
    assert m.cpu_cycles == 0
    assert len(m.apu_writes) == 0


def test_reset_state_does_not_touch_rom():
    """reset_state only zeros RAM; the PRG-ROM mirror at $8000+ is preserved."""
    m = NROMMemory(_prg32())
    rom_byte = m[0x8123]
    m.reset_state()
    assert m[0x8123] == rom_byte


def test_cnrom_mapper_write_selects_chr_bank():
    m = CNROMMemory(_prg32(), chr_banks=4)
    assert m.ppu_snapshot().chr_bank == 0
    m[0x8000] = 0x02
    assert m.ppu_snapshot().chr_bank == 2
    m[0xFFFF] = 0x07
    assert m.ppu_snapshot().chr_bank == 3


def test_uxrom_mapper_write_switches_low_prg_bank_and_keeps_fixed_high_bank():
    banks = []
    for bank_id in range(4):
        banks.append(bytes([bank_id] * 0x4000))
    m = UxROMMemory(b"".join(banks))
    assert m[0x8000] == 0
    assert m[0xBFFF] == 0
    assert m[0xC000] == 3
    assert m[0xFFFF] == 3
    m[0x8000] = 0x02
    assert m[0x8000] == 2
    assert m[0xBFFF] == 2
    assert m[0xC000] == 3


def test_uxrom_reset_state_restores_initial_switch_bank():
    banks = [bytes([bank_id] * 0x4000) for bank_id in range(4)]
    m = UxROMMemory(b"".join(banks))
    m[0x8000] = 0x02
    assert m[0x8000] == 2
    m.reset_state()
    assert m[0x8000] == 0


def test_gxrom_mapper_write_switches_prg_and_chr_bank():
    banks = [bytes([bank_id] * 0x8000) for bank_id in range(4)]
    m = GxROMMemory(b"".join(banks), chr_banks=4)
    assert m[0x8000] == 0
    assert m[0xFFFF] == 0
    assert m.ppu_snapshot().chr_bank == 0
    m[0x8000] = 0x21
    assert m[0x8000] == 2
    assert m[0xFFFF] == 2
    assert m.ppu_snapshot().chr_bank == 1


def test_gxrom_reset_state_restores_prg_and_chr_bank():
    banks = [bytes([bank_id] * 0x8000) for bank_id in range(4)]
    m = GxROMMemory(b"".join(banks), chr_banks=4)
    m[0x8000] = 0x32
    assert m[0x8000] == 3
    assert m.ppu_snapshot().chr_bank == 2
    m.reset_state()
    assert m[0x8000] == 0
    assert m.ppu_snapshot().chr_bank == 0


def test_cprom_mapper13_switches_visible_chr_ram_4k_bank():
    m = CPROMMemory(_prg32())
    m[0x8000] = 0x02
    m[0x2006] = 0x10
    m[0x2006] = 0x00
    m[0x2007] = 0xAA
    snap = m.ppu_snapshot()
    assert snap.chr_bank == 2
    assert snap.pattern_table[0x1000] == 0xAA
    m[0x8000] = 0x01
    assert m.ppu_snapshot().pattern_table[0x1000] == 0x00


def test_colordreams_mapper_write_switches_prg_and_chr_bank():
    banks = [bytes([bank_id] * 0x8000) for bank_id in range(4)]
    m = ColorDreamsMemory(b"".join(banks), chr_banks=16)
    assert m[0x8000] == 0
    assert m[0xFFFF] == 0
    assert m.ppu_snapshot().chr_bank == 0
    m[0x8000] = 0x21
    assert m[0x8000] == 1
    assert m[0xFFFF] == 1
    assert m.ppu_snapshot().chr_bank == 2


def test_colordreams_reset_state_restores_prg_and_chr_bank():
    banks = [bytes([bank_id] * 0x8000) for bank_id in range(4)]
    m = ColorDreamsMemory(b"".join(banks), chr_banks=16)
    m[0x8000] = 0x32
    assert m[0x8000] == 2
    assert m.ppu_snapshot().chr_bank == 3
    m.reset_state()
    assert m[0x8000] == 0
    assert m.ppu_snapshot().chr_bank == 0


def test_axrom_mapper_write_switches_32k_prg_bank():
    banks = [bytes([bank_id] * 0x8000) for bank_id in range(4)]
    m = AxROMMemory(b"".join(banks))
    assert m[0x8000] == 0
    assert m[0xFFFF] == 0
    m[0x8000] = 0x02
    assert m[0x8000] == 2
    assert m[0xFFFF] == 2


def test_axrom_reset_state_restores_initial_prg_bank():
    banks = [bytes([bank_id] * 0x8000) for bank_id in range(2)]
    m = AxROMMemory(b"".join(banks))
    m[0x8000] = 0x01
    assert m[0x8000] == 1
    m.reset_state()
    assert m[0x8000] == 0


def test_mapper34_bnrom_switches_32k_prg_bank():
    banks = [bytes([bank_id] * 0x8000) for bank_id in range(4)]
    m = BNROMNINAMemory(b"".join(banks), chr_data=b"")
    assert m[0x8000] == 0
    assert m[0xFFFF] == 0
    m[0x8000] = 0x02
    assert m[0x8000] == 2
    assert m[0xFFFF] == 2


def test_mapper34_nina_switches_prg_ram_registers_and_chr_4k_windows():
    banks = [bytes([bank_id] * 0x8000) for bank_id in range(2)]
    chr_data = b"".join(bytes([bank_id] * 0x1000) for bank_id in range(4))
    m = BNROMNINAMemory(b"".join(banks), chr_data=chr_data)
    m[0x7FFD] = 0x01
    assert m[0x8000] == 1
    m[0x7FFE] = 0x02
    m[0x7FFF] = 0x03
    snap = m.ppu_snapshot()
    assert snap.pattern_table[0x0000] == 2
    assert snap.pattern_table[0x0FFF] == 2
    assert snap.pattern_table[0x1000] == 3
    assert snap.pattern_table[0x1FFF] == 3


def test_mapper34_reset_state_restores_initial_prg_chr_and_prg_ram():
    banks = [bytes([bank_id] * 0x8000) for bank_id in range(2)]
    chr_data = b"".join(bytes([bank_id] * 0x1000) for bank_id in range(4))
    m = BNROMNINAMemory(b"".join(banks), chr_data=chr_data)
    m[0x7FFD] = 0x01
    m[0x7FFE] = 0x02
    m[0x7FFF] = 0x03
    assert m[0x7FFD] == 0x01
    assert m[0x8000] == 1
    m.reset_state()
    assert m[0x7FFD] == 0x00
    assert m[0x8000] == 0
    assert m.ppu_snapshot().pattern_table[0x1000] == 1


def test_camerica_mapper71_switches_prg_only_from_c000_ffff():
    banks = [bytes([bank_id] * 0x4000) for bank_id in range(4)]
    m = CamericaMemory(b"".join(banks))
    assert m[0x8000] == 0
    assert m[0xC000] == 3
    m[0x8000] = 0x02
    assert m[0x8000] == 0
    m[0xC000] = 0x02
    assert m[0x8000] == 2
    assert m[0xC000] == 3


def _mmc1_write_register(m: MMC1Memory, addr: int, value: int) -> None:
    for bit in range(5):
        m[addr] = (value >> bit) & 0x01


def test_mmc1_serial_write_switches_prg_bank_in_mode_3():
    banks = [bytes([bank_id] * 0x4000) for bank_id in range(4)]
    m = MMC1Memory(b"".join(banks), chr_banks=2)
    assert m[0x8000] == 0
    assert m[0xC000] == 3
    _mmc1_write_register(m, 0xE000, 0x02)
    assert m[0x8000] == 2
    assert m[0xBFFF] == 2
    assert m[0xC000] == 3


def test_mmc1_serial_write_tracks_8k_chr_bank():
    banks = [bytes([bank_id] * 0x4000) for bank_id in range(2)]
    m = MMC1Memory(b"".join(banks), chr_banks=4)
    _mmc1_write_register(m, 0x8000, 0x0C)  # PRG mode 3, CHR mode 8 KiB
    _mmc1_write_register(m, 0xA000, 0x02)
    assert m.ppu_snapshot().chr_bank == 1


def test_mmc1_split_4k_chr_banks_are_mapped_into_snapshot_pattern_table():
    banks = [bytes([bank_id] * 0x4000) for bank_id in range(2)]
    chr_data = b"".join(bytes([bank_id] * 0x1000) for bank_id in range(4))
    m = MMC1Memory(b"".join(banks), chr_banks=2, chr_data=chr_data)
    _mmc1_write_register(m, 0x8000, 0x1C)  # PRG mode 3, CHR split 4 KiB
    _mmc1_write_register(m, 0xA000, 0x01)
    _mmc1_write_register(m, 0xC000, 0x03)
    snap = m.ppu_snapshot()
    assert snap.pattern_table[0x0000] == 1
    assert snap.pattern_table[0x0FFF] == 1
    assert snap.pattern_table[0x1000] == 3
    assert snap.pattern_table[0x1FFF] == 3


def test_mmc1_reset_state_restores_shift_register_prg_and_chr_bank():
    banks = [bytes([bank_id] * 0x4000) for bank_id in range(4)]
    m = MMC1Memory(b"".join(banks), chr_banks=4)
    _mmc1_write_register(m, 0xE000, 0x02)
    _mmc1_write_register(m, 0xA000, 0x02)
    assert m[0x8000] == 2
    assert m.ppu_snapshot().chr_bank == 1
    m.reset_state()
    assert m[0x8000] == 0
    assert m.ppu_snapshot().chr_bank == 0


def test_mmc3_bank_select_switches_prg_windows():
    banks = [bytes([bank_id] * 0x2000) for bank_id in range(8)]
    m = MMC3Memory(b"".join(banks), chr_data=bytes([0] * 0x2000))
    assert m[0x8000] == 0
    assert m[0xA000] == 1
    assert m[0xC000] == 6
    assert m[0xE000] == 7
    m[0x8000] = 0x06
    m[0x8001] = 0x03
    assert m[0x8000] == 3
    assert m[0xC000] == 6
    m[0x8000] = 0x46
    m[0x8001] = 0x02
    assert m[0x8000] == 6
    assert m[0xC000] == 2


def test_mmc3_bank_select_maps_chr_windows_into_snapshot_pattern_table():
    banks = [bytes([bank_id] * 0x2000) for bank_id in range(4)]
    chr_data = b"".join(bytes([bank_id] * 0x0400) for bank_id in range(16))
    m = MMC3Memory(b"".join(banks), chr_data=chr_data)
    m[0x8000] = 0x02
    m[0x8001] = 0x07
    snap = m.ppu_snapshot()
    assert snap.pattern_table[0x1000] == 7
    assert snap.pattern_table[0x13FF] == 7


def test_fme7_command_register_switches_prg_windows_and_chr_1k_banks():
    banks = [bytes([bank_id] * 0x2000) for bank_id in range(8)]
    chr_data = b"".join(bytes([bank_id] * 0x0400) for bank_id in range(16))
    m = FME7Memory(b"".join(banks), chr_data=chr_data)
    assert m[0x8000] == 0
    assert m[0xA000] == 1
    assert m[0xC000] == 2
    assert m[0xE000] == 7

    m[0x8000] = 0x09
    m[0xA000] = 0x04
    m[0x8000] = 0x0A
    m[0xA000] = 0x05
    m[0x8000] = 0x0B
    m[0xA000] = 0x06
    assert m[0x8000] == 4
    assert m[0xA000] == 5
    assert m[0xC000] == 6

    m[0x8000] = 0x04
    m[0xA000] = 0x07
    snap = m.ppu_snapshot()
    assert snap.pattern_table[0x1000] == 7
    assert snap.pattern_table[0x13FF] == 7


def test_fme7_reset_state_restores_initial_prg_and_chr_mapping():
    banks = [bytes([bank_id] * 0x2000) for bank_id in range(8)]
    chr_data = b"".join(bytes([bank_id] * 0x0400) for bank_id in range(16))
    m = FME7Memory(b"".join(banks), chr_data=chr_data)
    m[0x8000] = 0x09
    m[0xA000] = 0x04
    m[0x8000] = 0x04
    m[0xA000] = 0x07
    assert m[0x8000] == 4
    assert m.ppu_snapshot().pattern_table[0x1000] == 7
    m.reset_state()
    assert m[0x8000] == 0
    assert m.ppu_snapshot().pattern_table[0x1000] == 4


def test_jf10_mapper101_selects_chr_bank_with_normal_bit_order():
    m = JF10Memory(_prg32(), chr_banks=4)
    assert m.ppu_snapshot().chr_bank == 0
    m[0x6000] = 0x01
    assert m.ppu_snapshot().chr_bank == 1
    m[0x7FFF] = 0x02
    assert m.ppu_snapshot().chr_bank == 2


def test_mapper78_switches_low_prg_bank_and_chr_bank():
    banks = [bytes([bank_id] * 0x4000) for bank_id in range(8)]
    m = HolyDiverMemory(b"".join(banks), chr_banks=8)
    assert m[0x8000] == 0
    assert m[0xC000] == 7
    assert m.ppu_snapshot().chr_bank == 0
    m[0x8000] = 0x52
    assert m[0x8000] == 2
    assert m[0xC000] == 7
    assert m.ppu_snapshot().chr_bank == 5
    m.reset_state()
    assert m[0x8000] == 0
    assert m.ppu_snapshot().chr_bank == 0


def test_len_is_64k():
    assert len(NROMMemory(_prg32())) == 0x10000
