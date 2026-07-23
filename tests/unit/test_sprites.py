import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from qlnes.sprites import (
    DEFAULT_SPRITE_PALETTE,
    chr_from_ines,
    decode_sprite_pattern,
    export_in_process_runtime_sprite_samples,
    export_in_process_runtime_sprites,
    export_runtime_oam_sprites,
    export_sprite_batch,
    export_sprite_pattern_table,
    load_runtime_sprite_snapshot,
    normalize_palette_ram,
    parse_palette_values,
    parse_runtime_input_script,
    rgba_for_sprite_pixel,
    sprite_palette_to_palette_ram,
)
from tests.test_setup import PRG_BANK, ines_header


def _encode_tile(rows: list[list[int]]) -> bytes:
    plane0: list[int] = []
    plane1: list[int] = []
    for row in rows:
        lo = 0
        hi = 0
        for col, value in enumerate(row):
            bit = 7 - col
            lo |= (value & 1) << bit
            hi |= ((value >> 1) & 1) << bit
        plane0.append(lo)
        plane1.append(hi)
    return bytes(plane0 + plane1)


def _sprite_test_rom() -> bytes:
    prg = bytes([0xEA] * PRG_BANK)
    chr_data = bytearray(0x2000)
    rows = [[0, 1, 2, 3, 0, 1, 2, 3] for _ in range(8)]
    # Tile $00 in sprite pattern table 1 ($1000).
    chr_data[0x1000 : 0x1010] = _encode_tile(rows)
    return ines_header(1, 1, 0) + prg + bytes(chr_data)


def _runtime_sprite_test_rom() -> bytes:
    code = [
        0x78,  # SEI
        0xD8,  # CLD
        0xA2, 0x00,  # LDX #$00
        0xA9, 0xF8,  # LDA #$F8
        # fill_oam:
        0x9D, 0x00, 0x02,  # STA $0200,X
        0xE8,  # INX
        0xD0, 0xFA,  # BNE fill_oam
        0xA9, 0x14, 0x8D, 0x00, 0x02,  # sprite0 y=$14
        0xA9, 0x00, 0x8D, 0x01, 0x02,  # sprite0 tile=$00
        0xA9, 0x00, 0x8D, 0x02, 0x02,  # sprite0 attr palette 0
        0xA9, 0x0C, 0x8D, 0x03, 0x02,  # sprite0 x=$0C
        0xA9, 0x00, 0x8D, 0x03, 0x20,  # OAMADDR=0
        0xA9, 0x02, 0x8D, 0x14, 0x40,  # OAMDMA page $02
        0xAD, 0x02, 0x20,  # LDA PPUSTATUS (reset addr latch)
        0xA9, 0x3F, 0x8D, 0x06, 0x20,  # PPUADDR high $3F
        0xA9, 0x10, 0x8D, 0x06, 0x20,  # PPUADDR low $10
    ]
    for value in (0x0F, 0x30, 0x16, 0x27):
        code.extend([0xA9, value, 0x8D, 0x07, 0x20])  # LDA #value ; STA PPUDATA
    code.extend(
        [
            0xA9, 0x88, 0x8D, 0x00, 0x20,  # PPUCTRL: NMI on, sprite PT1
            0xA9, 0x1E, 0x8D, 0x01, 0x20,  # PPUMASK
        ]
    )
    loop_addr = 0x8000 + len(code)
    code.extend([0x4C, loop_addr & 0xFF, loop_addr >> 8])  # JMP stable loop
    prg = bytearray([0xEA] * PRG_BANK)
    prg[: len(code)] = bytes(code)
    prg[0x0100] = 0x40  # RTI for NMI/IRQ
    prg[0x3FFA:0x3FFC] = (0x8100).to_bytes(2, "little")
    prg[0x3FFC:0x3FFE] = (0x8000).to_bytes(2, "little")
    prg[0x3FFE:0x4000] = (0x8100).to_bytes(2, "little")
    chr_data = bytearray(0x2000)
    rows = [[0, 1, 2, 3, 0, 1, 2, 3] for _ in range(8)]
    chr_data[0x1000 : 0x1010] = _encode_tile(rows)
    return ines_header(1, 1, 0) + bytes(prg) + bytes(chr_data)


def _runtime_nrom_chr_ram_sprite_test_rom() -> bytes:
    rows = [[0, 1, 2, 3, 0, 1, 2, 3] for _ in range(8)]
    tile = _encode_tile(rows)
    code = [
        0x78,  # SEI
        0xD8,  # CLD
        0xA2, 0x00,  # LDX #$00
        0xA9, 0xF8,  # LDA #$F8
        0x9D, 0x00, 0x02,  # fill_oam: STA $0200,X
        0xE8,  # INX
        0xD0, 0xFA,  # BNE fill_oam
        0xA9, 0x14, 0x8D, 0x00, 0x02,  # sprite0 y=$14
        0xA9, 0x00, 0x8D, 0x01, 0x02,  # sprite0 tile=$00
        0xA9, 0x00, 0x8D, 0x02, 0x02,  # sprite0 attr palette 0
        0xA9, 0x0C, 0x8D, 0x03, 0x02,  # sprite0 x=$0C
        0xA9, 0x00, 0x8D, 0x03, 0x20,  # OAMADDR=0
        0xA9, 0x02, 0x8D, 0x14, 0x40,  # OAMDMA page $02
        0xAD, 0x02, 0x20,  # LDA PPUSTATUS (reset addr latch)
        0xA9, 0x10, 0x8D, 0x06, 0x20,  # PPUADDR high $10
        0xA9, 0x00, 0x8D, 0x06, 0x20,  # PPUADDR low $00
    ]
    for value in tile:
        code.extend([0xA9, value, 0x8D, 0x07, 0x20])
    code.extend(
        [
            0xAD, 0x02, 0x20,  # LDA PPUSTATUS
            0xA9, 0x3F, 0x8D, 0x06, 0x20,  # PPUADDR high $3F
            0xA9, 0x10, 0x8D, 0x06, 0x20,  # PPUADDR low $10
        ]
    )
    for value in (0x0F, 0x30, 0x16, 0x27):
        code.extend([0xA9, value, 0x8D, 0x07, 0x20])
    code.extend(
        [
            0xA9, 0x88, 0x8D, 0x00, 0x20,  # PPUCTRL: NMI on, sprite PT1
            0xA9, 0x1E, 0x8D, 0x01, 0x20,  # PPUMASK
        ]
    )
    loop_addr = 0x8000 + len(code)
    code.extend([0x4C, loop_addr & 0xFF, loop_addr >> 8])  # JMP stable loop
    prg = bytearray([0xEA] * PRG_BANK)
    prg[: len(code)] = bytes(code)
    prg[0x0100] = 0x40
    prg[0x3FFA:0x3FFC] = (0x8100).to_bytes(2, "little")
    prg[0x3FFC:0x3FFE] = (0x8000).to_bytes(2, "little")
    prg[0x3FFE:0x4000] = (0x8100).to_bytes(2, "little")
    return ines_header(1, 0, 0) + bytes(prg)


def _runtime_prg_ram_oamdma_sprite_test_rom() -> bytes:
    code = [
        0x78,  # SEI
        0xD8,  # CLD
        0xA2, 0x00,  # LDX #$00
        0xA9, 0xF8,  # LDA #$F8
        0x9D, 0x00, 0x60,  # fill_prg_ram_oam: STA $6000,X
        0xE8,  # INX
        0xD0, 0xFA,  # BNE fill_prg_ram_oam
        0xA9, 0x14, 0x8D, 0x00, 0x60,  # sprite0 y=$14
        0xA9, 0x00, 0x8D, 0x01, 0x60,  # sprite0 tile=$00
        0xA9, 0x00, 0x8D, 0x02, 0x60,  # sprite0 attr palette 0
        0xA9, 0x0C, 0x8D, 0x03, 0x60,  # sprite0 x=$0C
        0xA9, 0x00, 0x8D, 0x03, 0x20,  # OAMADDR=0
        0xA9, 0x60, 0x8D, 0x14, 0x40,  # OAMDMA page $60
        0xAD, 0x02, 0x20,  # LDA PPUSTATUS (reset addr latch)
        0xA9, 0x3F, 0x8D, 0x06, 0x20,  # PPUADDR high $3F
        0xA9, 0x10, 0x8D, 0x06, 0x20,  # PPUADDR low $10
    ]
    for value in (0x0F, 0x30, 0x16, 0x27):
        code.extend([0xA9, value, 0x8D, 0x07, 0x20])
    code.extend(
        [
            0xA9, 0x88, 0x8D, 0x00, 0x20,  # PPUCTRL: NMI on, sprite PT1
            0xA9, 0x1E, 0x8D, 0x01, 0x20,  # PPUMASK
        ]
    )
    loop_addr = 0x8000 + len(code)
    code.extend([0x4C, loop_addr & 0xFF, loop_addr >> 8])
    prg = bytearray([0xEA] * PRG_BANK)
    prg[: len(code)] = bytes(code)
    prg[0x0100] = 0x40
    prg[0x3FFA:0x3FFC] = (0x8100).to_bytes(2, "little")
    prg[0x3FFC:0x3FFE] = (0x8000).to_bytes(2, "little")
    prg[0x3FFE:0x4000] = (0x8100).to_bytes(2, "little")
    chr_data = bytearray(0x2000)
    rows = [[0, 1, 2, 3, 0, 1, 2, 3] for _ in range(8)]
    chr_data[0x1000 : 0x1010] = _encode_tile(rows)
    return ines_header(1, 1, 0) + bytes(prg) + bytes(chr_data)


def _runtime_cprom_chr_ram_sprite_test_rom() -> bytes:
    rows = [[0, 1, 2, 3, 0, 1, 2, 3] for _ in range(8)]
    tile = _encode_tile(rows)
    code = [
        0x78,  # SEI
        0xD8,  # CLD
        0xA9, 0x02, 0x8D, 0x00, 0x80,  # CPROM CHR-RAM bank 2 at $1000-$1FFF
        0xA2, 0x00,
        0xA9, 0xF8,
        0x9D, 0x00, 0x02,
        0xE8,
        0xD0, 0xFA,
        0xA9, 0x14, 0x8D, 0x00, 0x02,
        0xA9, 0x00, 0x8D, 0x01, 0x02,
        0xA9, 0x00, 0x8D, 0x02, 0x02,
        0xA9, 0x0C, 0x8D, 0x03, 0x02,
        0xA9, 0x00, 0x8D, 0x03, 0x20,
        0xA9, 0x02, 0x8D, 0x14, 0x40,
        0xAD, 0x02, 0x20,
        0xA9, 0x10, 0x8D, 0x06, 0x20,
        0xA9, 0x00, 0x8D, 0x06, 0x20,
    ]
    for value in tile:
        code.extend([0xA9, value, 0x8D, 0x07, 0x20])
    code.extend(
        [
            0xAD, 0x02, 0x20,
            0xA9, 0x3F, 0x8D, 0x06, 0x20,
            0xA9, 0x10, 0x8D, 0x06, 0x20,
        ]
    )
    for value in (0x0F, 0x30, 0x16, 0x27):
        code.extend([0xA9, value, 0x8D, 0x07, 0x20])
    code.extend([0xA9, 0x88, 0x8D, 0x00, 0x20, 0xA9, 0x1E, 0x8D, 0x01, 0x20])
    loop_addr = 0x8000 + len(code)
    code.extend([0x4C, loop_addr & 0xFF, loop_addr >> 8])
    prg = bytearray([0xEA] * 0x8000)
    prg[: len(code)] = bytes(code)
    prg[0x0100] = 0x40
    prg[0x7FFA:0x7FFC] = (0x8100).to_bytes(2, "little")
    prg[0x7FFC:0x7FFE] = (0x8000).to_bytes(2, "little")
    prg[0x7FFE:0x8000] = (0x8100).to_bytes(2, "little")
    return ines_header(2, 0, 13) + bytes(prg)


def _runtime_start_gated_sprite_test_rom() -> bytes:
    reset = [
        0x78,  # SEI
        0xD8,  # CLD
        0xA2, 0x00,  # LDX #0
        0xA9, 0xF8,  # LDA #hidden Y
        0x9D, 0x00, 0x02,  # fill_oam: STA $0200,X
        0xE8,  # INX
        0xD0, 0xFA,  # BNE fill_oam
        0xA9, 0x00, 0x8D, 0x03, 0x20,  # OAMADDR=0
        0xA9, 0x02, 0x8D, 0x14, 0x40,  # OAMDMA page $02
        0xA9, 0x88, 0x8D, 0x00, 0x20,  # PPUCTRL: NMI on, sprite PT1
        0xA9, 0x1E, 0x8D, 0x01, 0x20,  # PPUMASK
        0x4C, 0x20, 0x80,  # JMP stable loop
    ]
    nmi = [
        0xA9, 0x01, 0x8D, 0x16, 0x40,  # strobe controller
        0xA9, 0x00, 0x8D, 0x16, 0x40,
        0xAD, 0x16, 0x40,  # read A
        0xAD, 0x16, 0x40,  # read B
        0xAD, 0x16, 0x40,  # read Select
        0xAD, 0x16, 0x40,  # read Start
        0x29, 0x01,  # AND #1
        0xF0, 0x3F,  # BEQ rti
        0xA9, 0x14, 0x8D, 0x00, 0x02,
        0xA9, 0x00, 0x8D, 0x01, 0x02,
        0xA9, 0x00, 0x8D, 0x02, 0x02,
        0xA9, 0x0C, 0x8D, 0x03, 0x02,
        0xA9, 0x00, 0x8D, 0x03, 0x20,
        0xA9, 0x02, 0x8D, 0x14, 0x40,
        0xAD, 0x02, 0x20,
        0xA9, 0x3F, 0x8D, 0x06, 0x20,
        0xA9, 0x10, 0x8D, 0x06, 0x20,
    ]
    for value in (0x0F, 0x30, 0x16, 0x27):
        nmi.extend([0xA9, value, 0x8D, 0x07, 0x20])
    nmi.extend([0x40])  # RTI target for BEQ
    prg = bytearray([0xEA] * PRG_BANK)
    prg[: len(reset)] = bytes(reset)
    prg[0x0100 : 0x0100 + len(nmi)] = bytes(nmi)
    prg[0x3FFA:0x3FFC] = (0x8100).to_bytes(2, "little")
    prg[0x3FFC:0x3FFE] = (0x8000).to_bytes(2, "little")
    prg[0x3FFE:0x4000] = (0x8100).to_bytes(2, "little")
    chr_data = bytearray(0x2000)
    rows = [[0, 1, 2, 3, 0, 1, 2, 3] for _ in range(8)]
    chr_data[0x1000 : 0x1010] = _encode_tile(rows)
    return ines_header(1, 1, 0) + bytes(prg) + bytes(chr_data)


def _runtime_cnrom_sprite_test_rom() -> bytes:
    code = [
        0x78,  # SEI
        0xD8,  # CLD
        0xA9, 0x01, 0x8D, 0x00, 0x80,  # select CHR bank 1
        0xA2, 0x00,  # LDX #$00
        0xA9, 0xF8,  # LDA #$F8
        0x9D, 0x00, 0x02,  # fill_oam: STA $0200,X
        0xE8,  # INX
        0xD0, 0xFA,  # BNE fill_oam
        0xA9, 0x14, 0x8D, 0x00, 0x02,
        0xA9, 0x00, 0x8D, 0x01, 0x02,
        0xA9, 0x00, 0x8D, 0x02, 0x02,
        0xA9, 0x0C, 0x8D, 0x03, 0x02,
        0xA9, 0x00, 0x8D, 0x03, 0x20,
        0xA9, 0x02, 0x8D, 0x14, 0x40,
        0xAD, 0x02, 0x20,
        0xA9, 0x3F, 0x8D, 0x06, 0x20,
        0xA9, 0x10, 0x8D, 0x06, 0x20,
    ]
    for value in (0x0F, 0x30, 0x16, 0x27):
        code.extend([0xA9, value, 0x8D, 0x07, 0x20])
    code.extend([0xA9, 0x88, 0x8D, 0x00, 0x20])
    loop_addr = 0x8000 + len(code)
    code.extend([0x4C, loop_addr & 0xFF, loop_addr >> 8])
    prg = bytearray([0xEA] * PRG_BANK)
    prg[: len(code)] = bytes(code)
    prg[0x0100] = 0x40
    prg[0x3FFA:0x3FFC] = (0x8100).to_bytes(2, "little")
    prg[0x3FFC:0x3FFE] = (0x8000).to_bytes(2, "little")
    prg[0x3FFE:0x4000] = (0x8100).to_bytes(2, "little")
    chr_data = bytearray(0x4000)
    rows = [[0, 1, 2, 3, 0, 1, 2, 3] for _ in range(8)]
    # Bank 0 is intentionally blank; bank 1 contains the sprite tile.
    chr_data[0x2000 + 0x1000 : 0x2000 + 0x1010] = _encode_tile(rows)
    return ines_header(1, 2, 3) + bytes(prg) + bytes(chr_data)


def _runtime_uxrom_sprite_test_rom() -> bytes:
    bank0 = bytearray([0xEA] * PRG_BANK)
    bank1 = bytearray([0xEA] * PRG_BANK)
    bank2 = bytearray([0xEA] * PRG_BANK)
    bank3 = bytearray([0xEA] * PRG_BANK)

    code = [
        0x78,  # SEI
        0xD8,  # CLD
        0xA2, 0x00,
        0xA9, 0xF8,
        0x9D, 0x00, 0x02,
        0xE8,
        0xD0, 0xFA,
        0xA9, 0x14, 0x8D, 0x00, 0x02,
        0xA9, 0x00, 0x8D, 0x01, 0x02,
        0xA9, 0x00, 0x8D, 0x02, 0x02,
        0xA9, 0x0C, 0x8D, 0x03, 0x02,
        0xA9, 0x00, 0x8D, 0x03, 0x20,
        0xA9, 0x02, 0x8D, 0x14, 0x40,
        0xAD, 0x02, 0x20,
        0xA9, 0x3F, 0x8D, 0x06, 0x20,
        0xA9, 0x10, 0x8D, 0x06, 0x20,
    ]
    for value in (0x0F, 0x30, 0x16, 0x27):
        code.extend([0xA9, value, 0x8D, 0x07, 0x20])
    code.extend([0xA9, 0x88, 0x8D, 0x00, 0x20])
    loop_addr = 0x8000 + len(code)
    code.extend([0x4C, loop_addr & 0xFF, loop_addr >> 8])
    bank1[0x0100 : 0x0100 + len(code)] = bytes(code)

    reset = [
        0xA9, 0x01, 0x8D, 0x00, 0x80,  # select switchable PRG bank 1
        0x4C, 0x00, 0x80,  # JMP $8000 in selected bank
    ]
    bank3[: len(reset)] = bytes(reset)
    bank3[0x0100] = 0x40
    bank3[0x3FFA:0x3FFC] = (0xC100).to_bytes(2, "little")
    bank3[0x3FFC:0x3FFE] = (0xC000).to_bytes(2, "little")
    bank3[0x3FFE:0x4000] = (0xC100).to_bytes(2, "little")

    chr_data = bytearray(0x2000)
    rows = [[0, 1, 2, 3, 0, 1, 2, 3] for _ in range(8)]
    chr_data[0x1000 : 0x1010] = _encode_tile(rows)
    return ines_header(4, 1, 2) + bytes(bank0 + bank1 + bank2 + bank3) + bytes(chr_data)


