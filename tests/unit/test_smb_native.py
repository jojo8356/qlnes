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
    assert data["stage_sequence"] == ["1-1", "1-2"]
    assert [stage["stage"] for stage in data["stages"]] == ["1-1", "1-2"]
    assert data["stages"][0]["asset"] == "assets/level_1_1.rgb"
    assert data["stages"][1]["asset"] == "assets/level_1_2.rgb"
    assert data["stages"][1]["collision_asset"] == "assets/collision_1_2.bin"
    assert data["stages"][1]["block_asset"] == "assets/blocks_1_2.bin"
    assert data["stages"][1]["enemy_asset"] == "assets/enemies_1_2.bin"
    assert data["stages"][1]["width"] > 256
    assert data["stages"][1]["interactive_block_count"] > 0
    assert all(isinstance(stage["area_type"], int) for stage in data["stages"])
    assert data["level"]["width"] > 256
    assert data["level"]["collision_columns"] == data["level"]["width"] // 16
    assert data["level"]["collision_rows"] == data["level"]["height"] // 16
    assert data["stage_clear"]["trigger_x"] == data["level"]["width"] - 192
    assert data["stage_clear"]["restart_ms"] == 2500
    assert data["stage_clear"]["time_bonus_per_second"] == 50
    assert data["stage_clear"]["behavior"].startswith("native stage-clear")
    assert "advances to the next generated stage" in data["stage_clear"]["behavior"]
    assert data["title_screen"]["asset"] == "assets/title_screen.rgb"
    assert data["title_screen"]["width"] == 256
    assert data["title_screen"]["height"] == 240
    assert data["title_screen"]["source_manifest"].endswith("smb-title-assets.json")
    assert data["title_screen"]["start_controls"] == ["Enter", "Space"]
    assert data["title_screen"]["behavior"].startswith("native title-screen")
    assert data["audio"] == {
        "backend": "SDL2 callback",
        "runtime_assets": [],
        "sample_rate": 44100,
        "format": "AUDIO_F32SYS stereo",
        "modes": ["title", "gameplay", "stage-clear", "death"],
        "sfx": ["jump", "coin", "stomp", "power-up", "shell-kick", "brick-shatter"],
        "behavior": "native procedural chiptune-style audio; no NSF, MP3, ROM or emulator is loaded at runtime",
    }
    assert data["controls"] == {
        "move_left": ["Left", "A"],
        "move_right": ["Right", "D"],
        "jump": ["Space", "Up", "W"],
        "run": ["Left Shift", "Right Shift", "J"],
        "start": ["Enter", "Space"],
        "quit": ["Esc"],
    }
    assert data["scoring"] == {
        "starting_time": 400,
        "coin_points": 200,
        "mushroom_points": 1000,
        "stomp_points": 100,
        "shell_kick_points": 400,
        "shell_hit_points": 500,
        "brick_points": 50,
        "stage_clear_time_bonus_per_second": 50,
    }
    assert data["damage"] == {
        "invulnerable_ms": 1400,
        "behavior": "big Mario shrinks on enemy contact, then blinks and ignores enemy damage briefly",
    }
    assert data["hud"] == {
        "renderer": "native framebuffer 5x7 glyphs",
        "fields": ["MARIO", "COIN", "WORLD", "TIME", "LIVES"],
        "asset_files": [],
    }
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
    assert data["interactive_blocks"]["brick_chunk_asset"] == "assets/brick_chunk.rgba"
    assert data["interactive_blocks"]["brick_chunk_width"] > 0
    assert data["interactive_blocks"]["brick_chunk_height"] > 0
    assert data["interactive_blocks"]["breakable_metatiles"] == ["0x51", "0x52"]
    assert data["interactive_blocks"]["break_behavior"].startswith("big Mario breaks")
    assert "spawns four native brick chunks" in data["interactive_blocks"]["break_behavior"]
    assert any(block["kind"] == "question-block" for block in data["interactive_blocks"]["blocks"])
    assert any(block["kind"] == "breakable-brick" for block in data["interactive_blocks"]["blocks"])
    assert any(block["kind"] == "item-brick" for block in data["interactive_blocks"]["blocks"])
    assert data["player"]["width"] > 0
    assert data["player"]["big_height"] > data["player"]["small_height"]
    assert data["player"]["big_width"] >= data["player"]["small_width"]
    assert [sprite["name"] for sprite in data["player"]["small_sprites"]] == [
        "small-stand",
        "small-walk-1",
        "small-walk-2",
        "small-walk-3",
        "small-jump",
    ]
    assert [sprite["name"] for sprite in data["player"]["big_sprites"]] == [
        "big-stand",
        "big-walk-1",
        "big-walk-2",
        "big-walk-3",
        "big-jump",
    ]
    assert [sprite["name"] for sprite in data["player"]["small_swim_sprites"]] == [
        "small-swim-1",
        "small-swim-2",
        "small-swim-3",
    ]
    assert [sprite["name"] for sprite in data["player"]["big_swim_sprites"]] == [
        "big-swim-1",
        "big-swim-2",
        "big-swim-3",
    ]
    assert data["player"]["swim_physics"] == {
        "water_area_type": 0,
        "behavior": "water stages use native low-gravity swim movement and ROM-derived swim sprites",
    }
    assert data["player"]["dead_sprite"]["name"] == "small-killed"
    assert data["player"]["dead_sprite"]["asset"] == "assets/mario_small_killed.rgba"
    assert data["player"]["dead_sprite"]["width"] > 0
    assert data["player"]["dead_sprite"]["height"] > 0
    assert data["player"]["sprites"] == data["player"]["small_sprites"]
    assert data["enemies"][0]["name"] == "goomba"
    assert data["enemies"][0]["spawn_count"] >= 8
    assert data["enemies"][1]["name"] == "koopa-troopa"
    assert data["enemies"][1]["spawn_count"] >= 1
    assert data["enemies"][2]["name"] == "koopa-shell"
    assert data["enemies"][2]["asset"] == "assets/koopa_shell.rgba"
    assert data["enemies"][2]["runtime_kind"] == "0x80"
    assert data["enemies"][2]["width"] > 0
    assert data["enemies"][2]["height"] > 0
    assert data["enemies"][3]["name"] == "blooper"
    assert data["enemies"][3]["runtime_kind"] == "0x07"
    assert [sprite["name"] for sprite in data["enemies"][3]["sprites"]] == [
        "blooper-1",
        "blooper-2",
    ]
    assert data["enemies"][3]["behavior"].startswith("native water enemy")
    assert data["enemies"][4]["name"] == "podoboo"
    assert data["enemies"][4]["asset"] == "assets/podoboo.rgba"
    assert data["enemies"][4]["runtime_kind"] == "0x0C"
    assert data["enemies"][4]["behavior"].startswith("native castle hazard")
    assert data["enemies"][5]["name"] == "piranha-plant"
    assert [sprite["name"] for sprite in data["enemies"][5]["sprites"]] == [
        "piranha-plant-1",
        "piranha-plant-2",
    ]
    assert data["enemies"][5]["runtime_kind"] == "0x0D"
    assert data["enemies"][5]["spawn_count_total"] > 0
    assert data["enemies"][5]["behavior"].startswith("native pipe hazard")
    assert data["enemies"][6]["name"] == "koopa-paratroopa"
    assert [sprite["name"] for sprite in data["enemies"][6]["sprites"]] == [
        "koopa-paratroopa-1",
        "koopa-paratroopa-2",
    ]
    assert data["enemies"][6]["runtime_kinds"] == ["0x0E", "0x0F", "0x10"]
    assert data["enemies"][6]["behavior"].startswith("native winged Koopa enemy")
    assert sum(enemy["spawn_count"] for enemy in data["enemies"] if "spawn_count" in enemy) == len(
        data["enemy_spawns"]
    )
    assert data["enemy_spawns"][0]["source_bytes"]
    assert any("group_id" in spawn for spawn in data["enemy_spawns"])
    assert any(spawn["kind"] == "koopa-troopa" for spawn in data["enemy_spawns"])
    assert export.source.exists()
    assert export.build_script.exists()
    assert export.appimage_script.exists()
    assert (export.out_dir / "assets" / "level_1_1.rgb").exists()
    assert (export.out_dir / "assets" / "level_1_2.rgb").exists()
    assert (export.out_dir / "assets" / "title_screen.rgb").exists()
    assert (export.out_dir / "assets" / "collision_1_1.bin").exists()
    assert (export.out_dir / "assets" / "collision_1_2.bin").exists()
    assert (export.out_dir / "assets" / "blocks_1_1.bin").exists()
    assert (export.out_dir / "assets" / "blocks_1_2.bin").exists()
    assert (export.out_dir / "assets" / "used_empty_block.rgb").exists()
    assert (export.out_dir / "assets" / "jumping_coin_frame_0.rgba").exists()
    assert (export.out_dir / "assets" / "jumping_coin_frame_1.rgba").exists()
    assert (export.out_dir / "assets" / "jumping_coin_frame_2.rgba").exists()
    assert (export.out_dir / "assets" / "jumping_coin_frame_3.rgba").exists()
    assert (export.out_dir / "assets" / "mushroom.rgba").exists()
    assert (export.out_dir / "assets" / "brick_chunk.rgba").exists()
    assert (export.out_dir / "assets" / "mario_small_stand.rgba").exists()
    assert (export.out_dir / "assets" / "mario_small_walk_1.rgba").exists()
    assert (export.out_dir / "assets" / "mario_small_walk_2.rgba").exists()
    assert (export.out_dir / "assets" / "mario_small_walk_3.rgba").exists()
    assert (export.out_dir / "assets" / "mario_small_jump.rgba").exists()
    assert (export.out_dir / "assets" / "mario_big_stand.rgba").exists()
    assert (export.out_dir / "assets" / "mario_big_walk_1.rgba").exists()
    assert (export.out_dir / "assets" / "mario_big_walk_2.rgba").exists()
    assert (export.out_dir / "assets" / "mario_big_walk_3.rgba").exists()
    assert (export.out_dir / "assets" / "mario_big_jump.rgba").exists()
    assert (export.out_dir / "assets" / "mario_small_swim_1.rgba").exists()
    assert (export.out_dir / "assets" / "mario_small_swim_2.rgba").exists()
    assert (export.out_dir / "assets" / "mario_small_swim_3.rgba").exists()
    assert (export.out_dir / "assets" / "mario_big_swim_1.rgba").exists()
    assert (export.out_dir / "assets" / "mario_big_swim_2.rgba").exists()
    assert (export.out_dir / "assets" / "mario_big_swim_3.rgba").exists()
    assert (export.out_dir / "assets" / "mario_small_killed.rgba").exists()
    assert (export.out_dir / "assets" / "goomba.rgba").exists()
    assert (export.out_dir / "assets" / "koopa_troopa.rgba").exists()
    assert (export.out_dir / "assets" / "koopa_shell.rgba").exists()
    assert (export.out_dir / "assets" / "blooper_1.rgba").exists()
    assert (export.out_dir / "assets" / "blooper_2.rgba").exists()
    assert (export.out_dir / "assets" / "podoboo.rgba").exists()
    assert (export.out_dir / "assets" / "piranha_plant_1.rgba").exists()
    assert (export.out_dir / "assets" / "piranha_plant_2.rgba").exists()
    assert (export.out_dir / "assets" / "koopa_paratroopa_1.rgba").exists()
    assert (export.out_dir / "assets" / "koopa_paratroopa_2.rgba").exists()
    assert (export.out_dir / "assets" / "enemies_1_1.bin").exists()
    assert (export.out_dir / "assets" / "enemies_1_2.bin").exists()
    assert not (export.out_dir / "emulator").exists()
    assert not list(export.out_dir.rglob("*.nes"))
    source = export.source.read_text(encoding="utf-8")
    assert "SDL_CreateWindow" in source
    assert "SDL_INIT_AUDIO" in source
    assert "SDL_OpenAudioDevice" in source
    assert "SDL_CloseAudioDevice" in source
    assert "audio_callback" in source
    assert "open_native_audio" in source
    assert "set_audio_mode" in source
    assert "trigger_sfx" in source
    assert "sfx_sample" in source
    assert "AUDIO_MODE_TITLE" in source
    assert "AUDIO_MODE_GAMEPLAY" in source
    assert "AUDIO_MODE_STAGE_CLEAR" in source
    assert "AUDIO_MODE_DEATH" in source
    assert "SFX_JUMP" in source
    assert "SFX_COIN" in source
    assert "SFX_STOMP" in source
    assert "SFX_POWERUP" in source
    assert "SFX_SHELL_KICK" in source
    assert "AUDIO_F32SYS" in source
    assert "--self-test" in source
    assert "TITLE_SCREEN_W" in source
    assert "TITLE_SCREEN_H" in source
    assert "title_screen_active" in source
    assert "draw_rgb_image(frame, title_screen, TITLE_SCREEN_W, TITLE_SCREEN_H)" in source
    assert "update_title_screen_window_title" in source
    assert "PRESS ENTER OR SPACE" in source
    assert "SDLK_RETURN" in source
    assert "rect_hits_solid" in source
    assert "ENEMY_COUNT" in source
    assert "Enemy *enemy" in source
    assert "KOOPA_W" in source
    assert "KOOPA_SHELL_KIND" in source
    assert "KOOPA_SHELL_W" in source
    assert "BLOOPER_KIND" in source
    assert "BLOOPER_FRAME_COUNT" in source
    assert "blooper_frames" in source
    assert "enemy->kind == BLOOPER_KIND" in source
    assert "PODOBOO_KIND" in source
    assert "enemy->origin_y" in source
    assert "enemy->kind == PODOBOO_KIND" in source
    assert "PIRANHA_KIND" in source
    assert "piranha_frames" in source
    assert "enemy->kind == PIRANHA_KIND" in source
    assert "PARATROOPA_JUMP_KIND" in source
    assert "enemy_is_paratroopa" in source
    assert "paratroopa_frames" in source
    assert "BRICK_CHUNK_W" in source
    assert "BRICK_CHUNK_H" in source
    assert "MARIO_FRAME_COUNT" in source
    assert "SWIM_FRAME_COUNT" in source
    assert "SMALL_SWIM_W" in source
    assert "BIG_SWIM_H" in source
    assert "mario_sprite" in source
    assert "small_swim_frames" in source
    assert "big_swim_frames" in source
    assert "mario_draw_width(mario_big, water_stage)" in source
    assert "mario_draw_height(mario_big, water_stage)" in source
    assert "SMALL_MARIO_H" in source
    assert "BIG_MARIO_H" in source
    assert "bool mario_big" in source
    assert "mario_width(mario_big)" in source
    assert "DEAD_MARIO_H" in source
    assert "WALK_SPEED" in source
    assert "RUN_SPEED" in source
    assert "STAGE_AREA_TYPES" in source
    assert "bool water_stage = STAGE_AREA_TYPES[current_stage] == 0" in source
    assert "water_stage = STAGE_AREA_TYPES[current_stage] == 0" in source
    assert "WATER_GRAVITY" in source
    assert "WATER_MAX_FALL_SPEED" in source
    assert "WATER_SWIM_IMPULSE" in source
    assert "jump_pressed && water_stage" in source
    assert "INVULNERABLE_MS" in source
    assert "SDL_SCANCODE_LSHIFT" in source
    assert "SDL_SCANCODE_RSHIFT" in source
    assert "SDL_SCANCODE_J" in source
    assert "float player_speed = run ? RUN_SPEED : WALK_SPEED" in source
    assert "STARTING_LIVES" in source
    assert "STARTING_TIME" in source
    assert "SCORE_COIN" in source
    assert "SCORE_MUSHROOM" in source
    assert "SCORE_STOMP" in source
    assert "SCORE_SHELL_KICK" in source
    assert "SCORE_SHELL_HIT" in source
    assert "SCORE_BRICK" in source
    assert "SCORE_TIME_BONUS" in source
    assert "KOOPA_SHELL_SPEED" in source
    assert "bool player_dead" in source
    assert "uint32_t invulnerable_until" in source
    assert "bool stage_clear" in source
    assert "reset_level_state" in source
    assert "begin_death" in source
    assert "begin_stage_clear" in source
    assert "update_stage_clear_title" in source
    assert "STAGE_COUNT 2" in source
    assert 'STAGE_LABELS[STAGE_COUNT] = {"1-1", "1-2"}' in source
    assert (
        'STAGE_LEVEL_FILES[STAGE_COUNT] = {"assets/level_1_1.rgb", "assets/level_1_2.rgb"}'
        in source
    )
    assert "stage_clear_x(current_level_w)" in source
    assert "current_stage = (current_stage + 1) % STAGE_COUNT" in source
    assert "draw_hud(frame, score, coins, time_left, lives, stage_clear, stage_label)" in source
    assert "STAGE_CLEAR_RESTART_MS" in source
    assert " CLEAR" in source
    assert "Score %06d" in source
    assert "Time %03d" in source
    assert "draw_hud" in source
    assert "draw_hud_text" in source
    assert "draw_hud_number" in source
    assert "hud_glyph_row" in source
    assert '"MARIO"' in source
    assert '"WORLD"' in source
    assert "timer_started_at" in source
    assert "score += SCORE_COIN" in source
    assert "score += SCORE_MUSHROOM" in source
    assert "score += SCORE_STOMP" in source
    assert "score += SCORE_SHELL_KICK" in source
    assert "score += SCORE_SHELL_HIT" in source
    assert "score += SCORE_BRICK" in source
    assert "trigger_sfx(audio_device, &audio_state, SFX_JUMP)" in source
    assert "trigger_sfx(audio_device, &audio_state, SFX_COIN)" in source
    assert "trigger_sfx(audio_device, &audio_state, SFX_STOMP)" in source
    assert "trigger_sfx(audio_device, &audio_state, SFX_POWERUP)" in source
    assert "trigger_sfx(audio_device, &audio_state, SFX_SHELL_KICK)" in source
    assert "trigger_sfx(audio_device, &audio_state, SFX_BRICK)" in source
    assert "block_is_breakable" in source
    assert "hit->broken = true" in source
    assert "if (block && block->broken) return false" in source
    assert "draw_broken_blocks(frame, blocks, level, camera)" in source
    assert "now < invulnerable_until" in source
    assert "invulnerable_until = now + INVULNERABLE_MS" in source
    assert "bool mario_visible = now >= invulnerable_until" in source
    assert "enemy->kind = KOOPA_SHELL_KIND" in source
    assert "shell_is_moving" in source
    assert "bool shell_stationary" in source
    assert "target->alive = false" in source
    assert "koopa_shell" in source
    assert "*score += *time_left * SCORE_TIME_BONUS" in source
    assert "Lives %d" in source
    assert "BLOCK_COUNT" in source
    assert "draw_used_blocks" in source
    assert "update_window_title" in source
    assert "CoinEffect" in source
    assert "draw_coin_effect" in source
    assert "BrickChunkEffect" in source
    assert "draw_brick_chunk_effect" in source
    assert "brick_effect.active = true" in source
    assert "brick_effect.started_at = now" in source
    assert "draw_brick_chunk_effect(frame, &brick_effect, brick_chunk, now, camera)" in source
    assert "free(brick_chunk)" in source
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
    assert (out / "assets" / "title_screen.rgb").exists()
    assert (out / "assets" / "collision_1_1.bin").exists()
    assert (out / "assets" / "collision_1_2.bin").exists()
    assert (out / "assets" / "blocks_1_1.bin").exists()
    assert (out / "assets" / "blocks_1_2.bin").exists()
    assert (out / "assets" / "used_empty_block.rgb").exists()
    assert (out / "assets" / "jumping_coin_frame_0.rgba").exists()
    assert (out / "assets" / "jumping_coin_frame_3.rgba").exists()
    assert (out / "assets" / "mushroom.rgba").exists()
    assert (out / "assets" / "brick_chunk.rgba").exists()
    assert (out / "assets" / "goomba.rgba").exists()
    assert (out / "assets" / "blooper_1.rgba").exists()
    assert (out / "assets" / "podoboo.rgba").exists()
    assert (out / "assets" / "piranha_plant_1.rgba").exists()
    assert (out / "assets" / "piranha_plant_2.rgba").exists()
    assert (out / "assets" / "koopa_paratroopa_1.rgba").exists()
    assert (out / "assets" / "koopa_paratroopa_2.rgba").exists()
    assert (out / "assets" / "mario_small_walk_1.rgba").exists()
    assert (out / "assets" / "mario_small_jump.rgba").exists()
    assert (out / "assets" / "mario_big_walk_1.rgba").exists()
    assert (out / "assets" / "mario_big_jump.rgba").exists()
    assert (out / "assets" / "mario_small_swim_1.rgba").exists()
    assert (out / "assets" / "mario_big_swim_1.rgba").exists()
    assert (out / "assets" / "mario_small_killed.rgba").exists()
    assert (out / "assets" / "koopa_troopa.rgba").exists()
    assert (out / "assets" / "koopa_shell.rgba").exists()
    assert (out / "assets" / "enemies_1_1.bin").exists()
    assert (out / "assets" / "enemies_1_2.bin").exists()
    assert not list(out.rglob("*.nes"))


