import os
import tempfile
import unittest
from pathlib import Path

from qlnes import Rom, RomProfile
from tests.test_setup import (
    HAS_CYNES,
    NESTEST_PATH,
    build_game_synth_rom_path,
    fake_rom,
)


class TestRomProfileStatic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rom = Rom.from_file(NESTEST_PATH)
        cls.profile = RomProfile.from_rom(cls.rom).analyze_static()

    def test_header_extracted(self):
        self.assertIsNotNone(self.profile.header)
        self.assertEqual(self.profile.header.mapper, 0)

    def test_vectors_present(self):
        names = {v.name for v in self.profile.vectors}
        self.assertEqual(names, {"NMI", "RESET", "IRQ"})

    def test_reset_vector_correct(self):
        reset = next(v for v in self.profile.vectors if v.name == "RESET")
        self.assertEqual(reset.addr, 0xC004)

    def test_static_report_present(self):
        self.assertIsNotNone(self.profile.static_report)
        self.assertGreater(len(self.profile.static_report.hardware), 0)

    def test_hardware_detection_nmi(self):
        self.assertTrue(self.profile.hardware.nmi_enabled)

    def test_hardware_detection_controller1(self):
        self.assertTrue(self.profile.hardware.controller1_read)

    def test_hardware_detection_palette(self):
        self.assertTrue(self.profile.hardware.palette_writes)

    def test_indirect_jumps_counted(self):
        self.assertGreater(self.profile.indirect_jumps, 0)


class TestRomProfileSynth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rom_path = build_game_synth_rom_path(with_game_over=False)
        cls.profile = RomProfile.from_path(cls.rom_path).analyze_static()

    @classmethod
    def tearDownClass(cls):
        os.unlink(cls.rom_path)

    def test_oam_dma_detected(self):
        self.assertTrue(self.profile.hardware.oam_dma_used)

    def test_no_scrolling(self):
        self.assertFalse(self.profile.hardware.scrolling_used)

    def test_no_apu_usage(self):
        self.assertFalse(self.profile.hardware.apu_used)
        self.assertFalse(self.profile.hardware.apu_dmc_used)

    def test_controller1_read(self):
        self.assertTrue(self.profile.hardware.controller1_read)

    def test_frame_counter_detected_statically(self):
        self.assertEqual(self.profile.static_report.dataflow.get(0x10), "frame_counter")


class TestMarkdownGeneration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = RomProfile.from_file = RomProfile.from_path(NESTEST_PATH).analyze_static()
        cls.md = cls.profile.to_markdown()

    def test_has_header_section(self):
        self.assertIn("## En-tête iNES", self.md)

    def test_has_vectors_section(self):
        self.assertIn("## Vecteurs CPU", self.md)
        self.assertIn("RESET", self.md)
        self.assertIn("$C004", self.md)

    def test_has_disasm_section(self):
        self.assertIn("## Désassemblage statique", self.md)

    def test_has_stack_section(self):
        self.assertIn("## Stack technique détectée", self.md)

    def test_has_characterization(self):
        self.assertIn("## Caractérisation", self.md)

    def test_mapper_name_present(self):
        self.assertIn("NROM", self.md)

    def test_register_names_present(self):
        for reg in ("PPUCTRL", "PPUMASK", "PPUSTATUS", "JOY1"):
            with self.subTest(reg=reg):
                self.assertIn(reg, self.md)


class TestWriteMarkdown(unittest.TestCase):
    def test_write_to_file(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "STACK.md"
            profile = RomProfile.from_path(NESTEST_PATH).analyze_static()
            profile.write_markdown(out)
            self.assertTrue(out.exists())
            content = out.read_text(encoding="utf-8")
            self.assertIn("# STACK", content)
            self.assertIn("NROM", content)


@unittest.skipUnless(HAS_CYNES, "cynes non installé")
class TestProfileWithDynamic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rom_path = build_game_synth_rom_path(with_game_over=False)
        cls.profile = (
            RomProfile.from_path(cls.rom_path).analyze_static().analyze_dynamic(cls.rom_path)
        )

    @classmethod
    def tearDownClass(cls):
        os.unlink(cls.rom_path)

    def test_dynamic_summary_present(self):
        self.assertIsNotNone(self.profile.dynamic_summary)
        self.assertIn("scenarios", self.profile.dynamic_summary)

    def test_press_a_finds_lives(self):
        scenarios = self.profile.dynamic_summary["scenarios"]
        names = [v["name"] for v in scenarios.get("press_a", [])]
        self.assertIn("lives", names)

    def test_markdown_includes_dynamic_section(self):
        md = self.profile.to_markdown()
        self.assertIn("## Discovery dynamique", md)
        self.assertIn("press_a", md)


class TestUnknownMapper(unittest.TestCase):
    def test_unsupported_mapper_raises(self):
        rom_bytes = fake_rom(2, 4)
        with self.assertRaises(NotImplementedError):
            Rom(rom_bytes)


class TestCLI(unittest.TestCase):
    def test_cli_writes_stack_md(self):
        from qlnes.cli import main

        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "STACK.md"
            rc = main(
                [
                    "analyze",
                    str(NESTEST_PATH),
                    "--output",
                    str(out),
                    "--no-dynamic",
                    "--quiet",
                ]
            )
            self.assertEqual(rc, 0)
            self.assertTrue(out.exists())
            content = out.read_text(encoding="utf-8")
            self.assertIn("# STACK", content)

    def test_cli_missing_rom(self):
        from qlnes.cli import main

        rc = main(["analyze", "/nonexistent/rom.nes", "--quiet"])
        self.assertEqual(rc, 2)

    def test_cli_writes_asm_when_requested(self):
        from qlnes.cli import main

        with tempfile.TemporaryDirectory() as td:
            stack = Path(td) / "STACK.md"
            asm = Path(td) / "out.asm"
            rc = main(
                [
                    "analyze",
                    str(NESTEST_PATH),
                    "--output",
                    str(stack),
                    "--asm",
                    str(asm),
                    "--no-dynamic",
                    "--quiet",
                ]
            )
            self.assertEqual(rc, 0)
            self.assertTrue(asm.exists())
            self.assertIn("PPUCTRL", asm.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