def _runtime_gxrom_sprite_test_rom() -> bytes:
    bank0 = bytearray([0xEA] * 0x8000)
    bank1 = bytearray([0xEA] * 0x8000)

    code = [
        0x78,  # SEI
        0xD8,  # CLD
        0xA2, 0x00,
        0xA9, 0xF8,
        0x9D, 0x00, 0x02,
        0xE8,
        0xD0, 0xFA,
        0xA9, 0x14, 0x8D, 0x00, 0x02,
        0xA9, 0x00, 0x8D, 0x01, 0x02,
        0xA9, 0x00, 0x8D, 0x02, 0x02,
        0xA9, 0x0C, 0x8D, 0x03, 0x02,
        0xA9, 0x00, 0x8D, 0x03, 0x20,
        0xA9, 0x02, 0x8D, 0x14, 0x40,
        0xAD, 0x02, 0x20,
        0xA9, 0x3F, 0x8D, 0x06, 0x20,
        0xA9, 0x10, 0x8D, 0x06, 0x20,
    ]
    for value in (0x0F, 0x30, 0x16, 0x27):
        code.extend([0xA9, value, 0x8D, 0x07, 0x20])
    code.extend([0xA9, 0x88, 0x8D, 0x00, 0x20])
    loop_addr = 0x8000 + len(code)
    code.extend([0x4C, loop_addr & 0xFF, loop_addr >> 8])
    bank1[: len(code)] = bytes(code)
    bank1[0x0100] = 0x40
    bank1[0x7FFA:0x7FFC] = (0x8100).to_bytes(2, "little")
    bank1[0x7FFC:0x7FFE] = (0x8000).to_bytes(2, "little")
    bank1[0x7FFE:0x8000] = (0x8100).to_bytes(2, "little")

    reset = [
        0xA9, 0x11, 0x8D, 0x00, 0x80,  # select PRG bank 1 and CHR bank 1
        0x4C, 0x00, 0x80,  # JMP $8000 in selected PRG bank
    ]
    bank0[: len(reset)] = bytes(reset)
    bank0[0x0100] = 0x40
    bank0[0x7FFA:0x7FFC] = (0x8100).to_bytes(2, "little")
    bank0[0x7FFC:0x7FFE] = (0x8000).to_bytes(2, "little")
    bank0[0x7FFE:0x8000] = (0x8100).to_bytes(2, "little")

    chr_data = bytearray(0x4000)
    rows = [[0, 1, 2, 3, 0, 1, 2, 3] for _ in range(8)]
    # Bank 0 is intentionally blank; bank 1 contains the sprite tile.
    chr_data[0x2000 + 0x1000 : 0x2000 + 0x1010] = _encode_tile(rows)
    return ines_header(4, 2, 66) + bytes(bank0 + bank1) + bytes(chr_data)


def _runtime_colordreams_sprite_test_rom() -> bytes:
    bank0 = bytearray([0xEA] * 0x8000)
    bank1 = bytearray([0xEA] * 0x8000)

    code = [
        0x78,  # SEI
        0xD8,  # CLD
        0xA2, 0x00,
        0xA9, 0xF8,
        0x9D, 0x00, 0x02,
        0xE8,
        0xD0, 0xFA,
        0xA9, 0x14, 0x8D, 0x00, 0x02,
        0xA9, 0x00, 0x8D, 0x01, 0x02,
        0xA9, 0x00, 0x8D, 0x02, 0x02,
        0xA9, 0x0C, 0x8D, 0x03, 0x02,
        0xA9, 0x00, 0x8D, 0x03, 0x20,
        0xA9, 0x02, 0x8D, 0x14, 0x40,
        0xAD, 0x02, 0x20,
        0xA9, 0x3F, 0x8D, 0x06, 0x20,
        0xA9, 0x10, 0x8D, 0x06, 0x20,
    ]
    for value in (0x0F, 0x30, 0x16, 0x27):
        code.extend([0xA9, value, 0x8D, 0x07, 0x20])
    code.extend([0xA9, 0x88, 0x8D, 0x00, 0x20])
    loop_addr = 0x8100 + len(code)
    code.extend([0x4C, loop_addr & 0xFF, loop_addr >> 8])
    bank1[0x0100 : 0x0100 + len(code)] = bytes(code)

    reset = [
        0xA9, 0x21, 0x8D, 0x00, 0x80,  # select PRG bank 1 and CHR bank 2
        0x4C, 0x00, 0x80,
    ]
    bank0[: len(reset)] = bytes(reset)
    bank1[0x0005:0x0008] = bytes([0x4C, 0x00, 0x81])
    bank0[0x1F00] = 0x40
    bank0[0x7FFA:0x7FFC] = (0x9F00).to_bytes(2, "little")
    bank0[0x7FFC:0x7FFE] = (0x8000).to_bytes(2, "little")
    bank0[0x7FFE:0x8000] = (0x9F00).to_bytes(2, "little")
    bank1[0x1F00] = 0x40
    bank1[0x7FFA:0x7FFC] = (0x9F00).to_bytes(2, "little")
    bank1[0x7FFC:0x7FFE] = (0x8000).to_bytes(2, "little")
    bank1[0x7FFE:0x8000] = (0x9F00).to_bytes(2, "little")

    chr_data = bytearray(0x6000)
    rows = [[0, 1, 2, 3, 0, 1, 2, 3] for _ in range(8)]
    # Bank 0/1 blank; Color Dreams register $21 selects 8 KiB CHR bank 2.
    chr_data[2 * 0x2000 + 0x1000 : 2 * 0x2000 + 0x1010] = _encode_tile(rows)
    return ines_header(4, 3, 11) + bytes(bank0 + bank1) + bytes(chr_data)


def _runtime_axrom_chr_ram_sprite_test_rom() -> bytes:
    bank0 = bytearray([0xEA] * 0x8000)
    bank1 = bytearray([0xEA] * 0x8000)

    rows = [[0, 1, 2, 3, 0, 1, 2, 3] for _ in range(8)]
    tile = _encode_tile(rows)
    code = [
        0x78,  # SEI
        0xD8,  # CLD
        0xA2, 0x00,
        0xA9, 0xF8,
        0x9D, 0x00, 0x02,
        0xE8,
        0xD0, 0xFA,
        0xA9, 0x14, 0x8D, 0x00, 0x02,
        0xA9, 0x00, 0x8D, 0x01, 0x02,
        0xA9, 0x00, 0x8D, 0x02, 0x02,
        0xA9, 0x0C, 0x8D, 0x03, 0x02,
        0xA9, 0x00, 0x8D, 0x03, 0x20,
        0xA9, 0x02, 0x8D, 0x14, 0x40,
        0xAD, 0x02, 0x20,
        0xA9, 0x10, 0x8D, 0x06, 0x20,  # PPUADDR high $10
        0xA9, 0x00, 0x8D, 0x06, 0x20,  # PPUADDR low $00
    ]
    for value in tile:
        code.extend([0xA9, value, 0x8D, 0x07, 0x20])
    code.extend(
        [
            0xAD, 0x02, 0x20,
            0xA9, 0x3F, 0x8D, 0x06, 0x20,
            0xA9, 0x10, 0x8D, 0x06, 0x20,
        ]
    )
    for value in (0x0F, 0x30, 0x16, 0x27):
        code.extend([0xA9, value, 0x8D, 0x07, 0x20])
    code.extend([0xA9, 0x88, 0x8D, 0x00, 0x20])
    loop_addr = 0x8100 + len(code)
    code.extend([0x4C, loop_addr & 0xFF, loop_addr >> 8])
    bank1[0x0100 : 0x0100 + len(code)] = bytes(code)

    reset = [
        0xA9, 0x01, 0x8D, 0x00, 0x80,  # select 32 KiB PRG bank 1
        0x4C, 0x00, 0x80,
    ]
    bank0[: len(reset)] = bytes(reset)
    bank1[0x0005:0x0008] = bytes([0x4C, 0x00, 0x81])
    bank0[0x1F00] = 0x40
    bank0[0x7FFA:0x7FFC] = (0x9F00).to_bytes(2, "little")
    bank0[0x7FFC:0x7FFE] = (0x8000).to_bytes(2, "little")
    bank0[0x7FFE:0x8000] = (0x9F00).to_bytes(2, "little")
    bank1[0x1F00] = 0x40
    bank1[0x7FFA:0x7FFC] = (0x9F00).to_bytes(2, "little")
    bank1[0x7FFC:0x7FFE] = (0x8000).to_bytes(2, "little")
    bank1[0x7FFE:0x8000] = (0x9F00).to_bytes(2, "little")
    return ines_header(4, 0, 7) + bytes(bank0 + bank1)


def _mmc1_serial_write(addr: int, value: int) -> list[int]:
    code: list[int] = []
    for bit in range(5):
        code.extend([0xA9, (value >> bit) & 0x01, 0x8D, addr & 0xFF, addr >> 8])
    return code


def _runtime_mmc1_sprite_test_rom() -> bytes:
    bank0 = bytearray([0xEA] * PRG_BANK)
    bank1 = bytearray([0xEA] * PRG_BANK)
    bank2 = bytearray([0xEA] * PRG_BANK)
    bank3 = bytearray([0xEA] * PRG_BANK)

    code = [
        0x78,  # SEI
        0xD8,  # CLD
        0xA2, 0x00,
        0xA9, 0xF8,
        0x9D, 0x00, 0x02,
        0xE8,
        0xD0, 0xFA,
        0xA9, 0x14, 0x8D, 0x00, 0x02,
        0xA9, 0x00, 0x8D, 0x01, 0x02,
        0xA9, 0x00, 0x8D, 0x02, 0x02,
        0xA9, 0x0C, 0x8D, 0x03, 0x02,
        0xA9, 0x00, 0x8D, 0x03, 0x20,
        0xA9, 0x02, 0x8D, 0x14, 0x40,
        0xAD, 0x02, 0x20,
        0xA9, 0x3F, 0x8D, 0x06, 0x20,
        0xA9, 0x10, 0x8D, 0x06, 0x20,
    ]
    for value in (0x0F, 0x30, 0x16, 0x27):
        code.extend([0xA9, value, 0x8D, 0x07, 0x20])
    code.extend([0xA9, 0x88, 0x8D, 0x00, 0x20])
    loop_addr = 0x8000 + len(code)
    code.extend([0x4C, loop_addr & 0xFF, loop_addr >> 8])
    bank1[: len(code)] = bytes(code)

    reset = [
        0xA9, 0x80, 0x8D, 0x00, 0x80,  # reset MMC1 shift register
    ]
    reset.extend(_mmc1_serial_write(0xA000, 0x02))  # 8 KiB CHR bank 1
    reset.extend(_mmc1_serial_write(0xE000, 0x01))  # switch PRG bank 1 at $8000
    reset.extend([0x4C, 0x00, 0x80])
    bank3[: len(reset)] = bytes(reset)
    bank3[0x0100] = 0x40
    bank3[0x3FFA:0x3FFC] = (0xC100).to_bytes(2, "little")
    bank3[0x3FFC:0x3FFE] = (0xC000).to_bytes(2, "little")
    bank3[0x3FFE:0x4000] = (0xC100).to_bytes(2, "little")

    chr_data = bytearray(0x4000)
    rows = [[0, 1, 2, 3, 0, 1, 2, 3] for _ in range(8)]
    # CHR bank 0 blank; 8 KiB bank 1 contains the visible sprite tile.
    chr_data[0x2000 + 0x1000 : 0x2000 + 0x1010] = _encode_tile(rows)
    return ines_header(4, 2, 1) + bytes(bank0 + bank1 + bank2 + bank3) + bytes(chr_data)


def _runtime_mmc1_split_chr_sprite_test_rom() -> bytes:
    bank0 = bytearray([0xEA] * PRG_BANK)
    bank1 = bytearray([0xEA] * PRG_BANK)
    bank2 = bytearray([0xEA] * PRG_BANK)
    bank3 = bytearray([0xEA] * PRG_BANK)

    code = [
        0x78,  # SEI
        0xD8,  # CLD
        0xA2, 0x00,
        0xA9, 0xF8,
        0x9D, 0x00, 0x02,
        0xE8,
        0xD0, 0xFA,
        0xA9, 0x14, 0x8D, 0x00, 0x02,
        0xA9, 0x00, 0x8D, 0x01, 0x02,
        0xA9, 0x00, 0x8D, 0x02, 0x02,
        0xA9, 0x0C, 0x8D, 0x03, 0x02,
        0xA9, 0x00, 0x8D, 0x03, 0x20,
        0xA9, 0x02, 0x8D, 0x14, 0x40,
        0xAD, 0x02, 0x20,
        0xA9, 0x3F, 0x8D, 0x06, 0x20,
        0xA9, 0x10, 0x8D, 0x06, 0x20,
    ]
    for value in (0x0F, 0x30, 0x16, 0x27):
        code.extend([0xA9, value, 0x8D, 0x07, 0x20])
    code.extend([0xA9, 0x88, 0x8D, 0x00, 0x20])
    loop_addr = 0x8000 + len(code)
    code.extend([0x4C, loop_addr & 0xFF, loop_addr >> 8])
    bank1[: len(code)] = bytes(code)

    reset = [
        0xA9, 0x80, 0x8D, 0x00, 0x80,  # reset MMC1 shift register
    ]
    reset.extend(_mmc1_serial_write(0x8000, 0x1C))  # PRG mode 3, CHR split 4 KiB
    reset.extend(_mmc1_serial_write(0xC000, 0x03))  # map CHR 4 KiB bank 3 at $1000
    reset.extend(_mmc1_serial_write(0xE000, 0x01))  # switch PRG bank 1 at $8000
    reset.extend([0x4C, 0x00, 0x80])
    bank3[: len(reset)] = bytes(reset)
    bank3[0x0100] = 0x40
    bank3[0x3FFA:0x3FFC] = (0xC100).to_bytes(2, "little")
    bank3[0x3FFC:0x3FFE] = (0xC000).to_bytes(2, "little")
    bank3[0x3FFE:0x4000] = (0xC100).to_bytes(2, "little")

    chr_data = bytearray(0x4000)
    rows = [[0, 1, 2, 3, 0, 1, 2, 3] for _ in range(8)]
    chr_data[3 * 0x1000 : 3 * 0x1000 + 0x10] = _encode_tile(rows)
    return ines_header(4, 2, 1) + bytes(bank0 + bank1 + bank2 + bank3) + bytes(chr_data)


def _runtime_mmc3_sprite_test_rom() -> bytes:
    banks = [bytearray([0xEA] * 0x2000) for _ in range(8)]

    code = [
        0x78,  # SEI
        0xD8,  # CLD
        0xA2, 0x00,
        0xA9, 0xF8,
        0x9D, 0x00, 0x02,
        0xE8,
        0xD0, 0xFA,
        0xA9, 0x14, 0x8D, 0x00, 0x02,
        0xA9, 0x00, 0x8D, 0x01, 0x02,
        0xA9, 0x00, 0x8D, 0x02, 0x02,
        0xA9, 0x0C, 0x8D, 0x03, 0x02,
        0xA9, 0x00, 0x8D, 0x03, 0x20,
        0xA9, 0x02, 0x8D, 0x14, 0x40,
        0xAD, 0x02, 0x20,
        0xA9, 0x3F, 0x8D, 0x06, 0x20,
        0xA9, 0x10, 0x8D, 0x06, 0x20,
    ]
    for value in (0x0F, 0x30, 0x16, 0x27):
        code.extend([0xA9, value, 0x8D, 0x07, 0x20])
    code.extend([0xA9, 0x88, 0x8D, 0x00, 0x20])
    loop_addr = 0x8000 + len(code)
    code.extend([0x4C, loop_addr & 0xFF, loop_addr >> 8])
    banks[1][: len(code)] = bytes(code)

    reset = [
        0xA9, 0x02, 0x8D, 0x00, 0x80,  # MMC3 select R2, maps $1000-$13FF
        0xA9, 0x07, 0x8D, 0x01, 0x80,  # CHR 1 KiB bank 7
        0xA9, 0x06, 0x8D, 0x00, 0x80,  # select R6 PRG window $8000-$9FFF
        0xA9, 0x01, 0x8D, 0x01, 0x80,  # switch PRG bank 1 there
        0x4C, 0x00, 0x80,
    ]
    banks[-1][: len(reset)] = bytes(reset)
    banks[-1][0x0100] = 0x40
    banks[-1][0x1FFA:0x1FFC] = (0xE100).to_bytes(2, "little")
    banks[-1][0x1FFC:0x1FFE] = (0xE000).to_bytes(2, "little")
    banks[-1][0x1FFE:0x2000] = (0xE100).to_bytes(2, "little")

    chr_data = bytearray(0x4000)
    rows = [[0, 1, 2, 3, 0, 1, 2, 3] for _ in range(8)]
    # MMC3 maps 1 KiB CHR bank 7 to PPU $1000-$13FF; tile $00 sits at bank start.
    chr_data[7 * 0x0400 : 7 * 0x0400 + 0x10] = _encode_tile(rows)
    return ines_header(4, 2, 4) + b"".join(bytes(bank) for bank in banks) + bytes(chr_data)


def _runtime_rambo1_sprite_test_rom() -> bytes:
    banks = [bytearray([0xEA] * 0x2000) for _ in range(8)]

    code = [
        0x78,
        0xD8,
        0xA2, 0x00,
        0xA9, 0xF8,
        0x9D, 0x00, 0x02,
        0xE8,
        0xD0, 0xFA,
        0xA9, 0x14, 0x8D, 0x00, 0x02,
        0xA9, 0x00, 0x8D, 0x01, 0x02,
        0xA9, 0x00, 0x8D, 0x02, 0x02,
        0xA9, 0x0C, 0x8D, 0x03, 0x02,
        0xA9, 0x00, 0x8D, 0x03, 0x20,
        0xA9, 0x02, 0x8D, 0x14, 0x40,
        0xAD, 0x02, 0x20,
        0xA9, 0x3F, 0x8D, 0x06, 0x20,
        0xA9, 0x10, 0x8D, 0x06, 0x20,
    ]
    for value in (0x0F, 0x30, 0x16, 0x27):
        code.extend([0xA9, value, 0x8D, 0x07, 0x20])
    code.extend([0xA9, 0x88, 0x8D, 0x00, 0x20])
    loop_addr = 0x8000 + len(code)
    code.extend([0x4C, loop_addr & 0xFF, loop_addr >> 8])
    banks[4][: len(code)] = bytes(code)

    reset = [
        0xA9, 0x22, 0x8D, 0x00, 0x80,  # K=1, select CHR R2 at PPU $1000-$13FF
        0xA9, 0x1B, 0x8D, 0x01, 0x80,  # CHR 1 KiB bank $1B
        0xA9, 0x06, 0x8D, 0x00, 0x80,  # select PRG R6 at CPU $8000-$9FFF
        0xA9, 0x04, 0x8D, 0x01, 0x80,  # PRG bank 4
        0x4C, 0x00, 0x80,
    ]
    banks[-1][: len(reset)] = bytes(reset)
    banks[-1][0x0100] = 0x40
    banks[-1][0x1FFA:0x1FFC] = (0xE100).to_bytes(2, "little")
    banks[-1][0x1FFC:0x1FFE] = (0xE000).to_bytes(2, "little")
    banks[-1][0x1FFE:0x2000] = (0xE100).to_bytes(2, "little")

    chr_data = bytearray(0x8000)
    rows = [[0, 1, 2, 3, 0, 1, 2, 3] for _ in range(8)]
    chr_data[0x1B * 0x0400 : 0x1B * 0x0400 + 0x10] = _encode_tile(rows)
    return ines_header(4, 4, 64) + b"".join(bytes(bank) for bank in banks) + bytes(chr_data)


