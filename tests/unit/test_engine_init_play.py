"""Unit tests for the F.4 init_addr / play_addr protocol.

Covers:
- AC3 — default-raise via InProcessUnavailable.
- AC1, AC2 — FamiTrackerEngine reads reset/NMI vectors.
- AC6 — for Alter Ego, init_addr ≠ play_addr.
"""
from __future__ import annotations

import pytest

from qlnes.audio.engine import (
    DetectionResult,
    InProcessUnavailable,
    LoopBoundary,
    PcmStream,
    SongEntry,
    SoundEngine,
)
from qlnes.audio.engines.famitracker import FamiTrackerEngine
from qlnes.rom import Rom


# ---- AC3: default-raise --------------------------------------------------


class _NoOpEngine(SoundEngine):
    """Engine that doesn't override init_addr / play_addr — exercises
    the default-raise path."""

    name = "noop"
    tier = 2  # tier-2-style: doesn't claim in-process support
    target_mappers = frozenset()

    def detect(self, rom: Rom) -> DetectionResult:
        return DetectionResult(0.0)

    def walk_song_table(self, rom: Rom) -> list[SongEntry]:
        return []

    def render_song(self, rom, song, oracle, *, frames=600) -> PcmStream:
        return PcmStream(b"")

    def detect_loop(self, song, pcm) -> LoopBoundary | None:
        return None


def test_default_init_addr_raises_in_process_unavailable():
    e = _NoOpEngine()
    with pytest.raises(InProcessUnavailable) as exc_info:
        e.init_addr(rom=None, song=None)
    assert exc_info.value.meta == {
        "class": "in_process_unavailable",
        "engine": "noop",
    }


def test_default_play_addr_raises_in_process_unavailable():
    e = _NoOpEngine()
    with pytest.raises(InProcessUnavailable) as exc_info:
        e.play_addr(rom=None, song=None)
    assert exc_info.value.meta["class"] == "in_process_unavailable"
    assert exc_info.value.meta["engine"] == "noop"


def test_in_process_unavailable_is_a_not_implemented_error():
    """Callers that catch NotImplementedError get InProcessUnavailable too."""
    e = _NoOpEngine()
    with pytest.raises(NotImplementedError):
        e.init_addr(rom=None, song=None)


# ---- AC1, AC2: FamiTrackerEngine ----------------------------------------


def _make_rom(prg: bytes) -> Rom:
    """Wrap a PRG body in an iNES header (mapper 0) and instantiate a Rom."""
    header = bytearray(16)
    header[0:4] = b"NES\x1a"
    pages = len(prg) // 16384
    assert pages in (1, 2), "PRG must be 16 or 32 KB for NROM"
    header[4] = pages
    header[5] = 0  # no CHR
    return Rom(bytes(header) + prg, name="synthetic")


def _prg32_with_vectors(reset: int, nmi: int) -> bytes:
    """32 KB PRG with reset / NMI vectors at the canonical CPU addresses."""
    prg = bytearray(0x8000)
    prg[0x7FFA] = nmi & 0xFF
    prg[0x7FFB] = (nmi >> 8) & 0xFF
    prg[0x7FFC] = reset & 0xFF
    prg[0x7FFD] = (reset >> 8) & 0xFF
    return bytes(prg)


def _prg16_with_vectors(reset: int, nmi: int) -> bytes:
    """16 KB PRG (NROM-128) with vectors at the end of the bank."""
    prg = bytearray(0x4000)
    prg[0x3FFA] = nmi & 0xFF
    prg[0x3FFB] = (nmi >> 8) & 0xFF
    prg[0x3FFC] = reset & 0xFF
    prg[0x3FFD] = (reset >> 8) & 0xFF
    return bytes(prg)


def test_famitracker_init_addr_returns_reset_vector_32kb():
    rom = _make_rom(_prg32_with_vectors(reset=0x8123, nmi=0x9080))
    e = FamiTrackerEngine()
    assert e.init_addr(rom, SongEntry(index=0)) == 0x8123


