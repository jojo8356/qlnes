"""SoundEngine ABC + registry tests."""

import pytest

from qlnes.audio.engine import (
    DetectionResult,
    LoopBoundary,
    PcmStream,
    SongEntry,
    SoundEngine,
    SoundEngineRegistry,
)
from qlnes.io.errors import QlnesError


class _FakeRom:
    """Minimal Rom-shaped object for registry tests."""

    def __init__(self, mapper: int, prg: bytes = b"") -> None:
        self.mapper = mapper
        self.raw = prg
        self.prg = prg
        self.path = None


def test_pcm_stream_n_samples_and_duration():
    s = PcmStream(samples=b"\x00" * 88200, sample_rate=44100)
    assert s.n_samples == 44100
    assert s.duration_seconds == pytest.approx(1.0)


def test_pcm_stream_default_sample_rate():
    s = PcmStream(samples=b"\x00\x00")
    assert s.sample_rate == 44_100


def test_pcm_stream_loop_default_none():
    s = PcmStream(samples=b"")
    assert s.loop is None


def test_song_entry_defaults():
    e = SongEntry(index=0)
    assert e.label is None
    assert e.referenced is True
    assert e.metadata == {}


def test_loop_boundary_is_immutable():
    lb = LoopBoundary(start_sample=10, end_sample=20)
    with pytest.raises(Exception):  # noqa: B017 — frozen dataclass
        lb.start_sample = 5  # type: ignore[misc]


def test_detection_result_defaults():
    r = DetectionResult(confidence=0.5)
    assert r.evidence == []
    assert r.metadata == {}


# ---- registry --------------------------------------------------------


@pytest.fixture
def isolated_registry():
    """Save and restore the registry around tests that mutate it."""
    saved = list(SoundEngineRegistry._engines)
    SoundEngineRegistry._engines.clear()
    try:
        yield
    finally:
        SoundEngineRegistry._engines.clear()
        SoundEngineRegistry._engines.extend(saved)


def test_registry_register_and_list(isolated_registry):
    @SoundEngineRegistry.register
    class _E(SoundEngine):
        name = "fake"
        tier = 1
        target_mappers = frozenset()

        def detect(self, rom):
            return DetectionResult(0.0)

        def walk_song_table(self, rom):
            return []

        def render_song(self, rom, song, oracle, *, frames=600):
            return PcmStream(samples=b"")

        def detect_loop(self, song, pcm):
            return None

    assert "fake" in SoundEngineRegistry.list_registered()


def test_registry_detect_no_match_raises_unsupported_mapper(isolated_registry):
    @SoundEngineRegistry.register
    class _E(SoundEngine):
        name = "low_conf"
        tier = 1
        target_mappers = frozenset()

        def detect(self, rom):
            return DetectionResult(0.1)  # below threshold

        def walk_song_table(self, rom):
            return []

        def render_song(self, rom, song, oracle, *, frames=600):
            return PcmStream(samples=b"")

        def detect_loop(self, song, pcm):
            return None

    with pytest.raises(QlnesError) as exc:
        SoundEngineRegistry.detect(_FakeRom(mapper=0))
    assert exc.value.cls == "unsupported_mapper"
    assert exc.value.extra["mapper"] == 0
    assert exc.value.extra["artifact"] == "audio"


def test_registry_detect_picks_highest_confidence(isolated_registry):
    @SoundEngineRegistry.register
    class _A(SoundEngine):
        name = "a"
        tier = 1
        target_mappers = frozenset()

        def detect(self, rom):
            return DetectionResult(0.7, evidence=["a"])

        def walk_song_table(self, rom):
            return []

        def render_song(self, rom, song, oracle, *, frames=600):
            return PcmStream(samples=b"")

        def detect_loop(self, song, pcm):
            return None

    @SoundEngineRegistry.register
    class _B(SoundEngine):
        name = "b"
        tier = 1
        target_mappers = frozenset()

        def detect(self, rom):
            return DetectionResult(0.9, evidence=["b"])

        def walk_song_table(self, rom):
            return []

        def render_song(self, rom, song, oracle, *, frames=600):
            return PcmStream(samples=b"")

        def detect_loop(self, song, pcm):
            return None

    engine, result = SoundEngineRegistry.detect(_FakeRom(mapper=0))
    assert engine.name == "b"
    assert result.confidence == 0.9


def test_registry_detect_target_mappers_filter(isolated_registry):
    @SoundEngineRegistry.register
    class _OnlyMapper4(SoundEngine):
        name = "m4"
        tier = 1
        target_mappers = frozenset({4})

        def detect(self, rom):
            return DetectionResult(0.99)  # would win if not filtered

        def walk_song_table(self, rom):
            return []

        def render_song(self, rom, song, oracle, *, frames=600):
            return PcmStream(samples=b"")

        def detect_loop(self, song, pcm):
            return None

    with pytest.raises(QlnesError):
        SoundEngineRegistry.detect(_FakeRom(mapper=0))


def test_registry_detect_threshold_excludes_low_confidence(isolated_registry):
    @SoundEngineRegistry.register
    class _Low(SoundEngine):
        name = "low"
        tier = 1
        target_mappers = frozenset()

        def detect(self, rom):
            return DetectionResult(0.5)

        def walk_song_table(self, rom):
            return []

        def render_song(self, rom, song, oracle, *, frames=600):
            return PcmStream(samples=b"")

        def detect_loop(self, song, pcm):
            return None

    with pytest.raises(QlnesError):
        SoundEngineRegistry.detect(_FakeRom(mapper=0), threshold=0.6)


def test_registry_clear(isolated_registry):
    @SoundEngineRegistry.register
    class _X(SoundEngine):
        name = "x"
        tier = 1
        target_mappers = frozenset()

        def detect(self, rom):
            return DetectionResult(0.0)

        def walk_song_table(self, rom):
            return []

        def render_song(self, rom, song, oracle, *, frames=600):
            return PcmStream(samples=b"")

        def detect_loop(self, song, pcm):
            return None

    assert len(SoundEngineRegistry._engines) == 1
    SoundEngineRegistry.clear()
    assert SoundEngineRegistry._engines == []
