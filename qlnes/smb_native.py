"""Generate a native Linux SMB proof-of-concept from ROM-derived assets.

The generated app is intentionally not an emulator wrapper. The ROM is used at
generation time only to render SMB level/player assets through qlnes' existing
reverse-engineered exporters. The runtime is a small C/SDL2 program that loads
raw RGB/RGBA assets and implements a minimal native side-scroller loop.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from .det import sha256_file
from .smb_graphics import (
    WORLD_MAP,
    SmbLevelExport,
    _SmbLevelRuntime,
    render_smb_blocks,
    render_smb_characters,
    render_smb_level,
    render_smb_title_assets,
    validate_smb_nrom,
)

SMB_ENEMY_DATA_LOW = 0x00E9
SMB_GREEN_KOOPA_ID = 0x00
SMB_NATIVE_KOOPA_SHELL_KIND = 0x80
SMB_GOOMBA_ID = 0x06
SMB_GOOMBA_GROUPS = {0x37: 2, 0x38: 3, 0x39: 2, 0x3A: 3}
SMB_KOOPA_GROUPS = {0x3B: 2, 0x3C: 3}
SMB_NATIVE_ENEMY_RECORD_BYTES = 5
SMB_NATIVE_BLOCK_RECORD_BYTES = 5
SMB_JUMPING_COIN_FRAME_COUNT = 4
SMB_NATIVE_DEFAULT_STAGE_SEQUENCE = ("1-1", "1-2")
SMB_INTERACTIVE_BLOCK_METATILES = {
    0xC0: "question-block",
    0xC1: "question-block",
    0x5F: "question-block",
    0x60: "question-block",
    0x51: "breakable-brick",
    0x52: "breakable-brick",
    0x57: "item-brick",
    0x58: "coin-brick",
}
SMB_BREAKABLE_BRICK_METATILES = {0x51, 0x52}
SMB_USED_BLOCK_METATILE = 0xC4
SMB_SMALL_MARIO_SPRITES = (
    ("small-stand", "mario_small_stand.rgba"),
    ("small-walk-1", "mario_small_walk_1.rgba"),
    ("small-walk-2", "mario_small_walk_2.rgba"),
    ("small-walk-3", "mario_small_walk_3.rgba"),
    ("small-jump", "mario_small_jump.rgba"),
)
SMB_BIG_MARIO_SPRITES = (
    ("big-stand", "mario_big_stand.rgba"),
    ("big-walk-1", "mario_big_walk_1.rgba"),
    ("big-walk-2", "mario_big_walk_2.rgba"),
    ("big-walk-3", "mario_big_walk_3.rgba"),
    ("big-jump", "mario_big_jump.rgba"),
)
SMB_DEAD_MARIO_SPRITE = ("small-killed", "mario_small_killed.rgba")


@dataclass(frozen=True)
class SmbNativeExport:
    rom: Path
    out_dir: Path
    app_name: str
    stage: str
    executable_name: str
    source: Path
    build_script: Path
    appimage_script: Path
    manifest_json: Path
    files: list[Path] = field(default_factory=list)


@dataclass(frozen=True)
class _SmbNativeStageAsset:
    stage: str
    safe_stage: str
    level: SmbLevelExport
    level_raw: Path
    collision_raw: Path
    blocks_raw: Path
    enemies_raw: Path
    collision_size: tuple[int, int]
    interactive_blocks: list[dict[str, object]]
    enemy_spawns: list[dict[str, object]]


def slugify_binary_name(name: str) -> str:
    slug = "".join(ch if ch.isalnum() else "-" for ch in name.strip())
    slug = "-".join(part for part in slug.split("-") if part)
    return slug or "smb-native"


def create_smb_native_port(
    rom_path: Path | str,
    out_dir: Path | str,
    *,
    app_name: str = "Super Mario Bros Native",
    stage: str = "1-1",
    force: bool = False,
) -> SmbNativeExport:
    """Generate a C/SDL2 native SMB MVP project and AppImage build scripts."""
    rom = Path(rom_path)
    out = Path(out_dir)
    if out.exists() and any(out.iterdir()) and not force:
        raise FileExistsError(f"{out} is not empty (use force=True)")
    out.mkdir(parents=True, exist_ok=True)

    rom_bytes = rom.read_bytes()
    validate_smb_nrom(rom_bytes)
    stage_names = list(SMB_NATIVE_DEFAULT_STAGE_SEQUENCE if stage == "1-1" else (stage,))
    for stage_name in stage_names:
        if stage_name not in WORLD_MAP:
            valid = ", ".join(sorted(WORLD_MAP))
            raise ValueError(f"unknown SMB stage {stage_name!r}; valid: {valid}")

    app_slug = slugify_binary_name(app_name)
    src_dir = out / "src"
    assets_dir = out / "assets"
    build_dir = out / "_asset-build"
    src_dir.mkdir(exist_ok=True)
    assets_dir.mkdir(exist_ok=True)
    build_dir.mkdir(exist_ok=True)

    rendered_levels = [
        render_smb_level(rom, build_dir / "levels", stage=stage_name, max_columns=256)
        for stage_name in stage_names
    ]
    max_level_width = max(level.width for level in rendered_levels)
    max_level_height = max(level.height for level in rendered_levels)
    max_collision_cols = max_level_width // 16
    max_collision_rows = max_level_height // 16
    title_assets = render_smb_title_assets(rom, build_dir / "title")
    characters = render_smb_characters(rom, build_dir / "characters")
    block_assets = render_smb_blocks(rom, build_dir / "blocks")
    mario_pngs = {
        sprite_name: build_dir / "characters" / "players" / f"{sprite_name}.png"
        for sprite_name, _ in SMB_SMALL_MARIO_SPRITES
    }
    big_mario_pngs = {
        sprite_name: build_dir / "characters" / "players" / f"{sprite_name}.png"
        for sprite_name, _ in SMB_BIG_MARIO_SPRITES
    }
    dead_mario_png = build_dir / "characters" / "players" / f"{SMB_DEAD_MARIO_SPRITE[0]}.png"
    goomba_png = build_dir / "characters" / "enemies" / "goomba.png"
    koopa_png = build_dir / "characters" / "enemies" / "koopa-troopa-1.png"
    koopa_shell_png = build_dir / "characters" / "enemies" / "koopa-shell-1.png"
    mushroom_png = build_dir / "blocks" / "sprites" / "mushroom.png"
    brick_chunk_png = build_dir / "blocks" / "sprites" / "brick-chunk.png"
    for mario_png in mario_pngs.values():
        if not mario_png.exists():
            raise RuntimeError(f"expected SMB player sprite missing: {mario_png}")
    for mario_png in big_mario_pngs.values():
        if not mario_png.exists():
            raise RuntimeError(f"expected SMB big player sprite missing: {mario_png}")
    if not dead_mario_png.exists():
        raise RuntimeError(f"expected SMB dead player sprite missing: {dead_mario_png}")
    if not goomba_png.exists():
        raise RuntimeError(f"expected SMB enemy sprite missing: {goomba_png}")
    if not koopa_png.exists():
        raise RuntimeError(f"expected SMB enemy sprite missing: {koopa_png}")
    if not koopa_shell_png.exists():
        raise RuntimeError(f"expected SMB enemy shell sprite missing: {koopa_shell_png}")
    if not mushroom_png.exists():
        raise RuntimeError(f"expected SMB power-up sprite missing: {mushroom_png}")
    if not brick_chunk_png.exists():
        raise RuntimeError(f"expected SMB brick chunk sprite missing: {brick_chunk_png}")

    title_screen_raw = assets_dir / "title_screen.rgb"
    used_block_raw = assets_dir / "used_empty_block.rgb"
    coin_frame_raws = [
        assets_dir / f"jumping_coin_frame_{idx}.rgba" for idx in range(SMB_JUMPING_COIN_FRAME_COUNT)
    ]
    mushroom_raw = assets_dir / "mushroom.rgba"
    brick_chunk_raw = assets_dir / "brick_chunk.rgba"
    goomba_raw = assets_dir / "goomba.rgba"
    koopa_raw = assets_dir / "koopa_troopa.rgba"
    koopa_shell_raw = assets_dir / "koopa_shell.rgba"
    dead_mario_raw = assets_dir / SMB_DEAD_MARIO_SPRITE[1]
    stage_assets: list[_SmbNativeStageAsset] = []
    for level in rendered_levels:
        safe_stage = level.stage.replace("-", "_")
        level_raw = assets_dir / f"level_{safe_stage}.rgb"
        collision_raw = assets_dir / f"collision_{safe_stage}.bin"
        blocks_raw = assets_dir / f"blocks_{safe_stage}.bin"
        enemies_raw = assets_dir / f"enemies_{safe_stage}.bin"
        _write_padded_rgb(level.png, level_raw, max_level_width, max_level_height)
        collision_size = _write_collision_map(
            level.png,
            collision_raw,
            pad_cols=max_collision_cols,
            pad_rows=max_collision_rows,
        )
        interactive_blocks, used_block_size = _write_block_interactions(
            rom_bytes,
            level.stage,
            blocks_raw,
            used_block_raw,
        )
        enemy_spawns = _write_enemy_spawns(rom_bytes, level.stage, enemies_raw)
        stage_assets.append(
            _SmbNativeStageAsset(
                stage=level.stage,
                safe_stage=safe_stage,
                level=level,
                level_raw=level_raw,
                collision_raw=collision_raw,
                blocks_raw=blocks_raw,
                enemies_raw=enemies_raw,
                collision_size=collision_size,
                interactive_blocks=interactive_blocks,
                enemy_spawns=enemy_spawns,
            )
        )

    max_block_count = max(len(stage_asset.interactive_blocks) for stage_asset in stage_assets)
    max_enemy_count = max(len(stage_asset.enemy_spawns) for stage_asset in stage_assets)
    for stage_asset in stage_assets:
        _pad_record_file(
            stage_asset.blocks_raw,
            current_count=len(stage_asset.interactive_blocks),
            max_count=max_block_count,
            record_bytes=SMB_NATIVE_BLOCK_RECORD_BYTES,
            fill_record=bytes((0, 0, 0, 0, 2)),
        )
        _pad_record_file(
            stage_asset.enemies_raw,
            current_count=len(stage_asset.enemy_spawns),
            max_count=max_enemy_count,
            record_bytes=SMB_NATIVE_ENEMY_RECORD_BYTES,
            fill_record=bytes((0, 0, 0, 0, 1)),
        )

    first_stage = stage_assets[0]
    used_block_size = _write_used_block_asset(rom_bytes, first_stage.stage, used_block_raw)
    title_screen_size = _write_rgb(title_assets.title_screen, title_screen_raw)
    coin_frame_size = _write_coin_frame_assets(build_dir / "blocks" / "sprites", coin_frame_raws)
    small_mario_size, small_mario_assets = _write_mario_frame_assets(
        mario_pngs,
        assets_dir,
        SMB_SMALL_MARIO_SPRITES,
    )
    big_mario_size, big_mario_assets = _write_mario_frame_assets(
        big_mario_pngs,
        assets_dir,
        SMB_BIG_MARIO_SPRITES,
    )
    mushroom_size = _write_rgba(mushroom_png, mushroom_raw)
    brick_chunk_size = _write_rgba(brick_chunk_png, brick_chunk_raw)
    dead_mario_size = _write_rgba(dead_mario_png, dead_mario_raw)
    goomba_size = _write_rgba(goomba_png, goomba_raw)
    koopa_size = _write_rgba(koopa_png, koopa_raw)
    koopa_shell_size = _write_rgba(koopa_shell_png, koopa_shell_raw)
    enemy_spawns = _write_enemy_spawns(rom_bytes, stage, enemies_raw)

    main_c = src_dir / "main.c"
    main_c.write_text(
        _main_c_source(
            app_name=app_name,
            stage_labels=[stage_asset.stage for stage_asset in stage_assets],
            stage_level_widths=[stage_asset.level.width for stage_asset in stage_assets],
            stage_level_files=[
                str(stage_asset.level_raw.relative_to(out)) for stage_asset in stage_assets
            ],
            stage_collision_files=[
                str(stage_asset.collision_raw.relative_to(out)) for stage_asset in stage_assets
            ],
            stage_block_files=[
                str(stage_asset.blocks_raw.relative_to(out)) for stage_asset in stage_assets
            ],
            stage_enemy_files=[
                str(stage_asset.enemies_raw.relative_to(out)) for stage_asset in stage_assets
            ],
            level_width=max_level_width,
            level_height=max_level_height,
            title_screen_width=title_screen_size[0],
            title_screen_height=title_screen_size[1],
            collision_cols=max_collision_cols,
            collision_rows=max_collision_rows,
            block_count=max_block_count,
            block_record_bytes=SMB_NATIVE_BLOCK_RECORD_BYTES,
            used_block_width=used_block_size[0],
            used_block_height=used_block_size[1],
            coin_width=coin_frame_size[0],
            coin_height=coin_frame_size[1],
            coin_frame_count=SMB_JUMPING_COIN_FRAME_COUNT,
            mushroom_width=mushroom_size[0],
            mushroom_height=mushroom_size[1],
            brick_chunk_width=brick_chunk_size[0],
            brick_chunk_height=brick_chunk_size[1],
            small_mario_width=small_mario_size[0],
            small_mario_height=small_mario_size[1],
            big_mario_width=big_mario_size[0],
            big_mario_height=big_mario_size[1],
            dead_mario_width=dead_mario_size[0],
            dead_mario_height=dead_mario_size[1],
            mario_frame_count=len(SMB_SMALL_MARIO_SPRITES),
            goomba_width=goomba_size[0],
            goomba_height=goomba_size[1],
            koopa_width=koopa_size[0],
            koopa_height=koopa_size[1],
            koopa_shell_width=koopa_shell_size[0],
            koopa_shell_height=koopa_shell_size[1],
            enemy_count=max_enemy_count,
            enemy_record_bytes=SMB_NATIVE_ENEMY_RECORD_BYTES,
        ),
        encoding="utf-8",
    )
    build_sh = out / "build.sh"
    build_sh.write_text(_build_sh(app_slug), encoding="utf-8")
    build_sh.chmod(0o755)

    appimage_sh = out / "build-appimage.sh"
    appimage_sh.write_text(_appimage_sh(app_slug, app_name), encoding="utf-8")
    appimage_sh.chmod(0o755)

    desktop = out / f"{app_slug}.desktop"
    desktop.write_text(
        f"""[Desktop Entry]
