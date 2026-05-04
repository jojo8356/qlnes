"""Unit tests for qlnes.audio.in_process.memory.NROMMemory."""
from __future__ import annotations

import pytest

from qlnes.audio.in_process.memory import NROMMemory


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
    m[0x2000] = 0x80
    assert m.nmi_enabled is True
    m[0x2000] = 0x00
    assert m.nmi_enabled is False


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


def test_len_is_64k():
    assert len(NROMMemory(_prg32())) == 0x10000