def _runtime_fme7_sprite_test_rom() -> bytes:
    banks = [bytearray([0xEA] * 0x2000) for _ in range(8)]

    code = [
        0x78,  # SEI
        0xD8,  # CLD
        0xA2, 0x00,
        0xA9, 0xF8,
        0x9D, 0x00, 0x02,
        0xE8,
        0xD0, 0xFA,
        0xA9, 0x14, 0x8D, 0x00, 0x02,
        0xA9, 0x00, 0x8D, 0x01, 0x02,
        0xA9, 0x00, 0x8D, 0x02, 0x02,
        0xA9, 0x0C, 0x8D, 0x03, 0x02,
        0xA9, 0x00, 0x8D, 0x03, 0x20,
        0xA9, 0x02, 0x8D, 0x14, 0x40,
        0xAD, 0x02, 0x20,
        0xA9, 0x3F, 0x8D, 0x06, 0x20,
        0xA9, 0x10, 0x8D, 0x06, 0x20,
    ]
    for value in (0x0F, 0x30, 0x16, 0x27):
        code.extend([0xA9, value, 0x8D, 0x07, 0x20])
    code.extend([0xA9, 0x88, 0x8D, 0x00, 0x20])
    loop_addr = 0x8000 + len(code)
    code.extend([0x4C, loop_addr & 0xFF, loop_addr >> 8])
    banks[1][: len(code)] = bytes(code)

    reset = [
        0xA9, 0x04, 0x8D, 0x00, 0x80,  # FME-7 command 4: CHR slot $1000-$13FF
        0xA9, 0x07, 0x8D, 0x00, 0xA0,  # map CHR 1 KiB bank 7 there
        0xA9, 0x09, 0x8D, 0x00, 0x80,  # FME-7 command 9: PRG window $8000-$9FFF
        0xA9, 0x01, 0x8D, 0x00, 0xA0,  # switch PRG bank 1 there
        0x4C, 0x00, 0x80,
    ]
    banks[-1][: len(reset)] = bytes(reset)
    banks[-1][0x0100] = 0x40
    banks[-1][0x1FFA:0x1FFC] = (0xE100).to_bytes(2, "little")
    banks[-1][0x1FFC:0x1FFE] = (0xE000).to_bytes(2, "little")
    banks[-1][0x1FFE:0x2000] = (0xE100).to_bytes(2, "little")

    chr_data = bytearray(0x4000)
    rows = [[0, 1, 2, 3, 0, 1, 2, 3] for _ in range(8)]
    chr_data[7 * 0x0400 : 7 * 0x0400 + 0x10] = _encode_tile(rows)
    return ines_header(4, 2, 69) + b"".join(bytes(bank) for bank in banks) + bytes(chr_data)


def _runtime_mmc5_sprite_test_rom() -> bytes:
    body = [
        0xA2, 0x00,
        0xA9, 0xF8,
        0x9D, 0x00, 0x02,
        0xE8,
        0xD0, 0xFA,
        0xA9, 0x14, 0x8D, 0x00, 0x02,
        0xA9, 0x00, 0x8D, 0x01, 0x02,
        0xA9, 0x00, 0x8D, 0x02, 0x02,
        0xA9, 0x0C, 0x8D, 0x03, 0x02,
        0xA9, 0x00, 0x8D, 0x03, 0x20,
        0xA9, 0x02, 0x8D, 0x14, 0x40,
        0xAD, 0x02, 0x20,
        0xA9, 0x3F, 0x8D, 0x06, 0x20,
        0xA9, 0x10, 0x8D, 0x06, 0x20,
    ]
    for value in (0x0F, 0x30, 0x16, 0x27):
        body.extend([0xA9, value, 0x8D, 0x07, 0x20])
    body.extend([0xA9, 0x88, 0x8D, 0x00, 0x20])
    loop_addr = 0x8000 + len(body)
    body.extend([0x4C, loop_addr & 0xFF, loop_addr >> 8])

    banks = [bytearray([0xEA] * 0x2000) for _ in range(8)]
    banks[4][: len(body)] = bytes(body)
    banks[-1][0x0100] = 0x40
    banks[-1][0x1FFA:0x1FFC] = (0xE100).to_bytes(2, "little")
    banks[-1][0x1FFC:0x1FFE] = (0xE000).to_bytes(2, "little")
    banks[-1][0x1FFE:0x2000] = (0xE100).to_bytes(2, "little")
    reset = [
        0x78,
        0xD8,
        0xA9, 0x03, 0x8D, 0x00, 0x51,  # PRG mode 3: four 8 KiB windows
        0xA9, 0x03, 0x8D, 0x01, 0x51,  # CHR mode 3: eight 1 KiB windows
        0xA9, 0x1B, 0x8D, 0x24, 0x51,  # CHR slot 4 ($1000-$13FF) = bank $1B
        0xA9, 0x84, 0x8D, 0x14, 0x51,  # PRG slot $8000 = ROM bank 4
        0x4C, 0x00, 0x80,
    ]
    banks[-1][: len(reset)] = bytes(reset)

    chr_data = bytearray(0x8000)
    rows = [[0, 1, 2, 3, 0, 1, 2, 3] for _ in range(8)]
    chr_data[0x1B * 0x0400 : 0x1B * 0x0400 + 0x10] = _encode_tile(rows)
    return ines_header(4, 4, 5) + b"".join(bytes(bank) for bank in banks) + bytes(chr_data)


def _runtime_vrc6_sprite_test_rom() -> bytes:
    body = [
        0xA2, 0x00,
        0xA9, 0xF8,
        0x9D, 0x00, 0x02,
        0xE8,
        0xD0, 0xFA,
        0xA9, 0x14, 0x8D, 0x00, 0x02,
        0xA9, 0x00, 0x8D, 0x01, 0x02,
        0xA9, 0x00, 0x8D, 0x02, 0x02,
        0xA9, 0x0C, 0x8D, 0x03, 0x02,
        0xA9, 0x00, 0x8D, 0x03, 0x20,
        0xA9, 0x02, 0x8D, 0x14, 0x40,
        0xAD, 0x02, 0x20,
        0xA9, 0x3F, 0x8D, 0x06, 0x20,
        0xA9, 0x10, 0x8D, 0x06, 0x20,
    ]
    for value in (0x0F, 0x30, 0x16, 0x27):
        body.extend([0xA9, value, 0x8D, 0x07, 0x20])
    body.extend([0xA9, 0x88, 0x8D, 0x00, 0x20])
    loop_addr = 0x8000 + len(body)
    body.extend([0x4C, loop_addr & 0xFF, loop_addr >> 8])

    banks = [bytearray([0xEA] * 0x2000) for _ in range(8)]
    banks[4][: len(body)] = bytes(body)
    banks[-1][0x0100] = 0x40
    banks[-1][0x1FFA:0x1FFC] = (0xE100).to_bytes(2, "little")
    banks[-1][0x1FFC:0x1FFE] = (0xE000).to_bytes(2, "little")
    banks[-1][0x1FFE:0x2000] = (0xE100).to_bytes(2, "little")
    reset = [
        0x78,
        0xD8,
        0xA9, 0x20, 0x8D, 0x03, 0xB0,  # VRC6 commercial CHR banking style 0
        0xA9, 0x1B, 0x8D, 0x00, 0xE0,  # CHR slot 4 ($1000-$13FF) = bank $1B
        0xA9, 0x02, 0x8D, 0x00, 0x80,  # 16 KiB PRG slot $8000 = bank pair 4/5
        0x4C, 0x00, 0x80,
    ]
    banks[-1][: len(reset)] = bytes(reset)

    chr_data = bytearray(0x8000)
    rows = [[0, 1, 2, 3, 0, 1, 2, 3] for _ in range(8)]
    chr_data[0x1B * 0x0400 : 0x1B * 0x0400 + 0x10] = _encode_tile(rows)
    return ines_header(4, 4, 24) + b"".join(bytes(bank) for bank in banks) + bytes(chr_data)


def _runtime_vrc4_sprite_test_rom() -> bytes:
    body = [
        0xA2, 0x00,
        0xA9, 0xF8,
        0x9D, 0x00, 0x02,
        0xE8,
        0xD0, 0xFA,
        0xA9, 0x14, 0x8D, 0x00, 0x02,
        0xA9, 0x00, 0x8D, 0x01, 0x02,
        0xA9, 0x00, 0x8D, 0x02, 0x02,
        0xA9, 0x0C, 0x8D, 0x03, 0x02,
        0xA9, 0x00, 0x8D, 0x03, 0x20,
        0xA9, 0x02, 0x8D, 0x14, 0x40,
        0xAD, 0x02, 0x20,
        0xA9, 0x3F, 0x8D, 0x06, 0x20,
        0xA9, 0x10, 0x8D, 0x06, 0x20,
    ]
    for value in (0x0F, 0x30, 0x16, 0x27):
        body.extend([0xA9, value, 0x8D, 0x07, 0x20])
    body.extend([0xA9, 0x88, 0x8D, 0x00, 0x20])
    loop_addr = 0x8000 + len(body)
    body.extend([0x4C, loop_addr & 0xFF, loop_addr >> 8])

    banks = [bytearray([0xEA] * 0x2000) for _ in range(8)]
    banks[4][: len(body)] = bytes(body)
    banks[-1][0x0100] = 0x40
    banks[-1][0x1FFA:0x1FFC] = (0xE100).to_bytes(2, "little")
    banks[-1][0x1FFC:0x1FFE] = (0xE000).to_bytes(2, "little")
    banks[-1][0x1FFE:0x2000] = (0xE100).to_bytes(2, "little")
    reset = [
        0x78,
        0xD8,
        0xA9, 0x0B, 0x8D, 0x00, 0xD0,  # CHR slot 4 low nibble
        0xA9, 0x01, 0x8D, 0x01, 0xD0,  # CHR slot 4 high bits -> bank $1B
        0xA9, 0x04, 0x8D, 0x00, 0x80,  # PRG slot $8000 = bank 4
        0x4C, 0x00, 0x80,
    ]
    banks[-1][: len(reset)] = bytes(reset)

    chr_data = bytearray(0x8000)
    rows = [[0, 1, 2, 3, 0, 1, 2, 3] for _ in range(8)]
    chr_data[0x1B * 0x0400 : 0x1B * 0x0400 + 0x10] = _encode_tile(rows)
    return ines_header(4, 4, 23) + b"".join(bytes(bank) for bank in banks) + bytes(chr_data)


def _runtime_vrc7_sprite_test_rom() -> bytes:
    body = [
        0xA2, 0x00,
        0xA9, 0xF8,
        0x9D, 0x00, 0x02,
        0xE8,
        0xD0, 0xFA,
        0xA9, 0x14, 0x8D, 0x00, 0x02,
        0xA9, 0x00, 0x8D, 0x01, 0x02,
        0xA9, 0x00, 0x8D, 0x02, 0x02,
        0xA9, 0x0C, 0x8D, 0x03, 0x02,
        0xA9, 0x00, 0x8D, 0x03, 0x20,
        0xA9, 0x02, 0x8D, 0x14, 0x40,
        0xAD, 0x02, 0x20,
        0xA9, 0x3F, 0x8D, 0x06, 0x20,
        0xA9, 0x10, 0x8D, 0x06, 0x20,
    ]
    for value in (0x0F, 0x30, 0x16, 0x27):
        body.extend([0xA9, value, 0x8D, 0x07, 0x20])
    body.extend([0xA9, 0x88, 0x8D, 0x00, 0x20])
    loop_addr = 0x8000 + len(body)
    body.extend([0x4C, loop_addr & 0xFF, loop_addr >> 8])

    banks = [bytearray([0xEA] * 0x2000) for _ in range(8)]
    banks[4][: len(body)] = bytes(body)
    banks[-1][0x0100] = 0x40
    banks[-1][0x1FFA:0x1FFC] = (0xE100).to_bytes(2, "little")
    banks[-1][0x1FFC:0x1FFE] = (0xE000).to_bytes(2, "little")
    banks[-1][0x1FFE:0x2000] = (0xE100).to_bytes(2, "little")
    reset = [
        0x78,
        0xD8,
        0xA9, 0x1B, 0x8D, 0x00, 0xC0,  # CHR slot 4 ($1000-$13FF) = bank $1B
        0xA9, 0x04, 0x8D, 0x00, 0x80,  # PRG slot $8000 = bank 4
        0x4C, 0x00, 0x80,
    ]
    banks[-1][: len(reset)] = bytes(reset)

    chr_data = bytearray(0x8000)
    rows = [[0, 1, 2, 3, 0, 1, 2, 3] for _ in range(8)]
    chr_data[0x1B * 0x0400 : 0x1B * 0x0400 + 0x10] = _encode_tile(rows)
    return ines_header(4, 4, 85) + b"".join(bytes(bank) for bank in banks) + bytes(chr_data)


def _runtime_mapper206_sprite_test_rom() -> bytes:
    banks = [bytearray([0xEA] * 0x2000) for _ in range(8)]

    code = [
        0x78,  # SEI
        0xD8,  # CLD
        0xA2, 0x00,
        0xA9, 0xF8,
        0x9D, 0x00, 0x02,
        0xE8,
        0xD0, 0xFA,
        0xA9, 0x14, 0x8D, 0x00, 0x02,
        0xA9, 0x00, 0x8D, 0x01, 0x02,
        0xA9, 0x00, 0x8D, 0x02, 0x02,
        0xA9, 0x0C, 0x8D, 0x03, 0x02,
        0xA9, 0x00, 0x8D, 0x03, 0x20,
        0xA9, 0x02, 0x8D, 0x14, 0x40,
        0xAD, 0x02, 0x20,
        0xA9, 0x3F, 0x8D, 0x06, 0x20,
        0xA9, 0x10, 0x8D, 0x06, 0x20,
    ]
    for value in (0x0F, 0x30, 0x16, 0x27):
        code.extend([0xA9, value, 0x8D, 0x07, 0x20])
    code.extend([0xA9, 0x88, 0x8D, 0x00, 0x20])
    loop_addr = 0x8000 + len(code)
    code.extend([0x4C, loop_addr & 0xFF, loop_addr >> 8])
    banks[1][: len(code)] = bytes(code)

    reset = [
        0xA9, 0x02, 0x8D, 0x00, 0x80,  # select CHR register 2, PPU $1000-$13FF
        0xA9, 0x07, 0x8D, 0x01, 0x80,  # CHR 1 KiB bank 7
        0xA9, 0x06, 0x8D, 0x00, 0x80,  # select PRG register 6, CPU $8000-$9FFF
        0xA9, 0x01, 0x8D, 0x01, 0x80,  # PRG bank 1
        0x4C, 0x00, 0x80,
    ]
    banks[-1][: len(reset)] = bytes(reset)
    banks[-1][0x0100] = 0x40
    banks[-1][0x1FFA:0x1FFC] = (0xE100).to_bytes(2, "little")
    banks[-1][0x1FFC:0x1FFE] = (0xE000).to_bytes(2, "little")
    banks[-1][0x1FFE:0x2000] = (0xE100).to_bytes(2, "little")

    chr_data = bytearray(0x4000)
    rows = [[0, 1, 2, 3, 0, 1, 2, 3] for _ in range(8)]
    chr_data[7 * 0x0400 : 7 * 0x0400 + 0x10] = _encode_tile(rows)
    return ines_header(4, 2, 206) + b"".join(bytes(bank) for bank in banks) + bytes(chr_data)


def _runtime_mapper34_nina_sprite_test_rom() -> bytes:
    bank0 = bytearray([0xEA] * 0x8000)
    bank1 = bytearray([0xEA] * 0x8000)

    code = [
        0x78,  # SEI
        0xD8,  # CLD
        0xA2, 0x00,
        0xA9, 0xF8,
        0x9D, 0x00, 0x02,
        0xE8,
        0xD0, 0xFA,
        0xA9, 0x14, 0x8D, 0x00, 0x02,
        0xA9, 0x00, 0x8D, 0x01, 0x02,
        0xA9, 0x00, 0x8D, 0x02, 0x02,
        0xA9, 0x0C, 0x8D, 0x03, 0x02,
        0xA9, 0x00, 0x8D, 0x03, 0x20,
        0xA9, 0x02, 0x8D, 0x14, 0x40,
        0xAD, 0x02, 0x20,
        0xA9, 0x3F, 0x8D, 0x06, 0x20,
        0xA9, 0x10, 0x8D, 0x06, 0x20,
    ]
    for value in (0x0F, 0x30, 0x16, 0x27):
        code.extend([0xA9, value, 0x8D, 0x07, 0x20])
    code.extend([0xA9, 0x88, 0x8D, 0x00, 0x20])
    code_addr = 0x8200
    loop_addr = code_addr + len(code)
    code.extend([0x4C, loop_addr & 0xFF, loop_addr >> 8])
    bank1[0x0200 : 0x0200 + len(code)] = bytes(code)

    reset = [
        0xA9, 0x03, 0x8D, 0xFF, 0x7F,  # NINA CHR bank 3 at PPU $1000-$1FFF
        0xA9, 0x01, 0x8D, 0xFD, 0x7F,  # switch 32 KiB PRG bank 1
        0x4C, 0x00, 0x82,
    ]
    bank0[: len(reset)] = bytes(reset)
    bank1[: len(reset)] = bytes(reset)
    for bank in (bank0, bank1):
        bank[0x0100] = 0x40
        bank[0x7FFA:0x7FFC] = (0x8100).to_bytes(2, "little")
        bank[0x7FFC:0x7FFE] = (0x8000).to_bytes(2, "little")
        bank[0x7FFE:0x8000] = (0x8100).to_bytes(2, "little")

    chr_data = bytearray(0x4000)
    rows = [[0, 1, 2, 3, 0, 1, 2, 3] for _ in range(8)]
    chr_data[3 * 0x1000 : 3 * 0x1000 + 0x10] = _encode_tile(rows)
    return ines_header(4, 2, 34) + bytes(bank0 + bank1) + bytes(chr_data)


def _runtime_mapper42_sprite_test_rom() -> bytes:
    banks = [bytearray([0xEA] * 0x2000) for _ in range(8)]

    code = [
        0x78,  # SEI
        0xD8,  # CLD
        0xA2, 0x00,
        0xA9, 0xF8,
        0x9D, 0x00, 0x02,
        0xE8,
        0xD0, 0xFA,
        0xA9, 0x14, 0x8D, 0x00, 0x02,
        0xA9, 0x00, 0x8D, 0x01, 0x02,
        0xA9, 0x00, 0x8D, 0x02, 0x02,
        0xA9, 0x0C, 0x8D, 0x03, 0x02,
        0xA9, 0x00, 0x8D, 0x03, 0x20,
        0xA9, 0x02, 0x8D, 0x14, 0x40,
        0xAD, 0x02, 0x20,
        0xA9, 0x3F, 0x8D, 0x06, 0x20,
        0xA9, 0x10, 0x8D, 0x06, 0x20,
    ]
    for value in (0x0F, 0x30, 0x16, 0x27):
        code.extend([0xA9, value, 0x8D, 0x07, 0x20])
    code.extend([0xA9, 0x88, 0x8D, 0x00, 0x20])
    loop_addr = 0x8000 + len(code)
    code.extend([0x4C, loop_addr & 0xFF, loop_addr >> 8])
    banks[4][: len(code)] = bytes(code)

    reset = [
        0xA9, 0x02, 0x8D, 0x00, 0x80,  # CHR bank 2 at PPU $0000-$1FFF
        0x4C, 0x00, 0x80,
    ]
    banks[-1][: len(reset)] = bytes(reset)
    banks[-1][0x0100] = 0x40
    banks[-1][0x1FFA:0x1FFC] = (0xE100).to_bytes(2, "little")
    banks[-1][0x1FFC:0x1FFE] = (0xE000).to_bytes(2, "little")
    banks[-1][0x1FFE:0x2000] = (0xE100).to_bytes(2, "little")

    chr_data = bytearray(4 * 0x2000)
    rows = [[0, 1, 2, 3, 0, 1, 2, 3] for _ in range(8)]
    chr_data[2 * 0x2000 + 0x1000 : 2 * 0x2000 + 0x1010] = _encode_tile(rows)
    return ines_header(4, 4, 42) + b"".join(bytes(bank) for bank in banks) + bytes(chr_data)