Type=Application
Name={app_name}
Exec={app_slug}
Icon={app_slug}
Categories=Game;
Terminal=false
""",
        encoding="utf-8",
    )

    icon = out / f"{app_slug}.svg"
    icon.write_text(_icon_svg(), encoding="utf-8")

    manifest = out / "smb-native-manifest.json"
    files = [
        main_c,
        build_sh,
        appimage_sh,
        desktop,
        icon,
        *(stage_asset.level_raw for stage_asset in stage_assets),
        title_screen_raw,
        *(stage_asset.collision_raw for stage_asset in stage_assets),
        *(stage_asset.blocks_raw for stage_asset in stage_assets),
        used_block_raw,
        *coin_frame_raws,
        mushroom_raw,
        brick_chunk_raw,
        *(assets_dir / asset_name for _, asset_name in SMB_SMALL_MARIO_SPRITES),
        *(assets_dir / asset_name for _, asset_name in SMB_BIG_MARIO_SPRITES),
        dead_mario_raw,
        goomba_raw,
        koopa_raw,
        koopa_shell_raw,
        *(stage_asset.enemies_raw for stage_asset in stage_assets),
        manifest,
    ]
    manifest.write_text(
        json.dumps(
            {
                "kind": "smb_native_port_mvp",
                "app_name": app_name,
                "executable_name": app_slug,
                "stage": first_stage.stage,
                "stage_sequence": [stage_asset.stage for stage_asset in stage_assets],
                "rom_source": str(rom),
                "rom_sha256": sha256_file(rom),
                "runtime": "C/SDL2 native side-scroller MVP; no ROM or emulator is bundled",
                "stages": [
                    {
                        "stage": stage_asset.stage,
                        "source_png": str(stage_asset.level.png),
                        "asset": str(stage_asset.level_raw.relative_to(out)),
                        "collision_asset": str(stage_asset.collision_raw.relative_to(out)),
                        "block_asset": str(stage_asset.blocks_raw.relative_to(out)),
                        "enemy_asset": str(stage_asset.enemies_raw.relative_to(out)),
                        "width": stage_asset.level.width,
                        "height": stage_asset.level.height,
                        "columns": stage_asset.level.columns,
                        "rows": stage_asset.level.rows,
                        "collision_columns": stage_asset.collision_size[0],
                        "collision_rows": stage_asset.collision_size[1],
                        "interactive_block_count": len(stage_asset.interactive_blocks),
                        "enemy_spawn_count": len(stage_asset.enemy_spawns),
                    }
                    for stage_asset in stage_assets
                ],
                "level": {
                    "source_png": str(first_stage.level.png),
                    "asset": str(first_stage.level_raw.relative_to(out)),
                    "collision_asset": str(first_stage.collision_raw.relative_to(out)),
                    "width": first_stage.level.width,
                    "height": first_stage.level.height,
                    "columns": first_stage.level.columns,
                    "rows": first_stage.level.rows,
                    "collision_columns": first_stage.collision_size[0],
                    "collision_rows": first_stage.collision_size[1],
                },
                "stage_clear": {
                    "trigger_x": max(first_stage.level.width - 192, 0),
                    "restart_ms": 2500,
                    "time_bonus_per_second": 50,
                    "behavior": "native stage-clear state freezes control, advances to the next generated stage, and loops after the final generated stage",
                },
                "title_screen": {
                    "source_png": str(title_assets.title_screen),
                    "asset": str(title_screen_raw.relative_to(out)),
                    "width": title_screen_size[0],
                    "height": title_screen_size[1],
                    "source_manifest": str(title_assets.manifest_json),
                    "start_controls": ["Enter", "Space"],
                    "behavior": "native title-screen state renders the ROM-derived SMB title screen before gameplay",
                },
                "audio": {
                    "backend": "SDL2 callback",
                    "runtime_assets": [],
                    "sample_rate": 44100,
                    "format": "AUDIO_F32SYS stereo",
                    "modes": ["title", "gameplay", "stage-clear", "death"],
                    "sfx": ["jump", "coin", "stomp", "power-up", "shell-kick", "brick-shatter"],
                    "behavior": "native procedural chiptune-style audio; no NSF, MP3, ROM or emulator is loaded at runtime",
                },
                "controls": {
                    "move_left": ["Left", "A"],
                    "move_right": ["Right", "D"],
                    "jump": ["Space", "Up", "W"],
                    "run": ["Left Shift", "Right Shift", "J"],
                    "start": ["Enter", "Space"],
                    "quit": ["Esc"],
                },
                "scoring": {
                    "starting_time": 400,
                    "coin_points": 200,
                    "mushroom_points": 1000,
                    "stomp_points": 100,
                    "shell_kick_points": 400,
                    "shell_hit_points": 500,
                    "brick_points": 50,
                    "stage_clear_time_bonus_per_second": 50,
                },
                "damage": {
                    "invulnerable_ms": 1400,
                    "behavior": "big Mario shrinks on enemy contact, then blinks and ignores enemy damage briefly",
                },
                "hud": {
                    "renderer": "native framebuffer 5x7 glyphs",
                    "fields": ["MARIO", "COIN", "WORLD", "TIME", "LIVES"],
                    "asset_files": [],
                },
                "interactive_blocks": {
                    "asset": str(first_stage.blocks_raw.relative_to(out)),
                    "used_block_asset": str(used_block_raw.relative_to(out)),
                    "jumping_coin_assets": [str(path.relative_to(out)) for path in coin_frame_raws],
                    "jumping_coin_width": coin_frame_size[0],
                    "jumping_coin_height": coin_frame_size[1],
                    "mushroom_asset": str(mushroom_raw.relative_to(out)),
                    "mushroom_width": mushroom_size[0],
                    "mushroom_height": mushroom_size[1],
                    "brick_chunk_asset": str(brick_chunk_raw.relative_to(out)),
                    "brick_chunk_width": brick_chunk_size[0],
                    "brick_chunk_height": brick_chunk_size[1],
                    "record_bytes": SMB_NATIVE_BLOCK_RECORD_BYTES,
                    "breakable_metatiles": [
                        f"0x{metatile:02X}" for metatile in sorted(SMB_BREAKABLE_BRICK_METATILES)
                    ],
                    "break_behavior": "big Mario breaks empty brick metatiles natively, removes their collision cell, and spawns four native brick chunks",
                    "count": len(first_stage.interactive_blocks),
                    "blocks": first_stage.interactive_blocks,
                },
                "player": {
                    "source_png": str(mario_pngs["small-stand"]),
                    "asset": "assets/mario_small_stand.rgba",
                    "width": small_mario_size[0],
                    "height": small_mario_size[1],
                    "small_width": small_mario_size[0],
                    "small_height": small_mario_size[1],
                    "big_width": big_mario_size[0],
                    "big_height": big_mario_size[1],
                    "small_sprites": small_mario_assets,
                    "big_sprites": big_mario_assets,
                    "dead_sprite": {
                        "name": SMB_DEAD_MARIO_SPRITE[0],
                        "source_png": str(dead_mario_png),
                        "asset": str(dead_mario_raw.relative_to(out)),
                        "width": dead_mario_size[0],
                        "height": dead_mario_size[1],
                    },
                    "sprites": small_mario_assets,
                },
                "enemies": [
                    {
                        "name": "goomba",
                        "source_png": str(goomba_png),
                        "asset": str(goomba_raw.relative_to(out)),
                        "width": goomba_size[0],
                        "height": goomba_size[1],
                        "spawn_asset": str(enemies_raw.relative_to(out)),
                        "spawn_count": sum(
                            1 for spawn in enemy_spawns if spawn["kind"] == "goomba"
                        ),
                    },
                    {
                        "name": "koopa-troopa",
                        "source_png": str(koopa_png),
                        "asset": str(koopa_raw.relative_to(out)),
                        "width": koopa_size[0],
                        "height": koopa_size[1],
                        "spawn_asset": str(enemies_raw.relative_to(out)),
                        "spawn_count": sum(
                            1 for spawn in enemy_spawns if spawn["kind"] == "koopa-troopa"
                        ),
                    },
                    {
                        "name": "koopa-shell",
                        "source_png": str(koopa_shell_png),
                        "asset": str(koopa_shell_raw.relative_to(out)),
                        "width": koopa_shell_size[0],
                        "height": koopa_shell_size[1],
                        "runtime_kind": f"0x{SMB_NATIVE_KOOPA_SHELL_KIND:02X}",
                    },
                ],
                "enemy_spawns": first_stage.enemy_spawns,
                "block_manifest": str(block_assets.manifest_json),
                "character_manifest": str(characters.manifest_json),
                "build": {
                    "elf": f"dist/{app_slug}",
                    "appimage": f"{app_slug}.AppImage",
                },
                "notes": [
                    "The generated runtime does not read a .nes file.",
                    "This is a native MVP, not a complete SMB engine yet.",
                    "Controls: arrows or A/D to move, Shift/J to run, Space/W/Up to jump, Esc to quit.",
                    "Title screen uses the ROM-derived SMB title nametable rendered at generation time.",
                    "Collision is derived from the rendered SMB metatile map at build time.",
                    "Default native AppImage sequence includes stages 1-1 and 1-2 with separate generated assets.",
                    "Supported enemy spawns are decoded from SMB EnemyData for each generated stage.",
                    "Small and big Mario standing, walking, and jumping sprites are normalized from SMB tables.",
                    "Mario death uses the SMB small-killed metasprite and restarts the native level state.",
                    "Big Mario shrinks on enemy damage and gets a short native invulnerability window.",
                    "Stage clear triggers near the end of the generated level and restarts after a short victory pause.",
                    "Score, coins, world, time and lives are rendered by a native framebuffer HUD.",
                    "Question/item blocks are decoded from SMB metatiles and can be hit natively.",
                    "Breakable brick metatiles are removed from native collision when big Mario hits them.",
                    "Brick shatter uses the ROM-derived brick chunk sprite as a native visual effect.",
                    "Koopa stomps switch to a native shell state using the ROM-derived shell sprite.",
                    "Stationary Koopa shells can be kicked and moving shells defeat other enemies natively.",
                ],
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    return SmbNativeExport(
        rom=rom,
        out_dir=out,
        app_name=app_name,
        stage=first_stage.stage,
        executable_name=app_slug,
        source=main_c,
        build_script=build_sh,
        appimage_script=appimage_sh,
        manifest_json=manifest,
        files=files,
    )


def _write_rgb(source_png: Path, target: Path) -> tuple[int, int]:
    image = Image.open(source_png).convert("RGB")
    target.write_bytes(image.tobytes())
    return image.size


def _write_padded_rgb(source_png: Path, target: Path, width: int, height: int) -> tuple[int, int]:
    image = Image.open(source_png).convert("RGB")
    try:
        padded = Image.new("RGB", (width, height), image.getpixel((0, 0)))
        padded.paste(image, (0, 0))
        target.write_bytes(padded.tobytes())
        return padded.size
    finally:
        image.close()


def _write_rgba(source_png: Path, target: Path) -> tuple[int, int]:
    image = Image.open(source_png).convert("RGBA")
    target.write_bytes(image.tobytes())
    return image.size


def _write_mario_frame_assets(
    source_pngs: dict[str, Path],
    assets_dir: Path,
    sprites: tuple[tuple[str, str], ...],
) -> tuple[tuple[int, int], list[dict[str, object]]]:
    images = {
        sprite_name: Image.open(source_pngs[sprite_name]).convert("RGBA")
        for sprite_name, _ in sprites
    }
    try:
        width = max(image.width for image in images.values())
        height = max(image.height for image in images.values())
        assets: list[dict[str, object]] = []
        for sprite_name, asset_name in sprites:
            source = images[sprite_name]
            normalized = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            x = (width - source.width) // 2
            y = height - source.height
            normalized.alpha_composite(source, (x, y))
            target = assets_dir / asset_name
            target.write_bytes(normalized.tobytes())
            assets.append(
                {
                    "name": sprite_name,
                    "source_png": str(source_pngs[sprite_name]),
                    "asset": f"assets/{asset_name}",
                    "width": width,
                    "height": height,
                    "source_width": source.width,
                    "source_height": source.height,
                }
            )
        return (width, height), assets
    finally:
        for image in images.values():
            image.close()


def _write_coin_frame_assets(
    source_dir: Path,
    targets: list[Path],
) -> tuple[int, int]:
    images = [
        Image.open(source_dir / f"jumping-coin-frame-{idx}.png").convert("RGBA")
        for idx in range(SMB_JUMPING_COIN_FRAME_COUNT)
    ]
    try:
        width = max(image.width for image in images)
        height = max(image.height for image in images)
        for image, target in zip(images, targets, strict=True):
            normalized = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            normalized.alpha_composite(
                image,
                ((width - image.width) // 2, height - image.height),
            )
            target.write_bytes(normalized.tobytes())
        return width, height
    finally:
        for image in images:
            image.close()


def _write_collision_map(
    source_png: Path,
    target: Path,
    *,
    pad_cols: int | None = None,
    pad_rows: int | None = None,
) -> tuple[int, int]:
    image = Image.open(source_png).convert("RGB")
    cols = image.width // 16
    rows = image.height // 16
    out_cols = pad_cols or cols
    out_rows = pad_rows or rows
    sky = image.getpixel((0, 0))
    cells = bytearray()
    for row in range(out_rows):
        for col in range(out_cols):
            if row >= rows or col >= cols:
                cells.append(0)
                continue
            non_sky = 0
            total = 0
            for y in range(row * 16, row * 16 + 16):
                for x in range(col * 16, col * 16 + 16):
                    total += 1
                    if image.getpixel((x, y)) != sky:
                        non_sky += 1
            cells.append(1 if non_sky / total >= 0.20 else 0)
    target.write_bytes(bytes(cells))
    return cols, rows


def _write_used_block_asset(
    rom_bytes: bytes, stage: str, used_block_target: Path
) -> tuple[int, int]:
    runtime = _SmbLevelRuntime(rom_bytes)
    runtime.load_stage(WORLD_MAP[stage], max_columns=256)
    palettes = runtime.load_background_palette()
    used_block = runtime.render_metatile(SMB_USED_BLOCK_METATILE, palettes).convert("RGB")
    try:
        used_block_target.write_bytes(used_block.tobytes())
        return int(used_block.width), int(used_block.height)
    finally:
        used_block.close()


def _pad_record_file(
    target: Path,
    *,
    current_count: int,
    max_count: int,
    record_bytes: int,
    fill_record: bytes,
) -> None:
    if len(fill_record) != record_bytes:
        raise ValueError("fill_record length must match record_bytes")
    if current_count > max_count:
        raise ValueError("current_count cannot exceed max_count")
    if current_count == max_count:
        return
    with target.open("ab") as f:
        for _ in range(max_count - current_count):
            f.write(fill_record)


def _write_block_interactions(
    rom_bytes: bytes,
    stage: str,
    blocks_target: Path,
    used_block_target: Path,
) -> tuple[list[dict[str, object]], tuple[int, int]]:
    if stage not in WORLD_MAP:
        valid = ", ".join(sorted(WORLD_MAP))
        raise ValueError(f"unknown SMB stage {stage!r}; valid: {valid}")

    runtime = _SmbLevelRuntime(rom_bytes)
    columns = runtime.load_stage(WORLD_MAP[stage], max_columns=256)
    palettes = runtime.load_background_palette()
    used_block = runtime.render_metatile(SMB_USED_BLOCK_METATILE, palettes).convert("RGB")
    used_block_target.write_bytes(used_block.tobytes())

    records = bytearray()
    blocks: list[dict[str, object]] = []
    for col, column in enumerate(columns):
        for row, metatile in enumerate(column):
            kind = SMB_INTERACTIVE_BLOCK_METATILES.get(metatile)
            if kind is None:
                continue
            x = col * 16
            y = row * 16
            records.extend((x & 0xFF, (x >> 8) & 0xFF, y & 0xFF, metatile & 0xFF, 0))
            blocks.append(
                {
                    "kind": kind,
                    "metatile": f"0x{metatile:02X}",
                    "x": x,
                    "y": y,
                    "column": col,
                    "row": row,
                }
            )

    blocks_target.write_bytes(bytes(records))
    return blocks, used_block.size


def _write_enemy_spawns(
    rom_bytes: bytes,
    stage: str,
    target: Path,
) -> list[dict[str, object]]:
    if stage not in WORLD_MAP:
        valid = ", ".join(sorted(WORLD_MAP))
        raise ValueError(f"unknown SMB stage {stage!r}; valid: {valid}")

    runtime = _SmbLevelRuntime(rom_bytes)
    runtime.load_stage(WORLD_MAP[stage], max_columns=256)
    enemy_data = runtime.read(SMB_ENEMY_DATA_LOW) | (runtime.read(SMB_ENEMY_DATA_LOW + 1) << 8)

    page_loc = 0
    page_selected = False
    offset = 0
    spawns: list[dict[str, object]] = []
    records = bytearray()
    while offset < 512:
        first = runtime.read(enemy_data + offset)
        if first == 0xFF:
            break

        row = first & 0x0F
        column = first >> 4
        if first & 0x80:
            page_selected = True
            page_loc += 1

        if row == 0x0F and not page_selected:
            second = runtime.read(enemy_data + offset + 1)
            page_loc = second & 0x3F
            page_selected = True
            offset += 2
            continue

        if row == 0x0E:
            offset += 3
            page_selected = False
            continue

        second = runtime.read(enemy_data + offset + 1)
        enemy_id = second & 0x3F
        hard_mode_only = bool(second & 0x40)
        if enemy_id == SMB_GOOMBA_ID and not hard_mode_only:
            x = page_loc * 256 + (first & 0xF0)
            y = row * 16 + 8
            _append_enemy_spawn(
                records,
                spawns,
                kind="goomba",
                enemy_id=SMB_GOOMBA_ID,
                x=x,
                y=y,
                page=page_loc,
                column=column,
                row=row,
                offset=offset,
                source=(first, second),
            )
        elif enemy_id in SMB_GOOMBA_GROUPS and not hard_mode_only:
            x = page_loc * 256 + (first & 0xF0)
            y = row * 16 + 8
            for group_index in range(SMB_GOOMBA_GROUPS[enemy_id]):
                _append_enemy_spawn(
                    records,
                    spawns,
                    kind="goomba",
                    enemy_id=SMB_GOOMBA_ID,
                    x=x + group_index * 24,
                    y=y,
                    page=page_loc,
                    column=column,
                    row=row,
                    offset=offset,
                    source=(first, second),
                    group_id=enemy_id,
                    group_index=group_index,
                )
        elif enemy_id == SMB_GREEN_KOOPA_ID and not hard_mode_only:
            x = page_loc * 256 + (first & 0xF0)
            y = row * 16
            _append_enemy_spawn(
                records,
                spawns,
                kind="koopa-troopa",
                enemy_id=SMB_GREEN_KOOPA_ID,
                x=x,
                y=y,
                page=page_loc,
                column=column,
                row=row,
                offset=offset,
                source=(first, second),
            )
        elif enemy_id in SMB_KOOPA_GROUPS and not hard_mode_only:
            x = page_loc * 256 + (first & 0xF0)
            y = row * 16
            for group_index in range(SMB_KOOPA_GROUPS[enemy_id]):
                _append_enemy_spawn(
                    records,
                    spawns,
                    kind="koopa-troopa",
                    enemy_id=SMB_GREEN_KOOPA_ID,
                    x=x + group_index * 24,
                    y=y,
                    page=page_loc,
                    column=column,
                    row=row,
                    offset=offset,
                    source=(first, second),
                    group_id=enemy_id,
                    group_index=group_index,
                )

        offset += 2
        page_selected = False

    target.write_bytes(bytes(records))
    return spawns


def _append_enemy_spawn(
    records: bytearray,
    spawns: list[dict[str, object]],
    *,
    kind: str,
    enemy_id: int,
    x: int,
    y: int,
    page: int,
    column: int,
    row: int,
    offset: int,
    source: tuple[int, int],
    group_id: int | None = None,
    group_index: int | None = None,
) -> None:
    records.extend((x & 0xFF, (x >> 8) & 0xFF, y & 0xFF, enemy_id, 0))
    spawn: dict[str, object] = {
        "kind": kind,
        "enemy_id": f"0x{enemy_id:02X}",
        "x": x,
        "y": y,
        "page": page,
        "column": column,
        "row": row,
        "data_offset": f"0x{offset:02X}",
        "source_bytes": [f"0x{source[0]:02X}", f"0x{source[1]:02X}"],
    }
    if group_id is not None:
        spawn["group_id"] = f"0x{group_id:02X}"
        spawn["group_index"] = group_index
    spawns.append(spawn)


def _main_c_source(
    *,
    app_name: str,
    stage_labels: list[str],
    stage_level_widths: list[int],
    stage_level_files: list[str],
    stage_collision_files: list[str],
    stage_block_files: list[str],
    stage_enemy_files: list[str],
    level_width: int,
    level_height: int,
    title_screen_width: int,
    title_screen_height: int,
    collision_cols: int,
    collision_rows: int,
    block_count: int,
    block_record_bytes: int,
    used_block_width: int,
    used_block_height: int,
    coin_width: int,
    coin_height: int,
    coin_frame_count: int,
    mushroom_width: int,
    mushroom_height: int,
    brick_chunk_width: int,
    brick_chunk_height: int,
    small_mario_width: int,
    small_mario_height: int,
    big_mario_width: int,
    big_mario_height: int,
    dead_mario_width: int,
    dead_mario_height: int,
    mario_frame_count: int,
    goomba_width: int,
    goomba_height: int,
    koopa_width: int,
    koopa_height: int,
    koopa_shell_width: int,
    koopa_shell_height: int,
    enemy_count: int,
    enemy_record_bytes: int,
) -> str:
    stage_labels_c = ", ".join(f'"{label}"' for label in stage_labels)
    stage_widths_c = ", ".join(str(width) for width in stage_level_widths)
    stage_level_files_c = ", ".join(f'"{path}"' for path in stage_level_files)
    stage_collision_files_c = ", ".join(f'"{path}"' for path in stage_collision_files)
    stage_block_files_c = ", ".join(f'"{path}"' for path in stage_block_files)
    stage_enemy_files_c = ", ".join(f'"{path}"' for path in stage_enemy_files)
    return f"""#include <SDL2/SDL.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#define APP_TITLE "{app_name}"
