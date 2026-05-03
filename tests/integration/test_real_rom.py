import time
import unittest

from qlnes.dataflow import find_reset_address
from tests.test_setup import (
    NESTEST_PATH,
    Rom,
    disassemble,
    disassemble_and_annotate,
)


@unittest.skipUnless(NESTEST_PATH.exists(), f"missing {NESTEST_PATH}")
class TestNestestPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rom = Rom.from_file(NESTEST_PATH)
        cls.image = cls.rom.single_image()
        cls.asm = disassemble(cls.image)
        cls.annotated, cls.report = disassemble_and_annotate(cls.image)

    def test_rom_metadata(self):
        self.assertEqual(self.rom.mapper, 0)
        self.assertEqual(self.rom.num_prg_banks, 1)

    def test_disasm_non_empty(self):
        self.assertGreater(len(self.asm.splitlines()), 1000)

    def test_reset_vector_traced(self):
        reset_addr = find_reset_address(self.image)
        self.assertEqual(reset_addr, 0xC004)
        self.assertIn(f"L_{reset_addr:04X}", self.asm)

    def test_ppu_registers_identified(self):
        for reg in ("PPUCTRL", "PPUMASK", "PPUSTATUS", "PPUSCROLL", "PPUADDR", "PPUDATA"):
            with self.subTest(reg=reg):
                self.assertIn(reg, self.annotated)

    def test_apu_registers_identified(self):
        for reg in ("APU_PULSE1_CTRL", "APU_PULSE2_CTRL", "APU_STATUS"):
            with self.subTest(reg=reg):
                self.assertIn(reg, self.annotated)

    def test_pointer_pair_in_zero_page(self):
        self.assertEqual(self.report.names.get(0xD0), "ptr0_lo")
        self.assertEqual(self.report.names.get(0xD1), "ptr0_hi")

    def test_low_unmapped_count(self):
        self.assertLess(
            len(self.report.unmapped),
            10,
            f"unmapped: {sorted(self.report.unmapped)[:20]}",
        )


@unittest.skipUnless(NESTEST_PATH.exists(), f"missing {NESTEST_PATH}")
class TestNestestPerformance(unittest.TestCase):
    def test_pipeline_under_2s(self):
        rom = Rom.from_file(NESTEST_PATH)
        t0 = time.time()
        disassemble_and_annotate(rom.single_image())
        elapsed = time.time() - t0
        self.assertLess(elapsed, 2.0, f"pipeline took {elapsed:.2f}s")


if __name__ == "__main__":
    unittest.main()
