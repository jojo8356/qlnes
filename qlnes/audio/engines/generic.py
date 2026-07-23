"""Generic tier-2 fallback for valid mapper-0 ROMs with unknown audio engines.

This handler intentionally does not claim engine understanding. It boots the
ROM naturally through the in-process runner, captures observed APU writes, and
replays them through the same APU renderer as tier-1 engines. Outputs are
therefore useful best-effort artifacts, but remain `unverified`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from ...apu import ApuEmulator
from ..engine import (
    CYCLES_PER_FRAME,
    DetectionResult,
    LoopBoundary,
    PcmStream,
    SongEntry,
    SoundEngine,
    SoundEngineRegistry,
)
from ..in_process import InProcessRunner

if TYPE_CHECKING:
    from ...oracle import FceuxOracle
    from ...rom import Rom


@SoundEngineRegistry.register
class GenericFallbackEngine(SoundEngine):
    name: ClassVar[str] = "unknown"
    tier: ClassVar = 2
    target_mappers: ClassVar[frozenset[int]] = frozenset({0})

    def detect(self, rom: Rom) -> DetectionResult:
        return DetectionResult(
            confidence=0.0,
            evidence=[f"fallback_mapper:{rom.mapper}"],
            metadata={"status": "unverified"},
        )

    def walk_song_table(self, rom: Rom) -> list[SongEntry]:
        return [
            SongEntry(
                index=0,
                label="unknown",
                referenced=True,
                metadata={"status": "unverified", "engine": self.name},
            )
        ]

    def render_song(
        self,
        rom: Rom,
        song: SongEntry,
        oracle: FceuxOracle,
        *,
        frames: int = 600,
    ) -> PcmStream:
        return self.render_song_in_process(rom, song, frames=frames)

    def render_song_in_process(self, rom: Rom, song: SongEntry, *, frames: int = 600) -> PcmStream:
        runner = InProcessRunner(rom)
        events = list(runner.run_natural_boot(frames=frames))
        emu = ApuEmulator()
        last_cycle = 0
        for ev in events:
            emu.write(ev.register, ev.value, ev.cpu_cycle)
            last_cycle = ev.cpu_cycle
        end_cycle = max(last_cycle, int(frames * CYCLES_PER_FRAME))
        return PcmStream(samples=emu.render_until(end_cycle), sample_rate=44_100)

    def detect_loop(self, song: SongEntry, pcm: PcmStream) -> LoopBoundary | None:
        return None
