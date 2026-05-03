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
    if output is None:
        output = rom.parent / "STACK.md"

    if not quiet:
        typer.echo(f"→ lecture de {rom}")
    rom_obj = Rom.from_file(rom)
    profile = RomProfile.from_rom(rom_obj)
    if not quiet:
        typer.echo(f"→ ROM : mapper={rom_obj.mapper}  PRG={rom_obj.num_prg_banks} bank(s)")
        typer.echo("→ analyse statique (QL6502 + heuristiques)…")
    profile.analyze_static()

    if not no_dynamic and _have_cynes() and rom_obj.mapper in (0,):
        if not quiet:
            typer.echo("→ discovery dynamique (cynes)…")
        try:
            profile.analyze_dynamic(rom)
        except Exception as e:
            typer.echo(f"  ! discovery dynamique ignorée : {e}", err=True)
    elif not quiet:
        if no_dynamic:
            typer.echo("→ discovery dynamique : désactivée (--no-dynamic)")
        elif not _have_cynes():
            typer.echo("→ discovery dynamique : ignorée (cynes non installé)")
        else:
            typer.echo(f"→ discovery dynamique : ignorée (mapper {rom_obj.mapper})")

    assets_dir = _resolve_assets_dir(rom, assets)
    if assets_dir is not None:
        if not quiet:
            typer.echo(f"→ extraction des assets dans {assets_dir}…")
        manifest = profile.extract_assets(assets_dir)
        if not quiet:
            for row in manifest.to_rows():
                typer.echo(f"  {row}")

    profile.write_markdown(output)
    if not quiet:
        typer.echo(f"✓ STACK.md écrit : {output}")

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
                if not quiet:
                    typer.echo(
                        f"✓ ASM annoté écrit : {bank_path} (bank {i}/{len(profile.bank_asms) - 1})"
                    )
        else:
            asm.write_text(profile.annotated_asm + chr_block, encoding="utf-8")
            if not quiet:
                typer.echo(f"✓ ASM annoté écrit : {asm}")

    if verify:
        if not quiet:
            typer.echo("→ vérification round-trip…")
        diff = profile.verify_round_trip()
        if diff.equal:
            typer.echo(f"✓ round-trip identique : {diff.summary()}")
        else:
            typer.echo(f"✗ round-trip différent : {diff.summary()}", err=True)
        if diff.notes:
            for n in diff.notes:
                typer.echo(f"  · {n}")


@app.command()
def recompile(
    rom: Annotated[Path, typer.Argument(help="ROM source à recompiler", exists=True)],
    output: Annotated[
        Path, typer.Option("-o", "--output", help="Chemin de sortie pour la ROM recompilée")
    ],
    quiet: Annotated[bool, typer.Option("-q", "--quiet")] = False,
) -> None:
    """Re-assemble la ROM depuis le désassemblage annoté."""
    rom_obj = Rom.from_file(rom)
    profile = RomProfile.from_rom(rom_obj).analyze_static()
    if not quiet:
        typer.echo(f"→ recompilation de {rom} …")
    profile.recompile(output)
    if not quiet:
        typer.echo(f"✓ ROM recompilée écrite : {output}")


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
        typer.echo(f"✓ {diff.summary()}")
        raise typer.Exit(0)
    typer.echo(f"✗ {diff.summary()}", err=True)
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
) -> None:
    """Rend l'audio de la ROM via FCEUX trace + APU emulator → WAV par-piste.

    Pipeline : ROM → SoundEngine.detect → walk_song_table → FCEUX trace →
    APU replay → WAV atomique.

    Exit codes (UX §6.2) : 0 success, 64 usage, 65 bad ROM, 66 missing input,
    70 internal, 73 cant_create, 100 unsupported_mapper, 130 SIGINT.
    """
    from .audio.renderer import render_rom_audio_v2
    from .config import ConfigLoader
    from .io.errors import QlnesError, emit
    from .io.preflight import Preflight

    use_color = (color == "always") or (color == "auto" and sys.stderr.isatty())

    try:
        cfg = ConfigLoader().resolve(
            "audio",
            cli_overrides={"format": fmt, "frames": frames},
        )
        resolved_fmt = cfg.get("format", "wav")
        resolved_frames = cfg.get("frames", 600)

        pf = Preflight()
        pf.add("rom_readable", lambda: _check_rom_readable(rom))
        pf.add("output_writable", lambda: _check_output_writable(output))
        pf.add("fceux_on_path", _check_fceux_on_path)
        pf.run()

        if not quiet:
            typer.echo(f"→ capture APU via fceux ({resolved_frames} frames)…", err=True)
        result = render_rom_audio_v2(
            rom,
            output,
            fmt=resolved_fmt,
            frames=resolved_frames,
            force=force,
        )
        if not quiet:
            for p in result.output_paths:
                typer.echo(f"✓ {p}", err=True)
            typer.echo(
                f"✓ {len(result.output_paths)} {resolved_fmt.upper()} "
                f"écrit(s)  (moteur={result.engine_name}, tier={result.tier})",
                err=True,
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
    from .nsf import write_nsf

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
    if not quiet:
        typer.echo(
            f"✓ NSF écrit : {output}  "
            f"(load=${build.load_addr:04X}, init=${build.init_addr:04X}, "
            f"play=${build.play_addr:04X})"
        )
        if build.note:
            typer.echo(build.note)


def main(argv: list[str] | None = None) -> int:
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
        typer.echo(f"erreur : {e}", err=True)
        return 2
    except Exception as e:
        if type(e).__name__ in ("UsageError", "BadParameter", "MissingParameter"):
            typer.echo(str(e), err=True)
            return 2
        raise


if __name__ == "__main__":
    sys.exit(main())
