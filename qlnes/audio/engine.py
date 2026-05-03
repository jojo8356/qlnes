"""SoundEngine plugin contract + registry.

Each per-engine handler subclasses `SoundEngine`, registers itself via
`@SoundEngineRegistry.register`, and implements four methods:

  - detect(rom)           → DetectionResult (confidence-scored hint)
  - walk_song_table(rom)  → list[SongEntry] (one per song in the ROM)
  - render_song(rom, ...) → PcmStream (int16 LE PCM)
  - detect_loop(...)      → LoopBoundary | None (A.3 onward)

Architecture step 9. Generic tier-2 fallback ships in A.5 — until then,
unrecognized engines raise `unsupported_mapper` from the registry's detect().
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar, Literal

if TYPE_CHECKING:
    from ..oracle import FceuxOracle
    from ..rom import Rom


@dataclass(frozen=True)
class DetectionResult:
    confidence: float  # 0.0 .. 1.0
    evidence: list[str] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class SongEntry:
    index: int
    label: str | None = None
    referenced: bool = True
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class LoopBoundary:
    start_sample: int
    end_sample: int


@dataclass
class PcmStream:
    """int16 LE samples + sample-rate. Single-channel mono."""

    samples: bytes
    sample_rate: int = 44_100
    loop: LoopBoundary | None = None

    @property
    def n_samples(self) -> int:
        return len(self.samples) // 2

    @property
    def duration_seconds(self) -> float:
        return self.n_samples / self.sample_rate


class SoundEngine(abc.ABC):
    """Base class for per-engine song-table walkers + renderers."""

    name: ClassVar[str]
    tier: ClassVar[Literal[1, 2]]
    target_mappers: ClassVar[frozenset[int]]  # empty frozenset = "any"

    @abc.abstractmethod
    def detect(self, rom: Rom) -> DetectionResult:
        """Return confidence that this engine matches the ROM."""

    @abc.abstractmethod
    def walk_song_table(self, rom: Rom) -> list[SongEntry]:
        """Enumerate songs the engine knows how to render."""

    @abc.abstractmethod
    def render_song(
        self,
        rom: Rom,
        song: SongEntry,
        oracle: FceuxOracle,
        *,
        frames: int = 600,
    ) -> PcmStream:
        """Render `song` as a PcmStream."""

    @abc.abstractmethod
    def detect_loop(self, song: SongEntry, pcm: PcmStream) -> LoopBoundary | None:
        """Return loop boundaries (engine-bytecode tier). A.3 implements per-engine logic."""


class SoundEngineRegistry:
    """Class-level registry. Engines register via the @register decorator."""

    _engines: ClassVar[list[type[SoundEngine]]] = []

    @classmethod
    def register(cls, engine: type[SoundEngine]) -> type[SoundEngine]:
        cls._engines.append(engine)
        return engine

    @classmethod
    def detect(
        cls,
        rom: Rom,
        *,
        threshold: float = 0.6,
    ) -> tuple[SoundEngine, DetectionResult]:
        """Pick the highest-confidence registered engine; raise if none qualify.

        A.5 will replace this raise with a fall-through to a generic tier-2
        engine that always wins. For A.1 we fail loudly: the user-visible
        outcome of an unrecognized ROM is `unsupported_mapper` exit 100.
        """
        from ..io.errors import QlnesError

        candidates: list[tuple[SoundEngine, DetectionResult]] = []
        for engine_cls in cls._engines:
            if engine_cls.target_mappers and rom.mapper not in engine_cls.target_mappers:
                continue
            inst = engine_cls()
            r = inst.detect(rom)
            if r.confidence >= threshold:
                candidates.append((inst, r))
        if not candidates:
            raise QlnesError(
                "unsupported_mapper",
                f"no recognized audio engine for mapper {rom.mapper}",
                extra={"mapper": rom.mapper, "artifact": "audio"},
            )
        # Highest confidence wins; ties broken by registration order.
        return max(candidates, key=lambda ir: ir[1].confidence)

    @classmethod
    def list_registered(cls) -> list[str]:
        return [e.name for e in cls._engines]

    @classmethod
    def clear(cls) -> None:
        """Test-only: reset registry between tests that import handlers."""
        cls._engines.clear()