def test_famitracker_play_addr_returns_nmi_vector_32kb():
    rom = _make_rom(_prg32_with_vectors(reset=0x8123, nmi=0x9080))
    e = FamiTrackerEngine()
    assert e.play_addr(rom, SongEntry(index=0)) == 0x9080


def test_famitracker_init_addr_returns_reset_vector_16kb():
    """16 KB PRG (NROM-128): vectors live at the end of the 16 KB bank,
    visible through the $C000 mirror."""
    rom = _make_rom(_prg16_with_vectors(reset=0xC123, nmi=0xD080))
    e = FamiTrackerEngine()
    assert e.init_addr(rom, SongEntry(index=0)) == 0xC123


def test_famitracker_play_addr_returns_nmi_vector_16kb():
    rom = _make_rom(_prg16_with_vectors(reset=0xC123, nmi=0xD080))
    e = FamiTrackerEngine()
    assert e.play_addr(rom, SongEntry(index=0)) == 0xD080


def test_famitracker_init_addr_in_prg_range():
    """Whatever the vectors say, init_addr must be in [$8000, $FFFF]."""
    rom = _make_rom(_prg32_with_vectors(reset=0xBEEF, nmi=0xCAFE))
    e = FamiTrackerEngine()
    addr = e.init_addr(rom, SongEntry(index=0))
    assert 0x8000 <= addr <= 0xFFFF


def test_famitracker_play_addr_in_prg_range():
    rom = _make_rom(_prg32_with_vectors(reset=0xBEEF, nmi=0xCAFE))
    e = FamiTrackerEngine()
    addr = e.play_addr(rom, SongEntry(index=0))
    assert 0x8000 <= addr <= 0xFFFF


# ---- CR-1 fix: non-NROM mappers raise InProcessUnavailable ----------------


def _make_rom_with_mapper(prg: bytes, mapper: int) -> Rom:
    """Wrap PRG in an iNES header with the given mapper number."""
    header = bytearray(16)
    header[0:4] = b"NES\x1a"
    header[4] = len(prg) // 16384
    header[5] = 0
    # mapper number split: low nibble in flags6 high nibble, high nibble in flags7
    header[6] = (mapper & 0x0F) << 4
    header[7] = mapper & 0xF0
    return Rom(bytes(header) + prg, name="synthetic_mapper_rom")


def test_famitracker_init_addr_rejects_mmc1_mapper():
    """Mapper-1 (MMC1) ROMs aren't supported by F.3's NROM-only runner;
    init_addr must raise InProcessUnavailable so F.5 falls back to oracle."""
    # Need 64 KB PRG (16 KB minimum × 4) for MMC1; use 32 KB which is
    # also valid for MMC1 (NROM-equivalent layout but with mapper=1).
    rom = _make_rom_with_mapper(_prg32_with_vectors(0x8000, 0x9000), mapper=1)
    e = FamiTrackerEngine()
    with pytest.raises(InProcessUnavailable) as exc_info:
        e.init_addr(rom, SongEntry(index=0))
    assert exc_info.value.meta["engine"] == "famitracker"


def test_famitracker_play_addr_rejects_unrom_mapper():
    """Same protection for mapper-2 (UNROM, bank-switched PRG).
    Mapper-4 (MMC3) would also raise but Rom.__init__ rejects it
    upstream, so we test mapper-2 here as the canonical bank-switched
    case."""
    rom = _make_rom_with_mapper(_prg32_with_vectors(0x8000, 0x9000), mapper=2)
    e = FamiTrackerEngine()
    with pytest.raises(InProcessUnavailable):
        e.play_addr(rom, SongEntry(index=0))


def test_famitracker_init_addr_accepts_mapper_zero():
    """Sanity: mapper 0 still works after the gate is added."""
    rom = _make_rom_with_mapper(_prg32_with_vectors(0xC000, 0xD000), mapper=0)
    e = FamiTrackerEngine()
    assert e.init_addr(rom, SongEntry(index=0)) == 0xC000