"""Extraction des assets graphiques d'une ROM NES.

Le format CHR-ROM NES :
- chaque tile = 8×8 pixels, 2 bits per pixel (4 couleurs : 0..3)
- 16 octets par tile : 8 octets pour le bit 0 de chaque pixel,
  puis 8 octets pour le bit 1
- pour la ligne r et la colonne c : pixel = ((plane0[r] >> (7-c)) & 1)
                                           | (((plane1[r] >> (7-c)) & 1) << 1)

Une banque CHR fait 8 KB = 512 tiles = 2 pattern tables (background +
sprites). Chaque pattern table est un grid 16×16 = 256 tiles.

Le module sort :
- `chr_rom.chr` : binaire brut (réutilisable dans un éditeur de tile)
- `chr_tiles.png` (ou .ppm si Pillow indispo) : grille complète
- `pattern_table_bg.png` : 1ère banque PT0 ($0000-$0FFF côté PPU)
- `pattern_table_spr.png` : 2e banque PT1 ($1000-$1FFF côté PPU)
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .ines import HEADER_SIZE
from .rom import Rom


NES_PALETTE_GRAYSCALE = [
    (0x00, 0x00, 0x00),
    (0x55, 0x55, 0x55),
    (0xAA, 0xAA, 0xAA),
    (0xFF, 0xFF, 0xFF),
]

NES_PALETTE_DEFAULT = [
    (0x0F, 0x0F, 0x0F),
    (0x77, 0x77, 0x77),
    (0xBB, 0xBB, 0xBB),
    (0xFF, 0xFF, 0xFF),
]

PATTERN_TABLE_BYTES = 0x1000
TILE_BYTES = 16


@dataclass
class AssetsManifest:
    out_dir: Path
    chr_raw: Optional[Path] = None
    chr_asm: Optional[Path] = None
    full_image: Optional[Path] = None
    bg_image: Optional[Path] = None
    spr_image: Optional[Path] = None
    n_tiles: int = 0
    notes: List[str] = field(default_factory=list)

    def to_rows(self) -> List[str]:
        rows: List[str] = []
        rows.append(f"- Dossier : `{self.out_dir}`")
        if self.chr_raw:
            rows.append(f"- CHR brute : `{self.chr_raw.name}` (binaire 8KB / banque)")
        if self.chr_asm:
            rows.append(f"- CHR en ASM (réassemblable) : `{self.chr_asm.name}`")
        if self.full_image:
            rows.append(f"- Aperçu image complète : `{self.full_image.name}` ({self.n_tiles} tiles)")
        if self.bg_image:
            rows.append(f"- Pattern table BG : `{self.bg_image.name}`")
        if self.spr_image:
            rows.append(f"- Pattern table sprites : `{self.spr_image.name}`")
        for n in self.notes:
            rows.append(f"- _{n}_")
        return rows


def decode_tile(tile_bytes: bytes) -> List[List[int]]:
    if len(tile_bytes) != TILE_BYTES:
        raise ValueError(f"tile must be {TILE_BYTES} bytes, got {len(tile_bytes)}")
    out: List[List[int]] = []
    for r in range(8):
        plane0 = tile_bytes[r]
        plane1 = tile_bytes[r + 8]
        row: List[int] = []
        for c in range(8):
            bit0 = (plane0 >> (7 - c)) & 1
            bit1 = (plane1 >> (7 - c)) & 1
            row.append(bit0 | (bit1 << 1))
        out.append(row)
    return out


def _draw_chr_to_pixels(
    chr_data: bytes, tiles_per_row: int = 16
) -> tuple:
    n_tiles = len(chr_data) // TILE_BYTES
    if n_tiles == 0:
        return None, 0, 0, 0
    n_rows = (n_tiles + tiles_per_row - 1) // tiles_per_row
    width = tiles_per_row * 8
    height = n_rows * 8
    pixels = bytearray(width * height)
    for i in range(n_tiles):
        tile = decode_tile(chr_data[i * TILE_BYTES : (i + 1) * TILE_BYTES])
        x_off = (i % tiles_per_row) * 8
        y_off = (i // tiles_per_row) * 8
        for r in range(8):
            for c in range(8):
                pixels[(y_off + r) * width + x_off + c] = tile[r][c]
    return pixels, width, height, n_tiles


def _tile_ascii_preview(tile_rows: List[List[int]]) -> List[str]:
    glyphs = (" ", "░", "▒", "█")
    return ["    ; " + "".join(glyphs[p] for p in row) for row in tile_rows]


def write_chr_asm(
    chr_data: bytes,
    out_path: Path,
    *,
    bank_label: str = "CHR_DATA",
    rom_name: str = "rom",
    with_preview: bool = True,
) -> Path:
    n_tiles = len(chr_data) // TILE_BYTES
    pt_size = PATTERN_TABLE_BYTES // TILE_BYTES
    total_pt = (len(chr_data) + PATTERN_TABLE_BYTES - 1) // PATTERN_TABLE_BYTES

    lines: List[str] = []
    lines.append(f"; ============================================================")
    lines.append(f"; CHR-ROM dump — {rom_name}")
    lines.append(f"; {len(chr_data)} octets / {n_tiles} tiles / {total_pt} pattern table(s)")
    lines.append(";")
    lines.append("; Chaque tile = 16 octets : 8 octets plane 0 + 8 octets plane 1")
    lines.append("; pixel = (plane0 bit) | (plane1 bit << 1)  ⇒ couleur 0..3")
    lines.append(";")
    lines.append("; Réassemblable avec ca65/asm6/nesasm :")
    lines.append("; ca65 chr.asm -o chr.o && ld65 -t nes chr.o -o chr.bin")
    lines.append("; ou via .incbin dans un projet existant.")
    lines.append("; ============================================================")
    lines.append("")
    lines.append(f"{bank_label}:")
    lines.append("")

    for tile_idx in range(n_tiles):
        offset = tile_idx * TILE_BYTES
        tile_bytes = chr_data[offset : offset + TILE_BYTES]
        pt_idx = tile_idx // pt_size
        in_pt_idx = tile_idx % pt_size
        if in_pt_idx == 0:
            lines.append(
                f"; ===== Pattern Table {pt_idx} "
                f"(PPU ${pt_idx * 0x1000:04X}-${pt_idx * 0x1000 + 0xFFF:04X}) ====="
            )
        lines.append(f"; --- Tile ${tile_idx:03X} (PT{pt_idx}[${in_pt_idx:02X}]) ---")
        plane0 = ",".join(f"${b:02X}" for b in tile_bytes[:8])
        plane1 = ",".join(f"${b:02X}" for b in tile_bytes[8:])
        lines.append(f"    .byte {plane0}  ; plane 0")
        lines.append(f"    .byte {plane1}  ; plane 1")
        if with_preview:
            decoded = decode_tile(tile_bytes)
            lines.extend(_tile_ascii_preview(decoded))
        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def _save_png_or_ppm(
    pixels: bytearray, width: int, height: int, out_path: Path,
    palette=NES_PALETTE_DEFAULT,
) -> Path:
    try:
        from PIL import Image
        img = Image.new("P", (width, height))
        flat: List[int] = []
        for color in palette:
            flat.extend(color)
        flat.extend([0] * (256 * 3 - len(flat)))
        img.putpalette(flat)
        img.putdata(bytes(pixels))
        png_path = out_path.with_suffix(".png")
        img.save(png_path)
        return png_path
    except ImportError:
        ppm_path = out_path.with_suffix(".ppm")
        with open(ppm_path, "wb") as f:
            f.write(f"P6\n{width} {height}\n255\n".encode())
            for color in pixels:
                f.write(bytes(palette[color]))
        return ppm_path


def extract_chr(rom: Rom, out_dir: Path) -> AssetsManifest:
    manifest = AssetsManifest(out_dir=out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    h = rom.header
    if h is None or h.chr_size == 0:
        manifest.notes.append("Pas de CHR-ROM (CHR-RAM ou ROM brute) — graphismes générés à l'exécution.")
        return manifest
    chr_offset = HEADER_SIZE + (512 if h.has_trainer else 0) + h.prg_size
    chr_data = rom.raw[chr_offset : chr_offset + h.chr_size]

    raw_path = out_dir / "chr_rom.chr"
    raw_path.write_bytes(chr_data)
    manifest.chr_raw = raw_path

    asm_path = out_dir / "chr_rom.asm"
    write_chr_asm(
        chr_data,
        asm_path,
        bank_label="CHR_DATA",
        rom_name=getattr(rom, "name", "rom"),
    )
    manifest.chr_asm = asm_path

    pixels, width, height, n_tiles = _draw_chr_to_pixels(chr_data, tiles_per_row=16)
    manifest.n_tiles = n_tiles
    if pixels is not None:
        full = out_dir / "chr_tiles"
        manifest.full_image = _save_png_or_ppm(pixels, width, height, full)

    if len(chr_data) >= PATTERN_TABLE_BYTES:
        bg = chr_data[:PATTERN_TABLE_BYTES]
        bg_pixels, bw, bh, _ = _draw_chr_to_pixels(bg, tiles_per_row=16)
        if bg_pixels is not None:
            manifest.bg_image = _save_png_or_ppm(
                bg_pixels, bw, bh, out_dir / "pattern_table_bg"
            )
    if len(chr_data) >= 2 * PATTERN_TABLE_BYTES:
        spr = chr_data[PATTERN_TABLE_BYTES : 2 * PATTERN_TABLE_BYTES]
        sp_pixels, sw, sh, _ = _draw_chr_to_pixels(spr, tiles_per_row=16)
        if sp_pixels is not None:
            manifest.spr_image = _save_png_or_ppm(
                sp_pixels, sw, sh, out_dir / "pattern_table_spr"
            )
    return manifest
