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
    assert data["level"]["collision_columns"] == data["level"]["width"] // 16
    assert data["level"]["collision_rows"] == data["level"]["height"] // 16
    assert data["interactive_blocks"]["count"] >= 10
    assert data["interactive_blocks"]["record_bytes"] == 5
    assert data["interactive_blocks"]["used_block_asset"] == "assets/used_empty_block.rgb"
    assert data["interactive_blocks"]["jumping_coin_assets"] == [
        "assets/jumping_coin_frame_0.rgba",
        "assets/jumping_coin_frame_1.rgba",
        "assets/jumping_coin_frame_2.rgba",
        "assets/jumping_coin_frame_3.rgba",
    ]
    assert data["interactive_blocks"]["jumping_coin_width"] > 0
    assert data["interactive_blocks"]["jumping_coin_height"] > 0
    assert data["interactive_blocks"]["mushroom_asset"] == "assets/mushroom.rgba"
    assert data["interactive_blocks"]["mushroom_width"] > 0
    assert data["interactive_blocks"]["mushroom_height"] > 0
    assert any(block["kind"] == "question-block" for block in data["interactive_blocks"]["blocks"])
    assert any(block["kind"] == "item-brick" for block in data["interactive_blocks"]["blocks"])
    assert data["player"]["width"] > 0
    assert [sprite["name"] for sprite in data["player"]["sprites"]] == [
        "small-stand",
        "small-walk-1",
        "small-walk-2",
        "small-walk-3",
        "small-jump",
    ]
    assert data["enemies"][0]["name"] == "goomba"
    assert data["enemies"][0]["spawn_count"] >= 8
    assert data["enemies"][1]["name"] == "koopa-troopa"
    assert data["enemies"][1]["spawn_count"] >= 1
    assert sum(enemy["spawn_count"] for enemy in data["enemies"]) == len(data["enemy_spawns"])
    assert data["enemy_spawns"][0]["source_bytes"]
    assert any("group_id" in spawn for spawn in data["enemy_spawns"])
    assert any(spawn["kind"] == "koopa-troopa" for spawn in data["enemy_spawns"])
    assert export.source.exists()
    assert export.build_script.exists()
    assert export.appimage_script.exists()
    assert (export.out_dir / "assets" / "level_1_1.rgb").exists()
    assert (export.out_dir / "assets" / "collision_1_1.bin").exists()
    assert (export.out_dir / "assets" / "blocks_1_1.bin").exists()
    assert (export.out_dir / "assets" / "used_empty_block.rgb").exists()
    assert (export.out_dir / "assets" / "jumping_coin_frame_0.rgba").exists()
    assert (export.out_dir / "assets" / "jumping_coin_frame_1.rgba").exists()
    assert (export.out_dir / "assets" / "jumping_coin_frame_2.rgba").exists()
    assert (export.out_dir / "assets" / "jumping_coin_frame_3.rgba").exists()
    assert (export.out_dir / "assets" / "mushroom.rgba").exists()
    assert (export.out_dir / "assets" / "mario_small_stand.rgba").exists()
    assert (export.out_dir / "assets" / "mario_small_walk_1.rgba").exists()
    assert (export.out_dir / "assets" / "mario_small_walk_2.rgba").exists()
    assert (export.out_dir / "assets" / "mario_small_walk_3.rgba").exists()
    assert (export.out_dir / "assets" / "mario_small_jump.rgba").exists()
    assert (export.out_dir / "assets" / "goomba.rgba").exists()
    assert (export.out_dir / "assets" / "koopa_troopa.rgba").exists()
    assert (export.out_dir / "assets" / "enemies_1_1.bin").exists()
    assert not (export.out_dir / "emulator").exists()
    assert not list(export.out_dir.rglob("*.nes"))
    source = export.source.read_text(encoding="utf-8")
    assert "SDL_CreateWindow" in source
    assert "--self-test" in source
    assert "rect_hits_solid" in source
    assert "ENEMY_COUNT" in source
    assert "Enemy *enemy" in source
    assert "KOOPA_W" in source
    assert "MARIO_FRAME_COUNT" in source
    assert "mario_sprite" in source
    assert "BLOCK_COUNT" in source
    assert "draw_used_blocks" in source
    assert "update_window_title" in source
    assert "CoinEffect" in source
    assert "draw_coin_effect" in source
    assert "Powerup" in source
    assert "spawn_mushroom" in source
    assert "update_powerup" in source


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
    assert (out / "assets" / "collision_1_1.bin").exists()
    assert (out / "assets" / "blocks_1_1.bin").exists()
    assert (out / "assets" / "used_empty_block.rgb").exists()
    assert (out / "assets" / "jumping_coin_frame_0.rgba").exists()
    assert (out / "assets" / "jumping_coin_frame_3.rgba").exists()
    assert (out / "assets" / "mushroom.rgba").exists()
    assert (out / "assets" / "goomba.rgba").exists()
    assert (out / "assets" / "mario_small_walk_1.rgba").exists()
    assert (out / "assets" / "mario_small_jump.rgba").exists()
    assert (out / "assets" / "koopa_troopa.rgba").exists()
    assert (out / "assets" / "enemies_1_1.bin").exists()
    assert not list(out.rglob("*.nes"))
