"""Generate desktop packaging scaffolds for a NES ROM.

This module does not pretend to convert 6502/NES code into native x86 code.
It creates a small launcher that embeds a ROM next to the app and opens it with
a bundled emulator binary or one found on PATH. The generated project can then
be compiled with PyInstaller for Windows/Linux or wrapped as an AppImage.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from .det import sha256_file
from .rom import Rom

SUPPORTED_TARGETS = ("portable", "pyinstaller", "appimage", "all")


@dataclass(frozen=True)
class RomBundleManifest:
    """Files emitted for a ROM desktop launcher scaffold."""

    output_dir: Path
    app_name: str
    target: str
    rom_path: Path
    launcher_path: Path
    manifest_path: Path
    build_scripts: list[Path]
    desktop_file: Path | None = None
    icon_file: Path | None = None


def slugify_app_name(name: str) -> str:
    """Return a filesystem and PyInstaller friendly app slug."""
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip()).strip("-._")
    return slug or "nes-rom"


def create_rom_bundle(
    rom_path: Path | str,
    output_dir: Path | str,
    *,
    app_name: str | None = None,
    target: str = "all",
    emulator: str = "fceux",
    force: bool = False,
) -> RomBundleManifest:
    """Create a ROM launcher project that can be built as .exe/AppImage.

    Args:
      rom_path: source `.nes` file.
      output_dir: generated launcher project directory.
      app_name: display/binary name. Defaults to the ROM stem.
      target: one of `portable`, `pyinstaller`, `appimage`, or `all`.
      emulator: emulator executable to prefer at runtime when no bundled
        emulator is present.
      force: overwrite an existing output directory.
    """
    if target not in SUPPORTED_TARGETS:
        raise ValueError(f"target must be one of {', '.join(SUPPORTED_TARGETS)}")

    source = Path(rom_path)
    if not source.exists():
        raise FileNotFoundError(source)
    rom = Rom.from_file(source)
    if rom.header is None:
        raise ValueError(f"{source} is not a valid iNES ROM")

    out = Path(output_dir)
    if out.exists() and any(out.iterdir()) and not force:
        raise FileExistsError(f"{out} is not empty (use force=True)")
    out.mkdir(parents=True, exist_ok=True)

    resolved_name = app_name or source.stem
    app_slug = slugify_app_name(resolved_name)
    rom_dir = out / "roms"
    emulator_dir = out / "emulator"
    rom_dir.mkdir(exist_ok=True)
    emulator_dir.mkdir(exist_ok=True)

    bundled_rom = rom_dir / source.name
    shutil.copy2(source, bundled_rom)

    launcher = out / "launcher.py"
    launcher.write_text(
        _launcher_source(app_name=resolved_name, rom_filename=source.name, emulator=emulator),
        encoding="utf-8",
    )

    build_scripts: list[Path] = []
    if target in ("pyinstaller", "all"):
        build_scripts.extend(_write_pyinstaller_scripts(out, app_slug, source.name))

    desktop_file: Path | None = None
    icon_file: Path | None = None
    if target in ("appimage", "all"):
        desktop_file, icon_file, script = _write_appimage_files(
            out, app_slug, resolved_name, source.name
        )
        build_scripts.append(script)

    manifest_path = out / "bundle-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "app_name": resolved_name,
                "app_slug": app_slug,
                "target": target,
                "rom": {
                    "source": str(source),
                    "bundled": str(bundled_rom.relative_to(out)),
                    "sha256": sha256_file(source),
                    "mapper": rom.mapper,
                    "prg_banks": rom.num_prg_banks,
                    "chr_banks": rom.header.chr_banks,
                },
                "runtime": {
                    "kind": "external-or-bundled-emulator-launcher",
                    "default_emulator": emulator,
                    "bundled_emulator_dir": "emulator",
                },
                "build_scripts": [str(path.relative_to(out)) for path in build_scripts],
                "notes": [
                    "This wraps the ROM with a launcher; it does not recompile NES code to native code.",
                    "Place an emulator binary in emulator/ to ship it inside the final app, or rely on PATH.",
                ],
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    return RomBundleManifest(
        output_dir=out,
        app_name=resolved_name,
        target=target,
        rom_path=bundled_rom,
        launcher_path=launcher,
        manifest_path=manifest_path,
        build_scripts=build_scripts,
        desktop_file=desktop_file,
        icon_file=icon_file,
    )


def _launcher_source(*, app_name: str, rom_filename: str, emulator: str) -> str:
    return f'''#!/usr/bin/env python3
"""Launcher generated by qlnes for {app_name}."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


