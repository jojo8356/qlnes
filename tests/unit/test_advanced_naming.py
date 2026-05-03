import unittest

from qlnes import Disasm, annotate
from qlnes.dataflow import (
    Subroutine,
    detect_loop_counters,
    detect_ppu_shadows,
    detect_subroutine_args,
    detect_subroutine_kinds,
    find_subroutines,
)
from tests.test_setup import disassemble


def _ines_rom_with_code(code: bytes, code_offset: int = 0x0000) -> bytes:
    header = bytes([0x4E, 0x45, 0x53, 0x1A, 0x01, 0x00, 0x00, 0x00] + [0] * 8)
    prg = bytearray(0x4000)
    prg[code_offset : code_offset + len(code)] = code
    reset_addr = 0x8000 + code_offset
    prg[0x3FFC] = reset_addr & 0xFF
    prg[0x3FFD] = (reset_addr >> 8) & 0xFF
    prg[0x3FFA] = reset_addr & 0xFF
    prg[0x3FFB] = (reset_addr >> 8) & 0xFF
    prg[0x3FFE] = reset_addr & 0xFF
    prg[0x3FFF] = (reset_addr >> 8) & 0xFF
    return header + bytes(prg)


def _image_with_code(code: bytes) -> bytes:
    image = bytearray(0x10000)
    image[0x8000 : 0x8000 + len(code)] = code
    image[0xFFFC] = 0x00
    image[0xFFFD] = 0x80
    image[0xFFFA] = 0x00
    image[0xFFFB] = 0x80
    return bytes(image)


def _disasm_for(code: bytes) -> Disasm:
    return Disasm(disassemble(_image_with_code(code)))


class TestPpuShadowDetection(unittest.TestCase):
    def test_ppu_ctrl_shadow_detected(self):
        code = bytes(
            [
                0xA9,
                0x80,
                0x85,
                0x42,
                0xA5,
                0x42,
                0x8D,
                0x00,
                0x20,
                0x4C,
                0x04,
                0x80,
            ]
        )
        d = _disasm_for(code)
        dets = detect_ppu_shadows(d)
        addrs = {x.addr: x.name for x in dets}
        self.assertEqual(addrs.get(0x42), "ppu_ctrl_shadow")

    def test_ppu_mask_shadow_detected(self):
        code = bytes(
            [
                0xA9,
                0x1E,
                0x85,
                0x55,
                0xA5,
                0x55,
                0x8D,
                0x01,
                0x20,
                0x4C,
                0x04,
                0x80,
            ]
        )
        d = _disasm_for(code)
        dets = detect_ppu_shadows(d)
        addrs = {x.addr: x.name for x in dets}
        self.assertEqual(addrs.get(0x55), "ppu_mask_shadow")


class TestLoopCounterDetection(unittest.TestCase):
    def test_dex_loop_with_zp_init(self):
        code = bytes(
            [
                0xA6,
                0x33,
                0xCA,
                0xD0,
                0xFD,
                0x4C,
                0x05,
                0x80,
            ]
        )
        d = _disasm_for(code)
        dets = detect_loop_counters(d)
        addrs = {x.addr for x in dets}
        self.assertIn(0x33, addrs)


class TestSubroutineDiscovery(unittest.TestCase):
    def test_find_subroutines_returns_jsr_targets(self):
        code = bytes(
            [
                0x20,
                0x10,
                0x80,
                0x4C,
                0x00,
                0x80,
                0xEA,
                0xEA,
                0xEA,
                0xEA,
                0xEA,
                0xEA,
                0xEA,
                0xEA,
                0xEA,
                0xEA,
                0x60,
            ]
        )
        d = _disasm_for(code)
        subs = find_subroutines(d)
        entries = {s.entry for s in subs}
        self.assertIn(0x8010, entries)


class TestSubroutineKinds(unittest.TestCase):
    def test_oam_dma_subroutine(self):
        code = bytes(
            [
                0x20,
                0x10,
                0x80,
                0x4C,
                0x00,
                0x80,
                0xEA,
                0xEA,
                0xEA,
                0xEA,
                0xEA,
                0xEA,
                0xEA,
                0xEA,
                0xEA,
                0xEA,
                0xA9,
                0x02,
                0x8D,
                0x14,
                0x40,
                0x60,
            ]
        )
        d = _disasm_for(code)
        kinds = detect_subroutine_kinds(d)
        self.assertEqual(kinds.get(0x8010, Subroutine(0, [])).kind, "oam_dma_transfer")

    def test_play_pulse_subroutine(self):
        code = bytes(
            [
                0x20,
                0x10,
                0x80,
                0x4C,
                0x00,
                0x80,
                0xEA,
                0xEA,
                0xEA,
                0xEA,
                0xEA,
                0xEA,
                0xEA,
                0xEA,
                0xEA,
                0xEA,
                0xA9,
                0x88,
                0x8D,
                0x00,
                0x40,
                0xA9,
                0x00,
                0x8D,
                0x01,
                0x40,
                0x60,
            ]
        )
        d = _disasm_for(code)
        kinds = detect_subroutine_kinds(d)
        self.assertEqual(kinds.get(0x8010, Subroutine(0, [])).kind, "play_pulse")


