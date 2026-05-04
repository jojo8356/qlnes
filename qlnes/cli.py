"""Entry point CLI Typer-based : `python -m qlnes <rom.nes>` → STACK.md."""

import sys
from pathlib import Path
from typing import Annotated

import typer

from .profile import RomProfile
from .rom import Rom

app = typer.Typer(
    add_completion=False,
    help="Analyse une ROM NES et génère STACK.md (+ ASM annoté + assets).",
    no_args_is_help=True,
)


@app.callback()
def _root_callback() -> None:
    """Top-level Typer callback — runs before every subcommand.

    Ensures `qlnes.io.log.setup_logging` has installed our formatter
    so that every subcommand emits "qlnes: <level>: ..." consistently.
    Default level is INFO; subcommands can override via their own
    `--log-level` / `--quiet` / `--debug` flags.
    """
    from .io.log import setup_logging
    setup_logging(level="INFO", use_color=sys.stderr.isatty())


def _resolve_log_level(quiet: bool, log_level: str, color: str) -> None:
    """Reconfigure the qlnes logger from a subcommand's flags.

    Convention:
      - `--quiet` clamps to WARNING (silences the `→`/`✓` info lines).
      - `--log-level` overrides explicitly; quiet wins over level if both.
      - `--color {auto,always,never}` resolves the use_color decision.
    """
    from .io.errors import QlnesError
    from .io.log import LOG_LEVELS, setup_logging

    resolved = "WARNING" if quiet else log_level.upper()
    if resolved not in LOG_LEVELS:
        raise QlnesError(
            "usage_error",
            f"--log-level {log_level!r} not recognized; valid: {', '.join(LOG_LEVELS)}",
            extra={"log_level": log_level},
        )
    use_color = (color == "always") or (color == "auto" and sys.stderr.isatty())
    setup_logging(level=resolved, use_color=use_color)  # type: ignore[arg-type]


def _have_cynes() -> bool:
    try:
        import cynes  # noqa: F401

        return True
    except ImportError:
        return False


def _resolve_assets_dir(rom: Path, value: str | None) -> Path | None:
    if value is None:
        return None
    if value in ("auto", "default", ""):
        return rom.parent / "assets" / rom.stem
    return Path(value)


@app.command()
def analyze(
    rom: Annotated[
        Path,
        typer.Argument(
            help="Chemin vers la ROM .nes",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
        ),
    ],
    output: Annotated[
        Path | None,
        typer.Option(
            "-o", "--output", help="Fichier de sortie (défaut : STACK.md à côté de la ROM)"
        ),
    ] = None,
    asm: Annotated[
        Path | None,
        typer.Option("--asm", help="Aussi écrire le désassemblage annoté à ce chemin"),
    ] = None,
    assets: Annotated[
        str | None,
        typer.Option(
            "--assets",
            help="Extraire les assets (CHR-ROM → .chr/.asm/.png) ; "
            "valeur 'auto' = assets/<rom>/, ou chemin custom",
        ),
    ] = None,
    no_dynamic: Annotated[
        bool, typer.Option("--no-dynamic", help="Désactive la discovery dynamique (cynes)")
    ] = False,
    verify: Annotated[
        bool,
        typer.Option(
            "--verify", help="Vérifie le round-trip (recompile et compare aux bytes originaux)"
        ),
    ] = False,
    quiet: Annotated[
        bool, typer.Option("-q", "--quiet", help="N'affiche rien sauf erreurs")
    ] = False,
) -> None:
    """Analyse une ROM NES."""
    from .io.log import get_logger
    _resolve_log_level(quiet, log_level="INFO", color="auto")
    logger = get_logger(__name__)

    if output is None:
        output = rom.parent / "STACK.md"

    logger.info("→ lecture de %s", rom)
    rom_obj = Rom.from_file(rom)
    profile = RomProfile.from_rom(rom_obj)
    logger.info("→ ROM : mapper=%s  PRG=%d bank(s)", rom_obj.mapper, rom_obj.num_prg_banks)
    logger.info("→ analyse statique (QL6502 + heuristiques)…")
    profile.analyze_static()

    if not no_dynamic and _have_cynes() and rom_obj.mapper in (0,):
        logger.info("→ discovery dynamique (cynes)…")
        try:
            profile.analyze_dynamic(rom)
        except Exception as e:
            logger.warning("discovery dynamique ignorée : %s", e)
    else:
        if no_dynamic:
            logger.info("→ discovery dynamique : désactivée (--no-dynamic)")
        elif not _have_cynes():
            logger.info("→ discovery dynamique : ignorée (cynes non installé)")
        else:
            logger.info("→ discovery dynamique : ignorée (mapper %s)", rom_obj.mapper)

    assets_dir = _resolve_assets_dir(rom, assets)
    if assets_dir is not None:
        logger.info("→ extraction des assets dans %s…", assets_dir)
        manifest = profile.extract_assets(assets_dir)
        for row in manifest.to_rows():
            logger.info("  %s", row)

    profile.write_markdown(output)
    logger.info("✓ STACK.md écrit : %s", output)

    if asm is not None:
        chr_block = ""
        if assets_dir is not None and profile.assets and profile.assets.chr_raw:
            import os

            chr_rel = os.path.relpath(profile.assets.chr_raw, asm.parent)
            chr_asm_rel = (
                os.path.relpath(profile.assets.chr_asm, asm.parent)
                if profile.assets.chr_asm is not None
                else ""
            )
            chr_block = (
                "\n\n"
                "; ============================================================\n"
                "; CHR-ROM extraite vers un fichier séparé (lien réassemblable)\n"
                "; ============================================================\n"
                '.segment "CHR"\n'
                f'.incbin "{chr_rel}"\n'
                f'; ou: .include "{chr_asm_rel}"\n'
            )

        if profile.is_multi_bank:
            for i, bank_asm in enumerate(profile.bank_asms):
                content = bank_asm + (chr_block if i == 0 else "")
                bank_path = asm.with_name(f"{asm.stem}.bank{i}{asm.suffix}")
                bank_path.write_text(content, encoding="utf-8")
                logger.info(
                    "✓ ASM annoté écrit : %s (bank %d/%d)",
                    bank_path, i, len(profile.bank_asms) - 1,
                )
        else:
            asm.write_text(profile.annotated_asm + chr_block, encoding="utf-8")
            logger.info("✓ ASM annoté écrit : %s", asm)

    if verify:
        logger.info("→ vérification round-trip…")
        diff = profile.verify_round_trip()
        if diff.equal:
            logger.info("✓ round-trip identique : %s", diff.summary())
        else:
            logger.error("✗ round-trip différent : %s", diff.summary())
        if diff.notes:
            for n in diff.notes:
                logger.info("  · %s", n)


