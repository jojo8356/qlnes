"""Unit tests for qlnes.audio.in_process.runner.InProcessRunner.

These tests use synthetic 32 KB ROMs so they don't depend on the corpus.
The Alter Ego full-render test lives under tests/integration/.
"""
from __future__ import annotations

import pytest

from qlnes.audio.in_process import InProcessRunner
from qlnes.rom import Rom


def _make_rom_with_reset_handler(prg: bytes) -> Rom:
    """Wrap a 32 KB PRG body in an iNES header (mapper 0)."""
    header = bytearray(16)
    header[0:4] = b"NES\x1a"
    header[4] = 2  # 2 × 16 KB PRG
    header[5] = 0  # 0 × 8 KB CHR
    return Rom(bytes(header) + prg, name="synthetic")


def _bare_prg(reset_target_lo: int, reset_target_hi: int) -> bytes:
    """32 KB PRG with $FFFC vector pointing to a halt loop at $8000."""
    prg = bytearray(0x8000)
    # $8000: an infinite loop (JMP $8000)
    prg[0x0000] = 0x4C  # JMP abs
    prg[0x0001] = 0x00
    prg[0x0002] = 0x80
    # Reset vector at $FFFC-$FFFD
    prg[0x7FFC] = reset_target_lo
    prg[0x7FFD] = reset_target_hi
    # NMI vector at $FFFA-$FFFB → also $8000 for safety
    prg[0x7FFA] = 0x00
    prg[0x7FFB] = 0x80
    return bytes(prg)


def test_constructor_rejects_unknown_backend():
    rom = _make_rom_with_reset_handler(_bare_prg(0x00, 0x80))
    with pytest.raises(ValueError, match="cpu_backend"):
        InProcessRunner(rom, cpu_backend="cynes")


def test_constructor_rejects_non_nrom_mapper():
    raw = bytearray(b"NES\x1a")
    raw += bytes([2, 0, 0x10, 0])  # mapper = 1 (MMC1) via flags6 high nibble
    raw += b"\x00" * 8
    raw += b"\x00" * 0x8000
    rom = Rom(bytes(raw), name="mmc1_synth")
    with pytest.raises(ValueError, match="mapper 0 only"):
        InProcessRunner(rom)


def test_run_natural_boot_returns_iterable_of_apu_events():
    """A halt-loop ROM produces zero APU events but completes cleanly."""
    rom = _make_rom_with_reset_handler(_bare_prg(0x00, 0x80))
    runner = InProcessRunner(rom)
    events = list(runner.run_natural_boot(frames=10))
    assert events == []  # halt loop never touches APU
    assert runner.last_stats is not None
    assert runner.last_stats.apu_event_count == 0


def test_run_natural_boot_captures_apu_writes():
    """A ROM that writes to $4015 in its main loop produces APU events."""
    prg = bytearray(0x8000)
    # $8000: LDA #$0F ; STA $4015 ; JMP $8000
    prg[0x0000] = 0xA9  # LDA imm
    prg[0x0001] = 0x0F
    prg[0x0002] = 0x8D  # STA abs
    prg[0x0003] = 0x15
    prg[0x0004] = 0x40
    prg[0x0005] = 0x4C  # JMP abs $8000
    prg[0x0006] = 0x00
    prg[0x0007] = 0x80
    # Reset vector → $8000
    prg[0x7FFC] = 0x00
    prg[0x7FFD] = 0x80
    prg[0x7FFA] = 0x00
    prg[0x7FFB] = 0x80
    rom = _make_rom_with_reset_handler(bytes(prg))
    runner = InProcessRunner(rom)
    events = list(runner.run_natural_boot(frames=2))
    assert len(events) > 0
    for e in events:
        assert e.register == 0x4015
        assert e.value == 0x0F


def test_run_natural_boot_is_deterministic():
    """Two consecutive runs must produce byte-identical event lists (NFR-REL-1)."""
    prg = bytearray(0x8000)
    # Same loop as above
    prg[0x0000] = 0xA9
    prg[0x0001] = 0x0F
    prg[0x0002] = 0x8D
    prg[0x0003] = 0x15
    prg[0x0004] = 0x40
    prg[0x0005] = 0x4C
    prg[0x0006] = 0x00
    prg[0x0007] = 0x80
    prg[0x7FFC] = 0x00
    prg[0x7FFD] = 0x80
    prg[0x7FFA] = 0x00
    prg[0x7FFB] = 0x80
    rom = _make_rom_with_reset_handler(bytes(prg))

    r1 = InProcessRunner(rom)
    e1 = list(r1.run_natural_boot(frames=3))
    r2 = InProcessRunner(rom)
    e2 = list(r2.run_natural_boot(frames=3))
    assert e1 == e2


def test_run_song_unimplemented_play_addr_does_not_crash():
    """run_song accepts the play_addr parameter for the architecture contract.

    F.4 wires play_addr through trigger_nmi_to. Smoke-check that an
    init that RTSes early (before INIT_BUDGET_CYCLES) lands the
    sentinel-trap and proceeds to phase 2 cleanly.
    """
    prg = bytearray(0x8000)
    # init_addr=$8000: LDA #$01 ; STA $4015 ; RTS
    prg[0x0000] = 0xA9
    prg[0x0001] = 0x01
    prg[0x0002] = 0x8D
    prg[0x0003] = 0x15
    prg[0x0004] = 0x40
    prg[0x0005] = 0x60  # RTS
    prg[0x7FFC] = 0x00
    prg[0x7FFD] = 0x80
    prg[0x7FFA] = 0x00
    prg[0x7FFB] = 0x80
    rom = _make_rom_with_reset_handler(bytes(prg))
    runner = InProcessRunner(rom)
    events = list(runner.run_song(init_addr=0x8000, play_addr=0x8000, frames=2))
    # init runs, captures one APU write; phase 2 fires NMIs to play_addr
    # which keeps writing $4015 every frame
    assert len(events) >= 1
    assert events[0].register == 0x4015


def test_run_song_back_to_back_on_same_runner_is_deterministic():
    """CR-3: run_song resets MPU state at entry, so calling it twice on
    the same runner produces identical traces (init+phase 2 same SP,
    PC, regs, processorCycles=0)."""
    prg = bytearray(0x8000)
    # Same RTS-init ROM as above
    prg[0x0000] = 0xA9
    prg[0x0001] = 0x01
    prg[0x0002] = 0x8D
    prg[0x0003] = 0x15
    prg[0x0004] = 0x40
    prg[0x0005] = 0x60
    prg[0x7FFC] = 0x00
    prg[0x7FFD] = 0x80
    prg[0x7FFA] = 0x00
    prg[0x7FFB] = 0x80
    rom = _make_rom_with_reset_handler(bytes(prg))
    runner = InProcessRunner(rom)
    e1 = list(runner.run_song(0x8000, 0x8000, frames=3))
    e2 = list(runner.run_song(0x8000, 0x8000, frames=3))
    # Cycle stamps should match exactly because mpu.reset() puts
    # processorCycles back to 0
    assert [(e.cpu_cycle, e.register, e.value) for e in e1] == \
           [(e.cpu_cycle, e.register, e.value) for e in e2]
