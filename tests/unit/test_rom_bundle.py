from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from qlnes.rom_bundle import create_rom_bundle, slugify_app_name

REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_minimal_rom(path: Path) -> None:
    header = bytearray(16)
    header[0:4] = b"NES\x1a"
    header[4] = 1
    header[5] = 1
    prg = bytearray(0x4000)
    chr_rom = bytearray(0x2000)
    path.write_bytes(bytes(header) + bytes(prg) + bytes(chr_rom))


def test_slugify_app_name_is_binary_friendly() -> None:
    assert slugify_app_name("Super Mario Bros. (World)") == "Super-Mario-Bros.-World"
    assert slugify_app_name(" ... ") == "nes-rom"


def test_create_rom_bundle_writes_pyinstaller_and_appimage_scaffold(tmp_path: Path) -> None:
    rom = tmp_path / "game.nes"
    _write_minimal_rom(rom)

    manifest = create_rom_bundle(
        rom,
        tmp_path / "bundle",
        app_name="Game Test",
        target="all",
        emulator="mesen",
    )

    data = json.loads(manifest.manifest_path.read_text(encoding="utf-8"))
    assert data["app_name"] == "Game Test"
    assert data["app_slug"] == "Game-Test"
    assert data["rom"]["bundled"] == "roms/game.nes"
    assert data["rom"]["mapper"] == 0
    assert data["runtime"]["default_emulator"] == "mesen"

    assert manifest.rom_path.read_bytes() == rom.read_bytes()
    assert "ROM_FILENAME = 'game.nes'" in manifest.launcher_path.read_text(encoding="utf-8")
    assert (manifest.output_dir / "build-exe.sh").exists()
    assert (manifest.output_dir / "build-exe.ps1").exists()
    assert (manifest.output_dir / "build-appimage.sh").exists()
    exe_script = (manifest.output_dir / "build-exe.sh").read_text(encoding="utf-8")
    appimage_script = (manifest.output_dir / "build-appimage.sh").read_text(encoding="utf-8")
    ps1_script = (manifest.output_dir / "build-exe.ps1").read_text(encoding="utf-8")
    assert "UV_CACHE_DIR" in exe_script
    assert "UV_CACHE_DIR" in appimage_script
    assert "UV_CACHE_DIR" in ps1_script
    assert "uv venv" in exe_script
    assert "uv pip install" in exe_script
    assert ".venv-build/bin/python -m PyInstaller" in exe_script
    assert "uv venv" in ps1_script
    assert "uv pip install" in ps1_script
    assert "appimagetool-$APPIMAGE_ARCH.AppImage" in appimage_script
    assert ".venv-build/bin/python -m PyInstaller" in appimage_script
    assert manifest.desktop_file is not None and manifest.desktop_file.exists()
    assert manifest.icon_file is not None and manifest.icon_file.exists()
    assert os.access(manifest.output_dir / "build-exe.sh", os.X_OK)
    assert os.access(manifest.output_dir / "build-appimage.sh", os.X_OK)


def test_create_rom_bundle_refuses_non_empty_output_without_force(tmp_path: Path) -> None:
    rom = tmp_path / "game.nes"
    _write_minimal_rom(rom)
    out = tmp_path / "bundle"
    out.mkdir()
    (out / "existing.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(FileExistsError):
        create_rom_bundle(rom, out)


def test_cli_bundle_rom_generates_project(tmp_path: Path) -> None:
    rom = tmp_path / "game.nes"
    _write_minimal_rom(rom)
    out = tmp_path / "bundle"
    env = {key: value for key, value in os.environ.items() if not key.startswith("QLNES_")}

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "qlnes",
            "bundle-rom",
            str(rom),
            "--output",
            str(out),
            "--name",
            "Game Test",
            "--target",
            "pyinstaller",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert (out / "launcher.py").exists()
    assert (out / "roms" / "game.nes").exists()
    assert (out / "build-exe.sh").exists()
    assert not (out / "build-appimage.sh").exists()


def test_cli_bundle_rom_refuses_existing_output_without_force(tmp_path: Path) -> None:
    rom = tmp_path / "game.nes"
    _write_minimal_rom(rom)
    out = tmp_path / "bundle"
    out.mkdir()
    (out / "existing.txt").write_text("keep", encoding="utf-8")
    env = {key: value for key, value in os.environ.items() if not key.startswith("QLNES_")}

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "qlnes",
            "bundle-rom",
            str(rom),
            "--output",
            str(out),
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode != 0
    assert "not empty" in result.stderr