@app.command()
def recompile(
    rom: Annotated[Path, typer.Argument(help="ROM source à recompiler", exists=True)],
    output: Annotated[
        Path, typer.Option("-o", "--output", help="Chemin de sortie pour la ROM recompilée")
    ],
    quiet: Annotated[bool, typer.Option("-q", "--quiet")] = False,
) -> None:
    """Re-assemble la ROM depuis le désassemblage annoté."""
    from .io.log import get_logger
    _resolve_log_level(quiet, log_level="INFO", color="auto")
    logger = get_logger(__name__)

    rom_obj = Rom.from_file(rom)
    profile = RomProfile.from_rom(rom_obj).analyze_static()
    logger.info("→ recompilation de %s …", rom)
    profile.recompile(output)
    logger.info("✓ ROM recompilée écrite : %s", output)


@app.command()
def verify(
    original: Annotated[Path, typer.Argument(help="ROM originale", exists=True)],
    recompiled: Annotated[
        Path | None,
        typer.Argument(
            help="ROM recompilée à comparer (optionnel : recompile à la volée si absent)"
        ),
    ] = None,
    quiet: Annotated[bool, typer.Option("-q", "--quiet")] = False,
) -> None:
    """Compare deux ROM byte-pour-byte (ou round-trip si recompiled absent)."""
    from .io.log import get_logger
    _resolve_log_level(quiet, log_level="INFO", color="auto")
    logger = get_logger(__name__)

    if recompiled is None:
        rom_obj = Rom.from_file(original)
        profile = RomProfile.from_rom(rom_obj).analyze_static()
        diff = profile.verify_round_trip()
    else:
        from .recompile import compare_roms

        a = original.read_bytes()
        b = recompiled.read_bytes()
        diff = compare_roms(a, b)
    if diff.equal:
        logger.info("✓ %s", diff.summary())
        raise typer.Exit(0)
    logger.error("✗ %s", diff.summary())
    raise typer.Exit(1)


