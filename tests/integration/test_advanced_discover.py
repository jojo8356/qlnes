import os
import unittest

from tests.test_setup import HAS_CYNES, build_game_synth_rom_path
from tests.fixtures.game_synth import (
    ZP_FRAME_COUNTER,
    ZP_LIVES,
    ZP_SCORE_LO,
    ZP_LEVEL,
    ZP_CONTROLLER1,
)


STATIC = {ZP_FRAME_COUNTER: "frame_counter", ZP_CONTROLLER1: "controller1_state"}


class TestClassifyDurations(unittest.TestCase):
    def test_linear_counter_high_conf(self):
        from qlnes.emu import DurationMeasurement, classify_durations
        ms = [
            DurationMeasurement(5, 0, 5),
            DurationMeasurement(10, 0, 10),
            DurationMeasurement(20, 0, 20),
        ]
        kind, conf, _ = classify_durations(ms)
        self.assertEqual(kind, "counter")
        self.assertGreater(conf, 0.9)

    def test_linear_gauge_high_conf(self):
        from qlnes.emu import DurationMeasurement, classify_durations
        ms = [
            DurationMeasurement(5, 50, 45),
            DurationMeasurement(10, 50, 40),
            DurationMeasurement(20, 50, 30),
        ]
        kind, conf, _ = classify_durations(ms)
        self.assertEqual(kind, "gauge")
        self.assertGreater(conf, 0.9)

    def test_saturation_detected(self):
        from qlnes.emu import DurationMeasurement, classify_durations
        ms = [
            DurationMeasurement(5, 0, 128),
            DurationMeasurement(10, 0, 128),
            DurationMeasurement(20, 0, 128),
        ]
        kind, _, _ = classify_durations(ms)
        self.assertEqual(kind, "flag")

    def test_no_change_is_flag(self):
        from qlnes.emu import DurationMeasurement, classify_durations
        ms = [DurationMeasurement(5, 7, 7), DurationMeasurement(10, 7, 7)]
        kind, _, _ = classify_durations(ms)
        self.assertEqual(kind, "flag")

    def test_empty_measurements(self):
        from qlnes.emu import classify_durations
        kind, conf, _ = classify_durations([])
        self.assertEqual(kind, "flag")
        self.assertEqual(conf, 0.0)


@unittest.skipUnless(HAS_CYNES, "cynes non installé")
class TestMultiDurationDiscovery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rom_path = build_game_synth_rom_path(with_game_over=False)
        from qlnes.emu import Discoverer
        import cynes
        cls.discoverer = Discoverer(cls.rom_path, static_names=STATIC)
        cls.cynes = cynes

    @classmethod
    def tearDownClass(cls):
        os.unlink(cls.rom_path)

    def _by_addr(self, findings):
        return {v.addr: v for v in findings}

    def test_press_a_classifies_lives_as_gauge(self):
        found = self.discoverer.discover_multi_duration(
            "press_a", self.cynes.NES_INPUT_A, durations=(5, 10, 20)
        )
        by_addr = self._by_addr(found)
        self.assertIn(ZP_LIVES, by_addr)
        v = by_addr[ZP_LIVES]
        self.assertEqual(v.name, "lives")
        self.assertGreaterEqual(v.confidence, 0.9)

    def test_press_b_classifies_score_as_counter(self):
        found = self.discoverer.discover_multi_duration(
            "press_b", self.cynes.NES_INPUT_B, durations=(5, 10, 20)
        )
        by_addr = self._by_addr(found)
        self.assertIn(ZP_SCORE_LO, by_addr)
        v = by_addr[ZP_SCORE_LO]
        self.assertEqual(v.name, "score")
        self.assertGreaterEqual(v.confidence, 0.9)

    def test_press_start_classifies_level(self):
        found = self.discoverer.discover_multi_duration(
            "press_start", self.cynes.NES_INPUT_START, durations=(5, 10, 20)
        )
        by_addr = self._by_addr(found)
        self.assertIn(ZP_LEVEL, by_addr)

    def test_static_addresses_excluded(self):
        found = self.discoverer.discover_multi_duration(
            "press_a", self.cynes.NES_INPUT_A
        )
        addrs = {v.addr for v in found}
        self.assertNotIn(ZP_FRAME_COUNTER, addrs)
        self.assertNotIn(ZP_CONTROLLER1, addrs)

    def test_durations_required(self):
        with self.assertRaises(ValueError):
            self.discoverer.discover_multi_duration(
                "press_a", self.cynes.NES_INPUT_A, durations=()
            )


