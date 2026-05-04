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

# NTSC NES timing — used by both the legacy oracle path and the v0.6
# in-process pipeline. Promoted here from `engines/famitracker.py` so the
# `SoundEngine.render_song_in_process` default impl can reference them
# without importing engine-specific modules (story F.5).
NTSC_CPU_HZ = 1_789_773
NTSC_FRAME_RATE = 60.0988
CYCLES_PER_FRAME = NTSC_CPU_HZ / NTSC_FRAME_RATE  # ≈ 29780.5

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


class InProcessUnavailable(NotImplementedError):
    """Raised when an engine doesn't support in-process rendering (F.4).

    Subclasses NotImplementedError so callers can `except
    NotImplementedError` and stay portable; the JSON-friendly `.meta`
    attribute lets F.5's resolver build a structured warning. Not a
    QlnesError — the engine-contract miss is internal, F.5 decides
    whether to surface it as a user-visible exit code.
    """

    def __init__(self, engine_name: str) -> None:
        super().__init__(
            f"engine {engine_name!r} does not support in-process rendering"
        )
        self.meta: dict[str, str] = {
            "class": "in_process_unavailable",
            "engine": engine_name,
        }


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

    # In-process render protocol (story F.4). Engines override to opt in.
    # Default-raise lets existing tier-1/2 handlers keep loading without
    # forced overrides; F.5's resolver catches InProcessUnavailable and
    # falls back to the oracle path.

    def init_addr(self, rom: Rom, song: SongEntry) -> int:
        """CPU address ($8000-$FFFF) of the music driver's init routine.

        Subclasses override to support in-process rendering. The default
        raises InProcessUnavailable; F.5's resolver treats this as a
        signal to fall back to the oracle path.
        """
        raise InProcessUnavailable(self.name)

    def play_addr(self, rom: Rom, song: SongEntry) -> int:
        """CPU address ($8000-$FFFF) of the per-frame play routine."""
        raise InProcessUnavailable(self.name)

    def render_song_in_process(
        self, rom: Rom, song: SongEntry, *, frames: int = 600
    ) -> PcmStream:
        """Render `song` via the v0.6 in-process pipeline (F.3 + F.4 + F.5).

        Default impl: call `init_addr` and `play_addr` to get the music
        driver entry points, then either:
          - **F.5b PyPy fast path** — when running under CPython and a
            PyPy interpreter is reachable (via
            `qlnes.audio.in_process._pypy_dispatch.find_pypy`), fork the
            entire pipeline into PyPy. The child runs CPU emulation +
            ApuEmulator and streams back PCM bytes directly. ~3-4×
            end-to-end speedup on Alter Ego (the F.2 measurement of 22×
            covered just the CPU loop; ApuEmulator dominates if it
            stays on CPython, so we move both).
          - **CPython slow path** — when already on PyPy, when PyPy is
            absent, or when the ROM has no on-disk path (in-memory
            test ROMs), drive `InProcessRunner.run_song` and
            `ApuEmulator` in-process.

        Engines override only if they need engine-specific tweaks
        (none expected for v0.6). Engines that don't support
        in-process rendering inherit `init_addr`/`play_addr`'s default
        which raises `InProcessUnavailable` — F.5's renderer dispatch
        catches this and falls back to the oracle path.
        """
        init = self.init_addr(rom, song)
        play = self.play_addr(rom, song)

        pcm_bytes, sample_rate = _resolve_in_process_pcm(rom, init, play, frames)
        return PcmStream(samples=pcm_bytes, sample_rate=sample_rate, loop=None)


def _resolve_in_process_pcm(
    rom: Rom, init_addr: int, play_addr: int, frames: int
) -> tuple[bytes, int]:
    """Produce int16 LE PCM bytes for a song via the fastest available path.

    Returns `(pcm_bytes, sample_rate)`.

    F.5b: when running under CPython AND a PyPy interpreter is reachable
    AND the ROM was constructed from a file on disk, fork the whole
    render (CPU emu + ApuEmulator) into PyPy and read back PCM bytes
    over a binary protocol. Otherwise run the same pipeline in-process.

    The CPython fallback is byte-equivalent to the PyPy path (verified
    in tests) — both go through identical Python source, so the only
    runtime-observable difference is wall-clock.
    """
    import subprocess
    import sys

    on_cpython = sys.implementation.name != "pypy"
    if on_cpython and rom.path is not None:
        from ..io.errors import warn
        from .in_process._pypy_dispatch import find_pypy, render_song_via_pypy

        pypy = find_pypy()
        if pypy is not None:
            try:
                result = render_song_via_pypy(
                    pypy, rom.path, init_addr, play_addr, frames=frames
                )
                if result.sample_rate != 44_100:
                    raise ValueError(
                        f"PyPy child returned unexpected sample_rate "
                        f"{result.sample_rate}; expected 44100"
                    )
                return result.pcm, result.sample_rate
            except (subprocess.CalledProcessError,
                    subprocess.TimeoutExpired,
                    ValueError) as e:
                # PyPy was tried but the render failed cleanly. Emit a
                # warning so the user can investigate (vs the previous
                # behavior which silently degraded to slow path), then
                # fall back to in-process. Other exception types
                # (KeyboardInterrupt, OSError on missing pypy binary
                # post-find, MemoryError, etc.) propagate as bugs.
                stderr_excerpt = ""
                if isinstance(e, subprocess.CalledProcessError) and e.stderr:
                    stderr_excerpt = e.stderr.decode("utf-8", "replace")[:200]
                warn(
                    "pypy_render_failed",
                    f"PyPy subprocess render failed ({type(e).__name__}); "
                    f"falling back to CPython in-process path",
                    hint=("Check `PYPY_BIN` points at a working PyPy 3.11 "
                          "with py65 installed."),
                    extra={
                        "exception": type(e).__name__,
                        "stderr_excerpt": stderr_excerpt,
                    },
                )

    # Fall back to in-process under whichever runtime we're on.
    from ..apu import ApuEmulator
    from .in_process import InProcessRunner

    runner = InProcessRunner(rom)
    events = runner.run_song(init_addr, play_addr, frames=frames)
    emu = ApuEmulator()
    last_cycle = 0
    for ev in events:
        emu.write(ev.register, ev.value, ev.cpu_cycle)
        last_cycle = ev.cpu_cycle
    end_cycle = max(last_cycle, int(frames * CYCLES_PER_FRAME))
    return emu.render_until(cycle=end_cycle), 44_100


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
