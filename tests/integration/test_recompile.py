import shutil
import tempfile
import unittest
from pathlib import Path

from qlnes import QL6502, Rom, RomProfile, annotate
from qlnes.recompile import (
    Recompiler,
    compare_roms,
    fast_equal,
    hash_rom,
    recompile_asm,
    verify_round_trip,
)
from tests.test_setup import NESTEST_PATH


class TestCompareRoms(unittest.TestCase):
    def test_equal_roms(self):
        a = b"\x01\x02\x03"
        b = b"\x01\x02\x03"
        d = compare_roms(a, b)
        self.assertTrue(d.equal)
        self.assertEqual(d.diff_bytes, 0)
        self.assertIsNone(d.first_diff_offset)

    def test_size_mismatch(self):
        d = compare_roms(b"\x00\x00", b"\x00\x00\x00")
        self.assertFalse(d.equal)
        self.assertFalse(d.sizes_match)

    def test_byte_difference_detected(self):
        d = compare_roms(b"\x01\x02\x03", b"\x01\x99\x03")
        self.assertFalse(d.equal)
        self.assertEqual(d.diff_bytes, 1)
        self.assertEqual(d.first_diff_offset, 1)

    def test_sha256_set_when_equal(self):
        d = compare_roms(b"hello world", b"hello world")
        self.assertTrue(d.equal)
        self.assertEqual(d.original_sha256, d.recompiled_sha256)
        self.assertEqual(len(d.original_sha256), 64)

    def test_hashes_differ_when_unequal(self):
        d = compare_roms(b"hello", b"world")
        self.assertNotEqual(d.original_sha256, d.recompiled_sha256)
        self.assertFalse(d.hashes_match)


