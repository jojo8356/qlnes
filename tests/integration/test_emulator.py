import os
import unittest

from tests.test_setup import HAS_CYNES, build_game_synth_rom_path


@unittest.skipUnless(HAS_CYNES, "cynes non installé")
class TestRunner(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rom_path = build_game_synth_rom_path()

    @classmethod
    def tearDownClass(cls):
        os.unlink(cls.rom_path)

    def setUp(self):
        from qlnes.emu import Runner
        self.r = Runner(self.rom_path)

    def test_boot_advances_frame_count(self):
        self.r.boot(30)
        self.assertEqual(self.r.frame, 30)

    def test_snapshot_size(self):
        self.r.boot(10)
        snap = self.r.snapshot_ram()
        self.assertEqual(len(snap.ram), 0x800)
        self.assertEqual(snap.frame, 10)

    def test_hold_advances_correctly(self):
        import cynes
        self.r.boot(60)
        self.r.hold(cynes.NES_INPUT_A, 5)
        self.assertEqual(self.r.frame, 65)

    def test_reset_restarts_frame_counter(self):
        self.r.boot(100)
        self.r.reset()
        self.assertEqual(self.r.frame, 0)

    def test_holding_a_decrements_lives(self):
        import cynes
        self.r.boot(60)
        before = self.r.snapshot_ram()
        self.r.hold(cynes.NES_INPUT_A, 10)
        after = self.r.snapshot_ram()
        self.assertNotEqual(before.ram[0x11], after.ram[0x11])

    def test_holding_b_increments_score(self):
        import cynes
        self.r.boot(60)
        before = self.r.snapshot_ram()
        self.r.hold(cynes.NES_INPUT_B, 7)
        after = self.r.snapshot_ram()
        self.assertEqual((after.ram[0x12] - before.ram[0x12]) & 0xFF, 7)


@unittest.skipUnless(HAS_CYNES, "cynes non installé")
class TestScenario(unittest.TestCase):
    def test_scenario_chaining(self):
        from qlnes.emu import Scenario
        sc = Scenario("test").hold(0x80, 10).idle(5).hold(0x40, 3)
        self.assertEqual(len(sc.steps), 3)
        self.assertEqual(sc.total_frames(), 18)

    def test_scenario_rejects_zero_frames(self):
        from qlnes.emu import Scenario
        with self.assertRaises(ValueError):
            Scenario("x").hold(0, 0)


@unittest.skipUnless(HAS_CYNES, "cynes non installé")
class TestRunScenario(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rom_path = build_game_synth_rom_path()

    @classmethod
    def tearDownClass(cls):
        os.unlink(cls.rom_path)

    def test_run_scenario_returns_initial_and_final(self):
        from qlnes.emu import Runner, Scenario
        import cynes
        r = Runner(self.rom_path)
        sc = Scenario("press_a").hold(cynes.NES_INPUT_A, 10)
        snaps = r.run_scenario(sc, boot_frames=30)
        self.assertEqual(len(snaps), 2)
        self.assertEqual(snaps[0].frame, 30)
        self.assertEqual(snaps[1].frame, 40)

    def test_run_scenario_each_step(self):
        from qlnes.emu import Runner, Scenario
        import cynes
        r = Runner(self.rom_path)
        sc = (
            Scenario("multi")
            .hold(cynes.NES_INPUT_A, 5)
            .idle(3)
            .hold(cynes.NES_INPUT_B, 2)
        )
        snaps = r.run_scenario(sc, boot_frames=30, snapshot_each_step=True)
        self.assertEqual(len(snaps), 4)


if __name__ == "__main__":
    unittest.main()