@pytest.mark.skipif(not SMB_ROM.exists(), reason=f"SMB ROM not at {SMB_ROM}")
def test_create_smb_native_port_stage_all_generates_main_quest_sequence(tmp_path: Path) -> None:
    export = create_smb_native_port(
        SMB_ROM,
        tmp_path / "native-all",
        app_name="SMB Native All Test",
        stage="all",
        force=True,
    )

    data = json.loads(export.manifest_json.read_text(encoding="utf-8"))
    assert len(data["stage_sequence"]) == 32
    assert data["stage_sequence"][:4] == ["1-1", "1-2", "1-3", "1-4"]
    assert data["stage_sequence"][-4:] == ["8-1", "8-2", "8-3", "8-4"]
    assert len(data["stages"]) == 32
    assert data["stages"][0]["asset"] == "assets/level_1_1.rgb"
    assert data["stages"][-1]["asset"] == "assets/level_8_4.rgb"
    assert data["stages"][-1]["collision_asset"] == "assets/collision_8_4.bin"
    assert data["stages"][-1]["block_asset"] == "assets/blocks_8_4.bin"
    assert data["stages"][-1]["enemy_asset"] == "assets/enemies_8_4.bin"
    area_types_by_stage = {stage["stage"]: stage["area_type"] for stage in data["stages"]}
    assert area_types_by_stage["2-2"] == 0
    assert area_types_by_stage["7-2"] == 0
    assert data["enemies"][3]["spawn_count_total"] == 14
    assert data["enemies"][4]["spawn_count_total"] == 14
    assert data["enemies"][5]["spawn_count_total"] == 106
    assert data["enemies"][6]["spawn_count_total"] == 48
    assert (export.out_dir / "assets" / "level_8_4.rgb").exists()
    assert (export.out_dir / "assets" / "collision_8_4.bin").exists()
    assert (export.out_dir / "assets" / "blocks_8_4.bin").exists()
    assert (export.out_dir / "assets" / "enemies_8_4.bin").exists()
    source = export.source.read_text(encoding="utf-8")
    assert "STAGE_COUNT 32" in source
    assert "STAGE_AREA_TYPES" in source
    assert "BLOOPER_KIND" in source
    assert "PODOBOO_KIND" in source
    assert "PIRANHA_KIND" in source
    assert "PARATROOPA_JUMP_KIND" in source
    assert '"8-4"' in source
    assert "current_stage = (current_stage + 1) % STAGE_COUNT" in source
    assert not list(export.out_dir.rglob("*.nes"))
