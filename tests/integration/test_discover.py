import os
import unittest

from tests.fixtures.game_synth import (
    ZP_CONTROLLER1,
    ZP_FRAME_COUNTER,
    ZP_LEVEL,
    ZP_LIVES,
    ZP_SCORE_LO,
)
from tests.test_setup import HAS_CYNES, build_game_synth_rom_path


class TestClassifyChange(unittest.TestCase):
    def test_no_change_is_flag(self):
        from qlnes.emu import classify_change

        kind, _conf, _ = classify_change(5, 5, 10)
        self.assertEqual(kind, "flag")

    def test_decrement_per_frame_is_gauge(self):
        from qlnes.emu import classify_change

        kind, conf, _ = classify_change(50, 40, 10)
        self.assertEqual(kind, "gauge")
        self.assertGreaterEqual(conf, 0.85)

    def test_increment_per_frame_is_counter(self):
        from qlnes.emu import classify_change

        kind, _conf, _ = classify_change(0, 10, 10)
        self.assertEqual(kind, "counter")

    def test_jump_is_flag(self):
        from qlnes.emu import classify_change

        kind, _, _ = classify_change(0, 128, 1)
        self.assertEqual(kind, "flag")


class TestClassifyLinearity(unittest.TestCase):
    def test_linear_decrement_high_confidence(self):
        from qlnes.emu import classify_with_linearity

        kind, conf, _ = classify_with_linearity(50, 45, 5, 50, 30, 20)
        self.assertEqual(kind, "gauge")
        self.assertGreater(conf, 0.9)

    def test_saturation_is_flag(self):
        from qlnes.emu import classify_with_linearity

        kind, _conf, _ = classify_with_linearity(0, 128, 5, 0, 128, 20)
        self.assertEqual(kind, "flag")


@unittest.skipUnless(HAS_CYNES, "cynes non installé")
class TestDiscoverSynth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rom_path = build_game_synth_rom_path()
        import cynes

        from qlnes.emu import Discoverer, Scenario

        d = Discoverer(
            cls.rom_path,
            static_names={ZP_FRAME_COUNTER: "frame_counter", ZP_CONTROLLER1: "controller1_state"},
        )
        scenarios = [
            Scenario("press_a").hold(cynes.NES_INPUT_A, 10),
            Scenario("press_b").hold(cynes.NES_INPUT_B, 10),
            Scenario("press_start").hold(cynes.NES_INPUT_START, 10),
        ]
        cls.result = d.discover(scenarios, idle_frames=10)

    @classmethod
    def tearDownClass(cls):
        os.unlink(cls.rom_path)

    def _findings(self, scenario_name):
        return self.result.by_scenario[scenario_name]

    def test_press_a_finds_lives(self):
        addrs = {v.addr for v in self._findings("press_a")}
        self.assertIn(ZP_LIVES, addrs)

    def test_press_b_finds_score(self):
        addrs = {v.addr for v in self._findings("press_b")}
        self.assertIn(ZP_SCORE_LO, addrs)

    def test_press_start_finds_level(self):
        addrs = {v.addr for v in self._findings("press_start")}
        self.assertIn(ZP_LEVEL, addrs)

    def test_static_names_are_excluded(self):
        for findings in self.result.by_scenario.values():
            addrs = {v.addr for v in findings}
            self.assertNotIn(ZP_FRAME_COUNTER, addrs)
            self.assertNotIn(ZP_CONTROLLER1, addrs)

    def test_lives_classified_as_gauge(self):
        for v in self._findings("press_a"):
            if v.addr == ZP_LIVES:
                self.assertEqual(v.name, "lives")
                self.assertGreaterEqual(v.confidence, 0.85)
                return
        self.fail("lives not found in press_a findings")

    def test_score_classified_as_counter(self):
        for v in self._findings("press_b"):
            if v.addr == ZP_SCORE_LO:
                self.assertEqual(v.name, "score")
                self.assertGreaterEqual(v.confidence, 0.85)
                return
        self.fail("score not found in press_b findings")

    def test_result_to_dict_serializable(self):
        import json

        d = self.result.to_dict()
        json.dumps(d)
        self.assertIn("scenarios", d)
        self.assertIn("noise", d)
        self.assertIn("summary", d)

    def test_names_property_returns_address_to_name(self):
        names = self.result.names()
        self.assertEqual(names.get(ZP_LIVES), "lives")
        self.assertEqual(names.get(ZP_SCORE_LO), "score")
        self.assertEqual(names.get(ZP_LEVEL), "level")


@unittest.skipUnless(HAS_CYNES, "cynes non installé")
class TestDiscoverNoise(unittest.TestCase):
    def test_calibrate_produces_baseline_and_noise(self):
        rom_path = build_game_synth_rom_path()
        try:
            from qlnes.emu import Discoverer

            d = Discoverer(rom_path)
            baseline, noise = d.calibrate_noise(idle_frames=10, samples=3)
            self.assertEqual(len(baseline.ram), 0x800)
            self.assertIsInstance(noise, set)
        finally:
            os.unlink(rom_path)


if __name__ == "__main__":
    unittest.main()
