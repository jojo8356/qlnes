"""Extraction des assets graphiques d'une ROM NES.

Le format CHR-ROM NES :
- chaque tile = 8x8 pixels, 2 bits per pixel (4 couleurs : 0..3)
- 16 octets par tile : 8 octets pour le bit 0 de chaque pixel,
  puis 8 octets pour le bit 1
- pour la ligne r et la colonne c : pixel = ((plane0[r] >> (7-c)) & 1)
                                           | (((plane1[r] >> (7-c)) & 1) << 1)

Une banque CHR fait 8 KB = 512 tiles = 2 pattern tables (background +
sprites). Chaque pattern table est un grid 16x16 = 256 tiles.

Le module sort :
- `chr_rom.chr` : binaire brut (réutilisable dans un éditeur de tile)
- `chr_tiles.png` (ou .ppm si Pillow indispo) : grille complète
- `pattern_table_bg.png` : 1ère banque PT0 ($0000-$0FFF côté PPU)
- `pattern_table_spr.png` : 2e banque PT1 ($1000-$1FFF côté PPU)
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from .ines import HEADER_SIZE
from .rom import Rom

if TYPE_CHECKING:
    from .annotate import AnnotationReport


_NAMED_LABEL_RE = re.compile(r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*):(?P<rest>\s+\S.*)$")


def _restore_named_labels(asm: str, name_to_addr: dict[str, int]) -> str:
    """Réécrit `update_scroll: ...` en `L_8EDD: ...` pour que `Disasm`
    (qui n'attend que des labels `L_XXXX`) puisse retrouver les adresses
    des subroutines déjà renommées par l'annotateur."""
    out: list[str] = []
    for line in asm.splitlines():
        m = _NAMED_LABEL_RE.match(line)
        if m:
            addr = name_to_addr.get(m.group("name"))
            if addr is not None:
                line = f"L_{addr:04X}:{m.group('rest')}"
        out.append(line)
    return "\n".join(out)


MUSIC_KINDS = frozenset({"play_pulse", "play_triangle", "play_noise", "play_dmc", "play_sound"})


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
    chr_raw: Path | None = None
    chr_asm: Path | None = None
    full_image: Path | None = None
    bg_image: Path | None = None
    spr_image: Path | None = None
    n_tiles: int = 0
    music_asm: Path | None = None
    music_routines: int = 0
    notes: list[str] = field(default_factory=list)

    def to_rows(self) -> list[str]:
        rows: list[str] = []
        rows.append(f"- Dossier : `{self.out_dir}`")
        if self.chr_raw:
            rows.append(f"- CHR brute : `{self.chr_raw.name}` (binaire 8KB / banque)")
        if self.chr_asm:
            rows.append(f"- CHR en ASM (réassemblable) : `{self.chr_asm.name}`")
        if self.full_image:
            rows.append(
                f"- Aperçu image complète : `{self.full_image.name}` ({self.n_tiles} tiles)"
            )
        if self.bg_image:
            rows.append(f"- Pattern table BG : `{self.bg_image.name}`")
        if self.spr_image:
            rows.append(f"- Pattern table sprites : `{self.spr_image.name}`")
        if self.music_asm:
            rows.append(
                f"- Sound engine en ASM : `{self.music_asm.name}` "
                f"({self.music_routines} routine{'s' if self.music_routines > 1 else ''})"
            )
        for n in self.notes:
            rows.append(f"- _{n}_")
        return rows


def decode_tile(tile_bytes: bytes) -> list[list[int]]:
    if len(tile_bytes) != TILE_BYTES:
        raise ValueError(f"tile must be {TILE_BYTES} bytes, got {len(tile_bytes)}")
    out: list[list[int]] = []
    for r in range(8):
        plane0 = tile_bytes[r]
        plane1 = tile_bytes[r + 8]
        row: list[int] = []
        for c in range(8):
            bit0 = (plane0 >> (7 - c)) & 1
            bit1 = (plane1 >> (7 - c)) & 1
            row.append(bit0 | (bit1 << 1))
        out.append(row)
    return out


def _draw_chr_to_pixels(
    chr_data: bytes, tiles_per_row: int = 16
) -> tuple[bytearray | None, int, int, int]:
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


def _tile_ascii_preview(tile_rows: list[list[int]]) -> list[str]:
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

    lines: list[str] = []
    lines.append("; ============================================================")
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
    pixels: bytearray,
    width: int,
    height: int,
    out_path: Path,
    palette: list[tuple[int, int, int]] = NES_PALETTE_DEFAULT,
) -> Path:
    try:
        from PIL import Image

        img = Image.new("P", (width, height))
        flat: list[int] = []
        for rgb in palette:
            flat.extend(rgb)
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
            for px in pixels:
                f.write(bytes(palette[px]))
        return ppm_path