#define SCREEN_W 256
#define SCREEN_H 240
#define SCALE 3
#define STAGE_COUNT {len(stage_labels)}
#define LEVEL_W {level_width}
#define LEVEL_H {level_height}
#define TITLE_SCREEN_W {title_screen_width}
#define TITLE_SCREEN_H {title_screen_height}
#define COLLISION_COLS {collision_cols}
#define COLLISION_ROWS {collision_rows}
#define BLOCK_COUNT {block_count}
#define BLOCK_RECORD_BYTES {block_record_bytes}
#define USED_BLOCK_W {used_block_width}
#define USED_BLOCK_H {used_block_height}
#define COIN_W {coin_width}
#define COIN_H {coin_height}
#define COIN_FRAME_COUNT {coin_frame_count}
#define MUSHROOM_W {mushroom_width}
#define MUSHROOM_H {mushroom_height}
#define BRICK_CHUNK_W {brick_chunk_width}
#define BRICK_CHUNK_H {brick_chunk_height}
#define SMALL_MARIO_W {small_mario_width}
#define SMALL_MARIO_H {small_mario_height}
#define BIG_MARIO_W {big_mario_width}
#define BIG_MARIO_H {big_mario_height}
#define DEAD_MARIO_W {dead_mario_width}
#define DEAD_MARIO_H {dead_mario_height}
#define MARIO_FRAME_COUNT {mario_frame_count}
#define GOOMBA_W {goomba_width}
#define GOOMBA_H {goomba_height}
#define KOOPA_W {koopa_width}
#define KOOPA_H {koopa_height}
#define KOOPA_SHELL_W {koopa_shell_width}
#define KOOPA_SHELL_H {koopa_shell_height}
#define KOOPA_SHELL_KIND {SMB_NATIVE_KOOPA_SHELL_KIND}
#define ENEMY_COUNT {enemy_count}
#define ENEMY_RECORD_BYTES {enemy_record_bytes}
#define TILE_SIZE 16
#define MARIO_START_X 48.0f
#define MARIO_START_Y 176.0f
#define WALK_SPEED 100.0f
#define RUN_SPEED 150.0f
#define STARTING_LIVES 3
#define STARTING_TIME 400
#define DEATH_RESTART_MS 1300
#define INVULNERABLE_MS 1400
#define STAGE_CLEAR_RESTART_MS 2500
#define SCORE_COIN 200
#define SCORE_MUSHROOM 1000
#define SCORE_STOMP 100
#define SCORE_SHELL_KICK 400
#define SCORE_SHELL_HIT 500
#define SCORE_BRICK 50
#define SCORE_TIME_BONUS 50
#define KOOPA_SHELL_SPEED 150.0f
#define AUDIO_RATE 44100

