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

from ..det import deterministic_track_filename
from ..io.atomic import atomic_write_bytes
from ..io.errors import QlnesError, warn
from ..oracle import FceuxOracle
from ..rom import Rom
from .engine import SoundEngine, SoundEngineRegistry

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


def render_rom_audio_v2(
    rom_path: Path | str,
    output_dir: Path | str,
    *,
    fmt: str = "wav",
    frames: int = 600,
    force: bool = False,
    oracle: FceuxOracle | None = None,
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
      oracle: optional FceuxOracle (mostly for test injection); defaults to a
        fresh FceuxOracle().

    Raises:
      QlnesError("missing_input")     — rom_path missing
      QlnesError("bad_format_arg")    — unsupported fmt
      QlnesError("cant_create")       — output exists and not --force
      QlnesError("unsupported_mapper")— no engine matches
      QlnesError("internal_error")    — fceux subprocess errors propagate
    """
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

    rom = Rom.from_file(rom_path)
    engine, _detection = SoundEngineRegistry.detect(rom)
    songs = engine.walk_song_table(rom)
    if not songs:
        raise QlnesError(
            "internal_error",
            f"engine {engine.name!r} returned no songs",
            extra={"engine": engine.name},
        )

    if oracle is None:
        oracle = FceuxOracle()

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

    written: list[Path] = []
    try:
        for song, target in zip(songs, targets, strict=True):
            pcm = engine.render_song(rom, song, oracle, frames=frames)
            # A.3: engine may attach a LoopBoundary; pass it through to the WAV
            # writer for `smpl`-chunk emission. detect_loop is opt-in per engine.
            loop = engine.detect_loop(song, pcm) or pcm.loop
            if fmt == "wav":
                write_wav(target, pcm.samples, pcm.sample_rate, loop=loop)
            elif fmt == "mp3":
                # MP3 has no equivalent of `smpl` — loop info is dropped (LAME
                # doesn't surface a loop frame format). Loop-aware MP3 is
                # downstream-tooling territory.
                mp3_bytes = Mp3Encoder().encode(pcm.samples)
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
    )


def supported_formats() -> tuple[str, ...]:
    """Currently supported output formats. NSF lands in C.1."""
    return ("wav", "mp3")


def list_engines() -> list[type[SoundEngine]]:
    """Public for `--debug` introspection."""
    return list(SoundEngineRegistry._engines)