def extract_music(
    bank_asms: list[str],
    bank_reports: list["AnnotationReport"],
    out_dir: Path,
    rom_name: str = "rom",
) -> tuple[Path | None, int]:
    """Extrait toutes les routines audio (kind ∈ play_pulse/triangle/noise/dmc/sound)
    dans `out_dir/music.asm`.

    Le fichier est **informatif** : les bytes restent dans les `.bank*.asm`
    pour que le round-trip continue à matcher byte-pour-byte. C'est un calque
    pratique pour modder le moteur audio sans naviguer dans les 5000 lignes
    du désassemblage complet.
    """
    from .parser import Disasm

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "music.asm"

    head: list[str] = [
        "; ============================================================",
        f"; Sound / music engine — {rom_name}",
        "; Extrait par qlnes (copie informative).",
        ";",
        "; Les bytes correspondants restent dans les fichiers .bank*.asm,",
        "; donc le round-trip qlnes recompile ne dépend PAS de ce fichier.",
        "; ============================================================",
        "",
    ]
    body: list[str] = []
    routine_count = 0

    for bank_idx, (asm, report) in enumerate(zip(bank_asms, bank_reports, strict=False)):
        music_subs = sorted(
            (entry, name)
            for entry, name in report.subroutines.items()
            if entry in report.subroutine_details
            and report.subroutine_details[entry].kind in MUSIC_KINDS
        )
        if not music_subs:
            continue

        body.append("; ============================================================")
        body.append(f"; === Bank {bank_idx} ===")
        body.append("; ============================================================")
        body.append("")

        name_to_addr = {n: a for a, n in report.subroutines.items()}
        disasm = Disasm(_restore_named_labels(asm, name_to_addr))
        addr_to_idx = {ln.addr: i for i, ln in enumerate(disasm.lines) if ln.addr >= 0}

        for entry, name in music_subs:
            sub = report.subroutine_details[entry]
            body.append("; ------------------------------------------------------------")
            body.append(f"; {name} @ ${entry:04X}  ({sub.kind})")
            if sub.why:
                body.append(f";   {sub.why}")
            body.append("; ------------------------------------------------------------")

            start = addr_to_idx.get(entry)
            if start is None:
                body.append(f"; <introuvable dans le bank {bank_idx}>")
                body.append("")
                continue

            for ln in disasm.lines[start : start + 200]:
                body.append(ln.raw)
                up = (ln.mnemonic or "").upper()
                if up in ("RTS", "RTI"):
                    break
            else:
                body.append("; ... (sub > 200 lignes, tronquée)")
            body.append("")
            routine_count += 1

    if routine_count == 0:
        return None, 0

    out_path.write_text("\n".join(head + body), encoding="utf-8")
    return out_path, routine_count


def extract_chr(rom: Rom, out_dir: Path) -> AssetsManifest:
    manifest = AssetsManifest(out_dir=out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    h = rom.header
    if h is None or h.chr_size == 0:
        manifest.notes.append(
            "Pas de CHR-ROM (CHR-RAM ou ROM brute) — graphismes générés à l'exécution."
        )
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
            manifest.bg_image = _save_png_or_ppm(bg_pixels, bw, bh, out_dir / "pattern_table_bg")
    if len(chr_data) >= 2 * PATTERN_TABLE_BYTES:
        spr = chr_data[PATTERN_TABLE_BYTES : 2 * PATTERN_TABLE_BYTES]
        sp_pixels, sw, sh, _ = _draw_chr_to_pixels(spr, tiles_per_row=16)
        if sp_pixels is not None:
            manifest.spr_image = _save_png_or_ppm(sp_pixels, sw, sh, out_dir / "pattern_table_spr")
    return manifest