APP_NAME = {app_name!r}
ROM_FILENAME = {rom_filename!r}
DEFAULT_EMULATOR = {emulator!r}


def _base_dir() -> Path:
    frozen_dir = getattr(sys, "_MEIPASS", None)
    if frozen_dir:
        return Path(frozen_dir)
    return Path(__file__).resolve().parent


def _candidate_emulators(base: Path) -> list[str]:
    env = os.environ.get("QLNES_EMULATOR")
    names = [
        env,
        str(base / "emulator" / "fceux.exe"),
        str(base / "emulator" / "fceux"),
        str(base / "emulator" / "mesen.exe"),
        str(base / "emulator" / "mesen"),
        str(base / "emulator" / "nestopia.exe"),
        str(base / "emulator" / "nestopia"),
        DEFAULT_EMULATOR,
        "fceux",
        "mesen",
        "nestopia",
    ]
    return [name for name in names if name]


def _resolve_emulator(base: Path) -> str:
    for candidate in _candidate_emulators(base):
        path = Path(candidate)
        if path.is_file():
            return str(path)
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    raise SystemExit(
        "No NES emulator found. Put fceux/mesen/nestopia in emulator/, "
        "install one on PATH, or set QLNES_EMULATOR."
    )


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    base = _base_dir()
    rom = base / "roms" / ROM_FILENAME
    if not rom.exists():
        raise SystemExit(f"Bundled ROM missing: {{rom}}")
    emulator = _resolve_emulator(base)
    return subprocess.call([emulator, str(rom), *args])


if __name__ == "__main__":
    raise SystemExit(main())
