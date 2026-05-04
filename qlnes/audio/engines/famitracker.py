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
    InProcessUnavailable,
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
        prg = rom.prg if hasattr(rom, "prg") else b""
        if not prg:
            prg = rom.raw

        # 1. ASCII signature scan. Most FT-authored homebrew compiled with
        # FamiTone does NOT embed the literal "FamiTracker" string, so this
        # only catches a subset (notably the FT export tool's debug builds).
        for sig in _FT_SIGNATURES:
            if sig in prg:
                evidence.append(f"signature:{sig.decode('ascii')}")
                confidence += 0.5
                break

        # 2. Mapper match (target_mappers already pre-filters at registry level
        # but we still record the evidence for debugging).
        if rom.mapper in self.target_mappers:
            evidence.append(f"mapper:{rom.mapper}")
            confidence += 0.2

        # 3. Heuristic: count static APU register writes in PRG. Pattern is
        # 6502 STA absolute = `0x8D <lo> <hi>` where <hi>=0x40 and <lo> ∈
        # 0x00..0x17. A real sound engine emits dozens of these; a non-audio
        # ROM has zero or a handful (e.g., $4014 OAMDMA, $4016/$4017 joypad
        # reads — those are STA too but to specific addrs).
        # We exclude the joypad/OAMDMA addresses to avoid false positives
        # from games that don't have a sound engine but poll the controllers.
        non_audio_apu_lo = {0x14, 0x16, 0x17}  # OAMDMA, JOY1, FRAME_CNT/JOY2
        n_apu_writes = 0
        i = 0
        while i < len(prg) - 2:
            if prg[i] == 0x8D and prg[i + 2] == 0x40:
                lo = prg[i + 1]
                if 0x00 <= lo <= 0x17 and lo not in non_audio_apu_lo:
                    n_apu_writes += 1
                i += 3
            else:
                i += 1
        if n_apu_writes >= 30:
            evidence.append(f"apu_writes_static:{n_apu_writes}")
            confidence += 0.5
        elif n_apu_writes >= 15:
            evidence.append(f"apu_writes_static:{n_apu_writes}")
            confidence += 0.4
        elif n_apu_writes >= 5:
            evidence.append(f"apu_writes_static:{n_apu_writes}")
            confidence += 0.2

        return DetectionResult(
            confidence=min(confidence, 1.0),
            evidence=evidence,
            metadata={"apu_writes_static": n_apu_writes},
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

    def init_addr(self, rom: Rom, song: SongEntry) -> int:
        """In-process init = the ROM's reset vector ($FFFC-$FFFD).

        For self-running FT homebrew (Alter Ego, Shiru's stack, most of
        the v0.5 FT corpus), the reset handler runs the entire game
        init including audio init. F.7 corpus expansion may surface
        ROMs where this heuristic doesn't hold; the right place to
        widen the heuristic is here, behind a per-ROM-fingerprint
        table or a static signature scan for FamiTone entry symbols.

        Mapper-1+ ROMs raise `InProcessUnavailable` — bank-switching
        breaks the mapper-0 vector-read trick, and F.5 falls back to
        the oracle path. F.8 will land MMC1/MMC3 support.
        """
        if rom.mapper not in (0, None):
            raise InProcessUnavailable(self.name)
        return _read_le16_at_cpu(rom, 0xFFFC)

    def play_addr(self, rom: Rom, song: SongEntry) -> int:
        """In-process play = the ROM's NMI vector ($FFFA-$FFFB).

        The NMI handler is what runs at 60 Hz on real hardware, and for
        FT-driven ROMs it is what calls FamiTone's play routine.

        Mapper-1+ ROMs raise `InProcessUnavailable` (see init_addr).
        """
        if rom.mapper not in (0, None):
            raise InProcessUnavailable(self.name)
        return _read_le16_at_cpu(rom, 0xFFFA)

    def detect_loop(self, song: SongEntry, pcm: PcmStream) -> LoopBoundary | None:
        # A.3 implements FT `Bxx` opcode parsing. A.1 returns no loop boundary.
        return None


def _read_le16_at_cpu(rom: Rom, cpu_addr: int) -> int:
    """Read a little-endian uint16 from CPU address `cpu_addr` (mapper 0).

    NROM PRG maps to $8000-$FFFF. 32 KB PRG occupies the full 32 KB;
    16 KB PRG mirrors at $8000 and $C000. cpu_addr must lie in
    [0x8000, 0xFFFF].
    """
    if not 0x8000 <= cpu_addr <= 0xFFFE:
        raise ValueError(
            f"cpu_addr {cpu_addr:#x} out of NROM PRG range "
            f"$8000-$FFFE (need 2 bytes)"
        )
    prg = rom.prg if rom.header is not None else rom.raw
    if len(prg) == 0x4000:
        # NROM-128: 16 KB PRG mirrored. Both $8xxx and $Cxxx map to same offset.
        offset = (cpu_addr - 0x8000) & 0x3FFF
    elif len(prg) == 0x8000:
        offset = cpu_addr - 0x8000
    else:
        raise ValueError(f"NROM PRG must be 16 or 32 KB; got {len(prg)} bytes")
    lo = prg[offset]
    hi = prg[offset + 1]
    return lo | (hi << 8)
