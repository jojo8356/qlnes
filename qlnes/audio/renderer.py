"""Audio rendering pipeline — ROM → engine → APU → WAV file(s).

End-to-end orchestration for `qlnes audio rom.nes --format wav --output dir/`.
This is the function `cli.py::audio` will call (phase 7.5).

Pipeline:
    1. Load Rom (caller passes a Path).
    2. SoundEngineRegistry.detect → engine + DetectionResult.
    3. engine.walk_song_table → list[SongEntry].
    4. For each song:
         oracle.trace(rom.path, frames) → ApuTrace
         engine.render_song(rom, song, oracle, frames) → PcmStream
         compose deterministic filename via det.deterministic_track_filename
         pre-flight: refuse-to-overwrite unless force
         atomic write WAV to output_dir/<filename>
    5. Return RenderResult with the list of paths.

Caller is expected to wrap the call in a try/except QlnesError → emit() block
(see qlnes/cli.py phase 7.5).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..det import deterministic_track_filename
from ..io.atomic import atomic_write_bytes
from ..io.errors import QlnesError, warn
from ..oracle import FceuxOracle
from ..rom import Rom
from .engine import (
    InProcessUnavailable,
    PcmStream,
    SongEntry,
    SoundEngine,
    SoundEngineRegistry,
)


EngineMode = Literal["auto", "in-process", "oracle"]
ENGINE_MODE_VALUES: tuple[str, ...] = ("auto", "in-process", "oracle")

# Force FT engine registration at import time. New engines (Capcom in A.4,
# generic in A.5) add their own import here.
from .engines import famitracker  # noqa: F401
from .mp3 import EXPECTED_VERSION as _LAMEENC_EXPECTED
from .mp3 import INSTALLED_VERSION as _LAMEENC_INSTALLED
from .mp3 import Mp3Encoder
from .mp3 import is_pinned_version as _lameenc_is_pinned
from .wav import write_wav


@dataclass
class RenderResult:
    output_paths: list[Path]
    engine_name: str
    tier: int
    rom_stem: str
    # F.5 AC8: which path actually produced the WAVs in this run.
    # `"in-process"` for the v0.6 in-process pipeline, `"oracle"` for
    # the v0.5 FCEUX path (kept for compat). Read by F.6 bilan v2.
    engine_mode_used: Literal["in-process", "oracle"] = "in-process"


def render_rom_audio_v2(
    rom_path: Path | str,
    output_dir: Path | str,
    *,
    fmt: str = "wav",
    frames: int = 600,
    force: bool = False,
    oracle: FceuxOracle | None = None,
    engine_mode: EngineMode = "auto",
) -> RenderResult:
    """Render every detected song from `rom_path` into `output_dir/`.

    Args:
      rom_path: path to a .nes file (caller's responsibility — the renderer
        does not download or fetch).
      output_dir: directory to write per-song files into. Created if missing.
      fmt: output format. A.1 supports "wav" only; "mp3" lands in A.2,
        "nsf" in C.1.
      frames: NTSC frame count to capture (60 = 1 s).
      force: if True, overwrite existing per-song files. Default refuses.
      oracle: optional FceuxOracle (mostly for test injection); used only
        on the oracle path. Constructed lazily.
      engine_mode: which extraction pipeline to use (story F.5).
        - `"auto"` (default): try in-process; on `InProcessUnavailable`
          fall back to oracle with a `warning: in_process_low_confidence`.
        - `"in-process"`: force the v0.6 in-process pipeline; raise
          `QlnesError("in_process_unavailable")` if the engine doesn't
          support it.
        - `"oracle"`: force the v0.5 FCEUX path. Emits
          `warning: oracle_path_deprecated`.

    Raises:
      QlnesError("missing_input")            — rom_path missing
      QlnesError("bad_format_arg")           — unsupported fmt
      QlnesError("usage_error")              — bad engine_mode
      QlnesError("cant_create")              — output exists and not --force
      QlnesError("unsupported_mapper")       — no engine matches
      QlnesError("in_process_unavailable")   — F.5: --engine-mode in-process
                                                on an engine without
                                                init_addr/play_addr
      QlnesError("internal_error")           — fceux subprocess errors propagate
    """
    if engine_mode not in ENGINE_MODE_VALUES:
        raise QlnesError(
            "usage_error",
            f"--engine-mode {engine_mode!r} not recognized; "
            f"valid: {', '.join(ENGINE_MODE_VALUES)}",
            extra={"engine_mode": engine_mode, "valid": list(ENGINE_MODE_VALUES)},
        )
    rom_path = Path(rom_path)
    output_dir = Path(output_dir)
    if not rom_path.exists():
        raise QlnesError(
            "missing_input",
            f"ROM not found: {rom_path}",
            extra={"path": str(rom_path)},
        )
    if fmt not in supported_formats():
        raise QlnesError(
            "bad_format_arg",
            f"--format {fmt!r} not supported; valid: {', '.join(supported_formats())}",
            hint="NSF lands in story C.1.",
            extra={"format": fmt},
        )

    if fmt == "mp3":
        # Pre-flight the encoder dep (Mp3Encoder() raises internal_error if
        # lameenc is missing). We instantiate eagerly so the error surfaces
        # before any fceux subprocess is spawned.
        Mp3Encoder()
        # M-1 (readiness pass-2): version drift warning. Fires only when the
        # installed lameenc is outside the 1.8.x range we benchmarked.
        if _LAMEENC_INSTALLED is not None and not _lameenc_is_pinned():
            warn(
                "mp3_encoder_version",
                f"lameenc {_LAMEENC_INSTALLED} is outside the verified {_LAMEENC_EXPECTED} range; "
                "MP3 byte-determinism is not guaranteed for this run",
                hint=f"Pin lameenc to a {_LAMEENC_EXPECTED} version for byte-equivalent MP3.",
                extra={"installed": _LAMEENC_INSTALLED, "expected": _LAMEENC_EXPECTED},
            )

    if engine_mode == "oracle":
        # AC6: signal that the oracle path is on the deprecation runway.
        # Suppressed by `--no-hints` (see io/errors.py::warn).
        warn(
            "oracle_path_deprecated",
            "--engine-mode oracle is kept for v0.5 compatibility; "
            "v0.6's default is in-process (FCEUX-free).",
            hint="Drop the flag to switch, or use --engine-mode auto for graceful fallback.",
            extra={"recommended": "--engine-mode auto"},
        )

    rom = Rom.from_file(rom_path)
    engine, _detection = SoundEngineRegistry.detect(rom)
    songs = engine.walk_song_table(rom)
    if not songs:
        raise QlnesError(
            "internal_error",
            f"engine {engine.name!r} returned no songs",
            extra={"engine": engine.name},
        )

    output_dir.mkdir(parents=True, exist_ok=True)

    # Pre-compute every target path so we can:
    #   1. Pre-flight refuse-overwrite up-front (D.1 AC4: report first conflict
    #      before writing ANY file when N > 1 songs).
    #   2. Track written files for dir-level rollback on mid-render failure
    #      (D.1 dir-level atomicity option (b)).
    targets = [
        output_dir
        / deterministic_track_filename(
            rom_path.stem,
            song.index,
            engine.name,
            fmt,
        )
        for song in songs
    ]
    if not force:
        for t in targets:
            if t.exists():
                raise QlnesError(
                    "cant_create",
                    f"cannot write {t}: file exists (use --force to overwrite)",
                    extra={"path": str(t), "cause": "exists"},
                )

    # F.5 dispatch (architecture step 20.4). Decide the path per song:
    # a single InProcessUnavailable on song N doesn't poison earlier
    # in-process renders or later attempts. The renderer-level
    # `engine_mode_used` is a SUMMARY: "in-process" if every song
    # rendered through it; "oracle" if any song fell back. F.6's
    # bilan v2 records per-(rom, song) labels for fine grain.
    used_mode: Literal["in-process", "oracle"] = "in-process"
    written: list[Path] = []
    try:
        for song, target in zip(songs, targets, strict=True):
            stream, song_mode, oracle = _render_one(
                engine, rom, song, frames, engine_mode, oracle=oracle,
            )
            if song_mode == "oracle":
                used_mode = "oracle"
            # A.3: engine may attach a LoopBoundary; pass it through to the WAV
            # writer for `smpl`-chunk emission. detect_loop is opt-in per engine.
            loop = engine.detect_loop(song, stream) or stream.loop
            if fmt == "wav":
                write_wav(target, stream.samples, stream.sample_rate, loop=loop)
            elif fmt == "mp3":
                # MP3 has no equivalent of `smpl` — loop info is dropped (LAME
                # doesn't surface a loop frame format). Loop-aware MP3 is
                # downstream-tooling territory.
                mp3_bytes = Mp3Encoder().encode(stream.samples)
                atomic_write_bytes(target, mp3_bytes)
            written.append(target)
    except BaseException:
        # Dir-level rollback (D.1): if anything goes wrong mid-render, delete
        # the per-song files we wrote in this invocation. Pre-existing files
        # at non-`written` paths are untouched. Best-effort: a failure to
        # unlink doesn't override the original exception.
        import contextlib

        for t in written:
            with contextlib.suppress(OSError):
                t.unlink()
        raise

    paths = written

    return RenderResult(
        output_paths=paths,
        engine_name=engine.name,
        tier=engine.tier,
        rom_stem=rom_path.stem,
        engine_mode_used=used_mode,
    )


def _render_one(
    engine: SoundEngine,
    rom: Rom,
    song: SongEntry,
    frames: int,
    engine_mode: EngineMode,
    *,
    oracle: FceuxOracle | None,
) -> tuple[PcmStream, Literal["in-process", "oracle"], FceuxOracle | None]:
    """Render one song through the appropriate pipeline.

    Returns `(stream, mode_used, oracle)`. The returned `oracle` is the
    same one passed in if the in-process path won; if we hit the oracle
    path (explicit or auto-fallback) and `oracle` was `None`, a fresh
    FceuxOracle is constructed and returned so the caller can reuse it
    on subsequent songs (avoiding redundant trace-tool subprocess
    spawns within a single render invocation).
    """
    if engine_mode == "in-process":
        try:
            stream = engine.render_song_in_process(rom, song, frames=frames)
        except InProcessUnavailable as e:
            raise QlnesError(
                "in_process_unavailable",
                str(e),
                extra=dict(e.meta),
            ) from e
        return stream, "in-process", oracle

    if engine_mode == "oracle":
        if oracle is None:
            oracle = FceuxOracle()
        stream = engine.render_song(rom, song, oracle, frames=frames)
        return stream, "oracle", oracle

    # auto
    try:
        stream = engine.render_song_in_process(rom, song, frames=frames)
        return stream, "in-process", oracle
    except InProcessUnavailable as e:
        # Strip "class" from the meta passthrough so warn()'s own class
        # name (in_process_low_confidence) lands in the JSON payload.
        # `_payload(extra=...)` does base.update(extra) and would
        # otherwise clobber the discriminator.
        meta = {k: v for k, v in e.meta.items() if k != "class"}
        warn(
            "in_process_low_confidence",
            f"engine {engine.name!r} has no in-process support; falling back to oracle",
            hint="Run `qlnes coverage` to see which engines support in-process.",
            extra=meta,
        )
        if oracle is None:
            oracle = FceuxOracle()
        stream = engine.render_song(rom, song, oracle, frames=frames)
        return stream, "oracle", oracle


def supported_formats() -> tuple[str, ...]:
    """Currently supported output formats. NSF lands in C.1."""
    return ("wav", "mp3")


def list_engines() -> list[type[SoundEngine]]:
    """Public for `--debug` introspection."""
    return list(SoundEngineRegistry._engines)