static const char *STAGE_LABELS[STAGE_COUNT] = {{{stage_labels_c}}};
static const int STAGE_LEVEL_WIDTHS[STAGE_COUNT] = {{{stage_widths_c}}};
static const char *STAGE_LEVEL_FILES[STAGE_COUNT] = {{{stage_level_files_c}}};
static const char *STAGE_COLLISION_FILES[STAGE_COUNT] = {{{stage_collision_files_c}}};
static const char *STAGE_BLOCK_FILES[STAGE_COUNT] = {{{stage_block_files_c}}};
static const char *STAGE_ENEMY_FILES[STAGE_COUNT] = {{{stage_enemy_files_c}}};

enum {{
    AUDIO_MODE_TITLE = 0,
    AUDIO_MODE_GAMEPLAY = 1,
    AUDIO_MODE_STAGE_CLEAR = 2,
    AUDIO_MODE_DEATH = 3
}};

enum {{
    SFX_NONE = 0,
    SFX_JUMP = 1,
    SFX_COIN = 2,
    SFX_STOMP = 3,
    SFX_POWERUP = 4,
    SFX_SHELL_KICK = 5,
    SFX_BRICK = 6
}};

typedef struct {{
    float x;
    float y;
    float vx;
    float vy;
    uint8_t kind;
    bool alive;
}} Enemy;

typedef struct {{
    uint16_t x;
    uint8_t y;
    uint8_t metatile;
    bool used;
    bool broken;
}} Block;

typedef struct {{
    bool active;
    float x;
    float y;
    uint32_t started_at;
}} CoinEffect;

typedef struct {{
    bool active;
    float x;
    float y;
    uint32_t started_at;
}} BrickChunkEffect;

typedef struct {{
    bool active;
    bool emerging;
    float x;
    float y;
    float vx;
    float vy;
    float target_y;
}} Powerup;

typedef struct {{
    int sample_rate;
    uint64_t sample_clock;
    double melody_phase;
    double bass_phase;
    double sfx_phase;
    uint64_t sfx_clock;
    int sfx_kind;
    int mode;
}} AudioState;

static void draw_sprite(
    uint32_t *frame,
    const uint8_t *sprite,
    int sprite_w,
    int sprite_h,
    int x,
    int y,
    bool flip
);

static uint8_t *read_asset(const char *path, size_t expected) {{
    FILE *f = fopen(path, "rb");
    if (!f) {{
        fprintf(stderr, "missing asset: %s\\n", path);
        return NULL;
    }}
    uint8_t *data = (uint8_t *)malloc(expected);
    if (!data) {{
        fclose(f);
        return NULL;
    }}
    size_t n = fread(data, 1, expected, f);
    fclose(f);
    if (n != expected) {{
        fprintf(stderr, "bad asset size for %s: got %zu expected %zu\\n", path, n, expected);
        free(data);
        return NULL;
    }}
    return data;
}}

static uint8_t *read_bundled_asset(const char *base, const char *asset, size_t expected) {{
    char path[4096];
    snprintf(path, sizeof(path), "%s%s", base ? base : "", asset);
    return read_asset(path, expected);
}}

static double square_sample(AudioState *state, double *phase, double hz) {{
    if (hz <= 0.0) return 0.0;
    *phase += hz / (double)state->sample_rate;
    while (*phase >= 1.0) *phase -= 1.0;
    return *phase < 0.5 ? 1.0 : -1.0;
}}

static double triangle_sample(AudioState *state, double *phase, double hz) {{
    if (hz <= 0.0) return 0.0;
    *phase += hz / (double)state->sample_rate;
    while (*phase >= 1.0) *phase -= 1.0;
    double p = *phase;
    if (p < 0.25) return p * 4.0;
    if (p < 0.75) return 2.0 - p * 4.0;
    return p * 4.0 - 4.0;
}}

static double sfx_sample(AudioState *state) {{
    if (state->sfx_kind == SFX_NONE) return 0.0;
    uint64_t duration = (uint64_t)(state->sample_rate / 5);
    if (state->sfx_clock >= duration) {{
        state->sfx_kind = SFX_NONE;
        state->sfx_clock = 0;
        return 0.0;
    }}
    double t = (double)state->sfx_clock / (double)duration;
    double hz = 0.0;
    double volume = (1.0 - t) * 0.16;
    if (state->sfx_kind == SFX_JUMP) {{
        hz = 420.0 + 520.0 * t;
    }} else if (state->sfx_kind == SFX_COIN) {{
        hz = state->sfx_clock < duration / 2 ? 988.0 : 1318.0;
    }} else if (state->sfx_kind == SFX_STOMP) {{
        hz = 180.0 - 70.0 * t;
        volume = (1.0 - t) * 0.20;
    }} else if (state->sfx_kind == SFX_POWERUP) {{
        hz = 659.0 + 659.0 * t;
    }} else if (state->sfx_kind == SFX_SHELL_KICK) {{
        hz = state->sfx_clock < duration / 3 ? 262.0 : 523.0;
        volume = (1.0 - t) * 0.18;
    }} else if (state->sfx_kind == SFX_BRICK) {{
        hz = 130.0 + 260.0 * (1.0 - t);
        volume = (1.0 - t) * 0.22;
    }}
    state->sfx_clock++;
    return square_sample(state, &state->sfx_phase, hz) * volume;
}}

static void audio_callback(void *userdata, uint8_t *stream, int len) {{
    AudioState *state = (AudioState *)userdata;
    float *out = (float *)stream;
    int frames = len / ((int)sizeof(float) * 2);
    static const int title_notes[] = {{659, 784, 988, 784, 659, 0, 523, 659}};
    static const int gameplay_notes[] = {{659, 659, 0, 659, 0, 523, 659, 0, 784, 0, 392, 0}};
    static const int clear_notes[] = {{523, 659, 784, 1046, 784, 1046, 1318, 0}};
    static const int death_notes[] = {{392, 370, 349, 330, 311, 294, 277, 262}};

    for (int i = 0; i < frames; i++) {{
        int mode = state->mode;
        uint64_t step = state->sample_clock / (uint64_t)(state->sample_rate / 8);
        int melody_hz = 0;
        int bass_hz = 0;
        double volume = 0.08;

        if (mode == AUDIO_MODE_TITLE) {{
            melody_hz = title_notes[step % (sizeof(title_notes) / sizeof(title_notes[0]))];
            bass_hz = (step / 2) % 2 == 0 ? 196 : 247;
        }} else if (mode == AUDIO_MODE_STAGE_CLEAR) {{
            melody_hz = clear_notes[step % (sizeof(clear_notes) / sizeof(clear_notes[0]))];
            bass_hz = 262;
            volume = 0.10;
        }} else if (mode == AUDIO_MODE_DEATH) {{
            melody_hz = death_notes[step % (sizeof(death_notes) / sizeof(death_notes[0]))];
            bass_hz = 0;
            volume = 0.09;
        }} else {{
            melody_hz = gameplay_notes[step % (sizeof(gameplay_notes) / sizeof(gameplay_notes[0]))];
            bass_hz = (step / 4) % 2 == 0 ? 130 : 196;
        }}

        double sample = square_sample(state, &state->melody_phase, (double)melody_hz) * volume;
        sample += triangle_sample(state, &state->bass_phase, (double)bass_hz) * 0.035;
        sample += sfx_sample(state);
        out[i * 2] = (float)sample;
        out[i * 2 + 1] = (float)sample;
        state->sample_clock++;
    }}
}}

static SDL_AudioDeviceID open_native_audio(AudioState *state) {{
    SDL_AudioSpec want;
    SDL_AudioSpec have;
    SDL_zero(want);
    want.freq = AUDIO_RATE;
    want.format = AUDIO_F32SYS;
    want.channels = 2;
    want.samples = 1024;
    want.callback = audio_callback;
    want.userdata = state;
    state->sample_rate = AUDIO_RATE;
    SDL_AudioDeviceID device = SDL_OpenAudioDevice(NULL, 0, &want, &have, 0);
    if (!device) {{
        fprintf(stderr, "audio disabled: %s\\n", SDL_GetError());
        return 0;
    }}
    state->sample_rate = have.freq;
    SDL_PauseAudioDevice(device, 0);
    return device;
}}

static void set_audio_mode(SDL_AudioDeviceID device, AudioState *state, int mode) {{
    if (!device) return;
    SDL_LockAudioDevice(device);
    state->mode = mode;
    state->sample_clock = 0;
    state->melody_phase = 0.0;
    state->bass_phase = 0.0;
    SDL_UnlockAudioDevice(device);
}}

static void trigger_sfx(SDL_AudioDeviceID device, AudioState *state, int kind) {{
    if (!device) return;
    SDL_LockAudioDevice(device);
    state->sfx_kind = kind;
    state->sfx_clock = 0;
    state->sfx_phase = 0.0;
    SDL_UnlockAudioDevice(device);
}}

static int stage_clear_x(int level_w) {{
    int trigger = level_w - 192;
    return trigger > 0 ? trigger : 0;
}}

static void draw_level(uint32_t *frame, const uint8_t *level, int level_w, int camera_x) {{
    for (int y = 0; y < SCREEN_H; y++) {{
        int sy = y < LEVEL_H ? y : LEVEL_H - 1;
        for (int x = 0; x < SCREEN_W; x++) {{
            int sx = camera_x + x;
            if (sx < 0) sx = 0;
            if (sx >= level_w) sx = level_w - 1;
            size_t i = ((size_t)sy * LEVEL_W + sx) * 3;
            frame[(size_t)y * SCREEN_W + x] = 0xFF000000u | ((uint32_t)level[i] << 16) |
                ((uint32_t)level[i + 1] << 8) | (uint32_t)level[i + 2];
        }}
    }}
}}

static void draw_rgb_image(uint32_t *frame, const uint8_t *image, int image_w, int image_h) {{
    for (int y = 0; y < SCREEN_H; y++) {{
        int sy = y < image_h ? y : image_h - 1;
        for (int x = 0; x < SCREEN_W; x++) {{
            int sx = x < image_w ? x : image_w - 1;
            size_t i = ((size_t)sy * image_w + sx) * 3;
            frame[(size_t)y * SCREEN_W + x] = 0xFF000000u | ((uint32_t)image[i] << 16) |
                ((uint32_t)image[i + 1] << 8) | (uint32_t)image[i + 2];
        }}
    }}
}}

static void draw_rgb_tile(
    uint32_t *frame,
    const uint8_t *tile,
    int tile_w,
    int tile_h,
    int x,
    int y
) {{
    for (int py = 0; py < tile_h; py++) {{
        int dy = y + py;
        if (dy < 0 || dy >= SCREEN_H) continue;
        for (int px = 0; px < tile_w; px++) {{
            int dx = x + px;
            if (dx < 0 || dx >= SCREEN_W) continue;
            size_t si = ((size_t)py * tile_w + px) * 3;
            frame[(size_t)dy * SCREEN_W + dx] = 0xFF000000u |
                ((uint32_t)tile[si] << 16) | ((uint32_t)tile[si + 1] << 8) | tile[si + 2];
        }}
    }}
}}

static void hud_pixel(uint32_t *frame, int x, int y, uint32_t color) {{
    if (x < 0 || x >= SCREEN_W || y < 0 || y >= SCREEN_H) return;
    frame[(size_t)y * SCREEN_W + x] = color;
}}

