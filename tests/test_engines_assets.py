import os
import tempfile
import unittest
from pathlib import Path

from tests.test_setup import NESTEST_PATH, fake_rom
from qlnes import Rom
from qlnes.engines import (
    EngineHint,
    detect_copyright_year,
    detect_engines,
    detect_publisher_by_mapper,
    detect_publisher_by_strings,
    find_ascii_strings,
)
from qlnes.ines import parse_header
from qlnes.assets import decode_tile, extract_chr, write_chr_asm


class TestFindAsciiStrings(unittest.TestCase):
    def test_finds_simple_string(self):
        data = b"\x00\x00HELLO WORLD\x00\xFF"
        strings = find_ascii_strings(data, min_len=4)
        self.assertEqual(len(strings), 1)
        self.assertEqual(strings[0][1], "HELLO WORLD")

    def test_skips_short_strings(self):
        data = b"\x00abc\x00ABCDEF\x00"
        strings = find_ascii_strings(data, min_len=4)
        names = [s for _, s in strings]
        self.assertNotIn("abc", names)
        self.assertIn("ABCDEF", names)

    def test_offset_correct(self):
        data = b"\x00\x00\x00HELLO"
        strings = find_ascii_strings(data, min_len=4)
        self.assertEqual(strings[0][0], 3)


class TestPublisherByStrings(unittest.TestCase):
    def test_detects_konami(self):
        data = b"\x00\x00(C) 1989 KONAMI\x00\x00"
        hints = detect_publisher_by_strings(data)
        self.assertTrue(any(h.name == "Konami" for h in hints))

    def test_detects_capcom(self):
        data = b"\x00\xFFCAPCOM CO LTD 1990\x00"
        hints = detect_publisher_by_strings(data)
        self.assertTrue(any(h.name == "Capcom" for h in hints))

    def test_no_false_positive_on_random(self):
        data = b"\x00\xAA\xBB\xCC\xDD" * 100
        hints = detect_publisher_by_strings(data)
        self.assertEqual(hints, [])


class TestPublisherByMapper(unittest.TestCase):
    def test_konami_vrc6(self):
        h = parse_header(fake_rom(2, 24)[:16])
        hints = detect_publisher_by_mapper(h)
        self.assertEqual(len(hints), 1)
        self.assertIn("Konami", hints[0].name)

    def test_sunsoft_fme7(self):
        h = parse_header(fake_rom(2, 69)[:16])
        hints = detect_publisher_by_mapper(h)
        self.assertEqual(len(hints), 1)
        self.assertIn("Sunsoft", hints[0].name)

    def test_unknown_mapper_returns_empty(self):
        h = parse_header(fake_rom(2, 0)[:16])
        hints = detect_publisher_by_mapper(h)
        self.assertEqual(hints, [])


class TestCopyrightDetection(unittest.TestCase):
    def test_copyright_marker_found(self):
        data = b"\x00(C) 1988 SOMETHING\x00"
        cr = detect_copyright_year(data)
        self.assertIsNotNone(cr)
        self.assertIn("1988", cr[1])

    def test_returns_none_when_no_copyright(self):
        self.assertIsNone(detect_copyright_year(b"\x00\xFF\x00\xFF" * 100))


class TestDetectEnginesIntegration(unittest.TestCase):
    def test_combines_mapper_and_strings(self):
        rom = fake_rom(2, 24)
        # Inject a publisher string in the PRG area
        rom_b = bytearray(rom)
        msg = b"KONAMI 1990"
        rom_b[0x100 : 0x100 + len(msg)] = msg
        h = parse_header(bytes(rom_b)[:16])
        hints = detect_engines(bytes(rom_b), h)
        names = {h.name for h in hints}
        self.assertTrue(any("Konami" in n for n in names))


class TestDecodeTile(unittest.TestCase):
    def test_solid_color_3(self):
        tile = bytes([0xFF] * 16)
        rows = decode_tile(tile)
        for r in range(8):
            for c in range(8):
                self.assertEqual(rows[r][c], 3)

    def test_blank_tile_color_0(self):
        tile = bytes([0x00] * 16)
        rows = decode_tile(tile)
        for r in range(8):
            for c in range(8):
                self.assertEqual(rows[r][c], 0)

    def test_only_plane0_set_color_1(self):
        tile = bytes([0xFF] * 8 + [0x00] * 8)
        rows = decode_tile(tile)
        for r in range(8):
            for c in range(8):
                self.assertEqual(rows[r][c], 1)

    def test_only_plane1_set_color_2(self):
        tile = bytes([0x00] * 8 + [0xFF] * 8)
        rows = decode_tile(tile)
        for r in range(8):
            for c in range(8):
                self.assertEqual(rows[r][c], 2)

    def test_invalid_size_raises(self):
        with self.assertRaises(ValueError):
            decode_tile(bytes([0x00] * 15))