@unittest.skipUnless(HAS_CYNES, "cynes non installé")
class TestMultiDurationOnGameOverROM(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rom_path = build_game_synth_rom_path(with_game_over=True)
        from qlnes.emu import Discoverer
        import cynes
        cls.discoverer = Discoverer(cls.rom_path, static_names=STATIC)
        cls.cynes = cynes

    @classmethod
    def tearDownClass(cls):
        os.unlink(cls.rom_path)

    def test_score_still_linear_despite_game_over(self):
        found = self.discoverer.discover_multi_duration(
            "press_b", self.cynes.NES_INPUT_B, durations=(5, 10, 20)
        )
        by_addr = {v.addr: v for v in found}
        self.assertIn(ZP_SCORE_LO, by_addr)
        v = by_addr[ZP_SCORE_LO]
        self.assertEqual(v.name, "score")
        self.assertGreaterEqual(v.confidence, 0.9)

    def test_lives_non_linear_due_to_reset(self):
        found = self.discoverer.discover_multi_duration(
            "press_a", self.cynes.NES_INPUT_A, durations=(3, 8, 25)
        )
        by_addr = {v.addr: v for v in found}
        if ZP_LIVES in by_addr:
            v = by_addr[ZP_LIVES]
            self.assertNotEqual(v.name, "lives")


@unittest.skipUnless(HAS_CYNES, "cynes non installé")
class TestComposedScenarios(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rom_path = build_game_synth_rom_path(with_game_over=False)
        from qlnes.emu import Discoverer
        import cynes
        cls.discoverer = Discoverer(cls.rom_path, static_names=STATIC)
        cls.cynes = cynes
        cls.inter = cls.discoverer.discover_composed(
            "press_a", cls.cynes.NES_INPUT_A, 5,
            "press_b", cls.cynes.NES_INPUT_B, 5,
        )

    @classmethod
    def tearDownClass(cls):
        os.unlink(cls.rom_path)

    def test_lives_changed_only_by_a(self):
        ir = self.inter.get(ZP_LIVES)
        self.assertIsNotNone(ir)
        self.assertEqual(ir.a_alone, -5)
        self.assertEqual(ir.b_alone, 0)

    def test_score_changed_only_by_b(self):
        ir = self.inter.get(ZP_SCORE_LO)
        self.assertIsNotNone(ir)
        self.assertEqual(ir.a_alone, 0)
        self.assertEqual(ir.b_alone, 5)

    def test_lives_independent_of_b_order(self):
        ir = self.inter.get(ZP_LIVES)
        self.assertEqual(ir.a_then_b, ir.b_then_a)
        self.assertTrue(ir.is_independent)

    def test_score_independent_of_a_order(self):
        ir = self.inter.get(ZP_SCORE_LO)
        self.assertEqual(ir.a_then_b, ir.b_then_a)
        self.assertTrue(ir.is_independent)

    def test_label_serialization(self):
        ir = self.inter.get(ZP_LIVES)
        d = ir.to_dict()
        self.assertEqual(d["label"], "independent")
        self.assertEqual(d["addr"], f"0x{ZP_LIVES:04X}")


@unittest.skipUnless(HAS_CYNES, "cynes non installé")
class TestInteractionResultLogic(unittest.TestCase):
    def test_independent_when_additive(self):
        from qlnes.emu import InteractionResult
        ir = InteractionResult(addr=0x10, a_alone=2, b_alone=3, a_then_b=5, b_then_a=5)
        self.assertTrue(ir.is_independent)
        self.assertFalse(ir.order_matters)
        self.assertEqual(ir.label(), "independent")

    def test_order_matters(self):
        from qlnes.emu import InteractionResult
        ir = InteractionResult(addr=0x10, a_alone=1, b_alone=1, a_then_b=3, b_then_a=5)
        self.assertTrue(ir.order_matters)
        self.assertEqual(ir.label(), "order_dependent")

    def test_interactive_when_nonadditive(self):
        from qlnes.emu import InteractionResult
        ir = InteractionResult(addr=0x10, a_alone=1, b_alone=1, a_then_b=10, b_then_a=10)
        self.assertFalse(ir.order_matters)
        self.assertTrue(ir.has_interaction)
        self.assertEqual(ir.label(), "interactive")


@unittest.skipUnless(HAS_CYNES, "cynes non installé")
class TestFindTransitions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rom_path = build_game_synth_rom_path(with_game_over=True)
        from qlnes.emu import Discoverer, Scenario
        import cynes
        d = Discoverer(cls.rom_path, static_names=STATIC)
        sc = Scenario("die_combo").hold(cynes.NES_INPUT_A | cynes.NES_INPUT_B, 16)
        cls.transitions = d.find_transitions(ZP_FRAME_COUNTER, sc)
        cls.discoverer = d

    @classmethod
    def tearDownClass(cls):
        os.unlink(cls.rom_path)

    def test_at_least_three_transitions_in_16_frames(self):
        self.assertGreaterEqual(len(self.transitions), 3)

    def test_all_transitions_show_fc_reset(self):
        for t in self.transitions:
            self.assertLess(t.fc_after, t.fc_before)
            self.assertEqual(t.fc_after, 0)

    def test_transitions_include_lives_reset(self):
        for t in self.transitions:
            self.assertIn(ZP_LIVES, t.ram_diff)
            before, after = t.ram_diff[ZP_LIVES]
            self.assertEqual(after, 3)

    def test_transition_state_addrs(self):
        state = self.discoverer.transition_state_addrs(self.transitions)
        self.assertIn(ZP_LIVES, state)
        before, after = state[ZP_LIVES]
        self.assertEqual(after, 3)

    def test_transition_serializes_to_dict(self):
        import json
        d = self.transitions[0].to_dict()
        json.dumps(d)
        self.assertIn("frame", d)
        self.assertIn("changed", d)


@unittest.skipUnless(HAS_CYNES, "cynes non installé")
class TestNoTransitionsOnLinearROM(unittest.TestCase):
    def test_idle_long_run_no_transitions(self):
        rom_path = build_game_synth_rom_path(with_game_over=False)
        try:
            from qlnes.emu import Discoverer, Scenario
            d = Discoverer(rom_path)
            sc = Scenario("idle").hold(0, 100)
            transitions = d.find_transitions(ZP_FRAME_COUNTER, sc)
            self.assertEqual(len(transitions), 0)
        finally:
            os.unlink(rom_path)


if __name__ == "__main__":
    unittest.main()