def _runtime_mapper70_sprite_test_rom() -> bytes:
    banks = [bytearray([0xEA] * PRG_BANK) for _ in range(4)]
    code = [
        0x78,  # SEI
        0xD8,  # CLD
        0xA2, 0x00,
        0xA9, 0xF8,
        0x9D, 0x00, 0x02,
        0xE8,
        0xD0, 0xFA,
        0xA9, 0x14, 0x8D, 0x00, 0x02,
        0xA9, 0x00, 0x8D, 0x01, 0x02,
        0xA9, 0x00, 0x8D, 0x02, 0x02,
        0xA9, 0x0C, 0x8D, 0x03, 0x02,
        0xA9, 0x00, 0x8D, 0x03, 0x20,
        0xA9, 0x02, 0x8D, 0x14, 0x40,
        0xAD, 0x02, 0x20,
        0xA9, 0x3F, 0x8D, 0x06, 0x20,
        0xA9, 0x10, 0x8D, 0x06, 0x20,
    ]
    for value in (0x0F, 0x30, 0x16, 0x27):
        code.extend([0xA9, value, 0x8D, 0x07, 0x20])
    code.extend([0xA9, 0x88, 0x8D, 0x00, 0x20])
    loop_addr = 0x8000 + len(code)
    code.extend([0x4C, loop_addr & 0xFF, loop_addr >> 8])
    banks[2][: len(code)] = bytes(code)

    reset = [
        0xA9, 0x25, 0x8D, 0x00, 0x80,  # PRG bank 2, CHR bank 5
        0x4C, 0x00, 0x80,
    ]
    banks[-1][: len(reset)] = bytes(reset)
    banks[-1][0x0100] = 0x40
    banks[-1][0x3FFA:0x3FFC] = (0xC100).to_bytes(2, "little")
    banks[-1][0x3FFC:0x3FFE] = (0xC000).to_bytes(2, "little")
    banks[-1][0x3FFE:0x4000] = (0xC100).to_bytes(2, "little")

    chr_data = bytearray(8 * 0x2000)
    rows = [[0, 1, 2, 3, 0, 1, 2, 3] for _ in range(8)]
    chr_data[5 * 0x2000 + 0x1000 : 5 * 0x2000 + 0x1010] = _encode_tile(rows)
    return ines_header(4, 8, 70) + b"".join(bytes(bank) for bank in banks) + bytes(chr_data)


def _runtime_mmc2_sprite_test_rom() -> bytes:
    body = [
        0xA2, 0x00,
        0xA9, 0xF8,
        0x9D, 0x00, 0x02,
        0xE8,
        0xD0, 0xFA,
        0xA9, 0x14, 0x8D, 0x00, 0x02,
        0xA9, 0x00, 0x8D, 0x01, 0x02,
        0xA9, 0x00, 0x8D, 0x02, 0x02,
        0xA9, 0x0C, 0x8D, 0x03, 0x02,
        0xA9, 0x00, 0x8D, 0x03, 0x20,
        0xA9, 0x02, 0x8D, 0x14, 0x40,
        0xAD, 0x02, 0x20,
        0xA9, 0x3F, 0x8D, 0x06, 0x20,
        0xA9, 0x10, 0x8D, 0x06, 0x20,
    ]
    for value in (0x0F, 0x30, 0x16, 0x27):
        body.extend([0xA9, value, 0x8D, 0x07, 0x20])
    body.extend([0xA9, 0x88, 0x8D, 0x00, 0x20])
    loop_addr = 0x8000 + len(body)
    body.extend([0x4C, loop_addr & 0xFF, loop_addr >> 8])

    banks = [bytearray([0xEA] * 0x2000) for _ in range(6)]
    banks[2][: len(body)] = bytes(body)
    banks[-1][0x0100] = 0x40
    banks[-1][0x1FFA:0x1FFC] = (0xE100).to_bytes(2, "little")
    banks[-1][0x1FFC:0x1FFE] = (0xE000).to_bytes(2, "little")
    banks[-1][0x1FFE:0x2000] = (0xE100).to_bytes(2, "little")
    reset = [
        0x78,  # SEI
        0xD8,  # CLD
        0xA9, 0x01, 0x8D, 0x00, 0xB0,  # CHR latch 0 FD = bank 1
        0xA9, 0x03, 0x8D, 0x00, 0xD0,  # CHR latch 1 FD = bank 3
        0xA9, 0x02, 0x8D, 0x00, 0xA0,  # PRG bank 2 at $8000-$9FFF
        0x4C, 0x00, 0x80,
    ]
    banks[-1][: len(reset)] = bytes(reset)

    chr_data = bytearray(8 * 0x1000)
    rows = [[0, 1, 2, 3, 0, 1, 2, 3] for _ in range(8)]
    chr_data[3 * 0x1000 : 3 * 0x1000 + 0x10] = _encode_tile(rows)
    return ines_header(3, 4, 9) + b"".join(bytes(bank) for bank in banks) + bytes(chr_data)


def _runtime_mmc4_sprite_test_rom() -> bytes:
    body = [
        0xA2, 0x00,
        0xA9, 0xF8,
        0x9D, 0x00, 0x02,
        0xE8,
        0xD0, 0xFA,
        0xA9, 0x14, 0x8D, 0x00, 0x02,
        0xA9, 0x00, 0x8D, 0x01, 0x02,
        0xA9, 0x00, 0x8D, 0x02, 0x02,
        0xA9, 0x0C, 0x8D, 0x03, 0x02,
        0xA9, 0x00, 0x8D, 0x03, 0x20,
        0xA9, 0x02, 0x8D, 0x14, 0x40,
        0xAD, 0x02, 0x20,
        0xA9, 0x3F, 0x8D, 0x06, 0x20,
        0xA9, 0x10, 0x8D, 0x06, 0x20,
    ]
    for value in (0x0F, 0x30, 0x16, 0x27):
        body.extend([0xA9, value, 0x8D, 0x07, 0x20])
    body.extend([0xA9, 0x88, 0x8D, 0x00, 0x20])
    loop_addr = 0x8000 + len(body)
    body.extend([0x4C, loop_addr & 0xFF, loop_addr >> 8])

    banks = [bytearray([0xEA] * 0x4000) for _ in range(4)]
    banks[2][: len(body)] = bytes(body)
    banks[-1][0x0100] = 0x40
    banks[-1][0x3FFA:0x3FFC] = (0xC100).to_bytes(2, "little")
    banks[-1][0x3FFC:0x3FFE] = (0xC000).to_bytes(2, "little")
    banks[-1][0x3FFE:0x4000] = (0xC100).to_bytes(2, "little")
    reset = [
        0x78,
        0xD8,
        0xA9, 0x01, 0x8D, 0x00, 0xB0,
        0xA9, 0x03, 0x8D, 0x00, 0xD0,
        0xA9, 0x02, 0x8D, 0x00, 0xA0,
        0x4C, 0x00, 0x80,
    ]
    banks[-1][: len(reset)] = bytes(reset)

    chr_data = bytearray(8 * 0x1000)
    rows = [[0, 1, 2, 3, 0, 1, 2, 3] for _ in range(8)]
    chr_data[3 * 0x1000 : 3 * 0x1000 + 0x10] = _encode_tile(rows)
    return ines_header(4, 4, 10) + b"".join(bytes(bank) for bank in banks) + bytes(chr_data)


def _runtime_mapper16_sprite_test_rom() -> bytes:
    body = [
        0xA2, 0x00,
        0xA9, 0xF8,
        0x9D, 0x00, 0x02,
        0xE8,
        0xD0, 0xFA,
        0xA9, 0x14, 0x8D, 0x00, 0x02,
        0xA9, 0x00, 0x8D, 0x01, 0x02,
        0xA9, 0x00, 0x8D, 0x02, 0x02,
        0xA9, 0x0C, 0x8D, 0x03, 0x02,
        0xA9, 0x00, 0x8D, 0x03, 0x20,
        0xA9, 0x02, 0x8D, 0x14, 0x40,
        0xAD, 0x02, 0x20,
        0xA9, 0x3F, 0x8D, 0x06, 0x20,
        0xA9, 0x10, 0x8D, 0x06, 0x20,
    ]
    for value in (0x0F, 0x30, 0x16, 0x27):
        body.extend([0xA9, value, 0x8D, 0x07, 0x20])
    body.extend([0xA9, 0x88, 0x8D, 0x00, 0x20])
    loop_addr = 0x8000 + len(body)
    body.extend([0x4C, loop_addr & 0xFF, loop_addr >> 8])

    banks = [bytearray([0xEA] * 0x4000) for _ in range(4)]
    banks[2][: len(body)] = bytes(body)
    banks[-1][0x0100] = 0x40
    banks[-1][0x3FFA:0x3FFC] = (0xC100).to_bytes(2, "little")
    banks[-1][0x3FFC:0x3FFE] = (0xC000).to_bytes(2, "little")
    banks[-1][0x3FFE:0x4000] = (0xC100).to_bytes(2, "little")
    reset = [
        0x78,
        0xD8,
        0xA9, 0x05, 0x8D, 0x04, 0x60,  # CHR slot 4 ($1000-$13FF) = 1 KiB bank 5
        0xA9, 0x02, 0x8D, 0x08, 0x60,  # PRG bank 2 at $8000-$BFFF
        0x4C, 0x00, 0x80,
    ]
    banks[-1][: len(reset)] = bytes(reset)

    chr_data = bytearray(0x4000)
    rows = [[0, 1, 2, 3, 0, 1, 2, 3] for _ in range(8)]
    chr_data[5 * 0x0400 : 5 * 0x0400 + 0x10] = _encode_tile(rows)
    return ines_header(4, 2, 16) + b"".join(bytes(bank) for bank in banks) + bytes(chr_data)


def _runtime_mapper18_sprite_test_rom() -> bytes:
    body = [
        0xA2, 0x00,
        0xA9, 0xF8,
        0x9D, 0x00, 0x02,
        0xE8,
        0xD0, 0xFA,
        0xA9, 0x14, 0x8D, 0x00, 0x02,
        0xA9, 0x00, 0x8D, 0x01, 0x02,
        0xA9, 0x00, 0x8D, 0x02, 0x02,
        0xA9, 0x0C, 0x8D, 0x03, 0x02,
        0xA9, 0x00, 0x8D, 0x03, 0x20,
        0xA9, 0x02, 0x8D, 0x14, 0x40,
        0xAD, 0x02, 0x20,
        0xA9, 0x3F, 0x8D, 0x06, 0x20,
        0xA9, 0x10, 0x8D, 0x06, 0x20,
    ]
    for value in (0x0F, 0x30, 0x16, 0x27):
        body.extend([0xA9, value, 0x8D, 0x07, 0x20])
    body.extend([0xA9, 0x88, 0x8D, 0x00, 0x20])
    loop_addr = 0x8000 + len(body)
    body.extend([0x4C, loop_addr & 0xFF, loop_addr >> 8])

    banks = [bytearray([0xEA] * 0x2000) for _ in range(8)]
    banks[4][: len(body)] = bytes(body)
    banks[-1][0x0100] = 0x40
    banks[-1][0x1FFA:0x1FFC] = (0xE100).to_bytes(2, "little")
    banks[-1][0x1FFC:0x1FFE] = (0xE000).to_bytes(2, "little")
    banks[-1][0x1FFE:0x2000] = (0xE100).to_bytes(2, "little")
    reset = [
        0x78,
        0xD8,
        0xA9, 0x0B, 0x8D, 0x00, 0xC0,  # CHR slot 4 low nibble = $B
        0xA9, 0x01, 0x8D, 0x01, 0xC0,  # CHR slot 4 high nibble = $1 -> bank $1B
        0xA9, 0x04, 0x8D, 0x00, 0x80,  # PRG slot $8000 low nibble = 4
        0xA9, 0x00, 0x8D, 0x01, 0x80,  # PRG slot $8000 high bits = 0
        0x4C, 0x00, 0x80,
    ]
    banks[-1][: len(reset)] = bytes(reset)

    chr_data = bytearray(0x8000)
    rows = [[0, 1, 2, 3, 0, 1, 2, 3] for _ in range(8)]
    chr_data[0x1B * 0x0400 : 0x1B * 0x0400 + 0x10] = _encode_tile(rows)
    return ines_header(4, 4, 18) + b"".join(bytes(bank) for bank in banks) + bytes(chr_data)


def _runtime_mapper19_sprite_test_rom() -> bytes:
    body = [
        0xA2, 0x00,
        0xA9, 0xF8,
        0x9D, 0x00, 0x02,
        0xE8,
        0xD0, 0xFA,
        0xA9, 0x14, 0x8D, 0x00, 0x02,
        0xA9, 0x00, 0x8D, 0x01, 0x02,
        0xA9, 0x00, 0x8D, 0x02, 0x02,
        0xA9, 0x0C, 0x8D, 0x03, 0x02,
        0xA9, 0x00, 0x8D, 0x03, 0x20,
        0xA9, 0x02, 0x8D, 0x14, 0x40,
        0xAD, 0x02, 0x20,
        0xA9, 0x3F, 0x8D, 0x06, 0x20,
        0xA9, 0x10, 0x8D, 0x06, 0x20,
    ]
    for value in (0x0F, 0x30, 0x16, 0x27):
        body.extend([0xA9, value, 0x8D, 0x07, 0x20])
    body.extend([0xA9, 0x88, 0x8D, 0x00, 0x20])
    loop_addr = 0x8000 + len(body)
    body.extend([0x4C, loop_addr & 0xFF, loop_addr >> 8])

    banks = [bytearray([0xEA] * 0x2000) for _ in range(8)]
    banks[4][: len(body)] = bytes(body)
    banks[-1][0x0100] = 0x40
    banks[-1][0x1FFA:0x1FFC] = (0xE100).to_bytes(2, "little")
    banks[-1][0x1FFC:0x1FFE] = (0xE000).to_bytes(2, "little")
    banks[-1][0x1FFE:0x2000] = (0xE100).to_bytes(2, "little")
    reset = [
        0x78,
        0xD8,
        0xA9, 0x1B, 0x8D, 0x00, 0xA0,  # CHR slot 4 ($1000-$13FF) = 1 KiB bank $1B
        0xA9, 0x04, 0x8D, 0x00, 0xE0,  # PRG slot $8000 = bank 4
        0x4C, 0x00, 0x80,
    ]
    banks[-1][: len(reset)] = bytes(reset)

    chr_data = bytearray(0x8000)
    rows = [[0, 1, 2, 3, 0, 1, 2, 3] for _ in range(8)]
    chr_data[0x1B * 0x0400 : 0x1B * 0x0400 + 0x10] = _encode_tile(rows)
    return ines_header(4, 4, 19) + b"".join(bytes(bank) for bank in banks) + bytes(chr_data)


def _runtime_mapper32_sprite_test_rom() -> bytes:
    body = [
        0xA2, 0x00,
        0xA9, 0xF8,
        0x9D, 0x00, 0x02,
        0xE8,
        0xD0, 0xFA,
        0xA9, 0x14, 0x8D, 0x00, 0x02,
        0xA9, 0x00, 0x8D, 0x01, 0x02,
        0xA9, 0x00, 0x8D, 0x02, 0x02,
        0xA9, 0x0C, 0x8D, 0x03, 0x02,
        0xA9, 0x00, 0x8D, 0x03, 0x20,
        0xA9, 0x02, 0x8D, 0x14, 0x40,
        0xAD, 0x02, 0x20,
        0xA9, 0x3F, 0x8D, 0x06, 0x20,
        0xA9, 0x10, 0x8D, 0x06, 0x20,
    ]
    for value in (0x0F, 0x30, 0x16, 0x27):
        body.extend([0xA9, value, 0x8D, 0x07, 0x20])
    body.extend([0xA9, 0x88, 0x8D, 0x00, 0x20])
    loop_addr = 0x8000 + len(body)
    body.extend([0x4C, loop_addr & 0xFF, loop_addr >> 8])

    banks = [bytearray([0xEA] * 0x2000) for _ in range(8)]
    banks[4][: len(body)] = bytes(body)
    banks[-1][0x0100] = 0x40
    banks[-1][0x1FFA:0x1FFC] = (0xE100).to_bytes(2, "little")
    banks[-1][0x1FFC:0x1FFE] = (0xE000).to_bytes(2, "little")
    banks[-1][0x1FFE:0x2000] = (0xE100).to_bytes(2, "little")
    reset = [
        0x78,
        0xD8,
        0xA9, 0x1B, 0x8D, 0x04, 0xB0,  # CHR slot 4 ($1000-$13FF) = 1 KiB bank $1B
        0xA9, 0x04, 0x8D, 0x00, 0x80,  # PRG slot $8000 = bank 4
        0x4C, 0x00, 0x80,
    ]
    banks[-1][: len(reset)] = bytes(reset)

    chr_data = bytearray(0x8000)
    rows = [[0, 1, 2, 3, 0, 1, 2, 3] for _ in range(8)]
    chr_data[0x1B * 0x0400 : 0x1B * 0x0400 + 0x10] = _encode_tile(rows)
    return ines_header(4, 4, 32) + b"".join(bytes(bank) for bank in banks) + bytes(chr_data)


def _runtime_mapper33_sprite_test_rom() -> bytes:
    body = [
        0xA2, 0x00,
        0xA9, 0xF8,
        0x9D, 0x00, 0x02,
        0xE8,
        0xD0, 0xFA,
        0xA9, 0x14, 0x8D, 0x00, 0x02,
        0xA9, 0x00, 0x8D, 0x01, 0x02,
        0xA9, 0x00, 0x8D, 0x02, 0x02,
        0xA9, 0x0C, 0x8D, 0x03, 0x02,
        0xA9, 0x00, 0x8D, 0x03, 0x20,
        0xA9, 0x02, 0x8D, 0x14, 0x40,
        0xAD, 0x02, 0x20,
        0xA9, 0x3F, 0x8D, 0x06, 0x20,
        0xA9, 0x10, 0x8D, 0x06, 0x20,
    ]
    for value in (0x0F, 0x30, 0x16, 0x27):
        body.extend([0xA9, value, 0x8D, 0x07, 0x20])
    body.extend([0xA9, 0x88, 0x8D, 0x00, 0x20])
    loop_addr = 0x8000 + len(body)
    body.extend([0x4C, loop_addr & 0xFF, loop_addr >> 8])

    banks = [bytearray([0xEA] * 0x2000) for _ in range(8)]
    banks[4][: len(body)] = bytes(body)
    banks[-1][0x0100] = 0x40
    banks[-1][0x1FFA:0x1FFC] = (0xE100).to_bytes(2, "little")
    banks[-1][0x1FFC:0x1FFE] = (0xE000).to_bytes(2, "little")
    banks[-1][0x1FFE:0x2000] = (0xE100).to_bytes(2, "little")
    reset = [
        0x78,
        0xD8,
        0xA9, 0x1B, 0x8D, 0x00, 0xA0,  # CHR 1 KiB slot $1000-$13FF = bank $1B
        0xA9, 0x04, 0x8D, 0x00, 0x80,  # PRG slot $8000 = bank 4
        0x4C, 0x00, 0x80,
    ]
    banks[-1][: len(reset)] = bytes(reset)

    chr_data = bytearray(0x8000)
    rows = [[0, 1, 2, 3, 0, 1, 2, 3] for _ in range(8)]
    chr_data[0x1B * 0x0400 : 0x1B * 0x0400 + 0x10] = _encode_tile(rows)
    return ines_header(4, 4, 33) + b"".join(bytes(bank) for bank in banks) + bytes(chr_data)


def _runtime_mapper71_sprite_test_rom() -> bytes:
    bank0 = bytearray([0xEA] * PRG_BANK)
    bank1 = bytearray([0xEA] * PRG_BANK)
    bank2 = bytearray([0xEA] * PRG_BANK)
    bank3 = bytearray([0xEA] * PRG_BANK)

    code = [
        0x78,  # SEI
        0xD8,  # CLD
        0xA2, 0x00,
        0xA9, 0xF8,
        0x9D, 0x00, 0x02,
        0xE8,
        0xD0, 0xFA,
        0xA9, 0x14, 0x8D, 0x00, 0x02,
        0xA9, 0x00, 0x8D, 0x01, 0x02,
        0xA9, 0x00, 0x8D, 0x02, 0x02,
        0xA9, 0x0C, 0x8D, 0x03, 0x02,
        0xA9, 0x00, 0x8D, 0x03, 0x20,
        0xA9, 0x02, 0x8D, 0x14, 0x40,
        0xAD, 0x02, 0x20,
        0xA9, 0x3F, 0x8D, 0x06, 0x20,
        0xA9, 0x10, 0x8D, 0x06, 0x20,
    ]
    for value in (0x0F, 0x30, 0x16, 0x27):
        code.extend([0xA9, value, 0x8D, 0x07, 0x20])
    code.extend([0xA9, 0x88, 0x8D, 0x00, 0x20])
    loop_addr = 0x8000 + len(code)
    code.extend([0x4C, loop_addr & 0xFF, loop_addr >> 8])
    bank1[: len(code)] = bytes(code)

    reset = [
        0xA9, 0x01, 0x8D, 0x00, 0xC0,  # select switchable PRG bank 1
        0x4C, 0x00, 0x80,
    ]
    bank3[: len(reset)] = bytes(reset)
    bank3[0x0100] = 0x40
    bank3[0x3FFA:0x3FFC] = (0xC100).to_bytes(2, "little")
    bank3[0x3FFC:0x3FFE] = (0xC000).to_bytes(2, "little")
    bank3[0x3FFE:0x4000] = (0xC100).to_bytes(2, "little")

    chr_data = bytearray(0x2000)
    rows = [[0, 1, 2, 3, 0, 1, 2, 3] for _ in range(8)]
    chr_data[0x1000 : 0x1010] = _encode_tile(rows)
    return ines_header(4, 1, 71) + bytes(bank0 + bank1 + bank2 + bank3) + bytes(chr_data)


