"""Super Mario Bros. assembled level background export.

This module drives SMB's original level parser in-process, reads the 13-row
metatile column buffer it produces, then renders those metatiles through the
ROM's CHR and palette data.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from py65.devices.mpu6502 import MPU

from .assets import TILE_BYTES, decode_tile
from .audio.in_process.memory import NROMMemory
from .ines import parse_header, strip_ines
from .sprites import NES_RGB_PALETTE, chr_from_ines

SMB_LOAD_AREA_POINTER = 0x9C03
SMB_INITIALIZE_AREA = 0x8FE4
SMB_AREA_PARSER_CORE = 0x93FC
SMB_INCREMENT_COLUMN_POS = 0x92DB

SMB_WORLD_NUMBER = 0x075F
SMB_AREA_NUMBER = 0x0760
SMB_AREA_POINTER = 0x0750
SMB_HALFWAY_PAGE = 0x075B
SMB_ALT_ENTRANCE_CONTROL = 0x0752
SMB_PRIMARY_HARD_MODE = 0x076A
SMB_OPER_MODE_TASK = 0x0772
SMB_AREA_TYPE = 0x074E
SMB_METATILE_BUFFER = 0x06A1

SMB_VRAM_ADDRTABLE_LOW = 0x805A
SMB_VRAM_ADDRTABLE_HIGH = 0x806D
SMB_METATILE_GRAPHICS_LOW = 0x8B08
SMB_METATILE_GRAPHICS_HIGH = 0x8B0C
SMB_PLAYER_GRAPHICS_TABLE = 0xEE17
SMB_ENEMY_GRAPHICS_TABLE = 0xE73E
SMB_JUMPING_COIN_TILES = 0xF99E
SMB_POWERUP_GFX_TABLE = 0xF9AA
SMB_DEFAULT_BLOCK_OBJ_TILES = 0xFF42
SMB_TITLE_SCREEN_DATA_OFFSET = 0x1EC0

SMB_AREA_PALETTE = (0x01, 0x02, 0x03, 0x04)
SMB_BACKGROUND_COLORS = (0x22, 0x22, 0x0F, 0x0F, 0x0F, 0x22, 0x0F, 0x0F)
SMB_TITLE_PALETTES = (
    (0x22, 0x29, 0x1A, 0x0F),
    (0x22, 0x36, 0x17, 0x0F),
    (0x22, 0x30, 0x21, 0x0F),
    (0x22, 0x27, 0x18, 0x0F),
)
SMB_FONT_PALETTE = (0x22, 0x0F, 0x30, 0x27)
SMB_MARIO_PALETTE = (0x22, 0x16, 0x27, 0x18)
SMB_GREEN_ENEMY_PALETTE = (0x22, 0x1A, 0x30, 0x27)
SMB_RED_ENEMY_PALETTE = (0x22, 0x16, 0x28, 0x18)
SMB_MISC_ENEMY_PALETTE = (0x22, 0x0F, 0x30, 0x27)
SMB_RETURN_SENTINEL = 0x6000
SMB_SUBROUTINE_BUDGET = 100_000

AREA_TYPE_NAMES = {
    0: "water",
    1: "ground",
    2: "underground",
    3: "castle",
}

WORLD_MAP: dict[str, tuple[int, int] | int] = {
    # Values are (public world number, internal AreaNumber). SMB inserts
    # short pipe-intro areas before some main stages; keep public labels mapped
    # to the actual playable area and expose the intros with explicit names.
    "1-1": (1, 0),
    "1-2-intro": (1, 1),
    "1-2": (1, 2),
    "1-3": (1, 3),
    "1-4": (1, 4),
    "2-1": (2, 0),
    "2-2-intro": (2, 1),
    "2-2": (2, 2),
    "2-3": (2, 3),
    "2-4": (2, 4),
    "3-1": (3, 0),
    "3-2": (3, 1),
    "3-3": (3, 2),
    "3-4": (3, 3),
    "4-1": (4, 0),
    "4-2-intro": (4, 1),
    "4-2": (4, 2),
    "4-3": (4, 3),
    "4-4": (4, 4),
    "5-1": (5, 0),
    "5-2": (5, 1),
    "5-3": (5, 2),
    "5-4": (5, 3),
    "6-1": (6, 0),
    "6-2": (6, 1),
    "6-3": (6, 2),
    "6-4": (6, 3),
    "7-1": (7, 0),
    "7-2-intro": (7, 1),
    "7-2": (7, 2),
    "7-3": (7, 3),
    "7-4": (7, 4),
    "8-1": (8, 0),
    "8-2": (8, 1),
    "8-3": (8, 2),
    "8-4": (8, 3),
}
WORLD_MAP.update(
    {
        "bonus": 0xC2,
        "cloud1": 0x2B,
        "cloud2": 0x34,
        "water1": 0x00,
        "water2": 0x02,
        "warp": 0x2F,
    }
)

PLAYER_METASPRITES: tuple[tuple[str, int], ...] = (
    ("big-walk-1", 0x00),
    ("big-walk-2", 0x08),
    ("big-walk-3", 0x10),
    ("big-skid", 0x18),
    ("big-jump", 0x20),
    ("big-swim-1", 0x28),
    ("big-swim-2", 0x30),
    ("big-swim-3", 0x38),
    ("big-climb-1", 0x40),
    ("big-climb-2", 0x48),
    ("big-crouch", 0x50),
    ("big-fireball", 0x58),
    ("small-walk-1", 0x60),
    ("small-walk-2", 0x68),
    ("small-walk-3", 0x70),
    ("small-skid", 0x78),
    ("small-jump", 0x80),
    ("small-swim-1", 0x88),
    ("small-swim-2", 0x90),
    ("small-swim-3", 0x98),
    ("small-climb-1", 0xA0),
    ("small-climb-2", 0xA8),
    ("small-killed", 0xB0),
    ("small-stand", 0xB8),
    ("grow-intermediate", 0xC0),
    ("big-stand", 0xC8),
)

ENEMY_METASPRITES: tuple[tuple[str, int, tuple[int, int, int, int]], ...] = (
    ("buzzy-beetle-1", 0x00, SMB_MISC_ENEMY_PALETTE),
    ("buzzy-beetle-2", 0x06, SMB_MISC_ENEMY_PALETTE),
    ("koopa-troopa-1", 0x0C, SMB_GREEN_ENEMY_PALETTE),
    ("koopa-troopa-2", 0x12, SMB_GREEN_ENEMY_PALETTE),
    ("koopa-paratroopa-1", 0x18, SMB_GREEN_ENEMY_PALETTE),
    ("koopa-paratroopa-2", 0x1E, SMB_GREEN_ENEMY_PALETTE),
    ("spiny-1", 0x24, SMB_RED_ENEMY_PALETTE),
    ("spiny-2", 0x2A, SMB_RED_ENEMY_PALETTE),
    ("spiny-egg-1", 0x30, SMB_RED_ENEMY_PALETTE),
    ("spiny-egg-2", 0x36, SMB_RED_ENEMY_PALETTE),
    ("blooper-1", 0x3C, SMB_MISC_ENEMY_PALETTE),
    ("blooper-2", 0x42, SMB_MISC_ENEMY_PALETTE),
    ("cheep-cheep-1", 0x48, SMB_RED_ENEMY_PALETTE),
    ("cheep-cheep-2", 0x4E, SMB_RED_ENEMY_PALETTE),
    ("goomba", 0x54, SMB_MISC_ENEMY_PALETTE),
    ("koopa-shell-upside-1", 0x5A, SMB_GREEN_ENEMY_PALETTE),
    ("koopa-shell-upside-2", 0x60, SMB_GREEN_ENEMY_PALETTE),
    ("koopa-shell-1", 0x66, SMB_GREEN_ENEMY_PALETTE),
    ("koopa-shell-2", 0x6C, SMB_GREEN_ENEMY_PALETTE),
    ("buzzy-shell-1", 0x72, SMB_MISC_ENEMY_PALETTE),
    ("buzzy-shell-2", 0x78, SMB_MISC_ENEMY_PALETTE),
    ("buzzy-shell-upside-1", 0x7E, SMB_MISC_ENEMY_PALETTE),
    ("buzzy-shell-upside-2", 0x84, SMB_MISC_ENEMY_PALETTE),
    ("goomba-defeated", 0x8A, SMB_MISC_ENEMY_PALETTE),
    ("lakitu-1", 0x90, SMB_GREEN_ENEMY_PALETTE),
    ("lakitu-2", 0x96, SMB_GREEN_ENEMY_PALETTE),
    ("princess", 0x9C, SMB_MARIO_PALETTE),
    ("mushroom-retainer", 0xA2, SMB_GREEN_ENEMY_PALETTE),
    ("hammer-bro-1", 0xA8, SMB_GREEN_ENEMY_PALETTE),
    ("hammer-bro-2", 0xAE, SMB_GREEN_ENEMY_PALETTE),
    ("hammer-bro-3", 0xB4, SMB_GREEN_ENEMY_PALETTE),
    ("hammer-bro-4", 0xBA, SMB_GREEN_ENEMY_PALETTE),
    ("piranha-plant-1", 0xC0, SMB_GREEN_ENEMY_PALETTE),
    ("piranha-plant-2", 0xC6, SMB_GREEN_ENEMY_PALETTE),
    ("podoboo", 0xCC, SMB_RED_ENEMY_PALETTE),
    ("bowser-front-1", 0xD2, SMB_GREEN_ENEMY_PALETTE),
    ("bowser-rear-1", 0xD8, SMB_GREEN_ENEMY_PALETTE),
    ("bowser-front-2", 0xDE, SMB_GREEN_ENEMY_PALETTE),
    ("bowser-rear-2", 0xE4, SMB_GREEN_ENEMY_PALETTE),
    ("bullet-bill", 0xEA, SMB_MISC_ENEMY_PALETTE),
    ("jumpspring-1", 0xF0, SMB_GREEN_ENEMY_PALETTE),
    ("jumpspring-2", 0xF6, SMB_GREEN_ENEMY_PALETTE),
    ("jumpspring-3", 0xFC, SMB_GREEN_ENEMY_PALETTE),
)

IMPORTANT_BLOCK_METATILES: tuple[tuple[str, int], ...] = (
    ("blank", 0x00),
    ("black", 0x01),
    ("row-of-coins-water", 0xC3),
    ("row-of-coins-ground-underground-castle", 0xC2),
    ("used-empty-block", 0xC4),
    ("question-block-state-1", 0xC1),
    ("question-block-state-2", 0xC0),
    ("question-block-state-3", 0x5F),
    ("question-block-state-4", 0x60),
    ("brick-ground-breakable-line", 0x51),
    ("brick-ground-breakable-no-line", 0x52),
    ("brick-ground-item-1", 0x55),
    ("brick-ground-item-2", 0x56),
    ("brick-ground-item-3", 0x57),
    ("brick-ground-coins-line", 0x58),
    ("brick-ground-1up", 0x59),
    ("brick-other-item-1", 0x5A),
    ("brick-other-item-2", 0x5B),
    ("brick-other-item-3", 0x5C),
    ("brick-other-coins-no-line", 0x5D),
    ("brick-other-1up", 0x5E),
    ("row-brick-water", 0x22),
    ("row-brick-ground", 0x51),
    ("row-brick-underground", 0x52),
    ("row-brick-castle", 0x52),
    ("row-brick-cloud-override", 0x88),
    ("solid-block-water", 0x69),
    ("solid-block-ground", 0x61),
    ("solid-block-underground", 0x61),
    ("solid-block-castle", 0x62),
    ("castle-bridge", 0x0C),
    ("castle-axe", 0x89),
    ("castle-chain", 0xC5),
)

POWERUP_METASPRITES: tuple[tuple[str, int, tuple[int, int, int, int]], ...] = (
    ("mushroom", 0x00, SMB_MISC_ENEMY_PALETTE),
    ("fire-flower", 0x04, SMB_GREEN_ENEMY_PALETTE),
    ("star", 0x08, SMB_MISC_ENEMY_PALETTE),
    ("one-up-mushroom", 0x0C, SMB_GREEN_ENEMY_PALETTE),
)


@dataclass(frozen=True)
class SmbLevelExport:
    rom: Path
    stage: str
    png: Path
    manifest_json: Path
    columns: int
    rows: int
    width: int
    height: int
    area_type: int
    unique_metatiles: int
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SmbLevelBatchExport:
    rom: Path
    out_dir: Path
    manifest_json: Path
    levels: list[SmbLevelExport]
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def success_count(self) -> int:
        return len(self.levels)

    @property
    def failure_count(self) -> int:
        return len(self.errors)


@dataclass(frozen=True)
class SmbCharacterExport:
    rom: Path
    out_dir: Path
    spritesheet: Path
    manifest_json: Path
    sprites: list[Path]


@dataclass(frozen=True)
class SmbBlockExport:
    rom: Path
    out_dir: Path
    metatile_sheets: list[Path]
    block_sheets: list[Path]
    sprite_sheet: Path
    manifest_json: Path
    files: list[Path]


@dataclass(frozen=True)
class SmbTitleAssetExport:
    rom: Path
    out_dir: Path
    title_screen: Path
    title_logo: Path
    font_sheet: Path
    title_glyph_sheet: Path
    manifest_json: Path
    files: list[Path]


def validate_smb_nrom(rom_bytes: bytes) -> None:
    """Validate the iNES shape expected by the original SMB renderer."""

    header = parse_header(rom_bytes)
    if header is None:
        raise ValueError("SMB level export requires an iNES ROM")
    if header.mapper != 0:
        raise ValueError(f"SMB level export expects mapper 0/NROM, got mapper {header.mapper}")
    if header.prg_size != 0x8000:
        raise ValueError(f"SMB level export expects 32 KiB PRG, got {header.prg_size}")
    if header.chr_size < 0x2000:
        raise ValueError("SMB level export expects at least one 8 KiB CHR-ROM bank")


class _SmbLevelRuntime:
    def __init__(self, rom_bytes: bytes) -> None:
        validate_smb_nrom(rom_bytes)
        self.prg = strip_ines(rom_bytes)
        self.chr = chr_from_ines(rom_bytes, chr_bank=0)
        self.mem = NROMMemory(self.prg)
        self.cpu = MPU(memory=self.mem, pc=0)

    def read(self, addr: int) -> int:
        return self.mem[addr & 0xFFFF]

    def write(self, addr: int, value: int) -> None:
        self.mem[addr & 0xFFFF] = value & 0xFF

    def call(self, addr: int) -> None:
        ret = (SMB_RETURN_SENTINEL - 1) & 0xFFFF
        self.cpu.sp = 0xFD
        self.mem[0x01FE] = ret & 0xFF
        self.mem[0x01FF] = ret >> 8
        self.cpu.pc = addr
        for _ in range(SMB_SUBROUTINE_BUDGET):
            self.cpu.step()
            if self.cpu.pc == SMB_RETURN_SENTINEL:
                return
        raise RuntimeError(f"SMB subroutine ${addr:04X} did not return")

    def load_stage(self, stage: tuple[int, int] | int, *, max_columns: int) -> list[list[int]]:
        if isinstance(stage, tuple):
            world, internal_area = stage
            if not 1 <= world <= 8 or not 0 <= internal_area <= 4:
                raise ValueError("SMB world stages must use world 1..8 and internal area 0..4")
            self.write(SMB_WORLD_NUMBER, world - 1)
            self.write(SMB_AREA_NUMBER, internal_area)
            self.call(SMB_LOAD_AREA_POINTER)
        else:
            self.write(SMB_AREA_POINTER, stage)

        self.write(SMB_HALFWAY_PAGE, 0)
        self.write(SMB_ALT_ENTRANCE_CONTROL, 0)
        self.write(SMB_PRIMARY_HARD_MODE, 0)
        self.write(SMB_OPER_MODE_TASK, 0)
        self.call(SMB_INITIALIZE_AREA)

        columns: list[list[int]] = []
        for _ in range(max_columns):
            self.call(SMB_AREA_PARSER_CORE)
            columns.append([self.read(SMB_METATILE_BUFFER + i) for i in range(13)])
            self.call(SMB_INCREMENT_COLUMN_POS)
            if len(columns) >= 96 and columns[-48:] == columns[-96:-48]:
                return columns[:-80]
        return columns

    def load_background_palette(self) -> tuple[tuple[tuple[int, int, int], ...], ...]:
        area_type = self.read(SMB_AREA_TYPE)
        return self.load_background_palette_for_area_type(area_type)

    def load_background_palette_for_area_type(
        self,
        area_type: int,
    ) -> tuple[tuple[tuple[int, int, int], ...], ...]:
        idx = SMB_AREA_PALETTE[area_type]
        ptr = (self.read(SMB_VRAM_ADDRTABLE_HIGH + idx) << 8) | self.read(
            SMB_VRAM_ADDRTABLE_LOW + idx
        )
        palette_data = list(self._read_ppu_palette_stream(ptr))
        if len(palette_data) != 32:
            raise RuntimeError(f"SMB palette stream yielded {len(palette_data)} bytes")
        bg_color = SMB_BACKGROUND_COLORS[area_type]
        palettes: list[tuple[tuple[int, int, int], ...]] = []
        for palette_id in range(4):
            values = palette_data[palette_id * 4 : palette_id * 4 + 4]
            values[0] = bg_color
            palettes.append(tuple(NES_RGB_PALETTE[value & 0x3F] for value in values))
        return tuple(palettes)

    def _read_ppu_palette_stream(self, addr: int):
        while True:
            high = self.read(addr)
            if high == 0:
                return
            low = self.read(addr + 1)
            flags_and_length = self.read(addr + 2)
            if high != 0x3F or low != 0x00:
                raise RuntimeError(f"unexpected SMB palette target ${high:02X}{low:02X}")
            if flags_and_length & 0xC0:
                raise RuntimeError("SMB palette stream uses unsupported repeat/increment flags")
            length = flags_and_length & 0x3F
            addr += 3
            for _ in range(length):
                yield self.read(addr)
                addr += 1

    def render_metatile(self, metatile: int, palettes: tuple[tuple[tuple[int, int, int], ...], ...]):
        from PIL import Image

        palette_id = (metatile >> 6) & 0x03
        metatile_id = metatile & 0x3F
        table = (self.read(SMB_METATILE_GRAPHICS_HIGH + palette_id) << 8) | self.read(
            SMB_METATILE_GRAPHICS_LOW + palette_id
        )
        addr = table + metatile_id * 4
        tile_ids = [
            self.read(addr),
            self.read(addr + 2),
            self.read(addr + 1),
            self.read(addr + 3),
        ]
        image = Image.new("RGB", (16, 16))
        for idx, tile_id in enumerate(tile_ids):
            tile = _decode_background_tile(self.chr, tile_id)
            x_off = (idx % 2) * 8
            y_off = (idx // 2) * 8
            for y, row in enumerate(tile):
                for x, color_index in enumerate(row):
                    image.putpixel((x_off + x, y_off + y), palettes[palette_id][color_index])
        return image


def _decode_background_tile(chr_data: bytes, tile_id: int) -> list[list[int]]:
    addr = 0x1000 + tile_id * TILE_BYTES
    if addr + TILE_BYTES > len(chr_data):
        raise ValueError(f"SMB background tile ${tile_id:02X} outside CHR data")
    return decode_tile(chr_data[addr : addr + TILE_BYTES])


def _background_tile_image(
    chr_data: bytes,
    tile_id: int,
    palette: tuple[tuple[int, int, int], ...],
):
    from PIL import Image

    image = Image.new("RGB", (8, 8))
    tile = _decode_background_tile(chr_data, tile_id)
    for y, row in enumerate(tile):
        for x, color_index in enumerate(row):
            image.putpixel((x, y), palette[color_index])
    return image


def _palette_rgb(values: tuple[int, int, int, int]) -> tuple[tuple[int, int, int], ...]:
    return tuple(NES_RGB_PALETTE[value & 0x3F] for value in values)


def _read_cpu_table(prg: bytes, addr: int, length: int) -> list[int]:
    offset = addr - 0x8000
    if offset < 0 or offset + length > len(prg):
        raise ValueError(f"SMB CPU table ${addr:04X}..${addr + length - 1:04X} outside PRG")
    return list(prg[offset : offset + length])


def _decode_sprite_tile_rgba(
    chr_data: bytes,
    tile_id: int,
    palette: tuple[int, int, int, int],
):
    from PIL import Image

    image = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    if tile_id == 0xFC:
        return image

    addr = tile_id * TILE_BYTES
    if addr + TILE_BYTES > len(chr_data):
        raise ValueError(f"SMB sprite tile ${tile_id:02X} outside CHR data")

    tile = decode_tile(chr_data[addr : addr + TILE_BYTES])
    for y, row in enumerate(tile):
        for x, color_index in enumerate(row):
            if color_index == 0:
                continue
            r, g, b = NES_RGB_PALETTE[palette[color_index] & 0x3F]
            image.putpixel((x, y), (r, g, b, 255))
    return image


def _render_metasprite_rgba(
    chr_data: bytes,
    tile_ids: list[int],
    *,
    rows: int,
    palette: tuple[int, int, int, int],
):
    from PIL import Image

    image = Image.new("RGBA", (16, rows * 8), (0, 0, 0, 0))
    for idx, tile_id in enumerate(tile_ids):
        tile = _decode_sprite_tile_rgba(chr_data, tile_id, palette)
        image.alpha_composite(tile, ((idx % 2) * 8, (idx // 2) * 8))

    bbox = image.getchannel("A").getbbox()
    return image.crop(bbox) if bbox is not None else image


def _write_character_spritesheet(
    sprite_paths: list[Path],
    out_path: Path,
    *,
    columns: int = 8,
) -> None:
    from PIL import Image

    images = [Image.open(path).convert("RGBA") for path in sprite_paths]
    try:
        cell_w = max(image.width for image in images)
        cell_h = max(image.height for image in images)
        padding = 4
        rows = (len(images) + columns - 1) // columns
        sheet = Image.new(
            "RGBA",
            (columns * (cell_w + padding) + padding, rows * (cell_h + padding) + padding),
            (0, 0, 0, 0),
        )
        for idx, image in enumerate(images):
            col = idx % columns
            row = idx // columns
            x = padding + col * (cell_w + padding) + (cell_w - image.width) // 2
            y = padding + row * (cell_h + padding) + cell_h - image.height
            sheet.alpha_composite(image, (x, y))
        sheet.save(out_path)
    finally:
        for image in images:
            image.close()


def _write_image_grid(
    images: list[tuple[str, object]],
    out_path: Path,
    *,
    columns: int = 16,
    padding: int = 1,
) -> None:
    from PIL import Image

    opened = [(name, image.convert("RGBA")) for name, image in images]
    try:
        cell_w = max(image.width for _, image in opened)
        cell_h = max(image.height for _, image in opened)
        rows = (len(opened) + columns - 1) // columns
        sheet = Image.new(
            "RGBA",
            (columns * (cell_w + padding) + padding, rows * (cell_h + padding) + padding),
            (0, 0, 0, 0),
        )
        for idx, (_, image) in enumerate(opened):
            col = idx % columns
            row = idx // columns
            x = padding + col * (cell_w + padding) + (cell_w - image.width) // 2
            y = padding + row * (cell_h + padding) + (cell_h - image.height) // 2
            sheet.alpha_composite(image, (x, y))
        sheet.save(out_path)
    finally:
        for _, image in opened:
            image.close()


def _render_jumping_coin(chr_data: bytes, tile_id: int):
    from PIL import Image

    image = Image.new("RGBA", (8, 16), (0, 0, 0, 0))
    top = _decode_sprite_tile_rgba(chr_data, tile_id, SMB_MISC_ENEMY_PALETTE)
    bottom = top.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    image.alpha_composite(top, (0, 0))
    image.alpha_composite(bottom, (0, 8))
    return image


def _parse_smb_title_nametable(
    chr_data: bytes,
) -> tuple[list[int], list[int]]:
    nametable = [0x24] * (32 * 30)
    attributes = [0x00] * 64
    ptr = SMB_TITLE_SCREEN_DATA_OFFSET
    end = min(len(chr_data), ptr + 0x13A)

    while ptr + 3 <= end:
        high = chr_data[ptr]
        if high == 0x00:
            break
        low = chr_data[ptr + 1]
        flags = chr_data[ptr + 2]
        ptr += 3

        addr = (high << 8) | low
        inc = 32 if flags & 0x80 else 1
        repeat = bool(flags & 0x40)
        length = flags & 0x3F
        if length == 0:
            continue

        if repeat:
            value = chr_data[ptr]
            ptr += 1
            values = [value] * length
        else:
            values = list(chr_data[ptr : ptr + length])
            ptr += length

        current = addr
        for value in values:
            offset = current - 0x2000
            if 0 <= offset < len(nametable):
                nametable[offset] = value
            elif 0x03C0 <= offset < 0x0400:
                attributes[offset - 0x03C0] = value
            current += inc

    return nametable, attributes


def _attribute_palette_id(attributes: list[int], tile_x: int, tile_y: int) -> int:
    attr_x = tile_x // 4
    attr_y = tile_y // 4
    attr = attributes[attr_y * 8 + attr_x]
    shift = ((tile_y % 4) // 2) * 4 + ((tile_x % 4) // 2) * 2
    return (attr >> shift) & 0x03


def _render_title_nametable(
    chr_data: bytes,
    nametable: list[int],
    attributes: list[int],
):
    from PIL import Image

    palettes = tuple(_palette_rgb(palette) for palette in SMB_TITLE_PALETTES)
    image = Image.new("RGB", (32 * 8, 30 * 8), palettes[0][0])
    tile_cache: dict[tuple[int, int], object] = {}
    for tile_y in range(30):
        for tile_x in range(32):
            tile_id = nametable[tile_y * 32 + tile_x]
            palette_id = _attribute_palette_id(attributes, tile_x, tile_y)
            key = (tile_id, palette_id)
            tile = tile_cache.get(key)
            if tile is None:
                tile = _background_tile_image(chr_data, tile_id, palettes[palette_id])
                tile_cache[key] = tile
            image.paste(tile, (tile_x * 8, tile_y * 8))
    return image


def _write_background_tile_sheet(
    chr_data: bytes,
    tile_ids: list[int],
    out_path: Path,
    *,
    palette: tuple[int, int, int, int] = SMB_FONT_PALETTE,
    columns: int = 16,
) -> None:
    images = [
        (f"{tile_id:02X}", _background_tile_image(chr_data, tile_id, _palette_rgb(palette)))
        for tile_id in tile_ids
    ]
    _write_image_grid(images, out_path, columns=columns, padding=1)


def render_smb_title_assets(rom_path: Path, out_dir: Path) -> SmbTitleAssetExport:
    """Export SMB title logo and font/tile sheets from title-screen data."""

    rom_path = Path(rom_path)
    out_dir = Path(out_dir)
    rom_bytes = rom_path.read_bytes()
    validate_smb_nrom(rom_bytes)
    chr_data = chr_from_ines(rom_bytes, chr_bank=0)

    out_dir.mkdir(parents=True, exist_ok=True)
    nametable, attributes = _parse_smb_title_nametable(chr_data)
    title = _render_title_nametable(chr_data, nametable, attributes)

    title_screen = out_dir / "smb-title-screen.png"
    title.save(title_screen)

    title_logo = out_dir / "smb-title-logo.png"
    title.crop((5 * 8, 4 * 8, 27 * 8, 14 * 8)).save(title_logo)

    font_sheet = out_dir / "smb-font-small-tiles-00-2f.png"
    _write_background_tile_sheet(chr_data, list(range(0x00, 0x30)), font_sheet)

    title_glyph_sheet = out_dir / "smb-title-glyph-tiles-d0-e8.png"
    _write_background_tile_sheet(
        chr_data,
        list(range(0xD0, 0xE9)),
        title_glyph_sheet,
        palette=SMB_TITLE_PALETTES[1],
    )

    manifest_json = out_dir / "smb-title-assets.json"
    files = [title_screen, title_logo, font_sheet, title_glyph_sheet]
    data = {
        "kind": "smb_title_logo_font_export",
        "rom": str(rom_path),
        "out_dir": str(out_dir),
        "title_screen": str(title_screen),
        "title_logo": str(title_logo),
        "font_sheet": str(font_sheet),
        "title_glyph_sheet": str(title_glyph_sheet),
        "title_screen_data_offset": f"0x{SMB_TITLE_SCREEN_DATA_OFFSET:04X}",
        "small_font_tile_range": "0x00..0x2F",
        "title_glyph_tile_range": "0xD0..0xE8",
        "notes": [
            "title screen reconstruit depuis le flux VRAM stocke en CHR a 0x1EC0",
            "logo croppe depuis le rendu title-screen; les glyphes du titre sont aussi exportes separement",
            "font-small contient les chiffres, lettres HUD/message et ponctuation courante de SMB",
        ],
    }
    manifest_json.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return SmbTitleAssetExport(
        rom=rom_path,
        out_dir=out_dir,
        title_screen=title_screen,
        title_logo=title_logo,
        font_sheet=font_sheet,
        title_glyph_sheet=title_glyph_sheet,
        manifest_json=manifest_json,
        files=files,
    )


def render_smb_blocks(rom_path: Path, out_dir: Path) -> SmbBlockExport:
    """Export SMB block/metatile sheets and block-related sprite objects."""

    rom_path = Path(rom_path)
    out_dir = Path(out_dir)
    rom_bytes = rom_path.read_bytes()
    validate_smb_nrom(rom_bytes)
    runtime = _SmbLevelRuntime(rom_bytes)
    chr_data = runtime.chr
    prg = runtime.prg

    metatile_dir = out_dir / "metatiles"
    block_dir = out_dir / "blocks"
    sprite_dir = out_dir / "sprites"
    metatile_dir.mkdir(parents=True, exist_ok=True)
    block_dir.mkdir(parents=True, exist_ok=True)
    sprite_dir.mkdir(parents=True, exist_ok=True)

    files: list[Path] = []
    metatile_sheets: list[Path] = []
    block_sheets: list[Path] = []
    metatile_entries: list[dict[str, object]] = []
    block_entries: list[dict[str, object]] = []
    sprite_entries: list[dict[str, object]] = []

    for area_type, area_name in AREA_TYPE_NAMES.items():
        palettes = runtime.load_background_palette_for_area_type(area_type)
        all_metatiles = [
            (f"{value:02X}", runtime.render_metatile(value, palettes))
            for value in range(0x100)
        ]
        sheet = metatile_dir / f"{area_name}-all-metatiles.png"
        _write_image_grid(all_metatiles, sheet, columns=16, padding=1)
        files.append(sheet)
        metatile_sheets.append(sheet)
        metatile_entries.append(
            {
                "area_type": area_type,
                "area_name": area_name,
                "png": str(sheet),
                "metatile_count": 256,
                "layout": "16 columns, row-major 0x00..0xFF",
            }
        )

        named_images = []
        for name, metatile in IMPORTANT_BLOCK_METATILES:
            image = runtime.render_metatile(metatile, palettes).convert("RGBA")
            png = block_dir / f"{area_name}-{name}-0x{metatile:02x}.png"
            image.save(png)
            files.append(png)
            named_images.append((name, image))
            block_entries.append(
                {
                    "area_type": area_type,
                    "area_name": area_name,
                    "name": name,
                    "metatile": f"0x{metatile:02X}",
                    "png": str(png),
                }
            )
        block_sheet = block_dir / f"{area_name}-important-blocks.png"
        _write_image_grid(named_images, block_sheet, columns=8, padding=2)
        files.append(block_sheet)
        block_sheets.append(block_sheet)

    jumping_coin_tiles = _read_cpu_table(prg, SMB_JUMPING_COIN_TILES, 4)
    sprite_images = []
    for idx, tile_id in enumerate(jumping_coin_tiles):
        image = _render_jumping_coin(chr_data, tile_id)
        png = sprite_dir / f"jumping-coin-frame-{idx}.png"
        image.save(png)
        files.append(png)
        sprite_images.append((f"jumping-coin-frame-{idx}", image))
        sprite_entries.append(
            {
                "kind": "jumping_coin",
                "name": f"jumping-coin-frame-{idx}",
                "tile_id": f"0x{tile_id:02X}",
                "png": str(png),
                "table_addr": f"0x{SMB_JUMPING_COIN_TILES + idx:04X}",
            }
        )

    block_tile_ids = _read_cpu_table(prg, SMB_DEFAULT_BLOCK_OBJ_TILES, 4)
    block_image = _render_metasprite_rgba(
        chr_data,
        block_tile_ids,
        rows=2,
        palette=SMB_MISC_ENEMY_PALETTE,
    )
    block_png = sprite_dir / "bouncing-brick-block.png"
    block_image.save(block_png)
    files.append(block_png)
    sprite_images.append(("bouncing-brick-block", block_image))
    sprite_entries.append(
        {
            "kind": "bouncing_block",
            "name": "bouncing-brick-block",
            "tile_ids": [f"0x{tile_id:02X}" for tile_id in block_tile_ids],
            "png": str(block_png),
            "table_addr": f"0x{SMB_DEFAULT_BLOCK_OBJ_TILES:04X}",
        }
    )

    brick_chunk = _decode_sprite_tile_rgba(chr_data, 0x84, SMB_MISC_ENEMY_PALETTE)
    chunk_png = sprite_dir / "brick-chunk.png"
    brick_chunk.save(chunk_png)
    files.append(chunk_png)
    sprite_images.append(("brick-chunk", brick_chunk))
    sprite_entries.append(
        {
            "kind": "brick_chunk",
            "name": "brick-chunk",
            "tile_id": "0x84",
            "png": str(chunk_png),
        }
    )

    for name, offset, palette in POWERUP_METASPRITES:
        tile_ids = _read_cpu_table(prg, SMB_POWERUP_GFX_TABLE + offset, 4)
        image = _render_metasprite_rgba(chr_data, tile_ids, rows=2, palette=palette)
        png = sprite_dir / f"{name}.png"
        image.save(png)
        files.append(png)
        sprite_images.append((name, image))
        sprite_entries.append(
            {
                "kind": "powerup",
                "name": name,
                "tile_ids": [f"0x{tile_id:02X}" for tile_id in tile_ids],
                "png": str(png),
                "table_addr": f"0x{SMB_POWERUP_GFX_TABLE + offset:04X}",
            }
        )

    sprite_sheet = sprite_dir / "smb-block-sprites.png"
    _write_image_grid(sprite_images, sprite_sheet, columns=8, padding=4)
    files.append(sprite_sheet)

    manifest_json = out_dir / "smb-blocks.json"
    data = {
        "kind": "smb_block_metatile_export",
        "rom": str(rom_path),
        "out_dir": str(out_dir),
        "metatile_sheets": metatile_entries,
        "important_blocks": block_entries,
        "sprites": sprite_entries,
        "engine_symbols": {
            "MetatileGraphics_Low": f"0x{SMB_METATILE_GRAPHICS_LOW:04X}",
            "MetatileGraphics_High": f"0x{SMB_METATILE_GRAPHICS_HIGH:04X}",
            "JumpingCoinTiles": f"0x{SMB_JUMPING_COIN_TILES:04X}",
            "PowerUpGfxTable": f"0x{SMB_POWERUP_GFX_TABLE:04X}",
            "DefaultBlockObjTiles": f"0x{SMB_DEFAULT_BLOCK_OBJ_TILES:04X}",
        },
        "notes": [
            "metatiles: feuilles 16x16 en ordre 0x00..0xFF pour chaque type de zone",
            "blocks: PNG nommes pour pieces, briques, question blocks, blocs solides et etats vides",
            "sprites: objets OAM lies aux blocs, dont piece sautante, brique bondissante et power-ups",
        ],
    }
    manifest_json.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return SmbBlockExport(
        rom=rom_path,
        out_dir=out_dir,
        metatile_sheets=metatile_sheets,
        block_sheets=block_sheets,
        sprite_sheet=sprite_sheet,
        manifest_json=manifest_json,
        files=files,
    )


def render_smb_characters(rom_path: Path, out_dir: Path) -> SmbCharacterExport:
    """Export SMB player/enemy metasprites assembled from the original tables."""

    rom_path = Path(rom_path)
    out_dir = Path(out_dir)
    rom_bytes = rom_path.read_bytes()
    validate_smb_nrom(rom_bytes)
    prg = strip_ines(rom_bytes)
    chr_data = chr_from_ines(rom_bytes, chr_bank=0)

    player_dir = out_dir / "players"
    enemy_dir = out_dir / "enemies"
    player_dir.mkdir(parents=True, exist_ok=True)
    enemy_dir.mkdir(parents=True, exist_ok=True)

    sprites: list[Path] = []
    entries: list[dict[str, object]] = []

    for name, offset in PLAYER_METASPRITES:
        tile_ids = _read_cpu_table(prg, SMB_PLAYER_GRAPHICS_TABLE + offset, 8)
        image = _render_metasprite_rgba(
            chr_data,
            tile_ids,
            rows=4,
            palette=SMB_MARIO_PALETTE,
        )
        png = player_dir / f"{name}.png"
        image.save(png)
        sprites.append(png)
        entries.append(
            {
                "kind": "player",
                "name": name,
                "png": str(png),
                "width": image.width,
                "height": image.height,
                "tile_ids": [f"0x{tile_id:02X}" for tile_id in tile_ids],
                "table": "PlayerGraphicsTable",
                "table_addr": f"0x{SMB_PLAYER_GRAPHICS_TABLE + offset:04X}",
                "palette": [f"0x{value:02X}" for value in SMB_MARIO_PALETTE],
            }
        )

    for name, offset, palette in ENEMY_METASPRITES:
        tile_ids = _read_cpu_table(prg, SMB_ENEMY_GRAPHICS_TABLE + offset, 6)
        image = _render_metasprite_rgba(
            chr_data,
            tile_ids,
            rows=3,
            palette=palette,
        )
        png = enemy_dir / f"{name}.png"
        image.save(png)
        sprites.append(png)
        entries.append(
            {
                "kind": "enemy",
                "name": name,
                "png": str(png),
                "width": image.width,
                "height": image.height,
                "tile_ids": [f"0x{tile_id:02X}" for tile_id in tile_ids],
                "table": "EnemyGraphicsTable",
                "table_addr": f"0x{SMB_ENEMY_GRAPHICS_TABLE + offset:04X}",
                "palette": [f"0x{value:02X}" for value in palette],
            }
        )

    spritesheet = out_dir / "smb-characters-spritesheet.png"
    _write_character_spritesheet(sprites, spritesheet)
    manifest_json = out_dir / "smb-characters.json"
    data = {
        "kind": "smb_character_metasprite_export",
        "rom": str(rom_path),
        "out_dir": str(out_dir),
        "spritesheet": str(spritesheet),
        "sprite_count": len(sprites),
        "player_count": len(PLAYER_METASPRITES),
        "enemy_count": len(ENEMY_METASPRITES),
        "engine_symbols": {
            "PlayerGraphicsTable": f"0x{SMB_PLAYER_GRAPHICS_TABLE:04X}",
            "EnemyGraphicsTable": f"0x{SMB_ENEMY_GRAPHICS_TABLE:04X}",
        },
        "sprites": entries,
        "notes": [
            "sprites personnages assembles depuis les tables graphiques SMB originales",
            "index couleur 0 rendu transparent; $FC traite comme tile vide SMB",
        ],
    }
    manifest_json.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return SmbCharacterExport(
        rom=rom_path,
        out_dir=out_dir,
        spritesheet=spritesheet,
        manifest_json=manifest_json,
        sprites=sprites,
    )


def render_smb_level(
    rom_path: Path,
    out_dir: Path,
    *,
    stage: str = "1-1",
    max_columns: int = 1000,
) -> SmbLevelExport:
    """Render one SMB level/stage background as an assembled PNG."""

    if stage not in WORLD_MAP:
        valid = ", ".join(sorted(WORLD_MAP))
        raise ValueError(f"unknown SMB stage {stage!r}; valid: {valid}")
    if max_columns <= 0:
        raise ValueError("max_columns must be positive")

    from PIL import Image

    rom_path = Path(rom_path)
    out_dir = Path(out_dir)
    runtime = _SmbLevelRuntime(rom_path.read_bytes())
    columns = runtime.load_stage(WORLD_MAP[stage], max_columns=max_columns)
    if not columns:
        raise RuntimeError("SMB level parser returned no columns")
    palettes = runtime.load_background_palette()
    unique = sorted({metatile for column in columns for metatile in column})
    metatile_images = {
        metatile: runtime.render_metatile(metatile, palettes)
        for metatile in unique
    }

    rows = 13
    image = Image.new("RGB", (len(columns) * 16, rows * 16))
    for x, column in enumerate(columns):
        for y, metatile in enumerate(column):
            image.paste(metatile_images[metatile], (x * 16, y * 16))

    out_dir.mkdir(parents=True, exist_ok=True)
    safe_stage = stage.replace("-", "_")
    png = out_dir / f"smb-{safe_stage}.png"
    image.save(png)

    manifest_json = out_dir / f"smb-{safe_stage}.json"
    data = {
        "kind": "smb_assembled_level_export",
        "rom": str(rom_path),
        "stage": stage,
        "png": str(png),
        "columns": len(columns),
        "rows": rows,
        "width": image.width,
        "height": image.height,
        "area_type": runtime.read(SMB_AREA_TYPE),
        "unique_metatile_count": len(unique),
        "unique_metatiles": [f"0x{value:02X}" for value in unique],
        "engine_symbols": {
            "LoadAreaPointer": f"0x{SMB_LOAD_AREA_POINTER:04X}",
            "InitializeArea": f"0x{SMB_INITIALIZE_AREA:04X}",
            "AreaParserCore": f"0x{SMB_AREA_PARSER_CORE:04X}",
            "IncrementColumnPos": f"0x{SMB_INCREMENT_COLUMN_POS:04X}",
        },
        "notes": [
            "background seulement: HUD et sprites mobiles ne sont pas composites ici",
            "rendu par le parser de niveau original SMB appele via py65",
        ],
    }
    manifest_json.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return SmbLevelExport(
        rom=rom_path,
        stage=stage,
        png=png,
        manifest_json=manifest_json,
        columns=len(columns),
        rows=rows,
        width=image.width,
        height=image.height,
        area_type=runtime.read(SMB_AREA_TYPE),
        unique_metatiles=len(unique),
        notes=list(data["notes"]),
    )


def render_smb_level_batch(
    rom_path: Path,
    out_dir: Path,
    *,
    stages: list[str] | None = None,
    max_columns: int = 1000,
    allow_failures: bool = False,
) -> SmbLevelBatchExport:
    """Render multiple SMB stages and write a batch manifest."""

    rom_path = Path(rom_path)
    out_dir = Path(out_dir)
    stage_names = stages or sorted(WORLD_MAP, key=_stage_sort_key)
    levels: list[SmbLevelExport] = []
    errors: dict[str, str] = {}
    for stage in stage_names:
        try:
            levels.append(
                render_smb_level(
                    rom_path,
                    out_dir,
                    stage=stage,
                    max_columns=max_columns,
                )
            )
        except Exception as exc:
            errors[stage] = str(exc)
            if not allow_failures:
                break

    manifest_json = out_dir / "smb-levels.json"
    data = {
        "kind": "smb_assembled_level_batch_export",
        "rom": str(rom_path),
        "out_dir": str(out_dir),
        "success_count": len(levels),
        "failure_count": len(errors),
        "levels": [
            {
                "stage": level.stage,
                "png": str(level.png),
                "manifest_json": str(level.manifest_json),
                "columns": level.columns,
                "rows": level.rows,
                "width": level.width,
                "height": level.height,
                "area_type": level.area_type,
                "unique_metatile_count": level.unique_metatiles,
            }
            for level in levels
        ],
        "errors": errors,
        "notes": [
            "batch background seulement: HUD et sprites mobiles ne sont pas composites ici",
            "stages speciaux inclus: bonus, cloud1, cloud2, water1, water2, warp",
        ],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_json.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if errors and not allow_failures:
        first_stage, first_error = next(iter(errors.items()))
        raise RuntimeError(f"SMB batch stopped at {first_stage}: {first_error}")
    return SmbLevelBatchExport(
        rom=rom_path,
        out_dir=out_dir,
        manifest_json=manifest_json,
        levels=levels,
        errors=errors,
    )


def _stage_sort_key(stage: str) -> tuple[int, int, int, str]:
    parts = stage.split("-")
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        suffix_rank = 1 if len(parts) > 2 else 0
        return (0, int(parts[0]), int(parts[1]) * 2 + suffix_rank, stage)
    return (1, 99, 99, stage)
