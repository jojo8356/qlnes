"""FamiTracker engine handler tests.

Detection runs on synthetic PRG bytes (no fixture ROM needed).
walk_song_table tests the A.1 simplification (returns 1 song).
render_song uses a fake oracle to avoid spawning fceux.
"""

from __future__ import annotations

import pytest

from qlnes.audio.engine import SongEntry
from qlnes.audio.engines.famitracker import FamiTrackerEngine
from qlnes.oracle.fceux import ApuTrace, TraceEvent


class _FakeRom:
    def __init__(
        self,
        mapper: int = 0,
        prg: bytes = b"\x00" * 0x4000,
        *,
        path=None,
    ) -> None:
        self.mapper = mapper
        self.raw = prg
        self.prg = prg
        self.path = path


class _FakeOracle:
    def __init__(self, trace: ApuTrace) -> None:
        self._trace = trace
        self.trace_calls: list[tuple] = []

    def trace(self, rom_path, frames=600):
        self.trace_calls.append((rom_path, frames))
        return self._trace


# ---- detect ---------------------------------------------------------


def test_detect_with_famitracker_signature_high_confidence():
    prg = b"FILLER" + b"FamiTracker v0.4.6" + b"FILLER"
    eng = FamiTrackerEngine()
    r = eng.detect(_FakeRom(mapper=0, prg=prg))
    assert r.confidence >= 0.5
    assert any("signature:FamiTracker" in e for e in r.evidence)


def test_detect_with_0cc_signature():
    prg = b"foo" + b"0CC-FamiTracker" + b"bar"
    eng = FamiTrackerEngine()
    r = eng.detect(_FakeRom(mapper=0, prg=prg))
    assert r.confidence >= 0.5
    assert any("0CC-FamiTracker" in e for e in r.evidence)


def test_detect_with_famitone_signature():
    prg = b"hello FamiTone end"
    eng = FamiTrackerEngine()
    r = eng.detect(_FakeRom(mapper=0, prg=prg))
    assert r.confidence >= 0.5
    assert any("FamiTone" in e for e in r.evidence)


def test_detect_no_signature_low_confidence():
    eng = FamiTrackerEngine()
    r = eng.detect(_FakeRom(mapper=0, prg=b"\x00" * 1000))
    # Mapper match alone gives 0.2; below the 0.6 threshold.
    assert r.confidence < 0.6


def test_detect_records_mapper_evidence():
    eng = FamiTrackerEngine()
    r = eng.detect(_FakeRom(mapper=4, prg=b"FamiTracker"))
    assert any("mapper:4" in e for e in r.evidence)


def test_detect_confidence_clamped_to_1():
    eng = FamiTrackerEngine()
    # All signatures + mapper evidence shouldn't exceed 1.0.
    r = eng.detect(_FakeRom(mapper=0, prg=b"FamiTracker0CC-FamiTrackerFamiTone"))
    assert r.confidence <= 1.0


# ---- walk_song_table -----------------------------------------------


def test_walk_song_table_a1_returns_single_song():
    """A.1 simplification: one ROM = one song. A.4 will replace this."""
    eng = FamiTrackerEngine()
    songs = eng.walk_song_table(_FakeRom(mapper=0))
    assert len(songs) == 1
    assert songs[0].index == 0
    assert songs[0].referenced is True


# ---- render_song ---------------------------------------------------


def test_render_song_requires_rom_path():
    eng = FamiTrackerEngine()
    rom = _FakeRom(mapper=0, path=None)
    oracle = _FakeOracle(ApuTrace())
    with pytest.raises(ValueError, match=r"Rom\.from_file"):
        eng.render_song(rom, SongEntry(index=0), oracle)


def test_render_song_calls_oracle_trace_with_path_and_frames(tmp_path):
    eng = FamiTrackerEngine()
    rom_path = tmp_path / "fake.nes"
    rom_path.write_bytes(b"\x00")
    rom = _FakeRom(mapper=0, path=rom_path)
    oracle = _FakeOracle(ApuTrace(events=[], end_cycle=0))
    eng.render_song(rom, SongEntry(index=0), oracle, frames=300)
    assert oracle.trace_calls == [(rom_path, 300)]


def test_render_song_returns_pcm_with_44100_rate(tmp_path):
    eng = FamiTrackerEngine()
    rom_path = tmp_path / "fake.nes"
    rom_path.write_bytes(b"\x00")
    rom = _FakeRom(mapper=0, path=rom_path)
    oracle = _FakeOracle(ApuTrace(events=[], end_cycle=0))
    pcm = eng.render_song(rom, SongEntry(index=0), oracle, frames=60)
    assert pcm.sample_rate == 44_100
    assert pcm.loop is None
    # 1 second at 60 frames NTSC ≈ 44100 samples.
    assert abs(pcm.n_samples - 44_100) < 100


def test_render_song_replays_register_writes(tmp_path):
    """A real APU write should produce non-silent PCM."""
    eng = FamiTrackerEngine()
    rom_path = tmp_path / "fake.nes"
    rom_path.write_bytes(b"\x00")
    rom = _FakeRom(mapper=0, path=rom_path)
    # Configure pulse1 + enable, then render 60 frames.
    events = [
        TraceEvent(frame=0, cycle=0, addr=0x4015, value=0x01),
        TraceEvent(frame=0, cycle=1, addr=0x4000, value=0xBF),
        TraceEvent(frame=0, cycle=2, addr=0x4002, value=0xFD),
        TraceEvent(frame=0, cycle=3, addr=0x4003, value=0x00),
    ]
    oracle = _FakeOracle(ApuTrace(events=events, end_cycle=3))
    pcm = eng.render_song(rom, SongEntry(index=0), oracle, frames=60)
    samples = [
        int.from_bytes(pcm.samples[i : i + 2], "little", signed=True)
        for i in range(0, len(pcm.samples), 2)
    ]
    # Audio should vary (pulse wave produces alternating amplitudes).
    assert len(set(samples)) > 1


def test_render_song_two_calls_byte_identical(tmp_path):
    """Determinism — same trace → same PCM."""
    eng = FamiTrackerEngine()
    rom_path = tmp_path / "fake.nes"
    rom_path.write_bytes(b"\x00")
    rom = _FakeRom(mapper=0, path=rom_path)
    events = [
        TraceEvent(0, 0, 0x4015, 0x01),
        TraceEvent(0, 1, 0x4000, 0xBF),
        TraceEvent(0, 2, 0x4002, 0xFD),
        TraceEvent(0, 3, 0x4003, 0x00),
    ]

    def run() -> bytes:
        oracle = _FakeOracle(ApuTrace(events=events, end_cycle=3))
        return eng.render_song(rom, SongEntry(index=0), oracle, frames=30).samples

    assert run() == run()


# ---- detect_loop ---------------------------------------------------


def test_detect_loop_returns_none_in_a1():
    """A.3 implements loop detection. A.1 returns None."""
    from qlnes.audio.engine import PcmStream

    eng = FamiTrackerEngine()
    assert eng.detect_loop(SongEntry(index=0), PcmStream(samples=b"\x00\x00")) is None


# ---- registry integration -------------------------------------------


def test_famitracker_is_registered():
    """Importing the module triggers @register; verify it landed."""
    from qlnes.audio.engine import SoundEngineRegistry

    assert "famitracker" in SoundEngineRegistry.list_registered()
