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
    _SmbLevelRuntime,
    render_smb_blocks,
    render_smb_characters,
    render_smb_level,
    validate_smb_nrom,
)

SMB_ENEMY_DATA_LOW = 0x00E9
SMB_GREEN_KOOPA_ID = 0x00
SMB_GOOMBA_ID = 0x06
SMB_GOOMBA_GROUPS = {0x37: 2, 0x38: 3, 0x39: 2, 0x3A: 3}
SMB_KOOPA_GROUPS = {0x3B: 2, 0x3C: 3}
SMB_NATIVE_ENEMY_RECORD_BYTES = 5
SMB_NATIVE_BLOCK_RECORD_BYTES = 5
SMB_JUMPING_COIN_FRAME_COUNT = 4
SMB_INTERACTIVE_BLOCK_METATILES = {
    0xC0: "question-block",
    0xC1: "question-block",
    0x5F: "question-block",
    0x60: "question-block",
    0x57: "item-brick",
    0x58: "coin-brick",
}
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

    app_slug = slugify_binary_name(app_name)
    src_dir = out / "src"
    assets_dir = out / "assets"
    build_dir = out / "_asset-build"
    src_dir.mkdir(exist_ok=True)
    assets_dir.mkdir(exist_ok=True)
    build_dir.mkdir(exist_ok=True)

    level = render_smb_level(rom, build_dir / "levels", stage=stage, max_columns=256)
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
    mushroom_png = build_dir / "blocks" / "sprites" / "mushroom.png"
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
    if not mushroom_png.exists():
        raise RuntimeError(f"expected SMB power-up sprite missing: {mushroom_png}")

    level_raw = assets_dir / "level_1_1.rgb"
    collision_raw = assets_dir / "collision_1_1.bin"
    blocks_raw = assets_dir / "blocks_1_1.bin"
    used_block_raw = assets_dir / "used_empty_block.rgb"
    coin_frame_raws = [
        assets_dir / f"jumping_coin_frame_{idx}.rgba" for idx in range(SMB_JUMPING_COIN_FRAME_COUNT)
    ]
    mushroom_raw = assets_dir / "mushroom.rgba"
    goomba_raw = assets_dir / "goomba.rgba"
    koopa_raw = assets_dir / "koopa_troopa.rgba"
    dead_mario_raw = assets_dir / SMB_DEAD_MARIO_SPRITE[1]
    enemies_raw = assets_dir / "enemies_1_1.bin"
    _write_rgb(level.png, level_raw)
    collision_size = _write_collision_map(level.png, collision_raw)
    interactive_blocks, used_block_size = _write_block_interactions(
        rom_bytes,
        stage,
        blocks_raw,
        used_block_raw,
    )
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
    dead_mario_size = _write_rgba(dead_mario_png, dead_mario_raw)
    goomba_size = _write_rgba(goomba_png, goomba_raw)
    koopa_size = _write_rgba(koopa_png, koopa_raw)
    enemy_spawns = _write_enemy_spawns(rom_bytes, stage, enemies_raw)

    main_c = src_dir / "main.c"
    main_c.write_text(
        _main_c_source(
            app_name=app_name,
            level_width=level.width,
            level_height=level.height,
            collision_cols=collision_size[0],
            collision_rows=collision_size[1],
            block_count=len(interactive_blocks),
            block_record_bytes=SMB_NATIVE_BLOCK_RECORD_BYTES,
            used_block_width=used_block_size[0],
            used_block_height=used_block_size[1],
            coin_width=coin_frame_size[0],
            coin_height=coin_frame_size[1],
            coin_frame_count=SMB_JUMPING_COIN_FRAME_COUNT,
            mushroom_width=mushroom_size[0],
            mushroom_height=mushroom_size[1],
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
            enemy_count=len(enemy_spawns),
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
        level_raw,
        collision_raw,
        blocks_raw,
        used_block_raw,
        *coin_frame_raws,
        mushroom_raw,
        *(assets_dir / asset_name for _, asset_name in SMB_SMALL_MARIO_SPRITES),
        *(assets_dir / asset_name for _, asset_name in SMB_BIG_MARIO_SPRITES),
        dead_mario_raw,
        goomba_raw,
        koopa_raw,
        enemies_raw,
        manifest,
    ]
    manifest.write_text(
        json.dumps(
            {
                "kind": "smb_native_port_mvp",
                "app_name": app_name,
                "executable_name": app_slug,
                "stage": stage,
                "rom_source": str(rom),
                "rom_sha256": sha256_file(rom),
                "runtime": "C/SDL2 native side-scroller MVP; no ROM or emulator is bundled",
                "level": {
                    "source_png": str(level.png),
                    "asset": str(level_raw.relative_to(out)),
                    "collision_asset": str(collision_raw.relative_to(out)),
                    "width": level.width,
                    "height": level.height,
                    "columns": level.columns,
                    "rows": level.rows,
                    "collision_columns": collision_size[0],
                    "collision_rows": collision_size[1],
                },
                "stage_clear": {
                    "trigger_x": max(level.width - 192, 0),
                    "restart_ms": 2500,
                    "time_bonus_per_second": 50,
                    "behavior": "native stage-clear state freezes control and restarts the generated level",
                },
                "scoring": {
                    "starting_time": 400,
                    "coin_points": 200,
                    "mushroom_points": 1000,
                    "stomp_points": 100,
                    "stage_clear_time_bonus_per_second": 50,
                },
                "interactive_blocks": {
                    "asset": str(blocks_raw.relative_to(out)),
                    "used_block_asset": str(used_block_raw.relative_to(out)),
                    "jumping_coin_assets": [str(path.relative_to(out)) for path in coin_frame_raws],
                    "jumping_coin_width": coin_frame_size[0],
                    "jumping_coin_height": coin_frame_size[1],
                    "mushroom_asset": str(mushroom_raw.relative_to(out)),
                    "mushroom_width": mushroom_size[0],
                    "mushroom_height": mushroom_size[1],
                    "record_bytes": SMB_NATIVE_BLOCK_RECORD_BYTES,
                    "count": len(interactive_blocks),
                    "blocks": interactive_blocks,
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
                ],
                "enemy_spawns": enemy_spawns,
                "block_manifest": str(block_assets.manifest_json),
                "character_manifest": str(characters.manifest_json),
                "build": {
                    "elf": f"dist/{app_slug}",
                    "appimage": f"{app_slug}.AppImage",
                },
                "notes": [
                    "The generated runtime does not read a .nes file.",
                    "This is a native MVP, not a complete SMB engine yet.",
                    "Controls: arrows or A/D to move, Space/W/Up to jump, Esc to quit.",
                    "Collision is derived from the rendered SMB metatile map at build time.",
                    "Supported enemy spawns are decoded from SMB EnemyData for the selected stage.",
                    "Small and big Mario standing, walking, and jumping sprites are normalized from SMB tables.",
                    "Mario death uses the SMB small-killed metasprite and restarts the native level state.",
                    "Stage clear triggers near the end of the generated level and restarts after a short victory pause.",
                    "Score and timer are tracked natively in the SDL title bar.",
                    "Question/item blocks are decoded from SMB metatiles and can be hit natively.",
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
        stage=stage,
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


def _write_collision_map(source_png: Path, target: Path) -> tuple[int, int]:
    image = Image.open(source_png).convert("RGB")
    cols = image.width // 16
    rows = image.height // 16
    sky = image.getpixel((0, 0))
    cells = bytearray()
    for row in range(rows):
        for col in range(cols):
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
    level_width: int,
    level_height: int,
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
    enemy_count: int,
    enemy_record_bytes: int,
) -> str:
    return f"""#include <SDL2/SDL.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#define APP_TITLE "{app_name}"
#define SCREEN_W 256
#define SCREEN_H 240
#define SCALE 3
#define LEVEL_W {level_width}
#define LEVEL_H {level_height}
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
#define ENEMY_COUNT {enemy_count}
#define ENEMY_RECORD_BYTES {enemy_record_bytes}
#define TILE_SIZE 16
#define MARIO_START_X 48.0f
#define MARIO_START_Y 176.0f
#define STARTING_LIVES 3
#define STARTING_TIME 400
#define DEATH_RESTART_MS 1300
#define STAGE_CLEAR_X {max(level_width - 192, 0)}
#define STAGE_CLEAR_RESTART_MS 2500
#define SCORE_COIN 200
#define SCORE_MUSHROOM 1000
#define SCORE_STOMP 100
#define SCORE_TIME_BONUS 50

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
}} Block;

typedef struct {{
    bool active;
    float x;
    float y;
    uint32_t started_at;
}} CoinEffect;

typedef struct {{
    bool active;
    bool emerging;
    float x;
    float y;
    float vx;
    float vy;
    float target_y;
}} Powerup;

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

static void draw_level(uint32_t *frame, const uint8_t *level, int camera_x) {{
    for (int y = 0; y < SCREEN_H; y++) {{
        int sy = y < LEVEL_H ? y : LEVEL_H - 1;
        for (int x = 0; x < SCREEN_W; x++) {{
            int sx = camera_x + x;
            if (sx < 0) sx = 0;
            if (sx >= LEVEL_W) sx = LEVEL_W - 1;
            size_t i = ((size_t)sy * LEVEL_W + sx) * 3;
            frame[(size_t)y * SCREEN_W + x] = 0xFF000000u | ((uint32_t)level[i] << 16) |
                ((uint32_t)level[i + 1] << 8) | (uint32_t)level[i + 2];
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

static bool solid_at(const uint8_t *collision, int world_x, int world_y) {{
    if (world_x < 0 || world_x >= LEVEL_W) return true;
    if (world_y >= LEVEL_H) return true;
    if (world_y < 0) return false;
    int col = world_x / TILE_SIZE;
    int row = world_y / TILE_SIZE;
    if (col < 0 || col >= COLLISION_COLS || row < 0 || row >= COLLISION_ROWS) return false;
    return collision[row * COLLISION_COLS + col] != 0;
}}

static bool rect_hits_solid(const uint8_t *collision, float x, float y, int w, int h) {{
    int left = (int)x;
    int right = (int)(x + w - 1);
    int top = (int)y;
    int bottom = (int)(y + h - 1);
    return solid_at(collision, left, top) || solid_at(collision, right, top) ||
        solid_at(collision, left, bottom) || solid_at(collision, right, bottom);
}}

static bool rects_overlap(float ax, float ay, int aw, int ah, float bx, float by, int bw, int bh) {{
    return ax < bx + bw && ax + aw > bx && ay < by + bh && ay + ah > by;
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
        enemies[i].alive = true;
    }}
    return true;
}}

static bool load_blocks(const uint8_t *data, Block *blocks) {{
    for (int i = 0; i < BLOCK_COUNT; i++) {{
        size_t o = (size_t)i * BLOCK_RECORD_BYTES;
        blocks[i].x = (uint16_t)data[o] | ((uint16_t)data[o + 1] << 8);
        blocks[i].y = data[o + 2];
        blocks[i].metatile = data[o + 3];
        blocks[i].used = data[o + 4] != 0;
    }}
    return true;
}}

static Block *block_at(Block *blocks, int world_x, int world_y) {{
    int tile_x = (world_x / TILE_SIZE) * TILE_SIZE;
    int tile_y = (world_y / TILE_SIZE) * TILE_SIZE;
    for (int i = 0; i < BLOCK_COUNT; i++) {{
        if ((int)blocks[i].x == tile_x && (int)blocks[i].y == tile_y) return &blocks[i];
    }}
    return NULL;
}}

static void draw_used_blocks(uint32_t *frame, const Block *blocks, const uint8_t *used_block, int camera_x) {{
    for (int i = 0; i < BLOCK_COUNT; i++) {{
        if (!blocks[i].used) continue;
        draw_rgb_tile(frame, used_block, USED_BLOCK_W, USED_BLOCK_H, (int)blocks[i].x - camera_x, blocks[i].y);
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

static void spawn_mushroom(Powerup *powerup, const Block *block) {{
    powerup->active = true;
    powerup->emerging = true;
    powerup->x = (float)block->x;
    powerup->y = (float)block->y;
    powerup->vx = 36.0f;
    powerup->vy = 0.0f;
    powerup->target_y = (float)block->y - MUSHROOM_H;
}}

static void update_powerup(Powerup *powerup, const uint8_t *collision, float dt) {{
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
    if (rect_hits_solid(collision, next_x, powerup->y, MUSHROOM_W, MUSHROOM_H)) {{
        powerup->vx = -powerup->vx;
    }} else {{
        powerup->x = next_x;
    }}
    float next_y = powerup->y + powerup->vy * dt;
    if (!rect_hits_solid(collision, powerup->x, next_y, MUSHROOM_W, MUSHROOM_H)) {{
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
    return enemy->kind == 0x00 ? KOOPA_W : GOOMBA_W;
}}

static int enemy_height(const Enemy *enemy) {{
    return enemy->kind == 0x00 ? KOOPA_H : GOOMBA_H;
}}

static const uint8_t *enemy_sprite(const Enemy *enemy, const uint8_t *goomba, const uint8_t *koopa) {{
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

static void update_window_title(SDL_Window *window, int score, int coins, int time_left, int lives) {{
    char title[256];
    snprintf(
        title,
        sizeof(title),
        "%s  Score %06d  Coins %02d  Time %03d  Lives %d",
        APP_TITLE,
        score,
        coins,
        time_left,
        lives
    );
    SDL_SetWindowTitle(window, title);
}}

static void update_stage_clear_title(SDL_Window *window, int score, int coins, int time_left, int lives) {{
    char title[256];
    snprintf(
        title,
        sizeof(title),
        "%s  STAGE CLEAR  Score %06d  Coins %02d  Time %03d  Lives %d",
        APP_TITLE,
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
    uint32_t *timer_started_at
) {{
    load_blocks(block_data, blocks);
    load_enemies(enemy_data, enemies);
    coin_effect->active = false;
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
    update_window_title(window, score, coins, time_left, *lives);
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
    update_stage_clear_title(window, *score, coins, *time_left, lives);
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
    char level_path[4096];
    char collision_path[4096];
    char blocks_path[4096];
    char used_block_path[4096];
    char coin_path_0[4096];
    char coin_path_1[4096];
    char coin_path_2[4096];
    char coin_path_3[4096];
    char mushroom_path[4096];
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
    char enemies_path[4096];
    snprintf(level_path, sizeof(level_path), "%sassets/level_1_1.rgb", base ? base : "");
    snprintf(collision_path, sizeof(collision_path), "%sassets/collision_1_1.bin", base ? base : "");
    snprintf(blocks_path, sizeof(blocks_path), "%sassets/blocks_1_1.bin", base ? base : "");
    snprintf(used_block_path, sizeof(used_block_path), "%sassets/used_empty_block.rgb", base ? base : "");
    snprintf(coin_path_0, sizeof(coin_path_0), "%sassets/jumping_coin_frame_0.rgba", base ? base : "");
    snprintf(coin_path_1, sizeof(coin_path_1), "%sassets/jumping_coin_frame_1.rgba", base ? base : "");
    snprintf(coin_path_2, sizeof(coin_path_2), "%sassets/jumping_coin_frame_2.rgba", base ? base : "");
    snprintf(coin_path_3, sizeof(coin_path_3), "%sassets/jumping_coin_frame_3.rgba", base ? base : "");
    snprintf(mushroom_path, sizeof(mushroom_path), "%sassets/mushroom.rgba", base ? base : "");
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
    snprintf(enemies_path, sizeof(enemies_path), "%sassets/enemies_1_1.bin", base ? base : "");

    uint8_t *level = read_asset(level_path, (size_t)LEVEL_W * LEVEL_H * 3);
    uint8_t *collision = read_asset(collision_path, (size_t)COLLISION_COLS * COLLISION_ROWS);
    uint8_t *block_data = read_asset(blocks_path, (size_t)BLOCK_COUNT * BLOCK_RECORD_BYTES);
    uint8_t *used_block = read_asset(used_block_path, (size_t)USED_BLOCK_W * USED_BLOCK_H * 3);
    uint8_t *coin_frames[COIN_FRAME_COUNT];
    coin_frames[0] = read_asset(coin_path_0, (size_t)COIN_W * COIN_H * 4);
    coin_frames[1] = read_asset(coin_path_1, (size_t)COIN_W * COIN_H * 4);
    coin_frames[2] = read_asset(coin_path_2, (size_t)COIN_W * COIN_H * 4);
    coin_frames[3] = read_asset(coin_path_3, (size_t)COIN_W * COIN_H * 4);
    uint8_t *mushroom = read_asset(mushroom_path, (size_t)MUSHROOM_W * MUSHROOM_H * 4);
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
    uint8_t *enemy_data = read_asset(enemies_path, (size_t)ENEMY_COUNT * ENEMY_RECORD_BYTES);
    bool mario_loaded = true;
    for (int i = 0; i < MARIO_FRAME_COUNT; i++) {{
        if (!small_mario_frames[i] || !big_mario_frames[i]) mario_loaded = false;
    }}
    bool coins_loaded = true;
    for (int i = 0; i < COIN_FRAME_COUNT; i++) {{
        if (!coin_frames[i]) coins_loaded = false;
    }}
    if (!level || !collision || !block_data || !used_block || !coins_loaded || !mushroom || !mario_loaded || !dead_mario || !goomba || !koopa || !enemy_data) return 2;
    Block blocks[BLOCK_COUNT > 0 ? BLOCK_COUNT : 1];
    Enemy enemies[ENEMY_COUNT > 0 ? ENEMY_COUNT : 1];
    load_blocks(block_data, blocks);
    load_enemies(enemy_data, enemies);

    if (argc > 1 && SDL_strcmp(argv[1], "--self-test") == 0) {{
        free(level);
        free(collision);
        free(block_data);
        free(used_block);
        for (int i = 0; i < COIN_FRAME_COUNT; i++) free(coin_frames[i]);
        free(mushroom);
        for (int i = 0; i < MARIO_FRAME_COUNT; i++) {{
            free(small_mario_frames[i]);
            free(big_mario_frames[i]);
        }}
        free(dead_mario);
        free(goomba);
        free(koopa);
        free(enemy_data);
        return 0;
    }}

    if (SDL_Init(SDL_INIT_VIDEO | SDL_INIT_GAMECONTROLLER) != 0) {{
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
    uint32_t death_started_at = 0;
    uint32_t stage_clear_started_at = 0;
    uint32_t timer_started_at = SDL_GetTicks();
    int score = 0;
    int coins = 0;
    int time_left = STARTING_TIME;
    int lives = STARTING_LIVES;
    CoinEffect coin_effect = {{false, 0.0f, 0.0f, 0}};
    Powerup powerup = {{false, false, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f}};
    uint32_t last = SDL_GetTicks();
    update_window_title(window, score, coins, time_left, lives);

    while (running) {{
        SDL_Event e;
        while (SDL_PollEvent(&e)) {{
            if (e.type == SDL_QUIT) running = false;
            if (e.type == SDL_KEYDOWN && e.key.keysym.sym == SDLK_ESCAPE) running = false;
        }}
        const uint8_t *keys = SDL_GetKeyboardState(NULL);
        float move = 0.0f;
        if (keys[SDL_SCANCODE_LEFT] || keys[SDL_SCANCODE_A]) move -= 1.0f;
        if (keys[SDL_SCANCODE_RIGHT] || keys[SDL_SCANCODE_D]) move += 1.0f;
        if (!player_dead && !stage_clear && move < 0) facing_left = true;
        if (!player_dead && !stage_clear && move > 0) facing_left = false;
        vx = (player_dead || stage_clear) ? 0.0f : move * 100.0f;
        bool jump = keys[SDL_SCANCODE_SPACE] || keys[SDL_SCANCODE_UP] || keys[SDL_SCANCODE_W];
        if (!player_dead && !stage_clear && jump && on_ground) vy = -245.0f;

        uint32_t now = SDL_GetTicks();
        float dt = (float)(now - last) / 1000.0f;
        if (dt > 0.05f) dt = 0.05f;
        last = now;
        if (!player_dead && !stage_clear) {{
            int elapsed_seconds = (int)((now - timer_started_at) / 1000);
            int next_time_left = STARTING_TIME - elapsed_seconds;
            if (next_time_left < 0) next_time_left = 0;
            if (next_time_left != time_left) {{
                time_left = next_time_left;
                update_window_title(window, score, coins, time_left, lives);
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
                    score,
                    coins,
                    time_left
                );
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
                    &timer_started_at
                );
                update_window_title(window, score, coins, time_left, lives);
            }}
        }} else if (stage_clear) {{
            if (now - stage_clear_started_at >= STAGE_CLEAR_RESTART_MS) {{
                reset_level_state(
                    block_data,
                    blocks,
                    enemy_data,
                    enemies,
                    &coin_effect,
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
                    &timer_started_at
                );
                update_window_title(window, score, coins, time_left, lives);
            }}
        }} else {{
        vy += 620.0f * dt;
        float next_x = mario_x + vx * dt;
        if (!rect_hits_solid(collision, next_x, mario_y, player_w, player_h)) {{
            mario_x = next_x;
        }}
        float next_y = mario_y + vy * dt;
        on_ground = false;
        if (!rect_hits_solid(collision, mario_x, next_y, player_w, player_h)) {{
            mario_y = next_y;
        }} else if (vy > 0.0f) {{
            int tile_y = ((int)(mario_y + player_h + vy * dt)) / TILE_SIZE;
            mario_y = (float)(tile_y * TILE_SIZE - player_h);
            vy = 0.0f;
            on_ground = true;
        }} else {{
            Block *hit = block_at(blocks, (int)(mario_x + player_w / 2), (int)next_y);
            if (hit && !hit->used) {{
                hit->used = true;
                if (hit->metatile == 0x57) {{
                    spawn_mushroom(&powerup, hit);
                }} else {{
                    score += SCORE_COIN;
                    coins += 1;
                    coin_effect.active = true;
                    coin_effect.x = (float)hit->x + 4.0f;
                    coin_effect.y = (float)hit->y - 8.0f;
                    coin_effect.started_at = now;
                    update_window_title(window, score, coins, time_left, lives);
                }}
            }}
            vy = 0.0f;
        }}
        if (mario_x < 0.0f) mario_x = 0.0f;
        if (mario_x > LEVEL_W - player_w) mario_x = LEVEL_W - player_w;
        update_powerup(&powerup, collision, dt);
        if (powerup.active && rects_overlap(mario_x, mario_y, player_w, player_h, powerup.x, powerup.y, MUSHROOM_W, MUSHROOM_H)) {{
            powerup.active = false;
            if (!mario_big) {{
                mario_y -= (float)(BIG_MARIO_H - SMALL_MARIO_H);
                mario_big = true;
            }}
            score += SCORE_MUSHROOM;
            coins += 10;
            update_window_title(window, score, coins, time_left, lives);
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
                score,
                coins,
                time_left
            );
        }}
        if (mario_x >= STAGE_CLEAR_X) {{
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
                coins,
                lives
            );
        }}

        for (int i = 0; i < ENEMY_COUNT; i++) {{
            Enemy *enemy = &enemies[i];
            if (!enemy->alive) continue;
            int ew = enemy_width(enemy);
            int eh = enemy_height(enemy);
            enemy->vy += 620.0f * dt;
            float gx = enemy->x + enemy->vx * dt;
            if (rect_hits_solid(collision, gx, enemy->y, ew, eh)) {{
                enemy->vx = -enemy->vx;
            }} else {{
                enemy->x = gx;
            }}
            float gy = enemy->y + enemy->vy * dt;
            if (!rect_hits_solid(collision, enemy->x, gy, ew, eh)) {{
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
            if (!solid_at(collision, probe_x, foot_y)) {{
                enemy->vx = -enemy->vx;
            }}
            if (rects_overlap(mario_x, mario_y, player_w, player_h, enemy->x, enemy->y, ew, eh)) {{
                if (vy > 40.0f && mario_y + player_h - 4.0f < enemy->y + 8.0f) {{
                    enemy->alive = false;
                    score += SCORE_STOMP;
                    update_window_title(window, score, coins, time_left, lives);
                    vy = -160.0f;
                }} else if (mario_big) {{
                    mario_big = false;
                    mario_y += (float)(BIG_MARIO_H - SMALL_MARIO_H);
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
                        score,
                        coins,
                        time_left
                    );
                }}
            }}
        }}
        }}

        int camera = (int)mario_x - 96;
        if (camera < 0) camera = 0;
        if (camera > LEVEL_W - SCREEN_W) camera = LEVEL_W - SCREEN_W;
        draw_level(frame, level, camera);
        draw_used_blocks(frame, blocks, used_block, camera);
        if (coin_effect.active && now - coin_effect.started_at >= 650) coin_effect.active = false;
        draw_coin_effect(frame, &coin_effect, coin_frames, now, camera);
        if (powerup.active) {{
            draw_sprite(frame, mushroom, MUSHROOM_W, MUSHROOM_H, (int)powerup.x - camera, (int)powerup.y, false);
        }}
        for (int i = 0; i < ENEMY_COUNT; i++) {{
            Enemy *enemy = &enemies[i];
            if (!enemy->alive) continue;
            draw_sprite(
                frame,
                enemy_sprite(enemy, goomba, koopa),
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

        SDL_UpdateTexture(texture, NULL, frame, SCREEN_W * (int)sizeof(uint32_t));
        SDL_RenderClear(renderer);
        SDL_RenderCopy(renderer, texture, NULL, NULL);
        SDL_RenderPresent(renderer);
    }}

    free(frame);
    free(level);
    free(collision);
    free(block_data);
    free(used_block);
    for (int i = 0; i < COIN_FRAME_COUNT; i++) free(coin_frames[i]);
    free(mushroom);
    for (int i = 0; i < MARIO_FRAME_COUNT; i++) {{
        free(small_mario_frames[i]);
        free(big_mario_frames[i]);
    }}
    free(dead_mario);
    free(goomba);
    free(koopa);
    free(enemy_data);
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
