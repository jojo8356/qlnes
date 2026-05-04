"""StaticWalker ABC + ApuWriteEvent tests (story F.1).

Verifies the v0.6 scaffolding contract without yet shipping any concrete
walker. Subsequent stories (F.3+) provide the FT walker.
"""

from __future__ import annotations

import pytest

from qlnes.audio.engine import (
    DetectionResult,
    PcmStream,
    SongEntry,
    SoundEngineRegistry,
)
from qlnes.audio.static import ApuWriteEvent, StaticWalker

# ---- ApuWriteEvent --------------------------------------------------


def test_apu_write_event_constructs():
    ev = ApuWriteEvent(cpu_cycle=100, register=0x4015, value=0x0F)
    assert ev.cpu_cycle == 100
    assert ev.register == 0x4015
    assert ev.value == 0x0F


def test_apu_write_event_is_frozen():
    ev = ApuWriteEvent(cpu_cycle=0, register=0x4000, value=0)
    with pytest.raises(Exception):  # noqa: B017 — frozen dataclass
        ev.cpu_cycle = 5  # type: ignore[misc]


def test_apu_write_event_register_range_validated():
    with pytest.raises(ValueError, match="register"):
        ApuWriteEvent(cpu_cycle=0, register=0x3FFF, value=0)
    with pytest.raises(ValueError, match="register"):
        ApuWriteEvent(cpu_cycle=0, register=0x4018, value=0)


def test_apu_write_event_value_range_validated():
    with pytest.raises(ValueError, match="value"):
        ApuWriteEvent(cpu_cycle=0, register=0x4000, value=256)
    with pytest.raises(ValueError, match="value"):
        ApuWriteEvent(cpu_cycle=0, register=0x4000, value=-1)


def test_apu_write_event_cycle_non_negative():
    with pytest.raises(ValueError, match="cpu_cycle"):
        ApuWriteEvent(cpu_cycle=-1, register=0x4000, value=0)


def test_apu_write_event_from_trace_event():
    """Backward-compat converter from v0.5 TraceEvent."""
    from qlnes.oracle.fceux import TraceEvent

    t = TraceEvent(frame=2, cycle=12345, addr=0x4015, value=0x0F)
    ev = ApuWriteEvent.from_trace_event(t)
    assert ev.cpu_cycle == 12345
    assert ev.register == 0x4015
    assert ev.value == 0x0F


# ---- StaticWalker ABC -----------------------------------------------


def test_static_walker_is_abstract():
    """A class that doesn't implement emit_apu_writes can't be instantiated."""
    from typing import ClassVar

    class _Incomplete(StaticWalker):
        name: ClassVar[str] = "incomplete"
        tier: ClassVar = 1
        target_mappers: ClassVar[frozenset[int]] = frozenset()

        def detect(self, rom):
            return DetectionResult(0.0)

        def walk_song_table(self, rom):
            return []

        def render_song(self, rom, song, oracle, *, frames=600):
            return PcmStream(samples=b"")

        def detect_loop(self, song, pcm):
            return None

        # MISSING: emit_apu_writes

    with pytest.raises(TypeError, match="abstract"):
        _Incomplete()


def test_static_walker_has_static_walker_flag_is_true():
    """The has_static_walker class attribute is set to True by the ABC."""
    assert StaticWalker.has_static_walker is True


def test_static_walker_subclass_can_register_and_emit():
    """End-to-end ABC contract: a complete StaticWalker subclass works."""
    from collections.abc import Iterator
    from typing import ClassVar

    saved = list(SoundEngineRegistry._engines)
    SoundEngineRegistry._engines.clear()
    try:

        @SoundEngineRegistry.register
        class _FakeWalker(StaticWalker):
            name: ClassVar[str] = "fake"
            tier: ClassVar = 1
            target_mappers: ClassVar[frozenset[int]] = frozenset()

            def detect(self, rom):
                return DetectionResult(0.99, evidence=["fake"])

            def walk_song_table(self, rom):
                return [SongEntry(index=0)]

            def render_song(self, rom, song, oracle, *, frames=600):
                return PcmStream(samples=b"")

            def detect_loop(self, song, pcm):
                return None

            def emit_apu_writes(self, rom, song, *, frames):  # type: ignore[override]
                yield ApuWriteEvent(cpu_cycle=0, register=0x4015, value=0x01)
                yield ApuWriteEvent(cpu_cycle=10, register=0x4000, value=0xBF)

        assert "fake" in SoundEngineRegistry.list_registered()
        inst = _FakeWalker()
        assert inst.has_static_walker is True
        events: Iterator[ApuWriteEvent] = inst.emit_apu_writes(
            rom=None,  # type: ignore[arg-type]
            song=SongEntry(index=0),
            frames=10,
        )
        events_list = list(events)
        assert len(events_list) == 2
        assert events_list[0].register == 0x4015
        assert events_list[1].register == 0x4000
    finally:
        SoundEngineRegistry._engines.clear()
        SoundEngineRegistry._engines.extend(saved)


def test_v05_engines_have_has_static_walker_false_by_default():
    """A v0.5 SoundEngine without StaticWalker subclass has no has_static_walker
    attribute; consumers should treat absence as 'oracle-only'."""
    from qlnes.audio.engines.famitracker import FamiTrackerEngine

    assert getattr(FamiTrackerEngine, "has_static_walker", False) is False