'''


def _write_pyinstaller_scripts(out: Path, app_slug: str, rom_filename: str) -> list[Path]:
    sh = out / "build-exe.sh"
    sh.write_text(
        f"""#!/usr/bin/env sh
set -eu
if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required to bootstrap PyInstaller locally. Install uv or add it to PATH." >&2
  exit 1
fi
export UV_CACHE_DIR="${{UV_CACHE_DIR:-.uv-cache}}"
PYTHON="${{PYTHON:-python3}}"
if [ ! -x ".venv-build/bin/python" ]; then
  uv venv --python "$PYTHON" .venv-build
fi
if ! .venv-build/bin/python -c "import PyInstaller" >/dev/null 2>&1; then
  uv pip install --python .venv-build/bin/python "pyinstaller>=6,<7"
fi
.venv-build/bin/python -m PyInstaller --clean --onefile --name {app_slug} \\
  --add-data "roms/{rom_filename}:roms" \\
  --add-data "emulator:emulator" \\
  launcher.py
""",
        encoding="utf-8",
    )
    sh.chmod(0o755)

    ps1 = out / "build-exe.ps1"
    ps1.write_text(
        f"""$ErrorActionPreference = "Stop"
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {{
  throw "uv is required to bootstrap PyInstaller locally. Install uv or add it to PATH."
}}
$env:UV_CACHE_DIR = if ($env:UV_CACHE_DIR) {{ $env:UV_CACHE_DIR }} else {{ ".uv-cache" }}
$Python = if ($env:PYTHON) {{ $env:PYTHON }} else {{ "python" }}
if (-not (Test-Path ".venv-build/Scripts/python.exe")) {{
  uv venv --python $Python .venv-build
}}
& .venv-build/Scripts/python.exe -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {{
  uv pip install --python .venv-build/Scripts/python.exe "pyinstaller>=6,<7"
}}
& .venv-build/Scripts/python.exe -m PyInstaller --clean --onefile --name {app_slug} `
  --add-data "roms/{rom_filename};roms" `
  --add-data "emulator;emulator" `
  launcher.py
""",
        encoding="utf-8",
    )
    return [sh, ps1]


def _write_appimage_files(
    out: Path,
    app_slug: str,
    app_name: str,
    rom_filename: str,
) -> tuple[Path, Path, Path]:
    desktop = out / f"{app_slug}.desktop"
    desktop.write_text(
        f"""[Desktop Entry]
Type=Application
Name={app_name}
Exec={app_slug}
Icon={app_slug}
Categories=Game;Emulator;
Terminal=false
""",
        encoding="utf-8",
    )

    icon = out / f"{app_slug}.svg"
    icon.write_text(
        """<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">
<rect width="256" height="256" rx="32" fill="#202020"/>
<rect x="36" y="64" width="184" height="128" rx="12" fill="#d8d8d8"/>
<rect x="60" y="88" width="136" height="80" rx="6" fill="#30343b"/>
<rect x="78" y="110" width="24" height="24" fill="#7bd88f"/>
<rect x="116" y="110" width="24" height="24" fill="#ffd866"/>
<rect x="154" y="110" width="24" height="24" fill="#fc9867"/>
<text x="128" y="212" text-anchor="middle" font-family="monospace" font-size="24" fill="#ffffff">NES</text>
</svg>
""",
        encoding="utf-8",
    )

    sh = out / "build-appimage.sh"
    sh.write_text(
        f"""#!/usr/bin/env sh
set -eu
if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required to bootstrap PyInstaller locally. Install uv or add it to PATH." >&2
  exit 1
fi
export UV_CACHE_DIR="${{UV_CACHE_DIR:-.uv-cache}}"
PYTHON="${{PYTHON:-python3}}"
if [ ! -x ".venv-build/bin/python" ]; then
  uv venv --python "$PYTHON" .venv-build
fi
if ! .venv-build/bin/python -c "import PyInstaller" >/dev/null 2>&1; then
  uv pip install --python .venv-build/bin/python "pyinstaller>=6,<7"
fi
APPIMAGETOOL="${{APPIMAGETOOL:-}}"
if [ -z "$APPIMAGETOOL" ]; then
  if command -v appimagetool >/dev/null 2>&1; then
    APPIMAGETOOL=appimagetool
  else
    mkdir -p .tools
    ARCH="$(uname -m)"
    case "$ARCH" in
      x86_64|amd64) APPIMAGE_ARCH=x86_64 ;;
      aarch64|arm64) APPIMAGE_ARCH=aarch64 ;;
      *) echo "unsupported AppImage architecture: $ARCH" >&2; exit 1 ;;
    esac
    APPIMAGETOOL=".tools/appimagetool-$APPIMAGE_ARCH.AppImage"
    if [ ! -x "$APPIMAGETOOL" ]; then
      URL="https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-$APPIMAGE_ARCH.AppImage"
      if command -v curl >/dev/null 2>&1; then
        curl -L "$URL" -o "$APPIMAGETOOL"
      elif command -v wget >/dev/null 2>&1; then
        wget -O "$APPIMAGETOOL" "$URL"
      else
        echo "curl or wget is required to download appimagetool" >&2
        exit 1
      fi
      chmod +x "$APPIMAGETOOL"
    fi
  fi
fi
.venv-build/bin/python -m PyInstaller --clean --onedir --name {app_slug} \\
  --add-data "roms/{rom_filename}:roms" \\
  --add-data "emulator:emulator" \\
  launcher.py
rm -rf AppDir
mkdir -p AppDir/usr/bin AppDir/usr/share/applications AppDir/usr/share/icons/hicolor/scalable/apps
cp -R "dist/{app_slug}/." "AppDir/usr/bin/"
cp "{app_slug}.desktop" "AppDir/usr/share/applications/{app_slug}.desktop"
cp "{app_slug}.svg" "AppDir/usr/share/icons/hicolor/scalable/apps/{app_slug}.svg"
cat > AppDir/AppRun <<'EOF'
#!/usr/bin/env sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/{app_slug}" "$@"
EOF
chmod +x AppDir/AppRun
cp "{app_slug}.desktop" "AppDir/{app_slug}.desktop"
cp "{app_slug}.svg" "AppDir/{app_slug}.svg"
"$APPIMAGETOOL" AppDir "{app_slug}.AppImage"
""",
        encoding="utf-8",
    )
    sh.chmod(0o755)
    return desktop, icon, sh
