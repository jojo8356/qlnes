"""FamiTracker / 0CC-FamiTracker engine handler — tier-1 sample-equivalent target.

A.1 scope. This handler ships:
  - `detect()` — real implementation, scans for canonical FT ASCII signatures
    plus mapper match. Same heuristics as `qlnes/engines.py::detect_famitone`,
    promoted to a tier-1 plugin.
  - `walk_song_table()` — A.1 simplification: returns a single SongEntry that
    represents "the whole capture window". Real per-song pointer-table walking
    lands in A.4 (FR10 — exhaustive song-table walk including unreferenced
    entries). Until then, one ROM = one WAV.
  - `render_song()` — captures the FCEUX trace via the oracle, replays the
    APU register writes through `ApuEmulator`, returns int16 LE PCM. Sample
    equivalence to FCEUX is NOT yet verified (no fixture corpus until 7.6+);
    architectural correctness IS verified by unit tests.
  - `detect_loop()` — returns None per story spec (A.3 implements the FT `Bxx`
    loop-opcode parser).

Spec: NESdev wiki — FamiTracker driver / 0CC-FamiTracker docs.
Story: A.1 §8.9.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from ...apu import ApuEmulator
from ...rom import Rom
from ..engine import (
    DetectionResult,
    LoopBoundary,
    PcmStream,
    SongEntry,
    SoundEngine,
    SoundEngineRegistry,
)

if TYPE_CHECKING:
    from ...oracle import FceuxOracle

# Default capture window matches `[audio] frames = 600` from the config schema
# (UX §4.4) — 600 NTSC frames ≈ 10 s.
DEFAULT_FRAMES = 600
NTSC_CPU_HZ = 1_789_773
NTSC_FRAME_RATE = 60.0988  # actual NTSC; close enough to 60 for our cycle math
CYCLES_PER_FRAME = NTSC_CPU_HZ / NTSC_FRAME_RATE  # ≈ 29780

# Ordered most-specific-first: 0CC-FamiTracker contains "FamiTracker" as a
# substring, so we must check the longer signature first to attribute the
# right tool name in detection evidence.
_FT_SIGNATURES: tuple[bytes, ...] = (
    b"0CC-FamiTracker",
    b"FamiTracker",
    b"FamiTone",
)


@SoundEngineRegistry.register
class FamiTrackerEngine(SoundEngine):
    name: ClassVar[str] = "famitracker"
    tier: ClassVar = 1
    # A.1 scope = mapper 0 (NROM) per the story; A.4 broadens to 1, 4, 66.
    target_mappers: ClassVar[frozenset[int]] = frozenset({0, 1, 4, 66})

    def detect(self, rom: Rom) -> DetectionResult:
        evidence: list[str] = []
        confidence = 0.0
        # 1. ASCII signature scan in PRG bytes.
        prg = rom.prg if hasattr(rom, "prg") else b""
        if not prg:
            prg = rom.raw
        for sig in _FT_SIGNATURES:
            if sig in prg:
                evidence.append(f"signature:{sig.decode('ascii')}")
                confidence += 0.5
                break
        # 2. Mapper match (target_mappers already pre-filters at registry level
        #    but we still record the evidence for debugging).
        if rom.mapper in self.target_mappers:
            evidence.append(f"mapper:{rom.mapper}")
            confidence += 0.2
        # 3. Heuristic: many APU writes per frame is a strong indicator of an
        #    active sound engine. We don't actually scan disasm here (that's
        #    expensive) — leaves room for A.4 to add stronger signals.
        return DetectionResult(
            confidence=min(confidence, 1.0),
            evidence=evidence,
            metadata={},
        )

    def walk_song_table(self, rom: Rom) -> list[SongEntry]:
        """A.1 simplification — return one song covering the whole capture.

        A.4 will replace this with a real FT pointer-table walker that:
          - locates `song_list_l` / `song_list_h` via known offsets,
          - reads each pointer pair until an end sentinel,
          - emits one SongEntry per pointer (referenced + unreferenced).
        """
        return [SongEntry(index=0, label=None, referenced=True, metadata={})]

    def render_song(
        self,
        rom: Rom,
        song: SongEntry,
        oracle: FceuxOracle,
        *,
        frames: int = DEFAULT_FRAMES,
    ) -> PcmStream:
        """Render one song by replaying the FCEUX trace through ApuEmulator."""
        if rom.path is None:
            raise ValueError(
                "rom must be constructed via Rom.from_file (oracle.trace needs the source path)"
            )
        trace = oracle.trace(rom.path, frames=frames)
        emu = ApuEmulator()
        for ev in trace.events:
            emu.write(ev.addr, ev.value, ev.cycle)
        end_cycle = max(trace.end_cycle, int(frames * CYCLES_PER_FRAME))
        pcm = emu.render_until(cycle=end_cycle)
        return PcmStream(samples=pcm, sample_rate=44_100, loop=None)

    def detect_loop(self, song: SongEntry, pcm: PcmStream) -> LoopBoundary | None:
        # A.3 implements FT `Bxx` opcode parsing. A.1 returns no loop boundary.
        return None
