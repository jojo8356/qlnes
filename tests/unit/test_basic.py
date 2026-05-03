import unittest

from qlnes import Disasm, annotate
from qlnes.ines import INES_MAGIC, parse_header, strip_ines
from qlnes.nes_hw import oam_name
from tests.test_setup import disassemble, simple_image


class TestQL6502(unittest.TestCase):
    def test_disassemble_simple(self):
        asm = disassemble(simple_image())
        self.assertIn("L_8000", asm)
        self.assertIn("LDA", asm)

    def test_parser_extracts_refs(self):
        d = Disasm(disassemble(simple_image()))
        self.assertIn(0x2002, d.referenced_addrs)
        self.assertIn(0x2005, d.referenced_addrs)
        self.assertIn(0x4016, d.referenced_addrs)
        self.assertIn(0x8000, d.referenced_addrs)


class TestAnnotate(unittest.TestCase):
    def test_hardware_register_renaming(self):
        img = simple_image()
        annotated, report = annotate(disassemble(img), image=img)
        self.assertIn("PPUSTATUS", annotated)
        self.assertIn("PPUSCROLL", annotated)
        self.assertIn("JOY1", annotated)
        self.assertEqual(report.hardware[0x2002], "PPUSTATUS")
        self.assertEqual(report.hardware[0x4016], "JOY1")


class TestNesHardware(unittest.TestCase):
    def test_oam_naming(self):
        self.assertEqual(oam_name(0x0200), "sprite_0_y")
        self.assertEqual(oam_name(0x0203), "sprite_0_x")
        self.assertEqual(oam_name(0x0204), "sprite_1_y")
        self.assertEqual(oam_name(0x02FF), "sprite_63_x")

    def test_oam_out_of_range(self):
        with self.assertRaises(ValueError):
            oam_name(0x0300)


class TestINes(unittest.TestCase):
    def test_parse_header_no_magic(self):
        self.assertIsNone(parse_header(b"hello world"))

    def test_parse_valid_nrom_header(self):
        header = INES_MAGIC + bytes([2, 1, 0, 0]) + bytes(8)
        h = parse_header(header)
        self.assertIsNotNone(h)
        self.assertEqual(h.prg_banks, 2)
        self.assertEqual(h.prg_size, 0x8000)
        self.assertEqual(h.mapper, 0)

    def test_strip_ines(self):
        header = INES_MAGIC + bytes([1, 0, 0, 0]) + bytes(8)
        prg = bytes([0xEA] * 0x4000)
        rom = header + prg
        self.assertEqual(strip_ines(rom), prg)


if __name__ == "__main__":
    unittest.main()