class TestSubroutineArgs(unittest.TestCase):
    def test_sta_before_jsr(self):
        code = bytes(
            [
                0xA9,
                0x05,
                0x85,
                0x77,
                0x20,
                0x20,
                0x80,
                0x4C,
                0x00,
                0x80,
                0xEA,
                0xEA,
                0xEA,
                0xEA,
                0xEA,
                0xEA,
                0xEA,
                0xEA,
                0xEA,
                0xEA,
                0x60,
            ]
        )
        d = _disasm_for(code)
        dets = detect_subroutine_args(d)
        addrs = {x.addr for x in dets}
        self.assertIn(0x77, addrs)


class TestAnnotateSubroutines(unittest.TestCase):
    def test_subroutines_in_report(self):
        code = bytes(
            [
                0x20,
                0x10,
                0x80,
                0x4C,
                0x00,
                0x80,
                0xEA,
                0xEA,
                0xEA,
                0xEA,
                0xEA,
                0xEA,
                0xEA,
                0xEA,
                0xEA,
                0xEA,
                0xA9,
                0x02,
                0x8D,
                0x14,
                0x40,
                0x60,
            ]
        )
        asm = disassemble(_image_with_code(code))
        _annotated, report = annotate(asm)
        self.assertIn(0x8010, report.subroutines)
        self.assertEqual(report.subroutines[0x8010], "oam_dma_transfer")

    def test_subroutine_name_in_rewritten_asm(self):
        code = bytes(
            [
                0x20,
                0x10,
                0x80,
                0x4C,
                0x00,
                0x80,
                0xEA,
                0xEA,
                0xEA,
                0xEA,
                0xEA,
                0xEA,
                0xEA,
                0xEA,
                0xEA,
                0xEA,
                0xA9,
                0x02,
                0x8D,
                0x14,
                0x40,
                0x60,
            ]
        )
        asm = disassemble(_image_with_code(code))
        annotated, _ = annotate(asm)
        self.assertIn("oam_dma_transfer", annotated)


class TestCrossReferenceModule(unittest.TestCase):
    def test_proposes_update_lives(self):
        from qlnes.cross_ref import cross_reference

        code = bytes(
            [
                0x20,
                0x10,
                0x80,
                0x4C,
                0x00,
                0x80,
                0xEA,
                0xEA,
                0xEA,
                0xEA,
                0xEA,
                0xEA,
                0xEA,
                0xEA,
                0xEA,
                0xEA,
                0xC6,
                0x11,
                0x60,
            ]
        )
        d = _disasm_for(code)
        proposals = cross_reference(d, dynamic_names={0x11: "lives"})
        names = {p.entry: p.name for p in proposals}
        self.assertEqual(names.get(0x8010), "update_lives")

    def test_no_proposal_without_dynamic_names(self):
        from qlnes.cross_ref import cross_reference

        d = _disasm_for(bytes([0x60]))
        self.assertEqual(cross_reference(d, dynamic_names={}), [])


class TestStackMdSubroutinesSection(unittest.TestCase):
    def test_subroutines_section_present_when_named(self):
        from qlnes import Rom, RomProfile

        rom_bytes = _ines_rom_with_code(
            bytes(
                [
                    0x20,
                    0x10,
                    0x80,
                    0x4C,
                    0x00,
                    0x80,
                    0xEA,
                    0xEA,
                    0xEA,
                    0xEA,
                    0xEA,
                    0xEA,
                    0xEA,
                    0xEA,
                    0xEA,
                    0xEA,
                    0xA9,
                    0x02,
                    0x8D,
                    0x14,
                    0x40,
                    0x60,
                ]
            )
        )
        rom = Rom(rom_bytes, name="synth_oam")
        profile = RomProfile.from_rom(rom).analyze_static()
        md = profile.to_markdown()
        self.assertIn("### Sous-routines nommées", md)
        self.assertIn("oam_dma_transfer", md)


if __name__ == "__main__":
    unittest.main()