static uint8_t hud_glyph_row(char ch, int row) {{
    static const uint8_t digits[10][7] = {{
        {{0x0E, 0x11, 0x13, 0x15, 0x19, 0x11, 0x0E}},
        {{0x04, 0x0C, 0x04, 0x04, 0x04, 0x04, 0x0E}},
        {{0x0E, 0x11, 0x01, 0x02, 0x04, 0x08, 0x1F}},
        {{0x1E, 0x01, 0x01, 0x0E, 0x01, 0x01, 0x1E}},
        {{0x02, 0x06, 0x0A, 0x12, 0x1F, 0x02, 0x02}},
        {{0x1F, 0x10, 0x10, 0x1E, 0x01, 0x01, 0x1E}},
        {{0x0E, 0x10, 0x10, 0x1E, 0x11, 0x11, 0x0E}},
        {{0x1F, 0x01, 0x02, 0x04, 0x08, 0x08, 0x08}},
        {{0x0E, 0x11, 0x11, 0x0E, 0x11, 0x11, 0x0E}},
        {{0x0E, 0x11, 0x11, 0x0F, 0x01, 0x01, 0x0E}},
    }};
    if (ch >= '0' && ch <= '9') return digits[ch - '0'][row];
    switch (ch) {{
        case 'A': return (uint8_t[]){{0x0E, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11}}[row];
        case 'C': return (uint8_t[]){{0x0F, 0x10, 0x10, 0x10, 0x10, 0x10, 0x0F}}[row];
        case 'D': return (uint8_t[]){{0x1E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x1E}}[row];
        case 'E': return (uint8_t[]){{0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x1F}}[row];
        case 'I': return (uint8_t[]){{0x1F, 0x04, 0x04, 0x04, 0x04, 0x04, 0x1F}}[row];
        case 'L': return (uint8_t[]){{0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x1F}}[row];
        case 'M': return (uint8_t[]){{0x11, 0x1B, 0x15, 0x15, 0x11, 0x11, 0x11}}[row];
        case 'O': return (uint8_t[]){{0x0E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E}}[row];
        case 'R': return (uint8_t[]){{0x1E, 0x11, 0x11, 0x1E, 0x14, 0x12, 0x11}}[row];
        case 'S': return (uint8_t[]){{0x0F, 0x10, 0x10, 0x0E, 0x01, 0x01, 0x1E}}[row];
        case 'T': return (uint8_t[]){{0x1F, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04}}[row];
        case 'V': return (uint8_t[]){{0x11, 0x11, 0x11, 0x11, 0x11, 0x0A, 0x04}}[row];
        case 'W': return (uint8_t[]){{0x11, 0x11, 0x11, 0x15, 0x15, 0x1B, 0x11}}[row];
        case '-': return (uint8_t[]){{0x00, 0x00, 0x00, 0x1F, 0x00, 0x00, 0x00}}[row];
        default: return 0x00;
    }}
}}

static void draw_hud_char(uint32_t *frame, char ch, int x, int y, uint32_t color) {{
    for (int row = 0; row < 7; row++) {{
        uint8_t bits = hud_glyph_row(ch, row);
        for (int col = 0; col < 5; col++) {{
            if (bits & (1 << (4 - col))) hud_pixel(frame, x + col, y + row, color);
        }}
    }}
}}

static void draw_hud_text(uint32_t *frame, const char *text, int x, int y, uint32_t color) {{
    for (int i = 0; text[i] != '\\0'; i++) {{
        if (text[i] != ' ') draw_hud_char(frame, text[i], x + i * 6, y, color);
    }}
}}

static void draw_hud_number(uint32_t *frame, int value, int digits, int x, int y, uint32_t color) {{
    if (value < 0) value = 0;
    int divisor = 1;
    for (int i = 1; i < digits; i++) divisor *= 10;
    for (int i = 0; i < digits; i++) {{
        int digit = (value / divisor) % 10;
        draw_hud_char(frame, (char)('0' + digit), x + i * 6, y, color);
        divisor /= 10;
    }}
}}

static void draw_hud(
    uint32_t *frame,
    int score,
    int coins,
    int time_left,
    int lives,
    bool stage_clear,
    const char *stage_label
) {{
    uint32_t shadow = 0xFF000000u;
    uint32_t color = stage_clear ? 0xFFFFFF40u : 0xFFFFFFFFu;
    draw_hud_text(frame, "MARIO", 8, 8, shadow);
    draw_hud_text(frame, "MARIO", 7, 7, color);
    draw_hud_number(frame, score, 6, 7, 16, color);
    draw_hud_text(frame, "COIN", 69, 7, color);
    draw_hud_number(frame, coins, 2, 76, 16, color);
    draw_hud_text(frame, "WORLD", 124, 7, color);
    draw_hud_text(frame, stage_label, 132, 16, color);
    draw_hud_text(frame, "TIME", 196, 7, color);
    draw_hud_number(frame, time_left, 3, 200, 16, color);
    draw_hud_text(frame, "LIVES", 8, 28, color);
    draw_hud_number(frame, lives, 1, 44, 28, color);
}}

static bool block_is_breakable(const Block *block) {{
    return block->metatile == 0x51 || block->metatile == 0x52;
}}

static Block *block_at(Block *blocks, int world_x, int world_y) {{
    int tile_x = (world_x / TILE_SIZE) * TILE_SIZE;
    int tile_y = (world_y / TILE_SIZE) * TILE_SIZE;
    for (int i = 0; i < BLOCK_COUNT; i++) {{
        if (blocks[i].broken) continue;
        if ((int)blocks[i].x == tile_x && (int)blocks[i].y == tile_y) return &blocks[i];
    }}
    return NULL;
}}

static const Block *const_block_at(const Block *blocks, int world_x, int world_y) {{
    int tile_x = (world_x / TILE_SIZE) * TILE_SIZE;
    int tile_y = (world_y / TILE_SIZE) * TILE_SIZE;
    for (int i = 0; i < BLOCK_COUNT; i++) {{
        if ((int)blocks[i].x == tile_x && (int)blocks[i].y == tile_y) return &blocks[i];
    }}
    return NULL;
}}

static bool solid_at(
    const uint8_t *collision,
    const Block *blocks,
    int level_w,
    int world_x,
    int world_y
) {{
    if (world_x < 0 || world_x >= level_w) return true;
    if (world_y >= LEVEL_H) return true;
    if (world_y < 0) return false;
    const Block *block = const_block_at(blocks, world_x, world_y);
    if (block && block->broken) return false;
    int col = world_x / TILE_SIZE;
    int row = world_y / TILE_SIZE;
    if (col < 0 || col >= COLLISION_COLS || row < 0 || row >= COLLISION_ROWS) return false;
    return collision[row * COLLISION_COLS + col] != 0;
}}

static bool rect_hits_solid(
    const uint8_t *collision,
    const Block *blocks,
    int level_w,
    float x,
    float y,
    int w,
    int h
) {{
    int left = (int)x;
    int right = (int)(x + w - 1);
    int top = (int)y;
    int bottom = (int)(y + h - 1);
    return solid_at(collision, blocks, level_w, left, top) ||
        solid_at(collision, blocks, level_w, right, top) ||
        solid_at(collision, blocks, level_w, left, bottom) ||
        solid_at(collision, blocks, level_w, right, bottom);
}}

static bool rects_overlap(float ax, float ay, int aw, int ah, float bx, float by, int bw, int bh) {{
    return ax < bx + bw && ax + aw > bx && ay < by + bh && ay + ah > by;
}}

static bool shell_is_moving(const Enemy *enemy) {{
    return enemy->kind == KOOPA_SHELL_KIND && (enemy->vx < -1.0f || enemy->vx > 1.0f);
}}

static bool load_enemies(const uint8_t *data, Enemy *enemies) {{
    for (int i = 0; i < ENEMY_COUNT; i++) {{
        size_t o = (size_t)i * ENEMY_RECORD_BYTES;
        uint16_t x = (uint16_t)data[o] | ((uint16_t)data[o + 1] << 8);
        uint8_t y = data[o + 2];
        uint8_t kind = data[o + 3];
        enemies[i].x = (float)x;
        enemies[i].y = (float)y;
        enemies[i].vx = -36.0f;
        enemies[i].vy = 0.0f;
        enemies[i].kind = kind;
        enemies[i].alive = data[o + 4] == 0;
    }}
    return true;
}}

static bool load_blocks(const uint8_t *data, Block *blocks) {{
    for (int i = 0; i < BLOCK_COUNT; i++) {{
        size_t o = (size_t)i * BLOCK_RECORD_BYTES;
        blocks[i].x = (uint16_t)data[o] | ((uint16_t)data[o + 1] << 8);
        blocks[i].y = data[o + 2];
        blocks[i].metatile = data[o + 3];
        blocks[i].used = data[o + 4] == 1;
        blocks[i].broken = data[o + 4] == 2;
    }}
    return true;
}}

static void draw_used_blocks(uint32_t *frame, const Block *blocks, const uint8_t *used_block, int camera_x) {{
    for (int i = 0; i < BLOCK_COUNT; i++) {{
        if (blocks[i].broken) continue;
        if (!blocks[i].used) continue;
        draw_rgb_tile(frame, used_block, USED_BLOCK_W, USED_BLOCK_H, (int)blocks[i].x - camera_x, blocks[i].y);
    }}
}}

static void draw_broken_blocks(uint32_t *frame, const Block *blocks, const uint8_t *level, int camera_x) {{
    uint32_t sky = 0xFF000000u | ((uint32_t)level[0] << 16) |
        ((uint32_t)level[1] << 8) | level[2];
    for (int i = 0; i < BLOCK_COUNT; i++) {{
        if (!blocks[i].broken) continue;
        int x = (int)blocks[i].x - camera_x;
        int y = blocks[i].y;
        for (int py = 0; py < TILE_SIZE; py++) {{
            int dy = y + py;
            if (dy < 0 || dy >= SCREEN_H) continue;
            for (int px = 0; px < TILE_SIZE; px++) {{
                int dx = x + px;
                if (dx < 0 || dx >= SCREEN_W) continue;
                frame[(size_t)dy * SCREEN_W + dx] = sky;
            }}
        }}
    }}
}}

static void draw_coin_effect(
    uint32_t *frame,
    const CoinEffect *coin_effect,
    uint8_t **coin_frames,
    uint32_t now,
    int camera_x
) {{
    if (!coin_effect->active) return;
    uint32_t elapsed = now - coin_effect->started_at;
    if (elapsed >= 650) return;
    int coin_frame = (elapsed / 80) % COIN_FRAME_COUNT;
    float t = (float)elapsed / 650.0f;
    float arc = -46.0f * (1.0f - (2.0f * t - 1.0f) * (2.0f * t - 1.0f));
    draw_sprite(
        frame,
        coin_frames[coin_frame],
        COIN_W,
        COIN_H,
        (int)coin_effect->x - camera_x,
        (int)(coin_effect->y + arc),
        false
    );
}}

static void draw_brick_chunk_effect(
    uint32_t *frame,
    const BrickChunkEffect *brick_effect,
    const uint8_t *brick_chunk,
    uint32_t now,
    int camera_x
) {{
    if (!brick_effect->active) return;
    uint32_t elapsed = now - brick_effect->started_at;
    if (elapsed >= 700) return;
    float t = (float)elapsed / 1000.0f;
    static const float vx[4] = {{-74.0f, -42.0f, 42.0f, 74.0f}};
    static const float vy[4] = {{-165.0f, -118.0f, -118.0f, -165.0f}};
    static const float ox[4] = {{0.0f, 7.0f, 1.0f, 8.0f}};
    static const float oy[4] = {{0.0f, 1.0f, 8.0f, 9.0f}};
    for (int i = 0; i < 4; i++) {{
        float px = brick_effect->x + ox[i] + vx[i] * t;
        float py = brick_effect->y + oy[i] + vy[i] * t + 360.0f * t * t;
        draw_sprite(frame, brick_chunk, BRICK_CHUNK_W, BRICK_CHUNK_H, (int)px - camera_x, (int)py, i >= 2);
    }}
}}

static void spawn_mushroom(Powerup *powerup, const Block *block) {{
    powerup->active = true;
    powerup->emerging = true;
    powerup->x = (float)block->x;
    powerup->y = (float)block->y;
    powerup->vx = 36.0f;
    powerup->vy = 0.0f;
    powerup->target_y = (float)block->y - MUSHROOM_H;
}}

static void update_powerup(
    Powerup *powerup,
    const uint8_t *collision,
    const Block *blocks,
    int level_w,
    float dt
) {{
    if (!powerup->active) return;
    if (powerup->emerging) {{
        powerup->y -= 22.0f * dt;
        if (powerup->y <= powerup->target_y) {{
            powerup->y = powerup->target_y;
            powerup->emerging = false;
        }}
        return;
    }}
    powerup->vy += 620.0f * dt;
    float next_x = powerup->x + powerup->vx * dt;
    if (rect_hits_solid(collision, blocks, level_w, next_x, powerup->y, MUSHROOM_W, MUSHROOM_H)) {{
        powerup->vx = -powerup->vx;
    }} else {{
        powerup->x = next_x;
    }}
    float next_y = powerup->y + powerup->vy * dt;
    if (!rect_hits_solid(collision, blocks, level_w, powerup->x, next_y, MUSHROOM_W, MUSHROOM_H)) {{
        powerup->y = next_y;
    }} else if (powerup->vy > 0.0f) {{
        int tile_y = ((int)(powerup->y + MUSHROOM_H + powerup->vy * dt)) / TILE_SIZE;
        powerup->y = (float)(tile_y * TILE_SIZE - MUSHROOM_H);
        powerup->vy = 0.0f;
    }} else {{
        powerup->vy = 0.0f;
    }}
}}