class TestHashAndFastEqual(unittest.TestCase):
    def test_hash_rom_sha256(self):
        h = hash_rom(b"abc")
        # Known sha256 of "abc"
        self.assertEqual(h, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")

    def test_hash_rom_md5(self):
        h = hash_rom(b"abc", algorithm="md5")
        self.assertEqual(h, "900150983cd24fb0d6963f7d28e17f72")

    def test_fast_equal_size_mismatch(self):
        self.assertFalse(fast_equal(b"abc", b"abcd"))

    def test_fast_equal_identical(self):
        self.assertTrue(fast_equal(b"hello world", b"hello world"))

    def test_fast_equal_different(self):
        self.assertFalse(fast_equal(b"hello", b"world"))


class TestComparePerformance(unittest.TestCase):
    def test_1mb_compare_under_10ms(self):
        import os
        import time

        rom = os.urandom(1024 * 1024)
        t0 = time.perf_counter()
        diff = compare_roms(rom, rom)
        elapsed = time.perf_counter() - t0
        self.assertTrue(diff.equal)
        self.assertLess(
            elapsed,
            0.050,
            f"compare_roms on 1MB took {elapsed * 1000:.1f}ms",
        )


class TestRecompileAsm(unittest.TestCase):
    def test_simple_program(self):
        asm = "L_8000: SEI\nL_8001  CLD\nL_8002  LDX  #0xFF\nL_8004  TXS\nL_8005  JMP  L_8000\n"
        image, errors = recompile_asm(asm)
        self.assertEqual(errors, [])
        self.assertEqual(image[0x8000], 0x78)
        self.assertEqual(image[0x8001], 0xD8)
        self.assertEqual(image[0x8002:0x8004], bytes([0xA2, 0xFF]))
        self.assertEqual(image[0x8004], 0x9A)
        self.assertEqual(image[0x8005:0x8008], bytes([0x4C, 0x00, 0x80]))

    def test_db_directives(self):
        asm = "L_8000: DB  0xDE,0xAD,0xBE,0xEF\n"
        image, _ = recompile_asm(asm)
        self.assertEqual(image[0x8000:0x8004], bytes([0xDE, 0xAD, 0xBE, 0xEF]))

    def test_byte_directive_with_string(self):
        asm = 'L_C000: .byte  "Hello",0x00\n'
        image, _ = recompile_asm(asm)
        self.assertEqual(image[0xC000:0xC006], b"Hello\x00")

    def test_branches(self):
        asm = "L_8000: LDA  #0x00\nL_8002  BNE  L_8000\nL_8004: BEQ  L_8000\n"
        image, errors = recompile_asm(asm)
        self.assertEqual(errors, [])
        self.assertEqual(image[0x8002:0x8004], bytes([0xD0, 0xFC]))
        self.assertEqual(image[0x8004:0x8006], bytes([0xF0, 0xFA]))


class TestRecompilerWithNames(unittest.TestCase):
    def test_resolves_named_constants(self):
        asm = "L_C000: STA  PPUCTRL\n"
        rec = Recompiler(names_to_addr={"PPUCTRL": 0x2000})
        from qlnes.parser import Disasm

        d = Disasm(asm)
        out = rec.encode_line(d.lines[0])
        self.assertEqual(out, bytes([0x8D, 0x00, 0x20]))

    def test_unknown_name_records_error(self):
        asm = "L_C000: STA  UNKNOWN_REG\n"
        rec = Recompiler()
        from qlnes.parser import Disasm

        d = Disasm(asm)
        out = rec.encode_line(d.lines[0])
        self.assertIsNone(out)
        self.assertEqual(len(rec.errors), 1)


class TestNestestRoundTrip(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rom_bytes = NESTEST_PATH.read_bytes()
        cls.rom = Rom.from_file(NESTEST_PATH)
        cls.image = cls.rom.single_image()
        cls.raw_asm = QL6502().load_image(cls.image).mark_blank(0x0000, 0x7FFF).generate_asm()
        cls.annotated, cls.report = annotate(cls.raw_asm, image=cls.image)

    def test_raw_asm_round_trip(self):
        diff, errors = verify_round_trip(self.raw_asm, NESTEST_PATH)
        self.assertTrue(diff.equal, f"diff: {diff.summary()}")
        self.assertEqual(errors, [])

    def test_annotated_asm_round_trip_with_names(self):
        names_to_addr = {}
        for d in (
            self.report.hardware,
            self.report.oam,
            self.report.dataflow,
            self.report.fallback,
            self.report.subroutines,
        ):
            for addr, name in d.items():
                names_to_addr.setdefault(name, addr)
        diff, errors = verify_round_trip(self.annotated, NESTEST_PATH, names_to_addr=names_to_addr)
        self.assertTrue(diff.equal, f"diff: {diff.summary()}")
        self.assertEqual(len(errors), 0)


class TestRomProfileRecompile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rom = Rom.from_file(NESTEST_PATH)
        cls.profile = RomProfile.from_rom(cls.rom).analyze_static()

    def test_verify_round_trip_method(self):
        diff = self.profile.verify_round_trip()
        self.assertTrue(diff.equal)
        self.assertEqual(diff.original_size, diff.recompiled_size)

    def test_recompile_method(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "rec.nes"
            self.profile.recompile(out)
            self.assertTrue(out.exists())
            self.assertEqual(out.read_bytes(), NESTEST_PATH.read_bytes())


class TestCliRecompileVerify(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="qlnes_recompile_")
        self.tmp_path = Path(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_cli_recompile(self):
        from qlnes.cli import main

        out = self.tmp_path / "out.nes"
        rc = main(
            [
                "recompile",
                str(NESTEST_PATH),
                "-o",
                str(out),
                "--quiet",
            ]
        )
        self.assertEqual(rc, 0)
        self.assertTrue(out.exists())
        self.assertEqual(out.read_bytes(), NESTEST_PATH.read_bytes())

    def test_cli_verify_round_trip(self):
        from qlnes.cli import main

        rc = main(["verify", str(NESTEST_PATH), "--quiet"])
        self.assertEqual(rc, 0)

    def test_cli_verify_two_roms(self):
        from qlnes.cli import main

        copy = self.tmp_path / "copy.nes"
        shutil.copy(NESTEST_PATH, copy)
        rc = main(["verify", str(NESTEST_PATH), str(copy), "--quiet"])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