@app.command()
def audio(
    rom: Annotated[Path, typer.Argument(help="ROM .nes à rendre")],
    output: Annotated[
        Path,
        typer.Option(
            "-o",
            "--output",
            help="Dossier de sortie pour les WAV par-piste (créé si absent)",
        ),
    ],
    fmt: Annotated[
        str,
        typer.Option("--format", help="Format de sortie : wav (mp3 → A.2, nsf → C.1)"),
    ] = "wav",
    frames: Annotated[
        int,
        typer.Option("--frames", help="Durée en frames NTSC (60 fps → 600 = 10 s)"),
    ] = 600,
    force: Annotated[
        bool,
        typer.Option("--force", help="Écraser les fichiers de sortie existants"),
    ] = False,
    quiet: Annotated[bool, typer.Option("-q", "--quiet", help="Silencer les lignes info")] = False,
    no_hints: Annotated[
        bool, typer.Option("--no-hints", help="Supprime la ligne `hint:` sur erreurs/warnings")
    ] = False,
    color: Annotated[
        str, typer.Option("--color", help="Couleur ANSI : auto | always | never")
    ] = "auto",
    engine_mode: Annotated[
        str,
        typer.Option(
            "--engine-mode",
            help="Pipeline d'extraction : auto (défaut), in-process, oracle (v0.5 compat, déprécié)",
        ),
    ] = "auto",
    log_level: Annotated[
        str,
        typer.Option(
            "--log-level",
            help="Niveau de log : DEBUG, INFO (défaut), WARNING, ERROR. "
            "`--quiet` est équivalent à `--log-level WARNING`.",
        ),
    ] = "INFO",
) -> None:
    """Rend l'audio de la ROM via le pipeline in-process (par défaut) ou
    l'oracle FCEUX (legacy v0.5).

    Pipeline : ROM → SoundEngine.detect → walk_song_table →
    [in-process: InProcessRunner | oracle: FCEUX trace] → APU replay →
    WAV atomique.

    Exit codes (UX §6.2) : 0 success, 64 usage, 65 bad ROM, 66 missing input,
    70 internal, 73 cant_create, 100 unsupported_mapper / in_process_unavailable,
    130 SIGINT.
    """
    from .audio.renderer import ENGINE_MODE_VALUES, render_rom_audio_v2
    from .config import ConfigLoader
    from .io.errors import QlnesError, emit
    from .io.log import LOG_LEVELS, get_logger, setup_logging
    from .io.preflight import Preflight

    use_color = (color == "always") or (color == "auto" and sys.stderr.isatty())

    # Resolve log level: --quiet wins over --log-level (we want a quick way
    # to silence INFO without remembering the level name).
    resolved_level = "WARNING" if quiet else log_level.upper()
    if resolved_level not in LOG_LEVELS:
        raise typer.BadParameter(
            f"--log-level {log_level!r} not recognized; valid: {', '.join(LOG_LEVELS)}"
        )
    setup_logging(level=resolved_level, use_color=use_color)  # type: ignore[arg-type]
    logger = get_logger(__name__)

    try:
        if engine_mode not in ENGINE_MODE_VALUES:
            raise QlnesError(
                "usage_error",
                f"--engine-mode {engine_mode!r} not recognized; "
                f"valid: {', '.join(ENGINE_MODE_VALUES)}",
                extra={"engine_mode": engine_mode},
            )

        cfg = ConfigLoader().resolve(
            "audio",
            cli_overrides={"format": fmt, "frames": frames},
        )
        resolved_fmt = cfg.get("format", "wav")
        resolved_frames = cfg.get("frames", 600)

        pf = Preflight()
        pf.add("rom_readable", lambda: _check_rom_readable(rom))
        pf.add("output_writable", lambda: _check_output_writable(output))
        # F.5 AC5: fceux preflight is conditional. `in-process` doesn't
        # need fceux at all; `oracle` requires it; `auto` may or may
        # not (only the auto-resolver knows). For `auto` we let the
        # render proceed and `_render_one` handles the missing-fceux
        # case via FceuxOracle's own error reporting.
        if engine_mode == "oracle":
            pf.add("fceux_on_path", _check_fceux_on_path)
        pf.run()

        if engine_mode == "oracle":
            logger.info("→ capture APU via fceux (%d frames)…", resolved_frames)
        else:
            logger.info("→ rendu in-process (%d frames)…", resolved_frames)
        result = render_rom_audio_v2(
            rom,
            output,
            fmt=resolved_fmt,
            frames=resolved_frames,
            force=force,
            engine_mode=engine_mode,  # type: ignore[arg-type]
        )
        for p in result.output_paths:
            logger.info("✓ %s", p)
        logger.info(
            "✓ %d %s écrit(s)  (moteur=%s, tier=%d, mode=%s)",
            len(result.output_paths),
            resolved_fmt.upper(),
            result.engine_name,
            result.tier,
            result.engine_mode_used,
        )
    except QlnesError as e:
        emit(e, no_hints=no_hints, color=use_color)
    except KeyboardInterrupt:
        emit(QlnesError("interrupted", "interrupted"), no_hints=no_hints, color=use_color)
    except Exception as exc:
        emit(
            QlnesError(
                "internal_error",
                f"{type(exc).__name__}: {exc}",
                extra={"detail": type(exc).__name__},
            ),
            no_hints=no_hints,
            color=use_color,
        )