static int enemy_width(const Enemy *enemy) {{
    if (enemy->kind == KOOPA_SHELL_KIND) return KOOPA_SHELL_W;
    return enemy->kind == 0x00 ? KOOPA_W : GOOMBA_W;
}}

static int enemy_height(const Enemy *enemy) {{
    if (enemy->kind == KOOPA_SHELL_KIND) return KOOPA_SHELL_H;
    return enemy->kind == 0x00 ? KOOPA_H : GOOMBA_H;
}}

static const uint8_t *enemy_sprite(
    const Enemy *enemy,
    const uint8_t *goomba,
    const uint8_t *koopa,
    const uint8_t *koopa_shell
) {{
    if (enemy->kind == KOOPA_SHELL_KIND) return koopa_shell;
    return enemy->kind == 0x00 ? koopa : goomba;
}}

static const uint8_t *mario_sprite(
    uint8_t **small_mario_frames,
    uint8_t **big_mario_frames,
    bool mario_big,
    bool on_ground,
    float vx,
    uint32_t ticks
) {{
    uint8_t **frames = mario_big ? big_mario_frames : small_mario_frames;
    if (!on_ground) return frames[4];
    if (vx < -1.0f || vx > 1.0f) {{
        uint32_t frame = (ticks / 90) % 3;
        return frames[1 + frame];
    }}
    return frames[0];
}}

static int mario_width(bool mario_big) {{
    return mario_big ? BIG_MARIO_W : SMALL_MARIO_W;
}}

static int mario_height(bool mario_big) {{
    return mario_big ? BIG_MARIO_H : SMALL_MARIO_H;
}}

static void update_window_title(
    SDL_Window *window,
    const char *stage_label,
    int score,
    int coins,
    int time_left,
    int lives
) {{
    char title[256];
    snprintf(
        title,
        sizeof(title),
        "%s  %s  Score %06d  Coins %02d  Time %03d  Lives %d",
        APP_TITLE,
        stage_label,
        score,
        coins,
        time_left,
        lives
    );
    SDL_SetWindowTitle(window, title);
}}

static void update_title_screen_window_title(SDL_Window *window) {{
    char title[256];
    snprintf(title, sizeof(title), "%s  PRESS ENTER OR SPACE", APP_TITLE);
    SDL_SetWindowTitle(window, title);
}}

static void update_stage_clear_title(
    SDL_Window *window,
    const char *stage_label,
    int score,
    int coins,
    int time_left,
    int lives
) {{
    char title[256];
    snprintf(
        title,
        sizeof(title),
        "%s  %s CLEAR  Score %06d  Coins %02d  Time %03d  Lives %d",
        APP_TITLE,
        stage_label,
        score,
        coins,
        time_left,
        lives
    );
    SDL_SetWindowTitle(window, title);
}}

static void reset_level_state(
    const uint8_t *block_data,
    Block *blocks,
    const uint8_t *enemy_data,
    Enemy *enemies,
    CoinEffect *coin_effect,
    BrickChunkEffect *brick_effect,
    Powerup *powerup,
    float *mario_x,
    float *mario_y,
    float *vx,
    float *vy,
    bool *mario_big,
    bool *on_ground,
    bool *player_dead,
    bool *stage_clear,
    int *time_left,
    uint32_t *invulnerable_until,
    uint32_t *timer_started_at
) {{
    load_blocks(block_data, blocks);
    load_enemies(enemy_data, enemies);
    coin_effect->active = false;
    brick_effect->active = false;
    powerup->active = false;
    powerup->emerging = false;
    *mario_x = MARIO_START_X;
    *mario_y = MARIO_START_Y;
    *vx = 0.0f;
    *vy = 0.0f;
    *mario_big = false;
    *on_ground = false;
    *player_dead = false;
    *stage_clear = false;
    *time_left = STARTING_TIME;
    *invulnerable_until = 0;
    *timer_started_at = SDL_GetTicks();
}}

static void begin_death(
    bool *player_dead,
    uint32_t *death_started_at,
    int *lives,
    float *vx,
    float *vy,
    bool *on_ground,
    uint32_t now,
    SDL_Window *window,
    const char *stage_label,
    int score,
    int coins,
    int time_left
) {{
    if (*player_dead) return;
    *player_dead = true;
    *death_started_at = now;
    *vx = 0.0f;
    *vy = -210.0f;
    *on_ground = false;
    if (*lives > 0) *lives -= 1;
    update_window_title(window, stage_label, score, coins, time_left, *lives);
}}

static void begin_stage_clear(
    bool *stage_clear,
    uint32_t *stage_clear_started_at,
    int *score,
    int *time_left,
    float *vx,
    float *vy,
    bool *on_ground,
    uint32_t now,
    SDL_Window *window,
    const char *stage_label,
    int coins,
    int lives
) {{
    if (*stage_clear) return;
    *stage_clear = true;
    *stage_clear_started_at = now;
    *score += *time_left * SCORE_TIME_BONUS;
    *time_left = 0;
    *vx = 0.0f;
    *vy = 0.0f;
    *on_ground = true;
    update_stage_clear_title(window, stage_label, *score, coins, *time_left, lives);
}}

static void draw_sprite(
    uint32_t *frame,
    const uint8_t *sprite,
    int sprite_w,
    int sprite_h,
    int x,
    int y,
    bool flip
) {{
    for (int py = 0; py < sprite_h; py++) {{
        int dy = y + py;
        if (dy < 0 || dy >= SCREEN_H) continue;
        for (int px = 0; px < sprite_w; px++) {{
            int sx = flip ? (sprite_w - 1 - px) : px;
            int dx = x + px;
            if (dx < 0 || dx >= SCREEN_W) continue;
            size_t si = ((size_t)py * sprite_w + sx) * 4;
            uint8_t a = sprite[si + 3];
            if (a < 16) continue;
            frame[(size_t)dy * SCREEN_W + dx] = 0xFF000000u |
                ((uint32_t)sprite[si] << 16) | ((uint32_t)sprite[si + 1] << 8) | sprite[si + 2];
        }}
    }}
}}