def _runtime_mapper72_sprite_test_rom() -> bytes:
    bank0 = bytearray([0xEA] * PRG_BANK)
    bank1 = bytearray([0xEA] * PRG_BANK)
    bank2 = bytearray([0xEA] * PRG_BANK)
    bank3 = bytearray([0xEA] * PRG_BANK)

    code = [
        0x78,  # SEI
        0xD8,  # CLD
        0xA2, 0x00,
        0xA9, 0xF8,
        0x9D, 0x00, 0x02,
        0xE8,
        0xD0, 0xFA,
        0xA9, 0x14, 0x8D, 0x00, 0x02,
        0xA9, 0x00, 0x8D, 0x01, 0x02,
        0xA9, 0x00, 0x8D, 0x02, 0x02,
        0xA9, 0x0C, 0x8D, 0x03, 0x02,
        0xA9, 0x00, 0x8D, 0x03, 0x20,
        0xA9, 0x02, 0x8D, 0x14, 0x40,
        0xAD, 0x02, 0x20,
        0xA9, 0x3F, 0x8D, 0x06, 0x20,
        0xA9, 0x10, 0x8D, 0x06, 0x20,
    ]
    for value in (0x0F, 0x30, 0x16, 0x27):
        code.extend([0xA9, value, 0x8D, 0x07, 0x20])
    code.extend([0xA9, 0x88, 0x8D, 0x00, 0x20])
    loop_addr = 0x8000 + len(code)
    code.extend([0x4C, loop_addr & 0xFF, loop_addr >> 8])
    bank2[: len(code)] = bytes(code)

    reset = [
        0xA9, 0x43, 0x8D, 0x00, 0x80,  # rising bit 6: CHR bank 3
        0xA9, 0x03, 0x8D, 0x00, 0x80,  # clear command bits
        0xA9, 0x82, 0x8D, 0x00, 0x80,  # rising bit 7: PRG bank 2
        0x4C, 0x00, 0x80,
    ]
    bank3[: len(reset)] = bytes(reset)
    bank3[0x0100] = 0x40
    bank3[0x3FFA:0x3FFC] = (0xC100).to_bytes(2, "little")
    bank3[0x3FFC:0x3FFE] = (0xC000).to_bytes(2, "little")
    bank3[0x3FFE:0x4000] = (0xC100).to_bytes(2, "little")

    chr_data = bytearray(4 * 0x2000)
    rows = [[0, 1, 2, 3, 0, 1, 2, 3] for _ in range(8)]
    chr_data[3 * 0x2000 + 0x1000 : 3 * 0x2000 + 0x1010] = _encode_tile(rows)
    return ines_header(4, 4, 72) + bytes(bank0 + bank1 + bank2 + bank3) + bytes(chr_data)


def _runtime_mapper75_sprite_test_rom() -> bytes:
    banks = [bytearray([0xEA] * 0x2000) for _ in range(8)]
    body = [
        0x78,
        0xD8,
        0xA2, 0x00,
        0xA9, 0xF8,
        0x9D, 0x00, 0x02,
        0xE8,
        0xD0, 0xFA,
        0xA9, 0x14, 0x8D, 0x00, 0x02,
        0xA9, 0x00, 0x8D, 0x01, 0x02,
        0xA9, 0x00, 0x8D, 0x02, 0x02,
        0xA9, 0x0C, 0x8D, 0x03, 0x02,
        0xA9, 0x00, 0x8D, 0x03, 0x20,
        0xA9, 0x02, 0x8D, 0x14, 0x40,
        0xAD, 0x02, 0x20,
        0xA9, 0x3F, 0x8D, 0x06, 0x20,
        0xA9, 0x10, 0x8D, 0x06, 0x20,
    ]
    for value in (0x0F, 0x30, 0x16, 0x27):
        body.extend([0xA9, value, 0x8D, 0x07, 0x20])
    body.extend([0xA9, 0x88, 0x8D, 0x00, 0x20])
    loop_addr = 0x8000 + len(body)
    body.extend([0x4C, loop_addr & 0xFF, loop_addr >> 8])
    banks[4][: len(body)] = bytes(body)

    reset = [
        0xA9, 0x04, 0x8D, 0x00, 0x90,  # high bit for CHR $1000-$1FFF
        0xA9, 0x02, 0x8D, 0x00, 0xF0,  # CHR 4 KiB bank $12 at PPU $1000-$1FFF
        0xA9, 0x04, 0x8D, 0x00, 0x80,  # PRG slot $8000 = bank 4
        0x4C, 0x00, 0x80,
    ]
    banks[-1][: len(reset)] = bytes(reset)
    banks[-1][0x0100] = 0x40
    banks[-1][0x1FFA:0x1FFC] = (0xE100).to_bytes(2, "little")
    banks[-1][0x1FFC:0x1FFE] = (0xE000).to_bytes(2, "little")
    banks[-1][0x1FFE:0x2000] = (0xE100).to_bytes(2, "little")

    chr_data = bytearray(16 * 0x2000)
    rows = [[0, 1, 2, 3, 0, 1, 2, 3] for _ in range(8)]
    chr_data[0x12 * 0x1000 : 0x12 * 0x1000 + 0x10] = _encode_tile(rows)
    return ines_header(4, 16, 75) + b"".join(bytes(bank) for bank in banks) + bytes(chr_data)


def _runtime_mapper79_sprite_test_rom() -> bytes:
    bank0 = bytearray([0xEA] * 0x8000)
    bank1 = bytearray([0xEA] * 0x8000)

    code = [
        0x78,  # SEI
        0xD8,  # CLD
        0xA2, 0x00,
        0xA9, 0xF8,
        0x9D, 0x00, 0x02,
        0xE8,
        0xD0, 0xFA,
        0xA9, 0x14, 0x8D, 0x00, 0x02,
        0xA9, 0x00, 0x8D, 0x01, 0x02,
        0xA9, 0x00, 0x8D, 0x02, 0x02,
        0xA9, 0x0C, 0x8D, 0x03, 0x02,
        0xA9, 0x00, 0x8D, 0x03, 0x20,
        0xA9, 0x02, 0x8D, 0x14, 0x40,
        0xAD, 0x02, 0x20,
        0xA9, 0x3F, 0x8D, 0x06, 0x20,
        0xA9, 0x10, 0x8D, 0x06, 0x20,
    ]
    for value in (0x0F, 0x30, 0x16, 0x27):
        code.extend([0xA9, value, 0x8D, 0x07, 0x20])
    code.extend([0xA9, 0x88, 0x8D, 0x00, 0x20])
    loop_addr = 0x8000 + len(code)
    code.extend([0x4C, loop_addr & 0xFF, loop_addr >> 8])
    bank1[: len(code)] = bytes(code)

    reset = [
        0xA9, 0x0D, 0x8D, 0x00, 0x41,  # PRG bank 1, CHR bank 5
        0x4C, 0x00, 0x80,
    ]
    bank0[: len(reset)] = bytes(reset)
    for bank in (bank0, bank1):
        bank[0x0100] = 0x40
        bank[0x7FFA:0x7FFC] = (0x8100).to_bytes(2, "little")
        bank[0x7FFC:0x7FFE] = (0x8000).to_bytes(2, "little")
        bank[0x7FFE:0x8000] = (0x8100).to_bytes(2, "little")

    chr_data = bytearray(8 * 0x2000)
    rows = [[0, 1, 2, 3, 0, 1, 2, 3] for _ in range(8)]
    chr_data[5 * 0x2000 + 0x1000 : 5 * 0x2000 + 0x1010] = _encode_tile(rows)
    return ines_header(4, 8, 79) + bytes(bank0 + bank1) + bytes(chr_data)


def _runtime_mapper78_sprite_test_rom() -> bytes:
    banks = [bytearray([0xEA] * PRG_BANK) for _ in range(8)]
    code = [
        0x78,  # SEI
        0xD8,  # CLD
        0xA2, 0x00,
        0xA9, 0xF8,
        0x9D, 0x00, 0x02,
        0xE8,
        0xD0, 0xFA,
        0xA9, 0x14, 0x8D, 0x00, 0x02,
        0xA9, 0x00, 0x8D, 0x01, 0x02,
        0xA9, 0x00, 0x8D, 0x02, 0x02,
        0xA9, 0x0C, 0x8D, 0x03, 0x02,
        0xA9, 0x00, 0x8D, 0x03, 0x20,
        0xA9, 0x02, 0x8D, 0x14, 0x40,
        0xAD, 0x02, 0x20,
        0xA9, 0x3F, 0x8D, 0x06, 0x20,
        0xA9, 0x10, 0x8D, 0x06, 0x20,
    ]
    for value in (0x0F, 0x30, 0x16, 0x27):
        code.extend([0xA9, value, 0x8D, 0x07, 0x20])
    code.extend([0xA9, 0x88, 0x8D, 0x00, 0x20])
    loop_addr = 0x8000 + len(code)
    code.extend([0x4C, loop_addr & 0xFF, loop_addr >> 8])
    banks[2][: len(code)] = bytes(code)

    reset = [
        0xA9, 0x52, 0x8D, 0x00, 0x80,  # select PRG bank 2 and CHR bank 5
        0x4C, 0x00, 0x80,
    ]
    banks[-1][: len(reset)] = bytes(reset)
    banks[-1][0x0100] = 0x40
    banks[-1][0x3FFA:0x3FFC] = (0xC100).to_bytes(2, "little")
    banks[-1][0x3FFC:0x3FFE] = (0xC000).to_bytes(2, "little")
    banks[-1][0x3FFE:0x4000] = (0xC100).to_bytes(2, "little")

    chr_data = bytearray(8 * 0x2000)
    rows = [[0, 1, 2, 3, 0, 1, 2, 3] for _ in range(8)]
    chr_data[5 * 0x2000 + 0x1000 : 5 * 0x2000 + 0x1010] = _encode_tile(rows)
    return ines_header(8, 8, 78) + b"".join(bytes(bank) for bank in banks) + bytes(chr_data)


def _runtime_mapper87_sprite_test_rom() -> bytes:
    code = [
        0x78,  # SEI
        0xD8,  # CLD
        0xA9, 0x01, 0x8D, 0x00, 0x60,  # select J87 CHR bank 2: bit0 is high bit
        0xA2, 0x00,
        0xA9, 0xF8,
        0x9D, 0x00, 0x02,
        0xE8,
        0xD0, 0xFA,
        0xA9, 0x14, 0x8D, 0x00, 0x02,
        0xA9, 0x00, 0x8D, 0x01, 0x02,
        0xA9, 0x00, 0x8D, 0x02, 0x02,
        0xA9, 0x0C, 0x8D, 0x03, 0x02,
        0xA9, 0x00, 0x8D, 0x03, 0x20,
        0xA9, 0x02, 0x8D, 0x14, 0x40,
        0xAD, 0x02, 0x20,
        0xA9, 0x3F, 0x8D, 0x06, 0x20,
        0xA9, 0x10, 0x8D, 0x06, 0x20,
    ]
    for value in (0x0F, 0x30, 0x16, 0x27):
        code.extend([0xA9, value, 0x8D, 0x07, 0x20])
    code.extend([0xA9, 0x88, 0x8D, 0x00, 0x20])
    loop_addr = 0x8000 + len(code)
    code.extend([0x4C, loop_addr & 0xFF, loop_addr >> 8])
    prg = bytearray([0xEA] * 0x8000)
    prg[: len(code)] = bytes(code)
    prg[0x0100] = 0x40
    prg[0x7FFA:0x7FFC] = (0x8100).to_bytes(2, "little")
    prg[0x7FFC:0x7FFE] = (0x8000).to_bytes(2, "little")
    prg[0x7FFE:0x8000] = (0x8100).to_bytes(2, "little")

    chr_data = bytearray(0x8000)
    rows = [[0, 1, 2, 3, 0, 1, 2, 3] for _ in range(8)]
    # Banks 0/1 are blank. J87 register value $01 maps bank 2, not bank 1.
    chr_data[2 * 0x2000 + 0x1000 : 2 * 0x2000 + 0x1010] = _encode_tile(rows)
    return ines_header(2, 4, 87) + bytes(prg) + bytes(chr_data)


def _runtime_mapper101_sprite_test_rom() -> bytes:
    code = [
        0x78,  # SEI
        0xD8,  # CLD
        0xA9, 0x01, 0x8D, 0x00, 0x60,  # select JF-10 CHR bank 1: normal bit order
        0xA2, 0x00,
        0xA9, 0xF8,
        0x9D, 0x00, 0x02,
        0xE8,
        0xD0, 0xFA,
        0xA9, 0x14, 0x8D, 0x00, 0x02,
        0xA9, 0x00, 0x8D, 0x01, 0x02,
        0xA9, 0x00, 0x8D, 0x02, 0x02,
        0xA9, 0x0C, 0x8D, 0x03, 0x02,
        0xA9, 0x00, 0x8D, 0x03, 0x20,
        0xA9, 0x02, 0x8D, 0x14, 0x40,
        0xAD, 0x02, 0x20,
        0xA9, 0x3F, 0x8D, 0x06, 0x20,
        0xA9, 0x10, 0x8D, 0x06, 0x20,
    ]
    for value in (0x0F, 0x30, 0x16, 0x27):
        code.extend([0xA9, value, 0x8D, 0x07, 0x20])
    code.extend([0xA9, 0x88, 0x8D, 0x00, 0x20])
    loop_addr = 0x8000 + len(code)
    code.extend([0x4C, loop_addr & 0xFF, loop_addr >> 8])
    prg = bytearray([0xEA] * 0x8000)
    prg[: len(code)] = bytes(code)
    prg[0x0100] = 0x40
    prg[0x7FFA:0x7FFC] = (0x8100).to_bytes(2, "little")
    prg[0x7FFC:0x7FFE] = (0x8000).to_bytes(2, "little")
    prg[0x7FFE:0x8000] = (0x8100).to_bytes(2, "little")

    chr_data = bytearray(0x8000)
    rows = [[0, 1, 2, 3, 0, 1, 2, 3] for _ in range(8)]
    # Banks 0/2 are blank. Mapper 101 value $01 maps bank 1, not bank 2.
    chr_data[1 * 0x2000 + 0x1000 : 1 * 0x2000 + 0x1010] = _encode_tile(rows)
    return ines_header(2, 4, 101) + bytes(prg) + bytes(chr_data)


class TestSpritePalettes(unittest.TestCase):
    def test_parse_palette_values_accepts_hex_style(self):
        self.assertEqual(parse_palette_values("0F,30,16,27"), (0x0F, 0x30, 0x16, 0x27))
        self.assertEqual(parse_palette_values("0x0f 0x30 0x16 0x27"), (0x0F, 0x30, 0x16, 0x27))

    def test_parse_runtime_input_script_builds_frame_masks(self):
        self.assertEqual(
            parse_runtime_input_script("start@1:2,a+right@4", 5),
            (0x08, 0x08, 0x00, 0x81, 0x00),
        )

    def test_palette_ram_from_one_sprite_palette(self):
        ram = sprite_palette_to_palette_ram((0x0F, 0x30, 0x16, 0x27))
        self.assertEqual(len(ram), 32)
        self.assertEqual(ram[0x10:0x14], (0x0F, 0x30, 0x16, 0x27))
        self.assertEqual(ram[0x1C:0x20], (0x0F, 0x30, 0x16, 0x27))

    def test_sprite_index_zero_is_transparent(self):
        ram = sprite_palette_to_palette_ram(DEFAULT_SPRITE_PALETTE)
        self.assertEqual(rgba_for_sprite_pixel(0, palette_id=0, palette_ram=ram), (0, 0, 0, 0))
        self.assertEqual(rgba_for_sprite_pixel(1, palette_id=0, palette_ram=ram)[3], 255)

    def test_normalize_accepts_full_palette_ram(self):
        values = tuple(range(32))
        self.assertEqual(normalize_palette_ram(values), values)


class TestSpriteChrDecode(unittest.TestCase):
    def test_extract_chr_bank_from_ines(self):
        chr_data = chr_from_ines(_sprite_test_rom())
        self.assertEqual(len(chr_data), 0x2000)

    def test_decode_sprite_pattern_from_pattern_table_1(self):
        chr_data = chr_from_ines(_sprite_test_rom())
        rows = decode_sprite_pattern(chr_data, 0, pattern_table=1, sprite_height=8)
        self.assertEqual(rows[0], [0, 1, 2, 3, 0, 1, 2, 3])