class TestChrAsmExtraction(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="qlnes_asm_")
        self.tmp_path = Path(self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp)

    def test_asm_contains_byte_directives(self):
        chr_data = bytes(range(256)) * 64
        out = self.tmp_path / "chr.asm"
        write_chr_asm(chr_data[:8192], out, rom_name="test")
        content = out.read_text()
        self.assertIn(".byte", content)
        self.assertIn("Pattern Table 0", content)
        self.assertIn("plane 0", content)
        self.assertIn("plane 1", content)

    def test_asm_includes_ascii_preview(self):
        tile = bytes([0xFF] * 16)
        chr_data = tile + b"\x00" * (8192 - 16)
        out = self.tmp_path / "chr.asm"
        write_chr_asm(chr_data, out)
        content = out.read_text()
        self.assertIn("█", content)

    def test_asm_byte_values_match_binary(self):
        chr_data = bytes(range(256)) * 32
        out = self.tmp_path / "chr.asm"
        write_chr_asm(chr_data, out, with_preview=False)
        content = out.read_text()
        recovered = bytearray()
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped.startswith(".byte"):
                continue
            parts = stripped.split(";", 1)[0]
            parts = parts.replace(".byte", "").strip()
            for tok in parts.split(","):
                tok = tok.strip()
                if tok.startswith("$"):
                    recovered.append(int(tok[1:], 16))
        self.assertEqual(bytes(recovered), chr_data)

    def test_asm_label_customizable(self):
        out = self.tmp_path / "chr.asm"
        write_chr_asm(b"\x00" * 16, out, bank_label="MY_TILES")
        self.assertIn("MY_TILES:", out.read_text())


class TestExtractChrOnNestest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="qlnes_assets_")
        self.tmp_path = Path(self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp)

    def test_extracts_chr_files(self):
        rom = Rom.from_file(NESTEST_PATH)
        manifest = extract_chr(rom, self.tmp_path)
        self.assertTrue(manifest.chr_raw.exists())
        self.assertEqual(manifest.chr_raw.stat().st_size, 8192)
        self.assertEqual(manifest.n_tiles, 512)
        self.assertTrue(manifest.chr_asm.exists())
        self.assertTrue(manifest.full_image.exists())
        self.assertTrue(manifest.bg_image.exists())
        self.assertTrue(manifest.spr_image.exists())

    def test_asm_roundtrip_matches_binary(self):
        rom = Rom.from_file(NESTEST_PATH)
        manifest = extract_chr(rom, self.tmp_path)
        binary = manifest.chr_raw.read_bytes()
        recovered = bytearray()
        for line in manifest.chr_asm.read_text().splitlines():
            stripped = line.strip()
            if not stripped.startswith(".byte"):
                continue
            parts = stripped.split(";", 1)[0]
            parts = parts.replace(".byte", "").strip()
            for tok in parts.split(","):
                tok = tok.strip()
                if tok.startswith("$"):
                    recovered.append(int(tok[1:], 16))
        self.assertEqual(bytes(recovered), binary)

    def test_no_chr_when_chr_ram(self):
        rom_bytes = bytearray(fake_rom(1, 0))
        rom_bytes[5] = 0
        rom = Rom(bytes(rom_bytes))
        manifest = extract_chr(rom, self.tmp_path)
        self.assertIsNone(manifest.chr_raw)
        self.assertIsNone(manifest.full_image)
        self.assertEqual(manifest.n_tiles, 0)
        self.assertGreaterEqual(len(manifest.notes), 1)


class TestProfileEnginesAssets(unittest.TestCase):
    def test_profile_includes_engine_hints_when_publisher_in_rom(self):
        rom_bytes = bytearray(fake_rom(2, 1))
        msg = b"KONAMI 1990"
        rom_bytes[16 + 0x100 : 16 + 0x100 + len(msg)] = msg
        from qlnes import RomProfile
        rom = Rom(bytes(rom_bytes), name="fakeKonami")
        profile = RomProfile.from_rom(rom).analyze_static()
        names = {h.name for h in profile.engine_hints}
        self.assertTrue(any("Konami" in n for n in names))
        md = profile.to_markdown()
        self.assertIn("## Éditeur", md)
        self.assertIn("Konami", md)

    def test_profile_extract_assets(self):
        with tempfile.TemporaryDirectory() as td:
            from qlnes import RomProfile
            rom = Rom.from_file(NESTEST_PATH)
            profile = RomProfile.from_rom(rom).analyze_static()
            manifest = profile.extract_assets(Path(td))
            self.assertEqual(manifest.n_tiles, 512)
            md = profile.to_markdown()
            self.assertIn("## Assets extraits", md)
            self.assertIn("chr_tiles", md)


class TestCLIAssets(unittest.TestCase):
    def test_cli_extracts_assets_to_default_dir(self):
        with tempfile.TemporaryDirectory() as td:
            import shutil
            tmp_rom = Path(td) / "nestest.nes"
            shutil.copy(NESTEST_PATH, tmp_rom)
            from qlnes.cli import main
            rc = main(["analyze", 
                str(tmp_rom),
                "--output", str(Path(td) / "STACK.md"),
                "--no-dynamic",
                "--assets", "auto",
                "--quiet",
            ])
            self.assertEqual(rc, 0)
            assets_dir = Path(td) / "assets" / "nestest"
            self.assertTrue(assets_dir.exists())
            self.assertTrue((assets_dir / "chr_rom.chr").exists())


if __name__ == "__main__":
    unittest.main()