int main(int argc, char **argv) {{
    const char *base = SDL_GetBasePath();
    char title_screen_path[4096];
    char used_block_path[4096];
    char coin_path_0[4096];
    char coin_path_1[4096];
    char coin_path_2[4096];
    char coin_path_3[4096];
    char mushroom_path[4096];
    char brick_chunk_path[4096];
    char mario_path_0[4096];
    char mario_path_1[4096];
    char mario_path_2[4096];
    char mario_path_3[4096];
    char mario_path_4[4096];
    char big_mario_path_0[4096];
    char big_mario_path_1[4096];
    char big_mario_path_2[4096];
    char big_mario_path_3[4096];
    char big_mario_path_4[4096];
    char dead_mario_path[4096];
    char goomba_path[4096];
    char koopa_path[4096];
    char koopa_shell_path[4096];
    snprintf(title_screen_path, sizeof(title_screen_path), "%sassets/title_screen.rgb", base ? base : "");
    snprintf(used_block_path, sizeof(used_block_path), "%sassets/used_empty_block.rgb", base ? base : "");
    snprintf(coin_path_0, sizeof(coin_path_0), "%sassets/jumping_coin_frame_0.rgba", base ? base : "");
    snprintf(coin_path_1, sizeof(coin_path_1), "%sassets/jumping_coin_frame_1.rgba", base ? base : "");
    snprintf(coin_path_2, sizeof(coin_path_2), "%sassets/jumping_coin_frame_2.rgba", base ? base : "");
    snprintf(coin_path_3, sizeof(coin_path_3), "%sassets/jumping_coin_frame_3.rgba", base ? base : "");
    snprintf(mushroom_path, sizeof(mushroom_path), "%sassets/mushroom.rgba", base ? base : "");
    snprintf(brick_chunk_path, sizeof(brick_chunk_path), "%sassets/brick_chunk.rgba", base ? base : "");
    snprintf(mario_path_0, sizeof(mario_path_0), "%sassets/mario_small_stand.rgba", base ? base : "");
    snprintf(mario_path_1, sizeof(mario_path_1), "%sassets/mario_small_walk_1.rgba", base ? base : "");
    snprintf(mario_path_2, sizeof(mario_path_2), "%sassets/mario_small_walk_2.rgba", base ? base : "");
    snprintf(mario_path_3, sizeof(mario_path_3), "%sassets/mario_small_walk_3.rgba", base ? base : "");
    snprintf(mario_path_4, sizeof(mario_path_4), "%sassets/mario_small_jump.rgba", base ? base : "");
    snprintf(big_mario_path_0, sizeof(big_mario_path_0), "%sassets/mario_big_stand.rgba", base ? base : "");
    snprintf(big_mario_path_1, sizeof(big_mario_path_1), "%sassets/mario_big_walk_1.rgba", base ? base : "");
    snprintf(big_mario_path_2, sizeof(big_mario_path_2), "%sassets/mario_big_walk_2.rgba", base ? base : "");
    snprintf(big_mario_path_3, sizeof(big_mario_path_3), "%sassets/mario_big_walk_3.rgba", base ? base : "");
    snprintf(big_mario_path_4, sizeof(big_mario_path_4), "%sassets/mario_big_jump.rgba", base ? base : "");
    snprintf(dead_mario_path, sizeof(dead_mario_path), "%sassets/mario_small_killed.rgba", base ? base : "");
    snprintf(goomba_path, sizeof(goomba_path), "%sassets/goomba.rgba", base ? base : "");
    snprintf(koopa_path, sizeof(koopa_path), "%sassets/koopa_troopa.rgba", base ? base : "");
    snprintf(koopa_shell_path, sizeof(koopa_shell_path), "%sassets/koopa_shell.rgba", base ? base : "");

    uint8_t *levels[STAGE_COUNT];
    uint8_t *collisions[STAGE_COUNT];
    uint8_t *block_sets[STAGE_COUNT];
    uint8_t *enemy_sets[STAGE_COUNT];
    bool stages_loaded = true;
    for (int i = 0; i < STAGE_COUNT; i++) {{
        levels[i] = read_bundled_asset(base, STAGE_LEVEL_FILES[i], (size_t)LEVEL_W * LEVEL_H * 3);
        collisions[i] = read_bundled_asset(base, STAGE_COLLISION_FILES[i], (size_t)COLLISION_COLS * COLLISION_ROWS);
        block_sets[i] = read_bundled_asset(base, STAGE_BLOCK_FILES[i], (size_t)BLOCK_COUNT * BLOCK_RECORD_BYTES);
        enemy_sets[i] = read_bundled_asset(base, STAGE_ENEMY_FILES[i], (size_t)ENEMY_COUNT * ENEMY_RECORD_BYTES);
        if (!levels[i] || !collisions[i] || !block_sets[i] || !enemy_sets[i]) stages_loaded = false;
    }}

    uint8_t *title_screen = read_asset(title_screen_path, (size_t)TITLE_SCREEN_W * TITLE_SCREEN_H * 3);
    uint8_t *used_block = read_asset(used_block_path, (size_t)USED_BLOCK_W * USED_BLOCK_H * 3);
    uint8_t *coin_frames[COIN_FRAME_COUNT];
    coin_frames[0] = read_asset(coin_path_0, (size_t)COIN_W * COIN_H * 4);
    coin_frames[1] = read_asset(coin_path_1, (size_t)COIN_W * COIN_H * 4);
    coin_frames[2] = read_asset(coin_path_2, (size_t)COIN_W * COIN_H * 4);
    coin_frames[3] = read_asset(coin_path_3, (size_t)COIN_W * COIN_H * 4);
    uint8_t *mushroom = read_asset(mushroom_path, (size_t)MUSHROOM_W * MUSHROOM_H * 4);
    uint8_t *brick_chunk = read_asset(brick_chunk_path, (size_t)BRICK_CHUNK_W * BRICK_CHUNK_H * 4);
    uint8_t *small_mario_frames[MARIO_FRAME_COUNT];
    small_mario_frames[0] = read_asset(mario_path_0, (size_t)SMALL_MARIO_W * SMALL_MARIO_H * 4);
    small_mario_frames[1] = read_asset(mario_path_1, (size_t)SMALL_MARIO_W * SMALL_MARIO_H * 4);
    small_mario_frames[2] = read_asset(mario_path_2, (size_t)SMALL_MARIO_W * SMALL_MARIO_H * 4);
    small_mario_frames[3] = read_asset(mario_path_3, (size_t)SMALL_MARIO_W * SMALL_MARIO_H * 4);
    small_mario_frames[4] = read_asset(mario_path_4, (size_t)SMALL_MARIO_W * SMALL_MARIO_H * 4);
    uint8_t *big_mario_frames[MARIO_FRAME_COUNT];
    big_mario_frames[0] = read_asset(big_mario_path_0, (size_t)BIG_MARIO_W * BIG_MARIO_H * 4);
    big_mario_frames[1] = read_asset(big_mario_path_1, (size_t)BIG_MARIO_W * BIG_MARIO_H * 4);
    big_mario_frames[2] = read_asset(big_mario_path_2, (size_t)BIG_MARIO_W * BIG_MARIO_H * 4);
    big_mario_frames[3] = read_asset(big_mario_path_3, (size_t)BIG_MARIO_W * BIG_MARIO_H * 4);
    big_mario_frames[4] = read_asset(big_mario_path_4, (size_t)BIG_MARIO_W * BIG_MARIO_H * 4);
    uint8_t *dead_mario = read_asset(dead_mario_path, (size_t)DEAD_MARIO_W * DEAD_MARIO_H * 4);
    uint8_t *goomba = read_asset(goomba_path, (size_t)GOOMBA_W * GOOMBA_H * 4);
    uint8_t *koopa = read_asset(koopa_path, (size_t)KOOPA_W * KOOPA_H * 4);
    uint8_t *koopa_shell = read_asset(koopa_shell_path, (size_t)KOOPA_SHELL_W * KOOPA_SHELL_H * 4);
    bool mario_loaded = true;
    for (int i = 0; i < MARIO_FRAME_COUNT; i++) {{
        if (!small_mario_frames[i] || !big_mario_frames[i]) mario_loaded = false;
    }}
    bool coins_loaded = true;
    for (int i = 0; i < COIN_FRAME_COUNT; i++) {{
        if (!coin_frames[i]) coins_loaded = false;
    }}
    if (!stages_loaded || !title_screen || !used_block || !coins_loaded || !mushroom || !brick_chunk || !mario_loaded || !dead_mario || !goomba || !koopa || !koopa_shell) return 2;
    int current_stage = 0;
    const char *stage_label = STAGE_LABELS[current_stage];
    int current_level_w = STAGE_LEVEL_WIDTHS[current_stage];
    uint8_t *level = levels[current_stage];
    uint8_t *collision = collisions[current_stage];
    uint8_t *block_data = block_sets[current_stage];
    uint8_t *enemy_data = enemy_sets[current_stage];
    Block blocks[BLOCK_COUNT > 0 ? BLOCK_COUNT : 1];
    Enemy enemies[ENEMY_COUNT > 0 ? ENEMY_COUNT : 1];
    load_blocks(block_data, blocks);
    load_enemies(enemy_data, enemies);

    if (argc > 1 && SDL_strcmp(argv[1], "--self-test") == 0) {{
        for (int i = 0; i < STAGE_COUNT; i++) {{
            free(levels[i]);
            free(collisions[i]);
            free(block_sets[i]);
            free(enemy_sets[i]);
        }}
        free(title_screen);
        free(used_block);
        for (int i = 0; i < COIN_FRAME_COUNT; i++) free(coin_frames[i]);
        free(mushroom);
        free(brick_chunk);
        for (int i = 0; i < MARIO_FRAME_COUNT; i++) {{
            free(small_mario_frames[i]);
            free(big_mario_frames[i]);
        }}
        free(dead_mario);
        free(goomba);
        free(koopa);
        free(koopa_shell);
        return 0;
    }}

    if (SDL_Init(SDL_INIT_VIDEO | SDL_INIT_AUDIO | SDL_INIT_GAMECONTROLLER) != 0) {{
        fprintf(stderr, "SDL_Init failed: %s\\n", SDL_GetError());
        return 3;
    }}
    SDL_Window *window = SDL_CreateWindow(APP_TITLE, SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED,
        SCREEN_W * SCALE, SCREEN_H * SCALE, SDL_WINDOW_SHOWN);
    SDL_Renderer *renderer = SDL_CreateRenderer(window, -1, SDL_RENDERER_ACCELERATED | SDL_RENDERER_PRESENTVSYNC);
    if (!renderer) renderer = SDL_CreateRenderer(window, -1, SDL_RENDERER_SOFTWARE);
    SDL_Texture *texture = SDL_CreateTexture(renderer, SDL_PIXELFORMAT_ARGB8888,
        SDL_TEXTUREACCESS_STREAMING, SCREEN_W, SCREEN_H);
    uint32_t *frame = (uint32_t *)malloc((size_t)SCREEN_W * SCREEN_H * sizeof(uint32_t));
    if (!window || !renderer || !texture || !frame) {{
        fprintf(stderr, "SDL setup failed: %s\\n", SDL_GetError());
        return 4;
    }}
    AudioState audio_state = {{AUDIO_RATE, 0, 0.0, 0.0, 0.0, 0, SFX_NONE, AUDIO_MODE_TITLE}};
    SDL_AudioDeviceID audio_device = open_native_audio(&audio_state);

    float mario_x = MARIO_START_X;
    float mario_y = MARIO_START_Y;
    float vx = 0.0f;
    float vy = 0.0f;
    bool running = true;
    bool facing_left = false;
    bool on_ground = false;
    bool mario_big = false;
    bool player_dead = false;
    bool stage_clear = false;
    bool title_screen_active = true;
    uint32_t death_started_at = 0;
    uint32_t stage_clear_started_at = 0;
    uint32_t timer_started_at = SDL_GetTicks();
    int score = 0;
    int coins = 0;
    int time_left = STARTING_TIME;
    int lives = STARTING_LIVES;
    uint32_t invulnerable_until = 0;
    CoinEffect coin_effect = {{false, 0.0f, 0.0f, 0}};
    BrickChunkEffect brick_effect = {{false, 0.0f, 0.0f, 0}};
    Powerup powerup = {{false, false, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f}};
    uint32_t last = SDL_GetTicks();
    update_title_screen_window_title(window);

    while (running) {{
        SDL_Event e;
        while (SDL_PollEvent(&e)) {{
            if (e.type == SDL_QUIT) running = false;
            if (e.type == SDL_KEYDOWN && e.key.keysym.sym == SDLK_ESCAPE) running = false;
            if (
                title_screen_active &&
                e.type == SDL_KEYDOWN &&
                (e.key.keysym.sym == SDLK_RETURN || e.key.keysym.sym == SDLK_SPACE)
            ) {{
                title_screen_active = false;
                timer_started_at = SDL_GetTicks();
                last = timer_started_at;
                set_audio_mode(audio_device, &audio_state, AUDIO_MODE_GAMEPLAY);
                update_window_title(window, stage_label, score, coins, time_left, lives);
            }}
        }}

        uint32_t now = SDL_GetTicks();
        float dt = (float)(now - last) / 1000.0f;
        if (dt > 0.05f) dt = 0.05f;
        last = now;

        if (title_screen_active) {{
            draw_rgb_image(frame, title_screen, TITLE_SCREEN_W, TITLE_SCREEN_H);
            SDL_UpdateTexture(texture, NULL, frame, SCREEN_W * (int)sizeof(uint32_t));
            SDL_RenderClear(renderer);
            SDL_RenderCopy(renderer, texture, NULL, NULL);
            SDL_RenderPresent(renderer);
            continue;
        }}

        const uint8_t *keys = SDL_GetKeyboardState(NULL);
        float move = 0.0f;
        if (keys[SDL_SCANCODE_LEFT] || keys[SDL_SCANCODE_A]) move -= 1.0f;
        if (keys[SDL_SCANCODE_RIGHT] || keys[SDL_SCANCODE_D]) move += 1.0f;
        if (!player_dead && !stage_clear && move < 0) facing_left = true;
        if (!player_dead && !stage_clear && move > 0) facing_left = false;
        bool run = keys[SDL_SCANCODE_LSHIFT] || keys[SDL_SCANCODE_RSHIFT] || keys[SDL_SCANCODE_J];
        float player_speed = run ? RUN_SPEED : WALK_SPEED;
        vx = (player_dead || stage_clear) ? 0.0f : move * player_speed;
        bool jump = keys[SDL_SCANCODE_SPACE] || keys[SDL_SCANCODE_UP] || keys[SDL_SCANCODE_W];
        if (!player_dead && !stage_clear && jump && on_ground) {{
            vy = -245.0f;
            trigger_sfx(audio_device, &audio_state, SFX_JUMP);
        }}
        if (!player_dead && !stage_clear) {{
            int elapsed_seconds = (int)((now - timer_started_at) / 1000);
            int next_time_left = STARTING_TIME - elapsed_seconds;
            if (next_time_left < 0) next_time_left = 0;
            if (next_time_left != time_left) {{
                time_left = next_time_left;
                update_window_title(window, stage_label, score, coins, time_left, lives);
            }}
            if (time_left <= 0) {{
                begin_death(
                    &player_dead,
                    &death_started_at,
                    &lives,
                    &vx,
                    &vy,
                    &on_ground,
                    now,
                    window,
                    stage_label,
                    score,
                    coins,
                    time_left
                );
                set_audio_mode(audio_device, &audio_state, AUDIO_MODE_DEATH);
            }}
        }}

        int player_w = mario_width(mario_big);
        int player_h = mario_height(mario_big);
        if (player_dead) {{
            vy += 620.0f * dt;
            mario_y += vy * dt;
            if (now - death_started_at >= DEATH_RESTART_MS) {{
                if (lives <= 0) {{
                    lives = STARTING_LIVES;
                    score = 0;
                    coins = 0;
                }}
                reset_level_state(
                    block_data,
                    blocks,
                    enemy_data,
                    enemies,
                    &coin_effect,
                    &brick_effect,
                    &powerup,
                    &mario_x,
                    &mario_y,
                    &vx,
                    &vy,
                    &mario_big,
                    &on_ground,
                    &player_dead,
                    &stage_clear,
                    &time_left,
                    &invulnerable_until,
                    &timer_started_at
                );
                set_audio_mode(audio_device, &audio_state, AUDIO_MODE_GAMEPLAY);
                update_window_title(window, stage_label, score, coins, time_left, lives);
            }}
        }} else if (stage_clear) {{
            if (now - stage_clear_started_at >= STAGE_CLEAR_RESTART_MS) {{
                current_stage = (current_stage + 1) % STAGE_COUNT;
                stage_label = STAGE_LABELS[current_stage];
                current_level_w = STAGE_LEVEL_WIDTHS[current_stage];
                level = levels[current_stage];
                collision = collisions[current_stage];
                block_data = block_sets[current_stage];
                enemy_data = enemy_sets[current_stage];
                reset_level_state(
                    block_data,
                    blocks,
                    enemy_data,
                    enemies,
                    &coin_effect,
                    &brick_effect,
                    &powerup,
                    &mario_x,
                    &mario_y,
                    &vx,
                    &vy,
                    &mario_big,
                    &on_ground,
                    &player_dead,
                    &stage_clear,
                    &time_left,
                    &invulnerable_until,
                    &timer_started_at
                );
                set_audio_mode(audio_device, &audio_state, AUDIO_MODE_GAMEPLAY);
                update_window_title(window, stage_label, score, coins, time_left, lives);
            }}
        }} else {{
        vy += 620.0f * dt;
        float next_x = mario_x + vx * dt;
        if (!rect_hits_solid(collision, blocks, current_level_w, next_x, mario_y, player_w, player_h)) {{
            mario_x = next_x;
        }}
        float next_y = mario_y + vy * dt;
        on_ground = false;
        if (!rect_hits_solid(collision, blocks, current_level_w, mario_x, next_y, player_w, player_h)) {{
            mario_y = next_y;
        }} else if (vy > 0.0f) {{
            int tile_y = ((int)(mario_y + player_h + vy * dt)) / TILE_SIZE;
            mario_y = (float)(tile_y * TILE_SIZE - player_h);
            vy = 0.0f;
            on_ground = true;
        }} else {{
            Block *hit = block_at(blocks, (int)(mario_x + player_w / 2), (int)next_y);
            if (hit && !hit->used) {{
                if (block_is_breakable(hit) && mario_big) {{
                    hit->broken = true;
                    score += SCORE_BRICK;
                    brick_effect.active = true;
                    brick_effect.x = (float)hit->x;
                    brick_effect.y = (float)hit->y;
                    brick_effect.started_at = now;
                    trigger_sfx(audio_device, &audio_state, SFX_BRICK);
                    update_window_title(window, stage_label, score, coins, time_left, lives);
                }} else if (!block_is_breakable(hit)) {{
                    hit->used = true;
                    if (hit->metatile == 0x57) {{
                        spawn_mushroom(&powerup, hit);
                    }} else {{
                        score += SCORE_COIN;
                        coins += 1;
                        trigger_sfx(audio_device, &audio_state, SFX_COIN);
                        coin_effect.active = true;
                        coin_effect.x = (float)hit->x + 4.0f;
                        coin_effect.y = (float)hit->y - 8.0f;
                        coin_effect.started_at = now;
                        update_window_title(window, stage_label, score, coins, time_left, lives);
                    }}
                }}
            }}
            vy = 0.0f;
        }}
        if (mario_x < 0.0f) mario_x = 0.0f;
        if (mario_x > current_level_w - player_w) mario_x = current_level_w - player_w;
        update_powerup(&powerup, collision, blocks, current_level_w, dt);
        if (powerup.active && rects_overlap(mario_x, mario_y, player_w, player_h, powerup.x, powerup.y, MUSHROOM_W, MUSHROOM_H)) {{
            powerup.active = false;
            if (!mario_big) {{
                mario_y -= (float)(BIG_MARIO_H - SMALL_MARIO_H);
                mario_big = true;
            }}
            score += SCORE_MUSHROOM;
            coins += 10;
            trigger_sfx(audio_device, &audio_state, SFX_POWERUP);
            update_window_title(window, stage_label, score, coins, time_left, lives);
        }}
        player_w = mario_width(mario_big);
        player_h = mario_height(mario_big);

        if (mario_y > LEVEL_H + 32.0f) {{
            begin_death(
                &player_dead,
                &death_started_at,
                &lives,
                &vx,
                &vy,
                &on_ground,
                now,
                window,
                stage_label,
                score,
                coins,
                time_left
            );
            set_audio_mode(audio_device, &audio_state, AUDIO_MODE_DEATH);
        }}
        if (mario_x >= stage_clear_x(current_level_w)) {{
            begin_stage_clear(
                &stage_clear,
                &stage_clear_started_at,
                &score,
                &time_left,
                &vx,
                &vy,
                &on_ground,
                now,
                window,
                stage_label,
                coins,
                lives
            );
            set_audio_mode(audio_device, &audio_state, AUDIO_MODE_STAGE_CLEAR);
        }}

        for (int i = 0; i < ENEMY_COUNT; i++) {{
            Enemy *enemy = &enemies[i];
            if (!enemy->alive) continue;
            int ew = enemy_width(enemy);
            int eh = enemy_height(enemy);
            enemy->vy += 620.0f * dt;
            float gx = enemy->x + enemy->vx * dt;
            if (rect_hits_solid(collision, blocks, current_level_w, gx, enemy->y, ew, eh)) {{
                enemy->vx = -enemy->vx;
            }} else {{
                enemy->x = gx;
            }}
            float gy = enemy->y + enemy->vy * dt;
            if (!rect_hits_solid(collision, blocks, current_level_w, enemy->x, gy, ew, eh)) {{
                enemy->y = gy;
            }} else if (enemy->vy > 0.0f) {{
                int tile_y = ((int)(enemy->y + eh + enemy->vy * dt)) / TILE_SIZE;
                enemy->y = (float)(tile_y * TILE_SIZE - eh);
                enemy->vy = 0.0f;
            }} else {{
                enemy->vy = 0.0f;
            }}
            int probe_x = enemy->vx < 0.0f ? (int)enemy->x - 2 : (int)(enemy->x + ew + 2);
            int foot_y = (int)(enemy->y + eh + 2);
            if (!solid_at(collision, blocks, current_level_w, probe_x, foot_y)) {{
                enemy->vx = -enemy->vx;
            }}
            if (rects_overlap(mario_x, mario_y, player_w, player_h, enemy->x, enemy->y, ew, eh)) {{
                bool shell_stationary = enemy->kind == KOOPA_SHELL_KIND && !shell_is_moving(enemy);
                if (vy > 40.0f && mario_y + player_h - 4.0f < enemy->y + 8.0f) {{
                    if (enemy->kind == 0x00) {{
                        enemy->kind = KOOPA_SHELL_KIND;
                        enemy->vx = 0.0f;
                        enemy->vy = 0.0f;
                        enemy->y += (float)(KOOPA_H - KOOPA_SHELL_H);
                    }} else if (enemy->kind == KOOPA_SHELL_KIND) {{
                        enemy->vx = 0.0f;
                        enemy->vy = 0.0f;
                    }} else {{
                        enemy->alive = false;
                    }}
                    score += SCORE_STOMP;
                    trigger_sfx(audio_device, &audio_state, SFX_STOMP);
                    update_window_title(window, stage_label, score, coins, time_left, lives);
                    vy = -160.0f;
                }} else if (shell_stationary) {{
                    enemy->vx = mario_x < enemy->x ? KOOPA_SHELL_SPEED : -KOOPA_SHELL_SPEED;
                    if (mario_x < enemy->x) {{
                        mario_x = enemy->x - (float)player_w - 1.0f;
                    }} else {{
                        mario_x = enemy->x + (float)ew + 1.0f;
                    }}
                    score += SCORE_SHELL_KICK;
                    trigger_sfx(audio_device, &audio_state, SFX_SHELL_KICK);
                    update_window_title(window, stage_label, score, coins, time_left, lives);
                }} else if (now < invulnerable_until) {{
                    continue;
                }} else if (mario_big) {{
                    mario_big = false;
                    mario_y += (float)(BIG_MARIO_H - SMALL_MARIO_H);
                    invulnerable_until = now + INVULNERABLE_MS;
                    trigger_sfx(audio_device, &audio_state, SFX_POWERUP);
                }} else {{
                    begin_death(
                        &player_dead,
                        &death_started_at,
                        &lives,
                        &vx,
                        &vy,
                        &on_ground,
                        now,
                        window,
                        stage_label,
                        score,
                        coins,
                        time_left
                    );
                    set_audio_mode(audio_device, &audio_state, AUDIO_MODE_DEATH);
                }}
            }}
        }}

        for (int i = 0; i < ENEMY_COUNT; i++) {{
            Enemy *shell = &enemies[i];
            if (!shell->alive || !shell_is_moving(shell)) continue;
            int sw = enemy_width(shell);
            int sh = enemy_height(shell);
            for (int j = 0; j < ENEMY_COUNT; j++) {{
                if (i == j) continue;
                Enemy *target = &enemies[j];
                if (!target->alive || target->kind == KOOPA_SHELL_KIND) continue;
                int tw = enemy_width(target);
                int th = enemy_height(target);
                if (rects_overlap(shell->x, shell->y, sw, sh, target->x, target->y, tw, th)) {{
                    target->alive = false;
                    score += SCORE_SHELL_HIT;
                    trigger_sfx(audio_device, &audio_state, SFX_STOMP);
                    update_window_title(window, stage_label, score, coins, time_left, lives);
                }}
            }}
        }}
        }}

        int camera = (int)mario_x - 96;
        if (camera < 0) camera = 0;
        if (camera > current_level_w - SCREEN_W) camera = current_level_w - SCREEN_W;
        draw_level(frame, level, current_level_w, camera);
        draw_hud(frame, score, coins, time_left, lives, stage_clear, stage_label);
        draw_broken_blocks(frame, blocks, level, camera);
        draw_used_blocks(frame, blocks, used_block, camera);
        if (coin_effect.active && now - coin_effect.started_at >= 650) coin_effect.active = false;
        if (brick_effect.active && now - brick_effect.started_at >= 700) brick_effect.active = false;
        draw_coin_effect(frame, &coin_effect, coin_frames, now, camera);
        draw_brick_chunk_effect(frame, &brick_effect, brick_chunk, now, camera);
        if (powerup.active) {{
            draw_sprite(frame, mushroom, MUSHROOM_W, MUSHROOM_H, (int)powerup.x - camera, (int)powerup.y, false);
        }}
        for (int i = 0; i < ENEMY_COUNT; i++) {{
            Enemy *enemy = &enemies[i];
            if (!enemy->alive) continue;
            draw_sprite(
                frame,
                enemy_sprite(enemy, goomba, koopa, koopa_shell),
                enemy_width(enemy),
                enemy_height(enemy),
                (int)enemy->x - camera,
                (int)enemy->y,
                enemy->vx > 0.0f
            );
        }}
        if (player_dead) {{
            draw_sprite(
                frame,
                dead_mario,
                DEAD_MARIO_W,
                DEAD_MARIO_H,
                (int)mario_x - camera,
                (int)mario_y,
                facing_left
            );
        }} else {{
            bool mario_visible = now >= invulnerable_until || ((now / 90) % 2 == 0);
            if (mario_visible) {{
            draw_sprite(
                frame,
                mario_sprite(small_mario_frames, big_mario_frames, mario_big, on_ground, vx, now),
                mario_width(mario_big),
                mario_height(mario_big),
                (int)mario_x - camera,
                (int)mario_y,
                facing_left
            );
            }}
        }}

        SDL_UpdateTexture(texture, NULL, frame, SCREEN_W * (int)sizeof(uint32_t));
        SDL_RenderClear(renderer);
        SDL_RenderCopy(renderer, texture, NULL, NULL);
        SDL_RenderPresent(renderer);
    }}

    free(frame);
    for (int i = 0; i < STAGE_COUNT; i++) {{
        free(levels[i]);
        free(collisions[i]);
        free(block_sets[i]);
        free(enemy_sets[i]);
    }}
    free(title_screen);
    free(used_block);
    for (int i = 0; i < COIN_FRAME_COUNT; i++) free(coin_frames[i]);
    free(mushroom);
    free(brick_chunk);
    for (int i = 0; i < MARIO_FRAME_COUNT; i++) {{
        free(small_mario_frames[i]);
        free(big_mario_frames[i]);
    }}
    free(dead_mario);
    free(goomba);
    free(koopa);
    free(koopa_shell);
    if (audio_device) SDL_CloseAudioDevice(audio_device);
    SDL_DestroyTexture(texture);
    SDL_DestroyRenderer(renderer);
    SDL_DestroyWindow(window);
    SDL_Quit();
    return 0;
}}
"""


def _build_sh(app_slug: str) -> str:
    return f"""#!/usr/bin/env sh