class TestSpriteExport(unittest.TestCase):
    def test_export_writes_transparent_png_and_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            rom_path = Path(td) / "sprite.nes"
            rom_path.write_bytes(_sprite_test_rom())
            out_dir = Path(td) / "sprites"

            manifest = export_sprite_pattern_table(
                rom_path,
                out_dir,
                pattern_table=1,
                palette_values=(0x0F, 0x30, 0x16, 0x27),
            )

            self.assertTrue(manifest.spritesheet.exists())
            self.assertTrue(manifest.manifest_json.exists())
            self.assertEqual(len(manifest.sprite_paths), 256)

            tile_png = manifest.sprite_paths[0].path
            img = Image.open(tile_png).convert("RGBA")
            self.assertEqual(img.size, (8, 8))
            self.assertEqual(img.getpixel((0, 0))[3], 0)
            self.assertEqual(img.getpixel((1, 0))[3], 255)

            data = json.loads(manifest.manifest_json.read_text())
            self.assertEqual(data["transparent_index"], 0)
            self.assertEqual(data["palette_source"], "preview")
            self.assertIn("spritesheet", data)

    def test_cli_sprites_command(self):
        with tempfile.TemporaryDirectory() as td:
            rom_path = Path(td) / "sprite.nes"
            rom_path.write_bytes(_sprite_test_rom())
            out_dir = Path(td) / "sprites"

            from qlnes.cli import main

            rc = main(
                [
                    "sprites",
                    str(rom_path),
                    "-o",
                    str(out_dir),
                    "--palette",
                    "0F,30,16,27",
                    "--quiet",
                ]
            )
            self.assertEqual(rc, 0)
            self.assertTrue((out_dir / "spritesheet-pt1-pal0.png").exists())
            self.assertTrue((out_dir / "sprites-manifest.json").exists())

    def test_cli_sprites_runtime_snapshot_command(self):
        with tempfile.TemporaryDirectory() as td:
            rom_path = Path(td) / "sprite.nes"
            rom_path.write_bytes(_sprite_test_rom())
            snapshot_path = Path(td) / "snapshot.json"
            palette_ram = [0x0F] * 32
            palette_ram[0x10:0x14] = [0x0F, 0x30, 0x16, 0x27]
            oam = [0xF8, 0, 0, 0] * 64
            oam[0:4] = [20, 0x00, 0x00, 12]
            snapshot_path.write_text(
                json.dumps({"ppuctrl": "0x08", "palette_ram": palette_ram, "oam": oam})
            )
            out_dir = Path(td) / "runtime"

            from qlnes.cli import main

            rc = main(
                [
                    "sprites",
                    str(rom_path),
                    "-o",
                    str(out_dir),
                    "--snapshot",
                    str(snapshot_path),
                    "--quiet",
                ]
            )
            self.assertEqual(rc, 0)
            self.assertTrue((out_dir / "oam-spritesheet.png").exists())
            self.assertTrue((out_dir / "oam" / "sprite-00-tile-00-pal0.png").exists())

    def test_in_process_runtime_export_captures_palette_and_oam(self):
        with tempfile.TemporaryDirectory() as td:
            rom_path = Path(td) / "runtime.nes"
            rom_path.write_bytes(_runtime_sprite_test_rom())
            out_dir = Path(td) / "auto"

            manifest = export_in_process_runtime_sprites(rom_path, out_dir, frames=1)

            self.assertEqual(manifest.palette_source, "runtime-snapshot")
            self.assertEqual(manifest.n_tiles, 1)
            sprite = out_dir / "oam" / "sprite-00-tile-00-pal0.png"
            self.assertTrue(sprite.exists())
            img = Image.open(sprite).convert("RGBA")
            self.assertEqual(img.getpixel((0, 0))[3], 0)
            self.assertEqual(img.getpixel((1, 0)), (0xFC, 0xFC, 0xFC, 255))
            data = json.loads((out_dir / "sprites-manifest.json").read_text())
            self.assertEqual(data["snapshot"], "in-process")
            self.assertEqual(data["runtime_frames"], 1)
            self.assertEqual(data["sprites"][0]["palette_ppu"], ["0x0F", "0x30", "0x16", "0x27"])
            self.assertEqual(data["sprites"][0]["palette_rgba"][0], [0, 0, 0, 0])
            self.assertEqual(data["sprites"][0]["palette_rgba"][1], [0xFC, 0xFC, 0xFC, 255])
            self.assertTrue((out_dir / "oam-screen.png").exists())
            screen = Image.open(out_dir / "oam-screen.png").convert("RGBA")
            self.assertEqual(screen.size, (256, 240))
            self.assertEqual(screen.getpixel((12, 21))[3], 0)
            self.assertEqual(screen.getpixel((13, 21)), (0xFC, 0xFC, 0xFC, 255))
            self.assertEqual(screen.getpixel((0, 0))[3], 0)

    def test_in_process_runtime_export_captures_nrom_chr_ram_pattern_table(self):
        with tempfile.TemporaryDirectory() as td:
            rom_path = Path(td) / "runtime-nrom-chr-ram.nes"
            rom_path.write_bytes(_runtime_nrom_chr_ram_sprite_test_rom())
            out_dir = Path(td) / "auto-chr-ram"

            manifest = export_in_process_runtime_sprites(rom_path, out_dir, frames=1)

            self.assertEqual(manifest.n_tiles, 1)
            sprite = out_dir / "oam" / "sprite-00-tile-00-pal0.png"
            img = Image.open(sprite).convert("RGBA")
            self.assertEqual(img.getpixel((0, 0))[3], 0)
            self.assertEqual(img.getpixel((1, 0)), (0xFC, 0xFC, 0xFC, 255))
            data = json.loads((out_dir / "sprites-manifest.json").read_text())
            self.assertTrue(data["chr_ram"])
            self.assertEqual(data["chr_source"], "snapshot")
            self.assertIn("CHR-RAM runtime export", data["notes"][0])

    def test_in_process_runtime_export_captures_oamdma_from_prg_ram(self):
        with tempfile.TemporaryDirectory() as td:
            rom_path = Path(td) / "runtime-prg-ram-oamdma.nes"
            rom_path.write_bytes(_runtime_prg_ram_oamdma_sprite_test_rom())
            out_dir = Path(td) / "auto-prg-ram-oamdma"

            manifest = export_in_process_runtime_sprites(rom_path, out_dir, frames=1)

            self.assertEqual(manifest.n_tiles, 1)
            sprite = out_dir / "oam" / "sprite-00-tile-00-pal0.png"
            img = Image.open(sprite).convert("RGBA")
            self.assertEqual(img.getpixel((0, 0))[3], 0)
            self.assertEqual(img.getpixel((1, 0)), (0xFC, 0xFC, 0xFC, 255))
            data = json.loads((out_dir / "sprites-manifest.json").read_text())
            self.assertEqual(data["sprites"][0]["x"], 12)
            self.assertEqual(data["sprites"][0]["y"], 21)
            self.assertEqual(data["chr_source"], "rom")

    def test_in_process_runtime_export_runs_cprom_chr_ram_bank(self):
        with tempfile.TemporaryDirectory() as td:
            rom_path = Path(td) / "runtime-cprom.nes"
            rom_path.write_bytes(_runtime_cprom_chr_ram_sprite_test_rom())
            out_dir = Path(td) / "auto-cprom"

            manifest = export_in_process_runtime_sprites(rom_path, out_dir, frames=1)

            self.assertEqual(manifest.chr_bank, 2)
            self.assertEqual(manifest.n_tiles, 1)
            sprite = out_dir / "oam" / "sprite-00-tile-00-pal0.png"
            img = Image.open(sprite).convert("RGBA")
            self.assertEqual(img.getpixel((0, 0))[3], 0)
            self.assertEqual(img.getpixel((1, 0)), (0xFC, 0xFC, 0xFC, 255))
            data = json.loads((out_dir / "sprites-manifest.json").read_text())
            self.assertTrue(data["chr_ram"])
            self.assertEqual(data["chr_bank"], 2)
            self.assertEqual(data["chr_source"], "snapshot")

    def test_in_process_runtime_export_accepts_controller_input_script(self):
        with tempfile.TemporaryDirectory() as td:
            rom_path = Path(td) / "runtime-start-gated.nes"
            rom_path.write_bytes(_runtime_start_gated_sprite_test_rom())
            no_input_out = Path(td) / "no-input"
            with_input_out = Path(td) / "with-input"

            no_input = export_in_process_runtime_sprites(rom_path, no_input_out, frames=2)
            self.assertEqual(no_input.n_tiles, 0)

            controller_frames = parse_runtime_input_script("start@1:2", 2)
            manifest = export_in_process_runtime_sprites(
                rom_path,
                with_input_out,
                frames=2,
                controller1_frames=controller_frames,
                runtime_input_script="start@1:2",
            )

            self.assertEqual(manifest.n_tiles, 1)
            sprite = with_input_out / "oam" / "sprite-00-tile-00-pal0.png"
            img = Image.open(sprite).convert("RGBA")
            self.assertEqual(img.getpixel((0, 0))[3], 0)
            self.assertEqual(img.getpixel((1, 0)), (0xFC, 0xFC, 0xFC, 255))
            data = json.loads((with_input_out / "sprites-manifest.json").read_text())
            self.assertEqual(data["runtime_input"], "start@1:2")
            self.assertEqual(data["controller1_nonzero_frames"], 2)

    def test_cli_sprites_runtime_frames_command(self):
        with tempfile.TemporaryDirectory() as td:
            rom_path = Path(td) / "runtime.nes"
            rom_path.write_bytes(_runtime_sprite_test_rom())
            out_dir = Path(td) / "auto"

            from qlnes.cli import main

            rc = main(
                [
                    "sprites",
                    str(rom_path),
                    "-o",
                    str(out_dir),
                    "--runtime-frames",
                    "1",
                    "--quiet",
                ]
            )
            self.assertEqual(rc, 0)
            self.assertTrue((out_dir / "oam-spritesheet.png").exists())
            self.assertTrue((out_dir / "sprites-manifest.json").exists())

    def test_cli_sprites_runtime_input_command(self):
        with tempfile.TemporaryDirectory() as td:
            rom_path = Path(td) / "runtime-start-gated.nes"
            rom_path.write_bytes(_runtime_start_gated_sprite_test_rom())
            out_dir = Path(td) / "runtime-input"

            from qlnes.cli import main

            rc = main(
                [
                    "sprites",
                    str(rom_path),
                    "-o",
                    str(out_dir),
                    "--runtime-frames",
                    "2",
                    "--runtime-input",
                    "start@1:2",
                    "--quiet",
                ]
            )
            self.assertEqual(rc, 0)
            self.assertTrue((out_dir / "oam" / "sprite-00-tile-00-pal0.png").exists())
            data = json.loads((out_dir / "sprites-manifest.json").read_text())
            self.assertEqual(data["runtime_input"], "start@1:2")

    def test_in_process_runtime_sample_export_writes_one_directory_per_frame(self):
        with tempfile.TemporaryDirectory() as td:
            rom_path = Path(td) / "runtime.nes"
            rom_path.write_bytes(_runtime_sprite_test_rom())
            out_dir = Path(td) / "samples"

            manifest = export_in_process_runtime_sprite_samples(
                rom_path,
                out_dir,
                sample_frames=(1, 2),
            )

            self.assertEqual([sample.frame for sample in manifest.samples], [1, 2])
            self.assertTrue((out_dir / "frame-000001" / "oam-spritesheet.png").exists())
            self.assertTrue((out_dir / "frame-000002" / "oam-spritesheet.png").exists())
            self.assertEqual(manifest.unique_count, 1)
            self.assertTrue((out_dir / "unique" / "sprite-0000.png").exists())
            self.assertTrue((out_dir / "unique-spritesheet.png").exists())
            self.assertTrue((out_dir / "unique-trimmed" / "sprite-0000.png").exists())
            self.assertTrue((out_dir / "unique-trimmed-spritesheet.png").exists())
            sheet = Image.open(out_dir / "unique-spritesheet.png").convert("RGBA")
            self.assertEqual(sheet.size, (16 * 8, 8))
            self.assertEqual(sheet.getpixel((0, 0))[3], 0)
            self.assertEqual(sheet.getpixel((1, 0)), (0xFC, 0xFC, 0xFC, 255))
            trimmed = Image.open(out_dir / "unique-trimmed" / "sprite-0000.png").convert("RGBA")
            self.assertEqual(trimmed.size, (7, 8))
            self.assertEqual(trimmed.getpixel((0, 0)), (0xFC, 0xFC, 0xFC, 255))
            trimmed_sheet = Image.open(out_dir / "unique-trimmed-spritesheet.png").convert("RGBA")
            self.assertEqual(trimmed_sheet.size, (16 * 7, 8))
            data = json.loads((out_dir / "runtime-sprite-samples-manifest.json").read_text())
            self.assertEqual(data["kind"], "runtime_sprite_samples_export")
            self.assertEqual(data["sample_frames"], [1, 2])
            self.assertEqual(data["unique_sprite_count"], 1)
            self.assertEqual(data["unique_spritesheet"], str(out_dir / "unique-spritesheet.png"))
            self.assertEqual(
                data["unique_trimmed_spritesheet"],
                str(out_dir / "unique-trimmed-spritesheet.png"),
            )
            self.assertEqual(data["unique_sprites"][0]["transparent_bbox"], [1, 0, 8, 8])
            self.assertEqual(data["unique_sprites"][0]["palette_ppu"], ["0x0F", "0x30", "0x16", "0x27"])
            self.assertEqual(data["unique_sprites"][0]["palette_rgba"][1], [0xFC, 0xFC, 0xFC, 255])
            self.assertRegex(data["unique_sprites"][0]["trimmed_sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(
                data["unique_sprites"][0]["sheet"],
                {"sheet_x": 0, "sheet_y": 0, "sheet_w": 8, "sheet_h": 8, "cell_w": 8, "cell_h": 8},
            )
            self.assertEqual(
                data["unique_sprites"][0]["trimmed_sheet"],
                {"sheet_x": 0, "sheet_y": 0, "sheet_w": 7, "sheet_h": 8, "cell_w": 7, "cell_h": 8},
            )
            self.assertEqual(data["transparent_index"], 0)

    def test_cli_sprites_runtime_sample_frames_command(self):
        with tempfile.TemporaryDirectory() as td:
            rom_path = Path(td) / "runtime.nes"
            rom_path.write_bytes(_runtime_sprite_test_rom())
            out_dir = Path(td) / "samples"

            from qlnes.cli import main

            rc = main(
                [
                    "sprites",
                    str(rom_path),
                    "-o",
                    str(out_dir),
                    "--runtime-sample-frames",
                    "1,2",
                    "--quiet",
                ]
            )

            self.assertEqual(rc, 0)
            self.assertTrue((out_dir / "frame-000001" / "oam-screen.png").exists())
            self.assertTrue((out_dir / "unique" / "sprite-0000.png").exists())
            self.assertTrue((out_dir / "unique-spritesheet.png").exists())
            self.assertTrue((out_dir / "unique-trimmed-spritesheet.png").exists())
            self.assertTrue((out_dir / "runtime-sprite-samples-manifest.json").exists())

    def test_cli_sprites_runtime_sample_range_command(self):
        with tempfile.TemporaryDirectory() as td:
            rom_path = Path(td) / "runtime.nes"
            rom_path.write_bytes(_runtime_sprite_test_rom())
            out_dir = Path(td) / "sample-range"

            from qlnes.cli import main

            rc = main(
                [
                    "sprites",
                    str(rom_path),
                    "-o",
                    str(out_dir),
                    "--runtime-sample-range",
                    "1:3:2",
                    "--quiet",
                ]
            )

            self.assertEqual(rc, 0)
            self.assertTrue((out_dir / "frame-000001" / "oam-screen.png").exists())
            self.assertTrue((out_dir / "frame-000003" / "oam-screen.png").exists())
            data = json.loads((out_dir / "runtime-sprite-samples-manifest.json").read_text())
            self.assertEqual(data["sample_frames"], [1, 3])

    def test_export_sprite_batch_writes_one_manifest_per_rom_and_summary(self):
        with tempfile.TemporaryDirectory() as td:
            rom_dir = Path(td) / "roms"
            rom_dir.mkdir()
            (rom_dir / "a.nes").write_bytes(_sprite_test_rom())
            (rom_dir / "b.NES").write_bytes(_sprite_test_rom())
            out_dir = Path(td) / "batch"

            manifest = export_sprite_batch(
                rom_dir,
                out_dir,
                palette_values=(0x0F, 0x30, 0x16, 0x27),
                palette_source="user",
                per_tile=False,
            )

            self.assertEqual(manifest.success_count, 2)
            self.assertEqual(manifest.failure_count, 0)
            self.assertTrue((out_dir / "a" / "sprites-manifest.json").exists())
            self.assertTrue((out_dir / "b" / "sprites-manifest.json").exists())
            data = json.loads((out_dir / "sprites-batch-manifest.json").read_text())
            self.assertEqual(data["rom_count"], 2)
            self.assertEqual(data["success_count"], 2)
            self.assertEqual(data["transparent_index"], 0)

    def test_cli_sprites_batch_runtime_records_failures_when_allowed(self):
        with tempfile.TemporaryDirectory() as td:
            rom_dir = Path(td) / "roms"
            rom_dir.mkdir()
            (rom_dir / "ok.nes").write_bytes(_runtime_sprite_test_rom())
            (rom_dir / "bad.nes").write_bytes(b"not a rom")
            out_dir = Path(td) / "batch-runtime"

            from qlnes.cli import main

            rc = main(
                [
                    "sprites-batch",
                    str(rom_dir),
                    "-o",
                    str(out_dir),
                    "--runtime-frames",
                    "1",
                    "--allow-failures",
                    "--quiet",
                ]
            )

            self.assertEqual(rc, 0)
            self.assertTrue((out_dir / "ok" / "oam-spritesheet.png").exists())
            data = json.loads((out_dir / "sprites-batch-manifest.json").read_text())
            self.assertEqual(data["mode"], "runtime")
            self.assertEqual(data["success_count"], 1)
            self.assertEqual(data["failure_count"], 1)
            self.assertEqual(data["all_unique_trimmed_count"], 1)
            self.assertTrue((out_dir / "all-unique-trimmed" / "sprite-0000.png").exists())
            self.assertTrue((out_dir / "all-unique-trimmed-atlas.json").exists())
            atlas = json.loads((out_dir / "all-unique-trimmed-atlas.json").read_text())
            self.assertEqual(atlas["sprite_count"], 1)
            self.assertEqual(atlas["sprites"][0]["first_seen_frame"], 1)
            self.assertEqual(atlas["sprites"][0]["palette_ppu"], ["0x0F", "0x30", "0x16", "0x27"])
            errors = [entry["error"] for entry in data["entries"] if not entry["ok"]]
            self.assertTrue(errors)

    def test_cli_sprites_batch_runtime_sample_frames(self):
        with tempfile.TemporaryDirectory() as td:
            rom_dir = Path(td) / "roms"
            rom_dir.mkdir()
            (rom_dir / "ok.nes").write_bytes(_runtime_sprite_test_rom())
            out_dir = Path(td) / "batch-samples"

            from qlnes.cli import main

            rc = main(
                [
                    "sprites-batch",
                    str(rom_dir),
                    "-o",
                    str(out_dir),
                    "--runtime-sample-frames",
                    "1,2",
                    "--quiet",
                ]
            )

            self.assertEqual(rc, 0)
            self.assertTrue(
                (out_dir / "ok" / "frame-000001" / "oam-spritesheet.png").exists()
            )
            data = json.loads((out_dir / "sprites-batch-manifest.json").read_text())
            self.assertEqual(data["mode"], "runtime-samples")
            self.assertEqual(data["runtime_sample_frames"], [1, 2])
            self.assertEqual(data["success_count"], 1)
            self.assertEqual(data["entries"][0]["n_tiles"], 1)
            self.assertEqual(data["all_unique_trimmed_count"], 1)
            self.assertTrue((out_dir / "all-unique-trimmed" / "sprite-0000.png").exists())
            self.assertTrue((out_dir / "all-unique-trimmed-spritesheet.png").exists())
            self.assertTrue((out_dir / "all-unique-trimmed-atlas.json").exists())
            self.assertEqual(
                data["all_unique_trimmed_atlas"],
                str(out_dir / "all-unique-trimmed-atlas.json"),
            )
            atlas = json.loads((out_dir / "all-unique-trimmed-atlas.json").read_text())
            self.assertEqual(atlas["kind"], "sprite_atlas")
            self.assertEqual(atlas["sprite_count"], 1)
            self.assertEqual(atlas["spritesheet"], str(out_dir / "all-unique-trimmed-spritesheet.png"))
            self.assertRegex(data["all_unique_trimmed"][0]["trimmed_sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(
                data["all_unique_trimmed"][0]["sheet"],
                {"sheet_x": 0, "sheet_y": 0, "sheet_w": 7, "sheet_h": 8, "cell_w": 7, "cell_h": 8},
            )

    def test_cli_sprites_batch_runtime_sample_range(self):
        with tempfile.TemporaryDirectory() as td:
            rom_dir = Path(td) / "roms"
            rom_dir.mkdir()
            (rom_dir / "ok.nes").write_bytes(_runtime_sprite_test_rom())
            out_dir = Path(td) / "batch-range"

            from qlnes.cli import main

            rc = main(
                [
                    "sprites-batch",
                    str(rom_dir),
                    "-o",
                    str(out_dir),
                    "--runtime-sample-range",
                    "1:3:2",
                    "--quiet",
                ]
            )

            self.assertEqual(rc, 0)
            data = json.loads((out_dir / "sprites-batch-manifest.json").read_text())
            self.assertEqual(data["runtime_sample_frames"], [1, 3])
            self.assertEqual(data["entries"][0]["n_tiles"], 1)
            self.assertEqual(data["all_unique_trimmed_count"], 1)

    def test_in_process_runtime_export_uses_cnrom_selected_chr_bank(self):
        with tempfile.TemporaryDirectory() as td:
            rom_path = Path(td) / "runtime-cnrom.nes"
            rom_path.write_bytes(_runtime_cnrom_sprite_test_rom())
            out_dir = Path(td) / "auto-cnrom"

            manifest = export_in_process_runtime_sprites(rom_path, out_dir, frames=1)

            self.assertEqual(manifest.chr_bank, 1)
            sprite = out_dir / "oam" / "sprite-00-tile-00-pal0.png"
            img = Image.open(sprite).convert("RGBA")
            self.assertEqual(img.getpixel((0, 0))[3], 0)
            self.assertEqual(img.getpixel((1, 0)), (0xFC, 0xFC, 0xFC, 255))
            data = json.loads((out_dir / "sprites-manifest.json").read_text())
            self.assertEqual(data["chr_bank"], 1)
            self.assertEqual(data["chr_source"], "rom")

    def test_in_process_runtime_export_runs_uxrom_switched_init_bank(self):
        with tempfile.TemporaryDirectory() as td:
            rom_path = Path(td) / "runtime-uxrom.nes"
            rom_path.write_bytes(_runtime_uxrom_sprite_test_rom())
            out_dir = Path(td) / "auto-uxrom"

            manifest = export_in_process_runtime_sprites(rom_path, out_dir, frames=1)

            self.assertEqual(manifest.chr_bank, 0)
            sprite = out_dir / "oam" / "sprite-00-tile-00-pal0.png"
            img = Image.open(sprite).convert("RGBA")
            self.assertEqual(img.getpixel((0, 0))[3], 0)
            self.assertEqual(img.getpixel((1, 0)), (0xFC, 0xFC, 0xFC, 255))
            data = json.loads((out_dir / "sprites-manifest.json").read_text())
            self.assertEqual(data["snapshot"], "in-process")
            self.assertEqual(data["palette_source"], "runtime-snapshot")

    def test_in_process_runtime_export_runs_gxrom_and_uses_selected_chr_bank(self):
        with tempfile.TemporaryDirectory() as td:
            rom_path = Path(td) / "runtime-gxrom.nes"
            rom_path.write_bytes(_runtime_gxrom_sprite_test_rom())
            out_dir = Path(td) / "auto-gxrom"

            manifest = export_in_process_runtime_sprites(rom_path, out_dir, frames=1)

            self.assertEqual(manifest.chr_bank, 1)
            sprite = out_dir / "oam" / "sprite-00-tile-00-pal0.png"
            img = Image.open(sprite).convert("RGBA")
            self.assertEqual(img.getpixel((0, 0))[3], 0)
            self.assertEqual(img.getpixel((1, 0)), (0xFC, 0xFC, 0xFC, 255))
            data = json.loads((out_dir / "sprites-manifest.json").read_text())
            self.assertEqual(data["chr_bank"], 1)
            self.assertEqual(data["snapshot"], "in-process")

    def test_in_process_runtime_export_runs_colordreams_and_uses_selected_chr_bank(self):
        with tempfile.TemporaryDirectory() as td:
            rom_path = Path(td) / "runtime-colordreams.nes"
            rom_path.write_bytes(_runtime_colordreams_sprite_test_rom())
            out_dir = Path(td) / "auto-colordreams"

            manifest = export_in_process_runtime_sprites(rom_path, out_dir, frames=1)

            self.assertEqual(manifest.chr_bank, 2)
            sprite = out_dir / "oam" / "sprite-00-tile-00-pal0.png"
            img = Image.open(sprite).convert("RGBA")
            self.assertEqual(img.getpixel((0, 0))[3], 0)
            self.assertEqual(img.getpixel((1, 0)), (0xFC, 0xFC, 0xFC, 255))
            data = json.loads((out_dir / "sprites-manifest.json").read_text())
            self.assertEqual(data["chr_bank"], 2)
            self.assertEqual(data["chr_source"], "rom")
            self.assertEqual(data["snapshot"], "in-process")

    def test_in_process_runtime_export_runs_axrom_chr_ram_and_uses_snapshot_chr(self):
        with tempfile.TemporaryDirectory() as td:
            rom_path = Path(td) / "runtime-axrom.nes"
            rom_path.write_bytes(_runtime_axrom_chr_ram_sprite_test_rom())
            out_dir = Path(td) / "auto-axrom"

            manifest = export_in_process_runtime_sprites(rom_path, out_dir, frames=1)

            self.assertEqual(manifest.n_tiles, 1)
            sprite = out_dir / "oam" / "sprite-00-tile-00-pal0.png"
            img = Image.open(sprite).convert("RGBA")
            self.assertEqual(img.getpixel((0, 0))[3], 0)
            self.assertEqual(img.getpixel((1, 0)), (0xFC, 0xFC, 0xFC, 255))
            data = json.loads((out_dir / "sprites-manifest.json").read_text())
            self.assertEqual(data["chr_source"], "snapshot")
            self.assertEqual(data["snapshot"], "in-process")

    def test_in_process_runtime_export_runs_mmc1_and_uses_selected_chr_bank(self):
        with tempfile.TemporaryDirectory() as td:
            rom_path = Path(td) / "runtime-mmc1.nes"
            rom_path.write_bytes(_runtime_mmc1_sprite_test_rom())
            out_dir = Path(td) / "auto-mmc1"

            manifest = export_in_process_runtime_sprites(rom_path, out_dir, frames=1)

            self.assertEqual(manifest.chr_bank, 1)
            sprite = out_dir / "oam" / "sprite-00-tile-00-pal0.png"
            img = Image.open(sprite).convert("RGBA")
            self.assertEqual(img.getpixel((0, 0))[3], 0)
            self.assertEqual(img.getpixel((1, 0)), (0xFC, 0xFC, 0xFC, 255))
            data = json.loads((out_dir / "sprites-manifest.json").read_text())
            self.assertEqual(data["chr_bank"], 1)
            self.assertEqual(data["snapshot"], "in-process")

    def test_in_process_runtime_export_runs_mmc1_split_chr_and_uses_snapshot_chr(self):
        with tempfile.TemporaryDirectory() as td:
            rom_path = Path(td) / "runtime-mmc1-split.nes"
            rom_path.write_bytes(_runtime_mmc1_split_chr_sprite_test_rom())
            out_dir = Path(td) / "auto-mmc1-split"

            manifest = export_in_process_runtime_sprites(rom_path, out_dir, frames=1)

            sprite = out_dir / "oam" / "sprite-00-tile-00-pal0.png"
            img = Image.open(sprite).convert("RGBA")
            self.assertEqual(img.getpixel((0, 0))[3], 0)
            self.assertEqual(img.getpixel((1, 0)), (0xFC, 0xFC, 0xFC, 255))
            data = json.loads((out_dir / "sprites-manifest.json").read_text())
            self.assertEqual(data["chr_source"], "snapshot")
            self.assertEqual(data["snapshot"], "in-process")
            self.assertEqual(manifest.n_tiles, 1)

    def test_in_process_runtime_export_runs_mmc3_and_uses_mapped_chr_windows(self):
        with tempfile.TemporaryDirectory() as td:
            rom_path = Path(td) / "runtime-mmc3.nes"
            rom_path.write_bytes(_runtime_mmc3_sprite_test_rom())
            out_dir = Path(td) / "auto-mmc3"

            manifest = export_in_process_runtime_sprites(rom_path, out_dir, frames=1)

            self.assertEqual(manifest.chr_bank, 0)
            sprite = out_dir / "oam" / "sprite-00-tile-00-pal0.png"
            img = Image.open(sprite).convert("RGBA")
            self.assertEqual(img.getpixel((0, 0))[3], 0)
            self.assertEqual(img.getpixel((1, 0)), (0xFC, 0xFC, 0xFC, 255))
            data = json.loads((out_dir / "sprites-manifest.json").read_text())
            self.assertEqual(data["chr_source"], "snapshot")
            self.assertEqual(data["snapshot"], "in-process")

    def test_in_process_runtime_export_runs_rambo1_and_uses_1k_chr_window(self):
        with tempfile.TemporaryDirectory() as td:
            rom_path = Path(td) / "runtime-rambo1.nes"
            rom_path.write_bytes(_runtime_rambo1_sprite_test_rom())
            out_dir = Path(td) / "auto-rambo1"

            manifest = export_in_process_runtime_sprites(rom_path, out_dir, frames=1)

            self.assertEqual(manifest.n_tiles, 1)
            sprite = out_dir / "oam" / "sprite-00-tile-00-pal0.png"
            img = Image.open(sprite).convert("RGBA")
            self.assertEqual(img.getpixel((0, 0))[3], 0)
            self.assertEqual(img.getpixel((1, 0)), (0xFC, 0xFC, 0xFC, 255))
            data = json.loads((out_dir / "sprites-manifest.json").read_text())
            self.assertEqual(data["chr_source"], "snapshot")
            self.assertEqual(data["snapshot"], "in-process")
            self.assertEqual(data["sprites"][0]["palette_ppu"], ["0x0F", "0x30", "0x16", "0x27"])

    def test_in_process_runtime_export_runs_mmc5_and_uses_mapped_chr_windows(self):
        with tempfile.TemporaryDirectory() as td:
            rom_path = Path(td) / "runtime-mmc5.nes"
            rom_path.write_bytes(_runtime_mmc5_sprite_test_rom())
            out_dir = Path(td) / "auto-mmc5"

            manifest = export_in_process_runtime_sprites(rom_path, out_dir, frames=1)

            self.assertEqual(manifest.n_tiles, 1)
            sprite = out_dir / "oam" / "sprite-00-tile-00-pal0.png"
            img = Image.open(sprite).convert("RGBA")
            self.assertEqual(img.getpixel((0, 0))[3], 0)
            self.assertEqual(img.getpixel((1, 0)), (0xFC, 0xFC, 0xFC, 255))
            data = json.loads((out_dir / "sprites-manifest.json").read_text())
            self.assertEqual(data["chr_source"], "snapshot")
            self.assertEqual(data["snapshot"], "in-process")
            self.assertEqual(data["sprites"][0]["palette_ppu"], ["0x0F", "0x30", "0x16", "0x27"])

    def test_in_process_runtime_export_runs_vrc6_and_uses_1k_chr_window(self):
        with tempfile.TemporaryDirectory() as td:
            rom_path = Path(td) / "runtime-vrc6.nes"
            rom_path.write_bytes(_runtime_vrc6_sprite_test_rom())
            out_dir = Path(td) / "auto-vrc6"

            manifest = export_in_process_runtime_sprites(rom_path, out_dir, frames=1)

            self.assertEqual(manifest.n_tiles, 1)
            sprite = out_dir / "oam" / "sprite-00-tile-00-pal0.png"
            img = Image.open(sprite).convert("RGBA")
            self.assertEqual(img.getpixel((0, 0))[3], 0)
            self.assertEqual(img.getpixel((1, 0)), (0xFC, 0xFC, 0xFC, 255))
            data = json.loads((out_dir / "sprites-manifest.json").read_text())
            self.assertEqual(data["chr_source"], "snapshot")
            self.assertEqual(data["snapshot"], "in-process")
            self.assertEqual(data["sprites"][0]["palette_ppu"], ["0x0F", "0x30", "0x16", "0x27"])

    def test_in_process_runtime_export_runs_vrc4_and_uses_1k_chr_window(self):
        with tempfile.TemporaryDirectory() as td:
            rom_path = Path(td) / "runtime-vrc4.nes"
            rom_path.write_bytes(_runtime_vrc4_sprite_test_rom())
            out_dir = Path(td) / "auto-vrc4"

            manifest = export_in_process_runtime_sprites(rom_path, out_dir, frames=1)

            self.assertEqual(manifest.n_tiles, 1)
            sprite = out_dir / "oam" / "sprite-00-tile-00-pal0.png"
            img = Image.open(sprite).convert("RGBA")
            self.assertEqual(img.getpixel((0, 0))[3], 0)
            self.assertEqual(img.getpixel((1, 0)), (0xFC, 0xFC, 0xFC, 255))
            data = json.loads((out_dir / "sprites-manifest.json").read_text())
            self.assertEqual(data["chr_source"], "snapshot")
            self.assertEqual(data["snapshot"], "in-process")
            self.assertEqual(data["sprites"][0]["palette_ppu"], ["0x0F", "0x30", "0x16", "0x27"])

    def test_in_process_runtime_export_runs_vrc7_and_uses_1k_chr_window(self):
        with tempfile.TemporaryDirectory() as td:
            rom_path = Path(td) / "runtime-vrc7.nes"
            rom_path.write_bytes(_runtime_vrc7_sprite_test_rom())
            out_dir = Path(td) / "auto-vrc7"

            manifest = export_in_process_runtime_sprites(rom_path, out_dir, frames=1)

            self.assertEqual(manifest.n_tiles, 1)
            sprite = out_dir / "oam" / "sprite-00-tile-00-pal0.png"
            img = Image.open(sprite).convert("RGBA")
            self.assertEqual(img.getpixel((0, 0))[3], 0)
            self.assertEqual(img.getpixel((1, 0)), (0xFC, 0xFC, 0xFC, 255))
            data = json.loads((out_dir / "sprites-manifest.json").read_text())
            self.assertEqual(data["chr_source"], "snapshot")
            self.assertEqual(data["snapshot"], "in-process")
            self.assertEqual(data["sprites"][0]["palette_ppu"], ["0x0F", "0x30", "0x16", "0x27"])

    def test_in_process_runtime_export_runs_mmc2_and_uses_latched_chr_windows(self):
        with tempfile.TemporaryDirectory() as td:
            rom_path = Path(td) / "runtime-mmc2.nes"
            rom_path.write_bytes(_runtime_mmc2_sprite_test_rom())
            out_dir = Path(td) / "auto-mmc2"

            manifest = export_in_process_runtime_sprites(rom_path, out_dir, frames=1)

            self.assertEqual(manifest.n_tiles, 1)
            sprite = out_dir / "oam" / "sprite-00-tile-00-pal0.png"
            img = Image.open(sprite).convert("RGBA")
            self.assertEqual(img.getpixel((0, 0))[3], 0)
            self.assertEqual(img.getpixel((1, 0)), (0xFC, 0xFC, 0xFC, 255))
            data = json.loads((out_dir / "sprites-manifest.json").read_text())
            self.assertEqual(data["chr_source"], "snapshot")
            self.assertEqual(data["snapshot"], "in-process")
            self.assertEqual(data["sprites"][0]["palette_ppu"], ["0x0F", "0x30", "0x16", "0x27"])

    def test_in_process_runtime_export_runs_mmc4_and_uses_latched_chr_windows(self):
        with tempfile.TemporaryDirectory() as td:
            rom_path = Path(td) / "runtime-mmc4.nes"
            rom_path.write_bytes(_runtime_mmc4_sprite_test_rom())
            out_dir = Path(td) / "auto-mmc4"

            manifest = export_in_process_runtime_sprites(rom_path, out_dir, frames=1)

            self.assertEqual(manifest.n_tiles, 1)
            sprite = out_dir / "oam" / "sprite-00-tile-00-pal0.png"
            img = Image.open(sprite).convert("RGBA")
            self.assertEqual(img.getpixel((0, 0))[3], 0)
            self.assertEqual(img.getpixel((1, 0)), (0xFC, 0xFC, 0xFC, 255))
            data = json.loads((out_dir / "sprites-manifest.json").read_text())
            self.assertEqual(data["chr_source"], "snapshot")
            self.assertEqual(data["snapshot"], "in-process")
            self.assertEqual(data["sprites"][0]["palette_ppu"], ["0x0F", "0x30", "0x16", "0x27"])

    def test_in_process_runtime_export_runs_mapper16_bandai_fcg_and_uses_1k_chr_window(self):
        with tempfile.TemporaryDirectory() as td:
            rom_path = Path(td) / "runtime-mapper16.nes"
            rom_path.write_bytes(_runtime_mapper16_sprite_test_rom())
            out_dir = Path(td) / "auto-mapper16"

            manifest = export_in_process_runtime_sprites(rom_path, out_dir, frames=1)

            self.assertEqual(manifest.n_tiles, 1)
            sprite = out_dir / "oam" / "sprite-00-tile-00-pal0.png"
            img = Image.open(sprite).convert("RGBA")
            self.assertEqual(img.getpixel((0, 0))[3], 0)
            self.assertEqual(img.getpixel((1, 0)), (0xFC, 0xFC, 0xFC, 255))
            data = json.loads((out_dir / "sprites-manifest.json").read_text())
            self.assertEqual(data["chr_source"], "snapshot")
            self.assertEqual(data["snapshot"], "in-process")
            self.assertEqual(data["sprites"][0]["palette_ppu"], ["0x0F", "0x30", "0x16", "0x27"])

    def test_in_process_runtime_export_runs_mapper18_jaleco_and_uses_1k_chr_window(self):
        with tempfile.TemporaryDirectory() as td:
            rom_path = Path(td) / "runtime-mapper18.nes"
            rom_path.write_bytes(_runtime_mapper18_sprite_test_rom())
            out_dir = Path(td) / "auto-mapper18"

            manifest = export_in_process_runtime_sprites(rom_path, out_dir, frames=1)

            self.assertEqual(manifest.n_tiles, 1)
            sprite = out_dir / "oam" / "sprite-00-tile-00-pal0.png"
            img = Image.open(sprite).convert("RGBA")
            self.assertEqual(img.getpixel((0, 0))[3], 0)
            self.assertEqual(img.getpixel((1, 0)), (0xFC, 0xFC, 0xFC, 255))
            data = json.loads((out_dir / "sprites-manifest.json").read_text())
            self.assertEqual(data["chr_source"], "snapshot")
            self.assertEqual(data["snapshot"], "in-process")
            self.assertEqual(data["sprites"][0]["palette_ppu"], ["0x0F", "0x30", "0x16", "0x27"])

    def test_in_process_runtime_export_runs_mapper19_namco163_and_uses_1k_chr_window(self):
        with tempfile.TemporaryDirectory() as td:
            rom_path = Path(td) / "runtime-mapper19.nes"
            rom_path.write_bytes(_runtime_mapper19_sprite_test_rom())
            out_dir = Path(td) / "auto-mapper19"

            manifest = export_in_process_runtime_sprites(rom_path, out_dir, frames=1)

            self.assertEqual(manifest.n_tiles, 1)
            sprite = out_dir / "oam" / "sprite-00-tile-00-pal0.png"
            img = Image.open(sprite).convert("RGBA")
            self.assertEqual(img.getpixel((0, 0))[3], 0)
            self.assertEqual(img.getpixel((1, 0)), (0xFC, 0xFC, 0xFC, 255))
            data = json.loads((out_dir / "sprites-manifest.json").read_text())
            self.assertEqual(data["chr_source"], "snapshot")
            self.assertEqual(data["snapshot"], "in-process")
            self.assertEqual(data["sprites"][0]["palette_ppu"], ["0x0F", "0x30", "0x16", "0x27"])

    def test_in_process_runtime_export_runs_mapper32_irem_g101_and_uses_1k_chr_window(self):
        with tempfile.TemporaryDirectory() as td:
            rom_path = Path(td) / "runtime-mapper32.nes"
            rom_path.write_bytes(_runtime_mapper32_sprite_test_rom())
            out_dir = Path(td) / "auto-mapper32"

            manifest = export_in_process_runtime_sprites(rom_path, out_dir, frames=1)

            self.assertEqual(manifest.n_tiles, 1)
            sprite = out_dir / "oam" / "sprite-00-tile-00-pal0.png"
            img = Image.open(sprite).convert("RGBA")
            self.assertEqual(img.getpixel((0, 0))[3], 0)
            self.assertEqual(img.getpixel((1, 0)), (0xFC, 0xFC, 0xFC, 255))
            data = json.loads((out_dir / "sprites-manifest.json").read_text())
            self.assertEqual(data["chr_source"], "snapshot")
            self.assertEqual(data["snapshot"], "in-process")
            self.assertEqual(data["sprites"][0]["palette_ppu"], ["0x0F", "0x30", "0x16", "0x27"])

    def test_in_process_runtime_export_runs_mapper33_taito_and_uses_mixed_chr_windows(self):
        with tempfile.TemporaryDirectory() as td:
            rom_path = Path(td) / "runtime-mapper33.nes"
            rom_path.write_bytes(_runtime_mapper33_sprite_test_rom())
            out_dir = Path(td) / "auto-mapper33"

            manifest = export_in_process_runtime_sprites(rom_path, out_dir, frames=1)

            self.assertEqual(manifest.n_tiles, 1)
            sprite = out_dir / "oam" / "sprite-00-tile-00-pal0.png"
            img = Image.open(sprite).convert("RGBA")
            self.assertEqual(img.getpixel((0, 0))[3], 0)
            self.assertEqual(img.getpixel((1, 0)), (0xFC, 0xFC, 0xFC, 255))
            data = json.loads((out_dir / "sprites-manifest.json").read_text())
            self.assertEqual(data["chr_source"], "snapshot")
            self.assertEqual(data["snapshot"], "in-process")
            self.assertEqual(data["sprites"][0]["palette_ppu"], ["0x0F", "0x30", "0x16", "0x27"])

    def test_in_process_runtime_export_runs_fme7_and_uses_mapped_chr_windows(self):
        with tempfile.TemporaryDirectory() as td:
            rom_path = Path(td) / "runtime-fme7.nes"
            rom_path.write_bytes(_runtime_fme7_sprite_test_rom())
            out_dir = Path(td) / "auto-fme7"

            manifest = export_in_process_runtime_sprites(rom_path, out_dir, frames=1)

            self.assertEqual(manifest.chr_bank, 0)
            sprite = out_dir / "oam" / "sprite-00-tile-00-pal0.png"
            img = Image.open(sprite).convert("RGBA")
            self.assertEqual(img.getpixel((0, 0))[3], 0)
            self.assertEqual(img.getpixel((1, 0)), (0xFC, 0xFC, 0xFC, 255))
            data = json.loads((out_dir / "sprites-manifest.json").read_text())
            self.assertEqual(data["chr_source"], "snapshot")
            self.assertEqual(data["snapshot"], "in-process")
            self.assertEqual(data["sprites"][0]["palette_ppu"], ["0x0F", "0x30", "0x16", "0x27"])

    def test_in_process_runtime_export_runs_mapper206_and_uses_mapped_chr_windows(self):
        with tempfile.TemporaryDirectory() as td:
            rom_path = Path(td) / "runtime-mapper206.nes"
            rom_path.write_bytes(_runtime_mapper206_sprite_test_rom())
            out_dir = Path(td) / "auto-mapper206"

            manifest = export_in_process_runtime_sprites(rom_path, out_dir, frames=1)

            self.assertEqual(manifest.chr_bank, 0)
            sprite = out_dir / "oam" / "sprite-00-tile-00-pal0.png"
            img = Image.open(sprite).convert("RGBA")
            self.assertEqual(img.getpixel((0, 0))[3], 0)
            self.assertEqual(img.getpixel((1, 0)), (0xFC, 0xFC, 0xFC, 255))
            data = json.loads((out_dir / "sprites-manifest.json").read_text())
            self.assertEqual(data["chr_source"], "snapshot")
            self.assertEqual(data["snapshot"], "in-process")
            self.assertEqual(data["sprites"][0]["palette_ppu"], ["0x0F", "0x30", "0x16", "0x27"])

    def test_in_process_runtime_export_runs_mapper34_nina_and_uses_split_chr(self):
        with tempfile.TemporaryDirectory() as td:
            rom_path = Path(td) / "runtime-mapper34.nes"
            rom_path.write_bytes(_runtime_mapper34_nina_sprite_test_rom())
            out_dir = Path(td) / "auto-mapper34"

            manifest = export_in_process_runtime_sprites(rom_path, out_dir, frames=1)

            self.assertEqual(manifest.n_tiles, 1)
            sprite = out_dir / "oam" / "sprite-00-tile-00-pal0.png"
            img = Image.open(sprite).convert("RGBA")
            self.assertEqual(img.getpixel((0, 0))[3], 0)
            self.assertEqual(img.getpixel((1, 0)), (0xFC, 0xFC, 0xFC, 255))
            data = json.loads((out_dir / "sprites-manifest.json").read_text())
            self.assertEqual(data["chr_source"], "snapshot")
            self.assertEqual(data["snapshot"], "in-process")

    def test_in_process_runtime_export_runs_mapper42_and_uses_selected_chr_bank(self):
        with tempfile.TemporaryDirectory() as td:
            rom_path = Path(td) / "runtime-mapper42.nes"
            rom_path.write_bytes(_runtime_mapper42_sprite_test_rom())
            out_dir = Path(td) / "auto-mapper42"

            manifest = export_in_process_runtime_sprites(rom_path, out_dir, frames=1)

            self.assertEqual(manifest.chr_bank, 2)
            sprite = out_dir / "oam" / "sprite-00-tile-00-pal0.png"
            img = Image.open(sprite).convert("RGBA")
            self.assertEqual(img.getpixel((0, 0))[3], 0)
            self.assertEqual(img.getpixel((1, 0)), (0xFC, 0xFC, 0xFC, 255))
            data = json.loads((out_dir / "sprites-manifest.json").read_text())
            self.assertEqual(data["chr_bank"], 2)
            self.assertEqual(data["chr_source"], "rom")
            self.assertFalse(data["chr_ram"])
            self.assertEqual(data["snapshot"], "in-process")

    def test_in_process_runtime_export_runs_mapper70_bandai_and_uses_selected_chr_bank(self):
        with tempfile.TemporaryDirectory() as td:
            rom_path = Path(td) / "runtime-mapper70.nes"
            rom_path.write_bytes(_runtime_mapper70_sprite_test_rom())
            out_dir = Path(td) / "auto-mapper70"

            manifest = export_in_process_runtime_sprites(rom_path, out_dir, frames=1)

            self.assertEqual(manifest.chr_bank, 5)
            sprite = out_dir / "oam" / "sprite-00-tile-00-pal0.png"
            img = Image.open(sprite).convert("RGBA")
            self.assertEqual(img.getpixel((0, 0))[3], 0)
            self.assertEqual(img.getpixel((1, 0)), (0xFC, 0xFC, 0xFC, 255))
            data = json.loads((out_dir / "sprites-manifest.json").read_text())
            self.assertEqual(data["chr_bank"], 5)
            self.assertEqual(data["chr_source"], "rom")
            self.assertFalse(data["chr_ram"])
            self.assertEqual(data["snapshot"], "in-process")

    def test_in_process_runtime_export_runs_mapper71_camerica(self):
        with tempfile.TemporaryDirectory() as td:
            rom_path = Path(td) / "runtime-mapper71.nes"
            rom_path.write_bytes(_runtime_mapper71_sprite_test_rom())
            out_dir = Path(td) / "auto-mapper71"

            manifest = export_in_process_runtime_sprites(rom_path, out_dir, frames=1)

            self.assertEqual(manifest.chr_bank, 0)
            sprite = out_dir / "oam" / "sprite-00-tile-00-pal0.png"
            img = Image.open(sprite).convert("RGBA")
            self.assertEqual(img.getpixel((0, 0))[3], 0)
            self.assertEqual(img.getpixel((1, 0)), (0xFC, 0xFC, 0xFC, 255))
            data = json.loads((out_dir / "sprites-manifest.json").read_text())
            self.assertEqual(data["chr_source"], "rom")
            self.assertEqual(data["snapshot"], "in-process")

    def test_in_process_runtime_export_runs_mapper72_jf17_and_uses_selected_chr_bank(self):
        with tempfile.TemporaryDirectory() as td:
            rom_path = Path(td) / "runtime-mapper72.nes"
            rom_path.write_bytes(_runtime_mapper72_sprite_test_rom())
            out_dir = Path(td) / "auto-mapper72"

            manifest = export_in_process_runtime_sprites(rom_path, out_dir, frames=1)

            self.assertEqual(manifest.chr_bank, 3)
            sprite = out_dir / "oam" / "sprite-00-tile-00-pal0.png"
            img = Image.open(sprite).convert("RGBA")
            self.assertEqual(img.getpixel((0, 0))[3], 0)
            self.assertEqual(img.getpixel((1, 0)), (0xFC, 0xFC, 0xFC, 255))
            data = json.loads((out_dir / "sprites-manifest.json").read_text())
            self.assertEqual(data["chr_bank"], 3)
            self.assertEqual(data["chr_source"], "rom")
            self.assertFalse(data["chr_ram"])
            self.assertEqual(data["snapshot"], "in-process")

    def test_in_process_runtime_export_runs_mapper75_vrc1_and_uses_4k_chr_window(self):
        with tempfile.TemporaryDirectory() as td:
            rom_path = Path(td) / "runtime-mapper75.nes"
            rom_path.write_bytes(_runtime_mapper75_sprite_test_rom())
            out_dir = Path(td) / "auto-mapper75"

            manifest = export_in_process_runtime_sprites(rom_path, out_dir, frames=1)

            self.assertEqual(manifest.n_tiles, 1)
            sprite = out_dir / "oam" / "sprite-00-tile-00-pal0.png"
            img = Image.open(sprite).convert("RGBA")
            self.assertEqual(img.getpixel((0, 0))[3], 0)
            self.assertEqual(img.getpixel((1, 0)), (0xFC, 0xFC, 0xFC, 255))
            data = json.loads((out_dir / "sprites-manifest.json").read_text())
            self.assertEqual(data["chr_source"], "snapshot")
            self.assertEqual(data["snapshot"], "in-process")
            self.assertEqual(data["sprites"][0]["palette_ppu"], ["0x0F", "0x30", "0x16", "0x27"])

    def test_in_process_runtime_export_runs_mapper79_nina0306_and_uses_selected_chr_bank(self):
        with tempfile.TemporaryDirectory() as td:
            rom_path = Path(td) / "runtime-mapper79.nes"
            rom_path.write_bytes(_runtime_mapper79_sprite_test_rom())
            out_dir = Path(td) / "auto-mapper79"

            manifest = export_in_process_runtime_sprites(rom_path, out_dir, frames=1)

            self.assertEqual(manifest.chr_bank, 5)
            sprite = out_dir / "oam" / "sprite-00-tile-00-pal0.png"
            img = Image.open(sprite).convert("RGBA")
            self.assertEqual(img.getpixel((0, 0))[3], 0)
            self.assertEqual(img.getpixel((1, 0)), (0xFC, 0xFC, 0xFC, 255))
            data = json.loads((out_dir / "sprites-manifest.json").read_text())
            self.assertEqual(data["chr_bank"], 5)
            self.assertEqual(data["chr_source"], "rom")
            self.assertFalse(data["chr_ram"])
            self.assertEqual(data["snapshot"], "in-process")

    def test_in_process_runtime_export_runs_mapper78_and_uses_selected_chr_bank(self):
        with tempfile.TemporaryDirectory() as td:
            rom_path = Path(td) / "runtime-mapper78.nes"
            rom_path.write_bytes(_runtime_mapper78_sprite_test_rom())
            out_dir = Path(td) / "auto-mapper78"

            manifest = export_in_process_runtime_sprites(rom_path, out_dir, frames=1)

            self.assertEqual(manifest.chr_bank, 5)
            sprite = out_dir / "oam" / "sprite-00-tile-00-pal0.png"
            img = Image.open(sprite).convert("RGBA")
            self.assertEqual(img.getpixel((0, 0))[3], 0)
            self.assertEqual(img.getpixel((1, 0)), (0xFC, 0xFC, 0xFC, 255))
            data = json.loads((out_dir / "sprites-manifest.json").read_text())
            self.assertEqual(data["chr_bank"], 5)
            self.assertEqual(data["chr_source"], "rom")
            self.assertFalse(data["chr_ram"])
            self.assertEqual(data["snapshot"], "in-process")

    def test_in_process_runtime_export_runs_mapper87_j87_and_uses_swapped_chr_bits(self):
        with tempfile.TemporaryDirectory() as td:
            rom_path = Path(td) / "runtime-mapper87.nes"
            rom_path.write_bytes(_runtime_mapper87_sprite_test_rom())
            out_dir = Path(td) / "auto-mapper87"

            manifest = export_in_process_runtime_sprites(rom_path, out_dir, frames=1)

            self.assertEqual(manifest.chr_bank, 2)
            sprite = out_dir / "oam" / "sprite-00-tile-00-pal0.png"
            img = Image.open(sprite).convert("RGBA")
            self.assertEqual(img.getpixel((0, 0))[3], 0)
            self.assertEqual(img.getpixel((1, 0)), (0xFC, 0xFC, 0xFC, 255))
            data = json.loads((out_dir / "sprites-manifest.json").read_text())
            self.assertEqual(data["chr_bank"], 2)
            self.assertEqual(data["chr_source"], "rom")
            self.assertFalse(data["chr_ram"])
            self.assertEqual(data["snapshot"], "in-process")

    def test_in_process_runtime_export_runs_mapper101_jf10_and_uses_normal_chr_bits(self):
        with tempfile.TemporaryDirectory() as td:
            rom_path = Path(td) / "runtime-mapper101.nes"
            rom_path.write_bytes(_runtime_mapper101_sprite_test_rom())
            out_dir = Path(td) / "auto-mapper101"

            manifest = export_in_process_runtime_sprites(rom_path, out_dir, frames=1)

            self.assertEqual(manifest.chr_bank, 1)
            sprite = out_dir / "oam" / "sprite-00-tile-00-pal0.png"
            img = Image.open(sprite).convert("RGBA")
            self.assertEqual(img.getpixel((0, 0))[3], 0)
            self.assertEqual(img.getpixel((1, 0)), (0xFC, 0xFC, 0xFC, 255))
            data = json.loads((out_dir / "sprites-manifest.json").read_text())
            self.assertEqual(data["chr_bank"], 1)
            self.assertEqual(data["chr_source"], "rom")
            self.assertFalse(data["chr_ram"])
            self.assertEqual(data["snapshot"], "in-process")

    def test_runtime_snapshot_exports_oam_sprites_with_original_palette(self):
        with tempfile.TemporaryDirectory() as td:
            rom_path = Path(td) / "sprite.nes"
            rom_path.write_bytes(_sprite_test_rom())
            snapshot_path = Path(td) / "snapshot.json"
            palette_ram = [0x0F] * 32
            palette_ram[0x18:0x1C] = [0x0F, 0x30, 0x16, 0x27]
            oam = [0xF8, 0, 0, 0] * 64
            # Sprite 0 visible, tile $00, palette 2, x=12, y raw=20.
            oam[0:4] = [20, 0x00, 0x02, 12]
            snapshot_path.write_text(
                json.dumps(
                    {
                        "frame": 123,
                        "ppuctrl": "0x08",
                        "ppumask": "0x1E",
                        "palette_ram": palette_ram,
                        "oam": oam,
                    }
                )
            )
            out_dir = Path(td) / "runtime"

            manifest = export_runtime_oam_sprites(rom_path, snapshot_path, out_dir)

            self.assertEqual(manifest.palette_source, "runtime-snapshot")
            self.assertEqual(manifest.n_tiles, 1)
            self.assertTrue((out_dir / "oam" / "sprite-00-tile-00-pal2.png").exists())
            img = Image.open(out_dir / "oam" / "sprite-00-tile-00-pal2.png").convert("RGBA")
            self.assertEqual(img.getpixel((0, 0))[3], 0)
            self.assertEqual(img.getpixel((1, 0)), (0xFC, 0xFC, 0xFC, 255))

            data = json.loads((out_dir / "sprites-manifest.json").read_text())
            self.assertEqual(data["kind"], "runtime_oam_sprite_export")
            self.assertEqual(data["palette_source"], "runtime-snapshot")
            self.assertEqual(data["screen_png"], str(out_dir / "oam-screen.png"))
            self.assertEqual(data["sprites"][0]["attr"], "0x02")
            self.assertFalse(data["sprites"][0]["flip_h"])
            self.assertFalse(data["sprites"][0]["flip_v"])
            self.assertEqual(data["sprites"][0]["x"], 12)
            self.assertEqual(data["sprites"][0]["y"], 21)

    def test_runtime_snapshot_exports_8x16_oam_sprite_with_flips(self):
        with tempfile.TemporaryDirectory() as td:
            rom_path = Path(td) / "sprite.nes"
            rom_path.write_bytes(_sprite_test_rom())
            snapshot_path = Path(td) / "snapshot-8x16-flip.json"
            palette_ram = [0x0F] * 32
            palette_ram[0x10:0x14] = [0x0F, 0x30, 0x16, 0x27]
            oam = [0xF8, 0, 0, 0] * 64
            # Sprite 0 visible, 8x16 tile pair from pattern table 1, H+V flips.
            oam[0:4] = [20, 0x01, 0xC0, 12]
            chr_data = [0] * 0x2000
            top_rows = [[1, 0, 0, 0, 0, 0, 0, 0] for _ in range(8)]
            bottom_rows = [[2, 0, 0, 0, 0, 0, 0, 0] for _ in range(8)]
            chr_data[0x1000 : 0x1010] = list(_encode_tile(top_rows))
            chr_data[0x1010 : 0x1020] = list(_encode_tile(bottom_rows))
            snapshot_path.write_text(
                json.dumps(
                    {
                        "ppuctrl": "0x20",
                        "ppumask": "0x1E",
                        "palette_ram": palette_ram,
                        "oam": oam,
                        "chr_data": chr_data,
                    }
                )
            )
            out_dir = Path(td) / "runtime"

            manifest = export_runtime_oam_sprites(rom_path, snapshot_path, out_dir)

            self.assertEqual(manifest.sprite_height, 16)
            img = Image.open(out_dir / "oam" / "sprite-00-tile-01-pal0.png").convert("RGBA")
            self.assertEqual(img.size, (8, 16))
            self.assertEqual(img.getpixel((0, 0))[3], 0)
            self.assertEqual(img.getpixel((7, 0)), (0xF8, 0x38, 0x00, 255))
            self.assertEqual(img.getpixel((7, 8)), (0xFC, 0xFC, 0xFC, 255))
            screen = Image.open(out_dir / "oam-screen.png").convert("RGBA")
            self.assertEqual(screen.getpixel((12, 21))[3], 0)
            self.assertEqual(screen.getpixel((19, 21)), (0xF8, 0x38, 0x00, 255))
            data = json.loads((out_dir / "sprites-manifest.json").read_text())
            self.assertEqual(data["sprite_height"], 16)
            self.assertTrue(data["sprites"][0]["flip_h"])
            self.assertTrue(data["sprites"][0]["flip_v"])
            self.assertEqual(data["sprites"][0]["height"], 16)

    def test_runtime_snapshot_can_supply_chr_data_for_chr_ram_rom(self):
        with tempfile.TemporaryDirectory() as td:
            rom_path = Path(td) / "chr-ram.nes"
            rom_path.write_bytes(ines_header(1, 0, 0) + bytes([0xEA] * PRG_BANK))
            snapshot_path = Path(td) / "snapshot.json"
            palette_ram = [0x0F] * 32
            palette_ram[0x10:0x14] = [0x0F, 0x30, 0x16, 0x27]
            oam = [0xF8, 0, 0, 0] * 64
            oam[0:4] = [20, 0x00, 0x00, 12]
            chr_data = [0] * 0x2000
            rows = [[0, 1, 2, 3, 0, 1, 2, 3] for _ in range(8)]
            tile = _encode_tile(rows)
            chr_data[0x1000 : 0x1010] = list(tile)
            snapshot_path.write_text(
                json.dumps(
                    {
                        "ppuctrl": "0x08",
                        "palette_ram": palette_ram,
                        "oam": oam,
                        "chr_data": chr_data,
                    }
                )
            )
            out_dir = Path(td) / "runtime"

            manifest = export_runtime_oam_sprites(rom_path, snapshot_path, out_dir)

            self.assertEqual(manifest.n_tiles, 1)
            img = Image.open(out_dir / "oam" / "sprite-00-tile-00-pal0.png").convert("RGBA")
            self.assertEqual(img.getpixel((0, 0))[3], 0)
            self.assertEqual(img.getpixel((1, 0)), (0xFC, 0xFC, 0xFC, 255))
            data = json.loads((out_dir / "sprites-manifest.json").read_text())
            self.assertEqual(data["chr_source"], "snapshot")

    def test_load_runtime_snapshot_requires_complete_oam(self):
        with tempfile.TemporaryDirectory() as td:
            snapshot = Path(td) / "bad.json"
            snapshot.write_text(json.dumps({"oam": [], "palette_ram": [0] * 32, "ppuctrl": 0}))
            with self.assertRaises(ValueError):
                load_runtime_sprite_snapshot(snapshot)


if __name__ == "__main__":
    unittest.main()
