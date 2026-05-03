import shutil
import tempfile
import unittest
from pathlib import Path

from qlnes.asm_text import (
    db_line_to_text,
    find_ascii_runs,
    parse_db_line,
    rewrite_db_strings,
)
from tests.test_setup import NESTEST_PATH


class TestParseDbLine(unittest.TestCase):
    def test_parse_simple(self):
        line = "L_8038: DB  0x52,0x75,0x6E    ; Run"
        parsed = parse_db_line(line)
        self.assertIsNotNone(parsed)
        _lead, mn, bytes_list, trail = parsed
        self.assertEqual(mn, "DB")
        self.assertEqual(bytes_list, [0x52, 0x75, 0x6E])
        self.assertIn("Run", trail)

    def test_parse_no_comment(self):
        parsed = parse_db_line("L_8000: DB  0x00")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed[2], [0x00])

    def test_returns_none_on_non_db(self):
        self.assertIsNone(parse_db_line("L_8000  LDA  0x10"))

    def test_returns_none_on_invalid_hex(self):
        self.assertIsNone(parse_db_line("L_8000: DB  not_a_byte"))


class TestFindAsciiRuns(unittest.TestCase):
    def test_finds_simple_run(self):
        bytes_ = [*list(b"Hello"), 0]
        runs = find_ascii_runs(bytes_, min_len=4)
        self.assertEqual(runs, [(0, 5)])

    def test_skips_short_run(self):
        bytes_ = list(b"Hi") + [0] * 5
        self.assertEqual(find_ascii_runs(bytes_, min_len=4), [])

    def test_multiple_runs_separated_by_zeros(self):
        bytes_ = [*list(b"Hello"), 0, *list(b"World")]
        runs = find_ascii_runs(bytes_, min_len=4)
        self.assertEqual(runs, [(0, 5), (6, 11)])

    def test_high_bytes_excluded(self):
        bytes_ = [128, 129, *list(b"Test"), 255]
        runs = find_ascii_runs(bytes_, min_len=4)
        self.assertEqual(runs, [(2, 6)])


class TestDbLineToText(unittest.TestCase):
    def test_full_string_replaced(self):
        line = "L_C700: DB  0x52,0x75,0x6E,0x20,0x61,0x6C,0x6C    ; Run all"
        new = db_line_to_text(line)
        self.assertIn('"Run all"', new)
        self.assertIn(".byte", new)

    def test_mixed_content(self):
        line = "L_C700: DB  0x00,0x52,0x75,0x6E,0x6E,0xFF    ; .Runn."
        new = db_line_to_text(line)
        self.assertIn('"Runn"', new)
        self.assertIn("0x00", new)
        self.assertIn("0xFF", new)

    def test_no_change_if_no_string(self):
        line = "L_8000: DB  0x00,0x00,0x00,0x00,0x00,0x00    ; ......"
        self.assertEqual(db_line_to_text(line), line)

    def test_preserves_label(self):
        line = "L_C700: DB  0x41,0x42,0x43,0x44"
        new = db_line_to_text(line)
        self.assertTrue(new.startswith("L_C700:"))

    def test_preserves_bytes_byte_for_byte(self):
        line = "L_C700: DB  0x00,0x52,0x75,0x6E,0x6E,0x6F,0xFF"
        new = db_line_to_text(line)
        # Reparse the new line: extract bytes from .byte directive
        # "Runno" should give 5 bytes (R, u, n, n, o)
        # And we should have 0x00 before, 0xFF after
        self.assertIn("0x00", new)
        self.assertIn("0xFF", new)
        self.assertIn('"Runno"', new)


class TestRewriteDbStrings(unittest.TestCase):
    def test_rewrites_all_lines(self):
        asm = (
            "L_C700: DB  0x52,0x75,0x6E,0x20,0x61,0x6C,0x6C    ; Run all\n"
            "L_C708: LDA  0x10\n"
            "L_C70A: DB  0x42,0x72,0x61,0x6E,0x63,0x68    ; Branch\n"
        )
        out = rewrite_db_strings(asm)
        self.assertIn('"Run all"', out)
        self.assertIn('"Branch"', out)
        self.assertIn("LDA  0x10", out)

    def test_preserves_trailing_newline(self):
        asm = "L_8000: DB  0x41,0x42,0x43,0x44\n"
        out = rewrite_db_strings(asm)
        self.assertTrue(out.endswith("\n"))

    def test_empty_input(self):
        self.assertEqual(rewrite_db_strings(""), "")


class TestNestestStringsExtracted(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="qlnes_strings_")
        self.tmp_path = Path(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_nestest_menu_strings_visible(self):
        from qlnes.cli import main

        rom_copy = self.tmp_path / "nestest.nes"
        shutil.copy(NESTEST_PATH, rom_copy)
        asm_path = self.tmp_path / "out.asm"
        rc = main(
            [
                "analyze",
                str(rom_copy),
                "--output",
                str(self.tmp_path / "STACK.md"),
                "--asm",
                str(asm_path),
                "--no-dynamic",
                "--quiet",
            ]
        )
        self.assertEqual(rc, 0)
        content = asm_path.read_text(encoding="utf-8")
        self.assertIn("Run al", content)
        self.assertIn("Branch", content)
        self.assertIn("Flag", content)
        self.assertIn("0123456", content)


class TestCliChrIncludeLink(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="qlnes_link_")
        self.tmp_path = Path(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_main_asm_includes_chr_when_assets(self):
        from qlnes.cli import main

        rom_copy = self.tmp_path / "nestest.nes"
        shutil.copy(NESTEST_PATH, rom_copy)
        asm_path = self.tmp_path / "out.asm"
        rc = main(
            [
                "analyze",
                str(rom_copy),
                "--output",
                str(self.tmp_path / "STACK.md"),
                "--asm",
                str(asm_path),
                "--assets",
                "auto",
                "--no-dynamic",
                "--quiet",
            ]
        )
        self.assertEqual(rc, 0)
        content = asm_path.read_text(encoding="utf-8")
        self.assertIn(".incbin", content)
        self.assertIn("chr_rom.chr", content)
        self.assertIn('.segment "CHR"', content)

    def test_main_asm_no_include_without_assets(self):
        from qlnes.cli import main

        rom_copy = self.tmp_path / "nestest.nes"
        shutil.copy(NESTEST_PATH, rom_copy)
        asm_path = self.tmp_path / "out.asm"
        rc = main(
            [
                "analyze",
                str(rom_copy),
                "--output",
                str(self.tmp_path / "STACK.md"),
                "--asm",
                str(asm_path),
                "--no-dynamic",
                "--quiet",
            ]
        )
        self.assertEqual(rc, 0)
        content = asm_path.read_text(encoding="utf-8")
        self.assertNotIn(".incbin", content)


if __name__ == "__main__":
    unittest.main()
