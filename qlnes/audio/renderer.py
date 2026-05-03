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
from ..io.errors import QlnesError
from ..oracle import FceuxOracle
from ..rom import Rom
from .engine import SoundEngine, SoundEngineRegistry

# Force FT engine registration at import time. New engines (Capcom in A.4,
# generic in A.5) add their own import here.
from .engines import famitracker  # noqa: F401
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
    if fmt != "wav":
        raise QlnesError(
            "bad_format_arg",
            f"--format {fmt!r} not yet supported in this story; use --format wav",
            hint="MP3 lands in story A.2; NSF in C.1.",
            extra={"format": fmt},
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

    paths: list[Path] = []
    for song in songs:
        target = output_dir / deterministic_track_filename(
            rom_path.stem,
            song.index,
            engine.name,
            fmt,
        )
        if target.exists() and not force:
            raise QlnesError(
                "cant_create",
                f"cannot write {target}: file exists (use --force to overwrite)",
                extra={"path": str(target), "cause": "exists"},
            )
        pcm = engine.render_song(rom, song, oracle, frames=frames)
        write_wav(target, pcm.samples, pcm.sample_rate)
        paths.append(target)

    return RenderResult(
        output_paths=paths,
        engine_name=engine.name,
        tier=engine.tier,
        rom_stem=rom_path.stem,
    )


def supported_formats() -> tuple[str, ...]:
    """Currently supported output formats. Grows in A.2 (mp3) and C.1 (nsf)."""
    return ("wav",)


def list_engines() -> list[type[SoundEngine]]:
    """Public for `--debug` introspection."""
    return list(SoundEngineRegistry._engines)
