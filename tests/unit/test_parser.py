import unittest

import tests.test_setup  # noqa: F401  (déclenche l'ajout au sys.path)
from qlnes.parser import Disasm

SAMPLE = """L_8000: SEI                      ;JMP Entry ..........
L_8001  CLD
L_8002  LDA  #0x03
L_8004  STA  L_2005
L_8007  LDA  L_4016
L_800A  JMP  L_8000
L_800D: DB  0x01,0x02,0x03                              ; ...
"""


class TestParserBasic(unittest.TestCase):
    def setUp(self):
        self.d = Disasm(SAMPLE)

    def test_parses_all_lines(self):
        self.assertEqual(len(self.d.lines), 7)

    def test_address_extracted(self):
        self.assertEqual(
            [ln.addr for ln in self.d.lines],
            [0x8000, 0x8001, 0x8002, 0x8004, 0x8007, 0x800A, 0x800D],
        )

    def test_label_marker(self):
        self.assertEqual(
            [ln.is_label for ln in self.d.lines],
            [True, False, False, False, False, False, True],
        )

    def test_mnemonic_parsing(self):
        self.assertEqual(
            [ln.mnemonic for ln in self.d.lines],
            ["SEI", "CLD", "LDA", "STA", "LDA", "JMP", "DB"],
        )

    def test_data_marker(self):
        self.assertEqual(
            [ln.is_data for ln in self.d.lines],
            [False, False, False, False, False, False, True],
        )

    def test_refs_extracted(self):
        self.assertIn(0x8000, self.d.find(0x800A).refs)
        self.assertIn(0x2005, self.d.find(0x8004).refs)

    def test_referenced_addrs_set(self):
        refs = self.d.referenced_addrs
        self.assertIn(0x2005, refs)
        self.assertIn(0x4016, refs)
        self.assertIn(0x8000, refs)

    def test_code_vs_data_lines(self):
        self.assertEqual(len(self.d.code_lines()), 6)
        self.assertEqual(len(self.d.data_lines()), 1)

    def test_comment_extracted(self):
        self.assertIn("JMP Entry", self.d.find(0x8000).comment)


class TestParserEdgeCases(unittest.TestCase):
    def test_empty_input(self):
        self.assertEqual(len(Disasm("").lines), 0)

    def test_blank_lines_skipped(self):
        self.assertEqual(len(Disasm("\n\nL_8000: NOP\n\n").lines), 1)

    def test_unparseable_line_kept(self):
        d = Disasm("garbage at start\nL_8000: NOP\n")
        self.assertEqual(len(d.lines), 2)
        self.assertEqual(d.lines[0].addr, -1)


if __name__ == "__main__":
    unittest.main()
