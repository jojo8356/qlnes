"""Colored NES sprite/tile PNG export.

CHR data stores 2bpp pixel indexes, not final RGB colors. This module turns
CHR sprite pattern tiles into RGBA PNGs by applying a PPU sprite palette. Pixel
index 0 is exported as transparent alpha, matching NES sprite rendering.

The output is "original color" only when the caller provides palette RAM from
the same runtime moment as the sprites. Without a runtime PPU snapshot, qlnes
uses an explicit preview palette and records that fact in the manifest.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from .assets import TILE_BYTES, decode_tile
from .ines import HEADER_SIZE, parse_header
from .rom import Rom

PATTERN_TABLE_SIZE = 0x1000
SPRITE_TILE_WIDTH = 8
DEFAULT_SPRITE_PALETTE = (0x0F, 0x30, 0x16, 0x27)

# FCEUX-like 64-color palette. qlnes keeps PPU palette values in manifests so
# the RGB profile can be changed later without losing original index evidence.
NES_RGB_PALETTE: tuple[tuple[int, int, int], ...] = (
    (0x7C, 0x7C, 0x7C), (0x00, 0x00, 0xFC), (0x00, 0x00, 0xBC), (0x44, 0x28, 0xBC),
    (0x94, 0x00, 0x84), (0xA8, 0x00, 0x20), (0xA8, 0x10, 0x00), (0x88, 0x14, 0x00),
    (0x50, 0x30, 0x00), (0x00, 0x78, 0x00), (0x00, 0x68, 0x00), (0x00, 0x58, 0x00),
    (0x00, 0x40, 0x58), (0x00, 0x00, 0x00), (0x00, 0x00, 0x00), (0x00, 0x00, 0x00),
    (0xBC, 0xBC, 0xBC), (0x00, 0x78, 0xF8), (0x00, 0x58, 0xF8), (0x68, 0x44, 0xFC),
    (0xD8, 0x00, 0xCC), (0xE4, 0x00, 0x58), (0xF8, 0x38, 0x00), (0xE4, 0x5C, 0x10),
    (0xAC, 0x7C, 0x00), (0x00, 0xB8, 0x00), (0x00, 0xA8, 0x00), (0x00, 0xA8, 0x44),
    (0x00, 0x88, 0x88), (0x00, 0x00, 0x00), (0x00, 0x00, 0x00), (0x00, 0x00, 0x00),
    (0xF8, 0xF8, 0xF8), (0x3C, 0xBC, 0xFC), (0x68, 0x88, 0xFC), (0x98, 0x78, 0xF8),
    (0xF8, 0x78, 0xF8), (0xF8, 0x58, 0x98), (0xF8, 0x78, 0x58), (0xFC, 0xA0, 0x44),
    (0xF8, 0xB8, 0x00), (0xB8, 0xF8, 0x18), (0x58, 0xD8, 0x54), (0x58, 0xF8, 0x98),
    (0x00, 0xE8, 0xD8), (0x78, 0x78, 0x78), (0x00, 0x00, 0x00), (0x00, 0x00, 0x00),
    (0xFC, 0xFC, 0xFC), (0xA4, 0xE4, 0xFC), (0xB8, 0xB8, 0xF8), (0xD8, 0xB8, 0xF8),
    (0xF8, 0xB8, 0xF8), (0xF8, 0xA4, 0xC0), (0xF0, 0xD0, 0xB0), (0xFC, 0xE0, 0xA8),
    (0xF8, 0xD8, 0x78), (0xD8, 0xF8, 0x78), (0xB8, 0xF8, 0xB8), (0xB8, 0xF8, 0xD8),
    (0x00, 0xFC, 0xFC), (0xF8, 0xD8, 0xF8), (0x00, 0x00, 0x00), (0x00, 0x00, 0x00),
)


@dataclass(frozen=True)
class SpriteExport:
    tile_index: int
    palette_id: int
    path: Path
    width: int
    height: int
    oam_index: int | None = None
    x: int | None = None
    y: int | None = None
    attr: int | None = None
    priority_behind_background: bool = False
    flip_h: bool = False
    flip_v: bool = False


@dataclass
class SpriteExportManifest:
    out_dir: Path
    spritesheet: Path | None = None
    screen_png: Path | None = None
    sprite_paths: list[SpriteExport] = field(default_factory=list)
    manifest_json: Path | None = None
    n_tiles: int = 0
    chr_bank: int = 0
    pattern_table: int = 1
    sprite_height: int = 8
    palette_source: str = "preview"
    palette_profile: str = "fceux-like"
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BatchSpriteExportEntry:
    rom: Path
    out_dir: Path
    ok: bool
    n_tiles: int = 0
    spritesheet: Path | None = None
    screen_png: Path | None = None
    manifest_json: Path | None = None
    error: str | None = None


@dataclass
class BatchSpriteExportManifest:
    out_dir: Path
    entries: list[BatchSpriteExportEntry] = field(default_factory=list)
    manifest_json: Path | None = None

    @property
    def success_count(self) -> int:
        return sum(1 for entry in self.entries if entry.ok)

    @property
    def failure_count(self) -> int:
        return sum(1 for entry in self.entries if not entry.ok)


def parse_palette_values(text: str) -> tuple[int, ...]:
    """Parse comma/space-separated NES PPU palette values.

    Accepts decimal or Python-style integer strings such as ``0x16``. Bare
    two-digit hexadecimal tokens like ``16`` are treated as hex because NES
    palette values are usually written that way.
    """

    raw_parts = text.replace(",", " ").split()
    if not raw_parts:
        raise ValueError("palette must contain at least one value")
    values: list[int] = []
    for part in raw_parts:
        base = 16 if part.lower().startswith("0x") or len(part) <= 2 else 10
        value = int(part, base)
        if not 0 <= value <= 0x3F:
            raise ValueError(f"NES palette value out of range 0x00..0x3F: {part}")
        values.append(value)
    return tuple(values)


def sprite_palette_to_palette_ram(sprite_palette: Sequence[int]) -> tuple[int, ...]:
    """Build 32-byte PPU palette RAM from one 4-color sprite palette."""

    if len(sprite_palette) != 4:
        raise ValueError("sprite palette must contain exactly 4 PPU colors")
    ram = [0x0F] * 32
    for palette_id in range(4):
        base = 0x10 + palette_id * 4
        ram[base : base + 4] = [value & 0x3F for value in sprite_palette]
    return tuple(ram)


def normalize_palette_ram(values: Sequence[int] | None) -> tuple[int, ...]:
    """Return 32 PPU palette RAM values.

    ``None`` means "preview palette". Four values mean "repeat this one sprite
    palette across all four sprite palettes". Thirty-two values mean complete
    PPU palette RAM.
    """

    if values is None:
        return sprite_palette_to_palette_ram(DEFAULT_SPRITE_PALETTE)
    if len(values) == 4:
        return sprite_palette_to_palette_ram(values)
    if len(values) == 32:
        return tuple(value & 0x3F for value in values)
    raise ValueError("palette must contain 4 sprite colors or 32 PPU palette RAM values")


def _parse_int(value: object) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value, 0)
    raise ValueError(f"expected int or int string, got {type(value).__name__}")


def _parse_int_list(values: object, *, name: str) -> tuple[int, ...]:
    if not isinstance(values, list):
        raise ValueError(f"{name} must be a list")
    return tuple(_parse_int(value) for value in values)


@dataclass(frozen=True)
class RuntimeSpriteSnapshot:
    """Runtime PPU/OAM state needed to color actual NES sprites."""

    oam: tuple[int, ...]
    palette_ram: tuple[int, ...]
    ppuctrl: int
    ppumask: int = 0
    frame: int | None = None
    chr_bank: int = 0
    chr_data: bytes | None = None

    @property
    def sprite_height(self) -> int:
        return 16 if (self.ppuctrl & 0x20) else 8

    @property
    def sprite_pattern_table(self) -> int:
        return 1 if (self.ppuctrl & 0x08) else 0


def load_runtime_sprite_snapshot(path: Path) -> RuntimeSpriteSnapshot:
    """Load a runtime sprite snapshot JSON file.

    Expected keys:
      - ``oam``: 256 integers or int strings
      - ``palette_ram``: 32 integers or int strings for PPU $3F00-$3F1F
      - ``ppuctrl``: integer or int string
    Optional keys: ``ppumask``, ``frame``, ``chr_bank``.
    """

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("sprite snapshot must be a JSON object")
    oam = _parse_int_list(data.get("oam"), name="oam")
    palette_ram = _parse_int_list(data.get("palette_ram"), name="palette_ram")
    if len(oam) != 256:
        raise ValueError(f"oam must contain 256 bytes, got {len(oam)}")
    if len(palette_ram) != 32:
        raise ValueError(f"palette_ram must contain 32 bytes, got {len(palette_ram)}")
    return RuntimeSpriteSnapshot(
        oam=tuple(value & 0xFF for value in oam),
        palette_ram=tuple(value & 0x3F for value in palette_ram),
        ppuctrl=_parse_int(data.get("ppuctrl", 0)) & 0xFF,
        ppumask=_parse_int(data.get("ppumask", 0)) & 0xFF,
        frame=_parse_int(data["frame"]) if "frame" in data else None,
        chr_bank=_parse_int(data.get("chr_bank", 0)),
        chr_data=bytes(_parse_int_list(data["chr_data"], name="chr_data"))
        if "chr_data" in data
        else None,
    )


def rgba_for_sprite_pixel(
    color_index: int,
    *,
    palette_id: int,
    palette_ram: Sequence[int],
) -> tuple[int, int, int, int]:
    """Resolve one decoded CHR pixel to RGBA.

    Sprite color index 0 is transparent on NES hardware, so it returns alpha 0.
    Other indexes resolve through sprite palette RAM at ``$3F10-$3F1F``.
    """

    if not 0 <= color_index <= 3:
        raise ValueError(f"sprite color index must be 0..3, got {color_index}")
    if not 0 <= palette_id <= 3:
        raise ValueError(f"sprite palette id must be 0..3, got {palette_id}")
    if color_index == 0:
        return (0, 0, 0, 0)
    ppu_value = palette_ram[0x10 + palette_id * 4 + color_index] & 0x3F
    return (*NES_RGB_PALETTE[ppu_value], 255)


def chr_from_ines(rom_bytes: bytes, *, chr_bank: int = 0) -> bytes:
    """Extract one 8 KiB CHR bank from an iNES ROM."""

    header = parse_header(rom_bytes)
    if header is None:
        raise ValueError("ROM iNES invalide (header manquant)")
    if header.chr_size == 0:
        raise ValueError("ROM has CHR-RAM, not static CHR-ROM; runtime PPU dump required")
    if chr_bank < 0 or chr_bank >= header.chr_banks:
        raise ValueError(f"CHR bank {chr_bank} hors range 0..{header.chr_banks - 1}")
    offset = HEADER_SIZE + (512 if header.has_trainer else 0) + header.prg_size
    start = offset + chr_bank * 0x2000
    return rom_bytes[start : start + 0x2000]


def decode_sprite_pattern(
    chr_data: bytes,
    tile_index: int,
    *,
    pattern_table: int = 1,
    sprite_height: int = 8,
) -> list[list[int]]:
    """Decode a sprite pattern as 8x8 or 8x16 color indexes."""

    if pattern_table not in (0, 1):
        raise ValueError("pattern_table must be 0 or 1")
    if sprite_height not in (8, 16):
        raise ValueError("sprite_height must be 8 or 16")
    if not 0 <= tile_index <= 0xFF:
        raise ValueError("tile_index must be 0..255")

    if sprite_height == 8:
        addr = pattern_table * PATTERN_TABLE_SIZE + tile_index * TILE_BYTES
        if addr + TILE_BYTES > len(chr_data):
            raise ValueError(f"tile ${tile_index:02X} outside CHR data")
        return decode_tile(chr_data[addr : addr + TILE_BYTES])

    table = tile_index & 0x01
    top_tile = tile_index & 0xFE
    rows: list[list[int]] = []
    for subtile in (top_tile, top_tile + 1):
        addr = table * PATTERN_TABLE_SIZE + subtile * TILE_BYTES
        if addr + TILE_BYTES > len(chr_data):
            raise ValueError(f"8x16 tile ${tile_index:02X} outside CHR data")
        rows.extend(decode_tile(chr_data[addr : addr + TILE_BYTES]))
    return rows


def _apply_sprite_flips(rows: list[list[int]], *, flip_h: bool, flip_v: bool) -> list[list[int]]:
    out = [list(reversed(row)) if flip_h else list(row) for row in rows]
    if flip_v:
        out = list(reversed(out))
    return out


def decode_oam_sprite_pattern(
    chr_data: bytes,
    snapshot: RuntimeSpriteSnapshot,
    oam_index: int,
) -> list[list[int]]:
    """Decode one runtime OAM sprite using PPUCTRL size/table rules."""

    if not 0 <= oam_index <= 63:
        raise ValueError("oam_index must be 0..63")
    base = oam_index * 4
    tile = snapshot.oam[base + 1]
    attr = snapshot.oam[base + 2]
    rows = decode_sprite_pattern(
        chr_data,
        tile,
        pattern_table=snapshot.sprite_pattern_table,
        sprite_height=snapshot.sprite_height,
    )
    return _apply_sprite_flips(
        rows,
        flip_h=bool(attr & 0x40),
        flip_v=bool(attr & 0x80),
    )


def write_sprite_png(
    rows: list[list[int]],
    out_path: Path,
    *,
    palette_id: int,
    palette_ram: Sequence[int],
) -> Path:
    """Write one decoded sprite pattern as an RGBA PNG."""

    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Pillow is required for transparent sprite PNG export") from exc

    height = len(rows)
    width = len(rows[0]) if rows else 0
    rgba: list[tuple[int, int, int, int]] = []
    for row in rows:
        if len(row) != width:
            raise ValueError("sprite rows must have stable width")
        for color_index in row:
            rgba.append(
                rgba_for_sprite_pixel(
                    color_index,
                    palette_id=palette_id,
                    palette_ram=palette_ram,
                )
            )
    image = Image.new("RGBA", (width, height))
    image.putdata(rgba)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path)
    return out_path


def _sprite_image_from_rows(
    rows: list[list[int]],
    *,
    palette_id: int,
    palette_ram: Sequence[int],
):
    from PIL import Image

    height = len(rows)
    width = len(rows[0]) if rows else 0
    rgba: list[tuple[int, int, int, int]] = []
    for row in rows:
        if len(row) != width:
            raise ValueError("sprite rows must have stable width")
        rgba.extend(
            rgba_for_sprite_pixel(color_index, palette_id=palette_id, palette_ram=palette_ram)
            for color_index in row
        )
    image = Image.new("RGBA", (width, height))
    image.putdata(rgba)
    return image


def write_spritesheet_png(
    decoded_sprites: Sequence[list[list[int]]],
    out_path: Path,
    *,
    palette_id: int,
    palette_ram: Sequence[int],
    palette_ids: Sequence[int] | None = None,
    columns: int = 16,
) -> Path:
    """Pack decoded sprite patterns into a transparent RGBA spritesheet."""

    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Pillow is required for transparent sprite PNG export") from exc

    if not decoded_sprites:
        raise ValueError("no sprites to write")
    sprite_w = len(decoded_sprites[0][0])
    sprite_h = len(decoded_sprites[0])
    rows = (len(decoded_sprites) + columns - 1) // columns
    sheet = Image.new("RGBA", (columns * sprite_w, rows * sprite_h), (0, 0, 0, 0))
    for idx, sprite_rows in enumerate(decoded_sprites):
        sprite_palette_id = palette_ids[idx] if palette_ids is not None else palette_id
        sprite_img = _sprite_image_from_rows(
            sprite_rows,
            palette_id=sprite_palette_id,
            palette_ram=palette_ram,
        )
        sheet.alpha_composite(sprite_img, ((idx % columns) * sprite_w, (idx // columns) * sprite_h))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)
    return out_path


def write_oam_screen_png(
    decoded_sprites: Sequence[list[list[int]]],
    exports: Sequence[SpriteExport],
    out_path: Path,
    *,
    palette_ram: Sequence[int],
) -> Path:
    """Compose runtime OAM sprites at their screen positions on transparent canvas.

    The canvas is 256x240 RGBA. Composition walks sprites from high OAM index
    down to low index so lower indexes appear in front, matching NES sprite
    priority among sprites. Background priority is recorded in the manifest but
    does not affect this transparent sprite-only image.
    """

    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Pillow is required for transparent sprite PNG export") from exc

    canvas = Image.new("RGBA", (256, 240), (0, 0, 0, 0))
    for rows, sprite in reversed(list(zip(decoded_sprites, exports, strict=True))):
        if sprite.x is None or sprite.y is None:
            continue
        sprite_img = _sprite_image_from_rows(
            rows,
            palette_id=sprite.palette_id,
            palette_ram=palette_ram,
        )
        left = max(0, sprite.x)
        top = max(0, sprite.y)
        right = min(256, sprite.x + sprite.width)
        bottom = min(240, sprite.y + sprite.height)
        if left >= right or top >= bottom:
            continue
        crop = sprite_img.crop((left - sprite.x, top - sprite.y, right - sprite.x, bottom - sprite.y))
        canvas.alpha_composite(crop, (left, top))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path)
    return out_path


def export_sprite_pattern_table(
    rom_path: Path,
    out_dir: Path,
    *,
    chr_bank: int = 0,
    pattern_table: int = 1,
    sprite_height: int = 8,
    palette_id: int = 0,
    palette_values: Sequence[int] | None = None,
    palette_source: str = "preview",
    per_tile: bool = True,
) -> SpriteExportManifest:
    """Export CHR sprite pattern tiles to transparent PNGs.

    This is a static CHR export. If ``palette_values`` comes from runtime PPU
    palette RAM, the colors correspond to that captured state. Otherwise the
    manifest marks the palette as preview.
    """

    rom_path = Path(rom_path)
    out_dir = Path(out_dir)
    palette_ram = normalize_palette_ram(palette_values)
    chr_data = chr_from_ines(rom_path.read_bytes(), chr_bank=chr_bank)
    n_tiles = PATTERN_TABLE_SIZE // TILE_BYTES
    decoded = [
        decode_sprite_pattern(
            chr_data,
            tile,
            pattern_table=pattern_table,
            sprite_height=sprite_height,
        )
        for tile in range(0, n_tiles, 2 if sprite_height == 16 else 1)
    ]

    manifest = SpriteExportManifest(
        out_dir=out_dir,
        n_tiles=len(decoded),
        chr_bank=chr_bank,
        pattern_table=pattern_table,
        sprite_height=sprite_height,
        palette_source=palette_source,
    )
    if palette_source == "preview":
        manifest.notes.append(
            "Static CHR export: colors use the selected preview palette, not a runtime PPU snapshot."
        )

    sheet = out_dir / f"spritesheet-pt{pattern_table}-pal{palette_id}.png"
    manifest.spritesheet = write_spritesheet_png(
        decoded,
        sheet,
        palette_id=palette_id,
        palette_ram=palette_ram,
    )

    if per_tile:
        tiles_dir = out_dir / "tiles"
        step = 2 if sprite_height == 16 else 1
        for out_idx, rows in enumerate(decoded):
            tile_index = out_idx * step
            path = tiles_dir / f"tile-{tile_index:02X}-pt{pattern_table}-pal{palette_id}.png"
            write_sprite_png(rows, path, palette_id=palette_id, palette_ram=palette_ram)
            manifest.sprite_paths.append(
                SpriteExport(
                    tile_index=tile_index,
                    palette_id=palette_id,
                    path=path,
                    width=8,
                    height=sprite_height,
                )
            )

    manifest_json = out_dir / "sprites-manifest.json"
    manifest_json.write_text(
        json.dumps(
            {
                "kind": "sprite_pattern_table_export",
                "rom": str(rom_path),
                "chr_bank": chr_bank,
                "pattern_table": pattern_table,
                "sprite_height": sprite_height,
                "palette_id": palette_id,
                "palette_source": palette_source,
                "palette_profile": manifest.palette_profile,
                "palette_ram": [f"0x{value:02X}" for value in palette_ram],
                "transparent_index": 0,
                "spritesheet": str(manifest.spritesheet),
                "tiles": [
                    {
                        "tile_index": f"0x{sprite.tile_index:02X}",
                        "palette_id": sprite.palette_id,
                        "path": str(sprite.path),
                        "width": sprite.width,
                        "height": sprite.height,
                    }
                    for sprite in manifest.sprite_paths
                ],
                "notes": manifest.notes,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    manifest.manifest_json = manifest_json
    return manifest


def export_runtime_oam_sprites(
    rom_path: Path,
    snapshot_path: Path,
    out_dir: Path,
    *,
    include_hidden: bool = False,
) -> SpriteExportManifest:
    """Export actual runtime OAM sprites using snapshot palette RAM.

    The snapshot supplies original palette/OAM state. CHR bytes still come from
    the ROM's selected CHR bank, which is correct for simple CHR-ROM mapper
    states and for snapshots that record the active bank.
    """

    rom_path = Path(rom_path)
    snapshot = load_runtime_sprite_snapshot(snapshot_path)
    chr_data = (
        snapshot.chr_data
        if snapshot.chr_data is not None
        else chr_from_ines(rom_path.read_bytes(), chr_bank=snapshot.chr_bank)
    )
    if len(chr_data) < 0x2000:
        raise ValueError(f"snapshot chr_data must contain at least 8192 bytes, got {len(chr_data)}")
    out_dir = Path(out_dir)
    decoded: list[list[list[int]]] = []
    palette_ids: list[int] = []
    exports: list[SpriteExport] = []
    tiles_dir = out_dir / "oam"

    for oam_index in range(64):
        base = oam_index * 4
        y_raw = snapshot.oam[base]
        tile = snapshot.oam[base + 1]
        attr = snapshot.oam[base + 2]
        x = snapshot.oam[base + 3]
        hidden = y_raw >= 0xEF
        if hidden and not include_hidden:
            continue
        rows = decode_oam_sprite_pattern(chr_data, snapshot, oam_index)
        palette_id = attr & 0x03
        path = tiles_dir / f"sprite-{oam_index:02d}-tile-{tile:02X}-pal{palette_id}.png"
        write_sprite_png(rows, path, palette_id=palette_id, palette_ram=snapshot.palette_ram)
        decoded.append(rows)
        palette_ids.append(palette_id)
        exports.append(
            SpriteExport(
                tile_index=tile,
                palette_id=palette_id,
                path=path,
                width=8,
                height=snapshot.sprite_height,
                oam_index=oam_index,
                x=x,
                y=y_raw + 1,
                attr=attr,
                priority_behind_background=bool(attr & 0x20),
                flip_h=bool(attr & 0x40),
                flip_v=bool(attr & 0x80),
            )
        )

    manifest = SpriteExportManifest(
        out_dir=out_dir,
        sprite_paths=exports,
        n_tiles=len(exports),
        chr_bank=snapshot.chr_bank,
        pattern_table=snapshot.sprite_pattern_table,
        sprite_height=snapshot.sprite_height,
        palette_source="runtime-snapshot",
    )
    if decoded:
        sheet = out_dir / "oam-spritesheet.png"
        manifest.spritesheet = write_spritesheet_png(
            decoded,
            sheet,
            palette_id=0,
            palette_ram=snapshot.palette_ram,
            palette_ids=palette_ids,
        )
        screen = out_dir / "oam-screen.png"
        manifest.screen_png = write_oam_screen_png(
            decoded,
            exports,
            screen,
            palette_ram=snapshot.palette_ram,
        )
    manifest_json = out_dir / "sprites-manifest.json"
    manifest_json.write_text(
        json.dumps(
            {
                "kind": "runtime_oam_sprite_export",
                "rom": str(rom_path),
                "snapshot": str(snapshot_path),
                "frame": snapshot.frame,
                "chr_bank": snapshot.chr_bank,
                "ppuctrl": f"0x{snapshot.ppuctrl:02X}",
                "ppumask": f"0x{snapshot.ppumask:02X}",
                "pattern_table": snapshot.sprite_pattern_table,
                "sprite_height": snapshot.sprite_height,
                "palette_source": manifest.palette_source,
                "palette_profile": manifest.palette_profile,
                "palette_ram": [f"0x{value:02X}" for value in snapshot.palette_ram],
                "chr_source": "snapshot" if snapshot.chr_data is not None else "rom",
                "transparent_index": 0,
                "spritesheet": str(manifest.spritesheet) if manifest.spritesheet else None,
                "screen_png": str(manifest.screen_png) if manifest.screen_png else None,
                "sprites": [
                    {
                        "oam_index": sprite.oam_index,
                        "tile_index": f"0x{sprite.tile_index:02X}",
                        "palette_id": sprite.palette_id,
                        "attr": f"0x{sprite.attr:02X}" if sprite.attr is not None else None,
                        "priority_behind_background": sprite.priority_behind_background,
                        "flip_h": sprite.flip_h,
                        "flip_v": sprite.flip_v,
                        "x": sprite.x,
                        "y": sprite.y,
                        "path": str(sprite.path),
                        "width": sprite.width,
                        "height": sprite.height,
                    }
                    for sprite in exports
                ],
                "notes": manifest.notes,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    manifest.manifest_json = manifest_json
    return manifest


def export_in_process_runtime_sprites(
    rom_path: Path,
    out_dir: Path,
    *,
    frames: int = 120,
    include_hidden: bool = False,
) -> SpriteExportManifest:
    """Boot a simple mapper ROM in-process, capture PPU/OAM, and export sprites.

    This automatic path is intentionally conservative. It relies on the
    in-process runner observing standard CPU writes to PPU palette RAM, pattern
    table writes and OAM/OAMDMA. Games with advanced mappers, mid-frame palette
    changes or advanced PPU effects need an external runtime snapshot.
    """

    from .audio.in_process.runner import InProcessRunner

    rom_path = Path(rom_path)
    rom = Rom.from_file(rom_path)
    runner = InProcessRunner(rom)
    list(runner.run_natural_boot(frames=frames))
    snap = runner.ppu_snapshot()
    with tempfile.TemporaryDirectory(prefix="qlnes-sprite-snapshot-") as td:
        snapshot_path = Path(td) / "snapshot.json"
        snapshot_data = {
            "frame": frames,
            "chr_bank": snap.chr_bank,
            "ppuctrl": snap.ppuctrl,
            "ppumask": snap.ppumask,
            "palette_ram": list(snap.palette_ram),
            "oam": list(snap.oam),
        }
        if not rom.header or rom.header.chr_size == 0 or rom.mapper in (1, 4):
            snapshot_data["chr_data"] = list(snap.pattern_table)
        snapshot_path.write_text(json.dumps(snapshot_data), encoding="utf-8")
        manifest = export_runtime_oam_sprites(
            rom_path,
            snapshot_path,
            out_dir,
            include_hidden=include_hidden,
        )
    if manifest.manifest_json is not None:
        data = json.loads(manifest.manifest_json.read_text(encoding="utf-8"))
        data["snapshot"] = "in-process"
        data["runtime_frames"] = frames
        data.setdefault("notes", []).append(
            "Captured by qlnes in-process PPU/OAM observer; advanced PPU effects are not modeled."
        )
        manifest.manifest_json.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return manifest


def discover_nes_roms(path: Path, *, recursive: bool = False) -> list[Path]:
    """Return `.nes` ROM paths from one file or directory."""

    path = Path(path)
    if path.is_file():
        return [path] if path.suffix.lower() == ".nes" else []
    if not path.is_dir():
        raise FileNotFoundError(path)
    candidates = path.rglob("*") if recursive else path.iterdir()
    return sorted(p for p in candidates if p.is_file() and p.suffix.lower() == ".nes")


def _batch_out_dir(root: Path, rom: Path, out_dir: Path, used: set[Path]) -> Path:
    try:
        rel = rom.relative_to(root if root.is_dir() else root.parent)
    except ValueError:
        rel = Path(rom.name)
    candidate = out_dir / rel.with_suffix("")
    if candidate not in used:
        used.add(candidate)
        return candidate
    base = candidate
    idx = 2
    while True:
        candidate = base.with_name(f"{base.name}-{idx}")
        if candidate not in used:
            used.add(candidate)
            return candidate
        idx += 1


def export_sprite_batch(
    input_path: Path,
    out_dir: Path,
    *,
    recursive: bool = False,
    runtime_frames: int | None = None,
    include_hidden: bool = False,
    chr_bank: int = 0,
    pattern_table: int = 1,
    sprite_height: int = 8,
    palette_id: int = 0,
    palette_values: Sequence[int] | None = None,
    palette_source: str = "preview",
    per_tile: bool = True,
) -> BatchSpriteExportManifest:
    """Export transparent sprite PNGs for every `.nes` ROM under `input_path`.

    Static mode writes CHR preview sprites for every discovered ROM. Runtime
    mode (`runtime_frames` set) boots each ROM with the in-process observer and
    writes original-palette OAM sprites when the mapper/init path is supported.
    Failures are captured per ROM in the batch manifest so a collection run can
    continue and expose unsupported cases clearly.
    """

    input_path = Path(input_path)
    out_dir = Path(out_dir)
    roms = discover_nes_roms(input_path, recursive=recursive)
    used: set[Path] = set()
    batch = BatchSpriteExportManifest(out_dir=out_dir)

    for rom in roms:
        rom_out = _batch_out_dir(input_path, rom, out_dir, used)
        try:
            if runtime_frames is not None:
                manifest = export_in_process_runtime_sprites(
                    rom,
                    rom_out,
                    frames=runtime_frames,
                    include_hidden=include_hidden,
                )
            else:
                manifest = export_sprite_pattern_table(
                    rom,
                    rom_out,
                    chr_bank=chr_bank,
                    pattern_table=pattern_table,
                    sprite_height=sprite_height,
                    palette_id=palette_id,
                    palette_values=palette_values,
                    palette_source=palette_source,
                    per_tile=per_tile,
                )
            batch.entries.append(
                BatchSpriteExportEntry(
                    rom=rom,
                    out_dir=rom_out,
                    ok=True,
                    n_tiles=manifest.n_tiles,
                    spritesheet=manifest.spritesheet,
                    screen_png=manifest.screen_png,
                    manifest_json=manifest.manifest_json,
                )
            )
        except Exception as exc:
            batch.entries.append(
                BatchSpriteExportEntry(
                    rom=rom,
                    out_dir=rom_out,
                    ok=False,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )

    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_json = out_dir / "sprites-batch-manifest.json"
    manifest_json.write_text(
        json.dumps(
            {
                "kind": "sprite_batch_export",
                "input": str(input_path),
                "recursive": recursive,
                "mode": "runtime" if runtime_frames is not None else "static",
                "runtime_frames": runtime_frames,
                "rom_count": len(batch.entries),
                "success_count": batch.success_count,
                "failure_count": batch.failure_count,
                "transparent_index": 0,
                "entries": [
                    {
                        "rom": str(entry.rom),
                        "out_dir": str(entry.out_dir),
                        "ok": entry.ok,
                        "n_tiles": entry.n_tiles,
                        "spritesheet": str(entry.spritesheet) if entry.spritesheet else None,
                        "screen_png": str(entry.screen_png) if entry.screen_png else None,
                        "manifest_json": (
                            str(entry.manifest_json) if entry.manifest_json else None
                        ),
                        "error": entry.error,
                    }
                    for entry in batch.entries
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    batch.manifest_json = manifest_json
    return batch
