"""Helpers partagés par toute la suite de tests qlnes.

Pas de TestCase ici : ce module est importé en tête de chaque fichier de test
pour fournir le sys.path setup, des builders d'images 6502/NES factices,
et des raccourcis de pipeline (disassemble, annotate).
"""

import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from qlnes import Disasm, QL6502, Rom, annotate
from qlnes.ines import INES_MAGIC, PRG_BANK


FIXTURES_DIR = _ROOT / "tests" / "fixtures"
NESTEST_PATH = FIXTURES_DIR / "nestest.nes"

try:
    import cynes  # noqa: F401
    HAS_CYNES = True
except ImportError:
    HAS_CYNES = False


def write_temp_rom(rom_bytes: bytes) -> Path:
    fd, path = tempfile.mkstemp(suffix=".nes")
    import os
    with os.fdopen(fd, "wb") as f:
        f.write(rom_bytes)
    return Path(path)


def build_game_synth_rom_path(with_game_over: bool = False) -> Path:
    from tests.fixtures.game_synth import build_rom
    return write_temp_rom(build_rom(with_game_over=with_game_over))


def disassemble(image, blanks=((0x0000, 0x7FFF),), jump_tables=()):
    q = QL6502().load_image(image)
    for s, e in blanks:
        q.mark_blank(s, e)
    for s, e in jump_tables:
        q.add_jump_table(s, e)
    return q.generate_asm()


def disassemble_and_annotate(image, **kwargs):
    asm = disassemble(image, **kwargs)
    return annotate(asm, image=image)


def synth_disasm():
    from tests.fixtures.synth_rom import build_image

    img = build_image()
    asm = disassemble(img)
    return img, asm, Disasm(asm)


def synth_annotate():
    from tests.fixtures.synth_rom import build_image

    img = build_image()
    asm = disassemble(img)
    annotated, report = annotate(asm, image=img)
    return img, asm, annotated, report


def simple_image():
    image = bytearray(0x10000)
    code = bytes(
        [
            0xAD, 0x02, 0x20,
            0x8D, 0x05, 0x20,
            0xAD, 0x16, 0x40,
            0x4C, 0x00, 0x80,
        ]
    )
    image[0x8000 : 0x8000 + len(code)] = code
    image[0xFFFC] = 0x00
    image[0xFFFD] = 0x80
    return bytes(image)


def ines_header(prg_banks: int, chr_banks: int = 0, mapper: int = 0) -> bytes:
    flags6 = (mapper & 0x0F) << 4
    flags7 = mapper & 0xF0
    return INES_MAGIC + bytes([prg_banks, chr_banks, flags6, flags7]) + bytes(8)


def fake_rom(prg_banks: int, mapper: int) -> bytes:
    header = ines_header(prg_banks, 0, mapper)
    prg = bytearray()
    for i in range(prg_banks):
        bank = bytearray([0xEA] * PRG_BANK)
        bank[0] = i
        if i == prg_banks - 1:
            bank[PRG_BANK - 4] = 0x00
            bank[PRG_BANK - 3] = 0x80
            bank[PRG_BANK - 6] = 0x00
            bank[PRG_BANK - 5] = 0x80
        prg.extend(bank)
    return header + bytes(prg)
