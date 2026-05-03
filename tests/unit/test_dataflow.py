import unittest

from qlnes.dataflow import (
    detect_controller_reads,
    detect_frame_counter,
    detect_oam_indices,
    detect_oamdma_buffer,
    detect_pointer_pairs,
    find_nmi_address,
    find_reset_address,
)
from qlnes.parser import Disasm
from tests.fixtures.synth_rom import EXPECTED_NAMES, build_image
from tests.test_setup import synth_annotate, synth_disasm


class TestVectorHelpers(unittest.TestCase):
    def test_find_vectors(self):
        img = build_image()
        self.assertEqual(find_reset_address(img), 0x8000)
        self.assertEqual(find_nmi_address(img), 0x8050)

    def test_find_vectors_short_image(self):
        self.assertIsNone(find_reset_address(b"\x00" * 100))
        self.assertIsNone(find_nmi_address(b"\x00" * 100))


class TestFrameCounterDetection(unittest.TestCase):
    def test_detected_on_synth(self):
        img, _, d = synth_disasm()
        nmi = find_nmi_address(img)
        addrs = {x.addr for x in detect_frame_counter(d, nmi)}
        self.assertIn(0x10, addrs)

    def test_no_false_positive_without_nmi(self):
        d = Disasm("L_8000: RTS\nL_8001: RTS\n")
        self.assertEqual(detect_frame_counter(d, None), [])


class TestControllerDetection(unittest.TestCase):
    def test_both_controllers(self):
        _, _, d = synth_disasm()
        names = {x.addr: x.name for x in detect_controller_reads(d)}
        self.assertEqual(names.get(0x20), "controller1_state")
        self.assertEqual(names.get(0x21), "controller2_state")

    def test_high_confidence(self):
        _, _, d = synth_disasm()
        for det in detect_controller_reads(d):
            self.assertGreaterEqual(det.confidence, 0.8)


class TestOamIndexDetection(unittest.TestCase):
    def test_detected(self):
        _, _, d = synth_disasm()
        addrs = {x.addr for x in detect_oam_indices(d)}
        self.assertIn(0x30, addrs)


class TestPointerPairDetection(unittest.TestCase):
    def test_pair_detected(self):
        _, _, d = synth_disasm()
        names = {x.addr: x.name for x in detect_pointer_pairs(d)}
        self.assertEqual(names.get(0x40), "ptr0_lo")
        self.assertEqual(names.get(0x41), "ptr0_hi")


class TestOamDmaDetection(unittest.TestCase):
    def test_page_2_detected(self):
        _, _, d = synth_disasm()
        addrs = {x.addr for x in detect_oamdma_buffer(d)}
        self.assertIn(0x0200, addrs)


class TestDetectAll(unittest.TestCase):
    def test_all_expected_patterns_match(self):
        _, _, _, rep = synth_annotate()
        names = rep.names
        for addr, expected in EXPECTED_NAMES.items():
            with self.subTest(addr=hex(addr)):
                self.assertEqual(
                    names.get(addr),
                    expected,
                    f"expected {expected} at {addr:#06x}, got {names.get(addr)}",
                )

    def test_annotated_asm_uses_semantic_names(self):
        _, _, ann, _ = synth_annotate()
        for token in (
            "frame_counter",
            "controller1_state",
            "oam_index",
            "ptr0_lo",
            "PPUSTATUS",
            "OAMDMA",
        ):
            self.assertIn(token, ann)


if __name__ == "__main__":
    unittest.main()
