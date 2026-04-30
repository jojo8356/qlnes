"""Entry point CLI Typer-based : `python -m qlnes <rom.nes>` → STACK.md."""

import sys
from pathlib import Path
from typing import Optional

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


def _resolve_assets_dir(rom: Path, value: Optional[str]) -> Optional[Path]:
    if value is None:
        return None
    if value in ("auto", "default", ""):
        return rom.parent / "assets" / rom.stem
    return Path(value)


@app.command()
def analyze(
    rom: Path = typer.Argument(
        ...,
        help="Chemin vers la ROM .nes",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
    ),
    output: Optional[Path] = typer.Option(
        None,
        "-o",
        "--output",
        help="Fichier de sortie (défaut : STACK.md à côté de la ROM)",
    ),
    asm: Optional[Path] = typer.Option(
        None,
        "--asm",
        help="Aussi écrire le désassemblage annoté à ce chemin",
    ),
    assets: Optional[str] = typer.Option(
        None,
        "--assets",
        help="Extraire les assets (CHR-ROM → .chr/.asm/.png) ; "
             "valeur 'auto' = assets/<rom>/, ou chemin custom",
    ),
    no_dynamic: bool = typer.Option(
        False, "--no-dynamic", help="Désactive la discovery dynamique (cynes)"
    ),
    verify: bool = typer.Option(
        False, "--verify", help="Vérifie le round-trip (recompile et compare aux bytes originaux)"
    ),
    quiet: bool = typer.Option(
        False, "-q", "--quiet", help="N'affiche rien sauf erreurs"
    ),
):
    """Analyse une ROM NES."""
    if output is None:
        output = rom.parent / "STACK.md"

    if not quiet:
        typer.echo(f"→ lecture de {rom}")
    rom_obj = Rom.from_file(rom)
    profile = RomProfile.from_rom(rom_obj)
    if not quiet:
        typer.echo(
            f"→ ROM : mapper={rom_obj.mapper}  "
            f"PRG={rom_obj.num_prg_banks} bank(s)"
        )
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
            typer.echo(
                f"→ discovery dynamique : ignorée (mapper {rom_obj.mapper})"
            )

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
        content = profile.annotated_asm
        if assets_dir is not None and profile.assets and profile.assets.chr_raw:
            import os
            chr_rel = os.path.relpath(profile.assets.chr_raw, asm.parent)
            content += (
                "\n\n"
                "; ============================================================\n"
                "; CHR-ROM extraite vers un fichier séparé (lien réassemblable)\n"
                "; ============================================================\n"
                ".segment \"CHR\"\n"
                f".incbin \"{chr_rel}\"\n"
                f"; ou: .include \"{os.path.relpath(profile.assets.chr_asm, asm.parent)}\"\n"
            )
        asm.write_text(content, encoding="utf-8")
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
    rom: Path = typer.Argument(..., help="ROM source à recompiler", exists=True),
    output: Path = typer.Option(
        ..., "-o", "--output", help="Chemin de sortie pour la ROM recompilée"
    ),
    quiet: bool = typer.Option(False, "-q", "--quiet"),
):
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
    original: Path = typer.Argument(..., help="ROM originale", exists=True),
    recompiled: Optional[Path] = typer.Argument(
        None, help="ROM recompilée à comparer (optionnel : recompile à la volée si absent)"
    ),
    quiet: bool = typer.Option(False, "-q", "--quiet"),
):
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


def main(argv=None) -> int:
    try:
        app(argv, standalone_mode=False)
        return 0
    except (typer.Exit, SystemExit) as e:
        return getattr(e, "exit_code", 0) or 0
    except (typer.Abort, click_exception()) as e:
        typer.echo(str(e), err=True)
        return 2
    except FileNotFoundError as e:
        typer.echo(f"erreur : {e}", err=True)
        return 2


def click_exception():
    import click
    return click.exceptions.UsageError


if __name__ == "__main__":
    sys.exit(main())
