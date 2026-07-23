from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from qlnes.smb_native import create_smb_native_port, slugify_binary_name

REPO_ROOT = Path(__file__).resolve().parents[2]
SMB_ROM = REPO_ROOT / "roms" / "Super Mario Bros. (World).nes"


def test_slugify_binary_name_is_shell_friendly() -> None:
    assert slugify_binary_name("Super Mario Bros Native") == "Super-Mario-Bros-Native"
    assert slugify_binary_name(" ... ") == "smb-native"


@pytest.mark.skipif(not SMB_ROM.exists(), reason=f"SMB ROM not at {SMB_ROM}")
def test_create_smb_native_port_generates_c_sdl_project_without_rom_or_emulator(
    tmp_path: Path,
) -> None:
    export = create_smb_native_port(
        SMB_ROM,
        tmp_path / "native",
        app_name="SMB Native Test",
        force=True,
    )

    data = json.loads(export.manifest_json.read_text(encoding="utf-8"))
    assert data["kind"] == "smb_native_port_mvp"
    assert data["runtime"].startswith("C/SDL2")
    assert data["level"]["width"] > 256
    assert data["player"]["width"] > 0
    assert export.source.exists()
    assert export.build_script.exists()
    assert export.appimage_script.exists()
    assert (export.out_dir / "assets" / "level_1_1.rgb").exists()
    assert (export.out_dir / "assets" / "mario_small_stand.rgba").exists()
    assert not (export.out_dir / "emulator").exists()
    assert not list(export.out_dir.rglob("*.nes"))
    source = export.source.read_text(encoding="utf-8")
    assert "SDL_CreateWindow" in source
    assert "--self-test" in source


@pytest.mark.skipif(not SMB_ROM.exists(), reason=f"SMB ROM not at {SMB_ROM}")
def test_cli_smb_native_generates_project(tmp_path: Path) -> None:
    out = tmp_path / "native"
    env = {key: value for key, value in os.environ.items() if not key.startswith("QLNES_")}

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "qlnes",
            "smb-native",
            str(SMB_ROM),
            "--output",
            str(out),
            "--name",
            "SMB Native Test",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert (out / "src" / "main.c").exists()
    assert (out / "build-appimage.sh").exists()
    assert not list(out.rglob("*.nes"))