set -eu
command -v pkg-config >/dev/null 2>&1 || {{ echo "pkg-config is required" >&2; exit 1; }}
pkg-config --exists sdl2 || {{ echo "SDL2 development files are required (pkg-config sdl2)" >&2; exit 1; }}
mkdir -p dist
cc -O2 -Wall -Wextra src/main.c -o "dist/{app_slug}" $(pkg-config --cflags --libs sdl2)
mkdir -p dist/assets
cp assets/*.bin assets/*.rgb assets/*.rgba dist/assets/
"""


def _appimage_sh(app_slug: str, app_name: str) -> str:
    return f"""#!/usr/bin/env sh
set -eu
./build.sh
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
rm -rf AppDir
mkdir -p AppDir/usr/bin AppDir/usr/lib AppDir/usr/share/applications AppDir/usr/share/icons/hicolor/scalable/apps
cp "dist/{app_slug}" AppDir/usr/bin/
cp -R dist/assets AppDir/usr/bin/assets
cp "{app_slug}.desktop" "AppDir/usr/share/applications/{app_slug}.desktop"
cp "{app_slug}.svg" "AppDir/usr/share/icons/hicolor/scalable/apps/{app_slug}.svg"
SDL_LIB="$(ldd "dist/{app_slug}" | awk '/libSDL2-2.0.so.0/ {{print $3; exit}}')"
if [ -n "$SDL_LIB" ] && [ -f "$SDL_LIB" ]; then
  cp "$SDL_LIB" AppDir/usr/lib/
fi
cat > AppDir/AppRun <<'EOF'
#!/usr/bin/env sh
HERE="$(dirname "$(readlink -f "$0")")"
export LD_LIBRARY_PATH="$HERE/usr/lib:${{LD_LIBRARY_PATH:-}}"
exec "$HERE/usr/bin/{app_slug}" "$@"
EOF
chmod +x AppDir/AppRun
cp "{app_slug}.desktop" "AppDir/{app_slug}.desktop"
cp "{app_slug}.svg" "AppDir/{app_slug}.svg"
"$APPIMAGETOOL" AppDir "{app_slug}.AppImage"
"""


def _icon_svg() -> str:
    return """<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">
<rect width="256" height="256" rx="32" fill="#5c94fc"/>
<rect x="0" y="184" width="256" height="72" fill="#c84c0c"/>
<rect x="56" y="96" width="64" height="80" fill="#d82800"/>
<rect x="80" y="64" width="48" height="32" fill="#f8d878"/>
<rect x="120" y="128" width="32" height="48" fill="#0058f8"/>
<rect x="48" y="176" width="136" height="16" fill="#00a800"/>
</svg>
"""