def _check_rom_readable(rom_path: Path) -> None:
    from .io.errors import QlnesError

    if not rom_path.exists():
        raise QlnesError(
            "missing_input",
            f"ROM not found: {rom_path}",
            extra={"path": str(rom_path), "cwd": str(Path.cwd())},
        )
    if not rom_path.is_file():
        raise QlnesError(
            "bad_rom",
            f"not a regular file: {rom_path}",
            extra={"path": str(rom_path)},
        )


def _check_output_writable(output_dir: Path) -> None:
    from .io.errors import QlnesError

    if output_dir.exists() and not output_dir.is_dir():
        raise QlnesError(
            "cant_create",
            f"output path exists and is not a directory: {output_dir}",
            extra={"path": str(output_dir), "cause": "not_a_directory"},
        )
    parent = output_dir if output_dir.exists() else output_dir.parent
    if not parent.exists():
        raise QlnesError(
            "cant_create",
            f"parent directory does not exist: {parent}",
            extra={"path": str(output_dir), "cause": "parent_missing"},
        )


def _check_fceux_on_path() -> None:
    import shutil

    from .io.errors import QlnesError

    if shutil.which("fceux") is None:
        raise QlnesError(
            "internal_error",
            "fceux binary not found on PATH",
            hint="Install fceux >= 2.6.6 (apt install fceux on Debian/Ubuntu).",
            extra={"detail": "missing_dependency", "dep": "fceux"},
        )


@app.command()
def nsf(
    rom: Annotated[Path, typer.Argument(help="ROM .nes source", exists=True)],
    output: Annotated[Path, typer.Option("-o", "--output", help="Sortie .nsf")],
    title: Annotated[str, typer.Option("--title", help="Titre du morceau")] = "",
    artist: Annotated[str, typer.Option("--artist")] = "qlnes",
    copyright_: Annotated[str, typer.Option("--copyright")] = "",
    init_addr: Annotated[
        str | None,
        typer.Option("--init", help="Adresse INIT (hex, ex: 0x8000) — défaut RESET vector"),
    ] = None,
    play_addr: Annotated[
        str | None,
        typer.Option("--play", help="Adresse PLAY (hex, ex: 0x8082) — défaut NMI vector"),
    ] = None,
    songs: Annotated[int, typer.Option("--songs", help="Nombre total de morceaux")] = 1,
    experimental: Annotated[
        bool,
        typer.Option(
            "--experimental",
            help="Pour mappers ≠ 0 : packagise la banque fixe en best-effort",
        ),
    ] = False,
    quiet: Annotated[bool, typer.Option("-q", "--quiet")] = False,
) -> None:
    """Construit un fichier NSF depuis la ROM (mapper 0 auto, autres mappers expérimental)."""
    from .io.log import get_logger
    from .nsf import write_nsf

    _resolve_log_level(quiet, log_level="INFO", color="auto")
    logger = get_logger(__name__)

    init_int = int(init_addr, 0) if init_addr else None
    play_int = int(play_addr, 0) if play_addr else None

    build = write_nsf(
        rom,
        output,
        title=title,
        artist=artist,
        copyright_=copyright_,
        init_addr=init_int,
        play_addr=play_int,
        songs=songs,
        experimental=experimental,
    )
    logger.info(
        "✓ NSF écrit : %s  (load=$%04X, init=$%04X, play=$%04X)",
        output, build.load_addr, build.init_addr, build.play_addr,
    )
    if build.note:
        logger.info("%s", build.note)


def main(argv: list[str] | None = None) -> int:
    # Ensure the qlnes logger is configured EVEN on the early-failure
    # paths below. The @app.callback() also calls setup_logging, but if
    # typer raises a UsageError on argv parsing the callback never fires.
    from .io.log import get_logger, setup_logging
    setup_logging(level="INFO", use_color=sys.stderr.isatty())
    logger = get_logger(__name__)
    try:
        app(argv, standalone_mode=False)
        return 0
    except typer.Exit as e:
        return getattr(e, "exit_code", 0) or 0
    except SystemExit as e:
        # sys.exit(int) raised by qlnes/io/errors.py::emit() lands here.
        # SystemExit exposes the code on .code (not .exit_code like typer.Exit).
        if isinstance(e.code, int):
            return e.code
        return 0 if e.code is None else 1
    except typer.Abort:
        return 1
    except FileNotFoundError as e:
        logger.error("%s", e)
        return 2
    except Exception as e:
        if type(e).__name__ in ("UsageError", "BadParameter", "MissingParameter"):
            logger.error("%s", e)
            return 2
        raise


if __name__ == "__main__":
    sys.exit(main())
