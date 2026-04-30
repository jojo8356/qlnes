import unittest

from tests.test_setup import fake_rom, ines_header
from qlnes import Rom, rom_to_images
from qlnes.ines import PRG_BANK, SUPPORTED_MAPPERS, parse_header, strip_ines


class TestMapperHeader(unittest.TestCase):
    def test_magic_validation(self):
        self.assertIsNone(parse_header(b"NOPE" + bytes(20)))

    def test_mapper_extraction(self):
        for m in (0, 1, 2, 3, 4):
            h = parse_header(ines_header(1, 1, m))
            self.assertEqual(h.mapper, m, f"mapper={m}")

    def test_strip_ines_drops_header(self):
        rom = fake_rom(2, 0)
        prg = strip_ines(rom)
        self.assertEqual(len(prg), 2 * PRG_BANK)
        self.assertEqual(prg[0], 0)
        self.assertEqual(prg[PRG_BANK], 1)


class TestNROM(unittest.TestCase):
    def test_nrom_32k(self):
        images = rom_to_images(fake_rom(2, 0))
        self.assertEqual(len(images), 1)
        _, image = images[0]
        self.assertEqual(len(image), 0x10000)
        self.assertEqual(image[0x8000], 0)
        self.assertEqual(image[0xC000], 1)

    def test_nrom_16k_mirrored(self):
        images = rom_to_images(fake_rom(1, 0))
        self.assertEqual(len(images), 1)
        _, image = images[0]
        self.assertEqual(image[0x8000], image[0xC000])


class TestCNROM(unittest.TestCase):
    def test_cnrom_treats_prg_like_nrom(self):
        self.assertEqual(len(rom_to_images(fake_rom(2, 3))), 1)


class TestUxROM(unittest.TestCase):
    def test_uxrom_yields_one_layout_per_switchable_bank(self):
        self.assertEqual(len(rom_to_images(fake_rom(8, 2))), 8)

    def test_uxrom_last_bank_fixed(self):
        images = rom_to_images(fake_rom(4, 2))
        for bank_id, image in images:
            self.assertEqual(image[0xC000], 3, f"bank {bank_id}")
        self.assertEqual(images[0][1][0x8000], 0)
        self.assertEqual(images[1][1][0x8000], 1)
        self.assertEqual(images[2][1][0x8000], 2)


class TestMMC1Default(unittest.TestCase):
    def test_mmc1_layout_like_uxrom(self):
        images = rom_to_images(fake_rom(4, 1))
        self.assertEqual(len(images), 4)
        for _, image in images:
            self.assertEqual(image[0xC000], 3)


class TestGxROM(unittest.TestCase):
    def test_gxrom_one_image_per_32k_bank(self):
        # 4 PRG banks (16K) = 2 banks de 32K → 2 images
        images = rom_to_images(fake_rom(4, 66))
        self.assertEqual(len(images), 2)
        for _, image in images:
            self.assertEqual(len(image), 0x10000)

    def test_gxrom_bank_marker_at_8000(self):
        # fake_rom marque le 1er octet de chaque bank 16K avec son index
        images = rom_to_images(fake_rom(4, 66))
        self.assertEqual(images[0][1][0x8000], 0)
        self.assertEqual(images[1][1][0x8000], 2)

    def test_gxrom_single_32k_bank(self):
        images = rom_to_images(fake_rom(2, 66))
        self.assertEqual(len(images), 1)


class TestUnsupportedMapper(unittest.TestCase):
    def test_mmc3_raises(self):
        with self.assertRaises(NotImplementedError):
            rom_to_images(fake_rom(2, 4))


class TestRom(unittest.TestCase):
    def test_rom_metadata(self):
        rom = Rom(fake_rom(1, 0), name="fake")
        self.assertEqual(rom.mapper, 0)
        self.assertEqual(rom.num_prg_banks, 1)

    def test_single_image_for_nrom(self):
        self.assertEqual(len(Rom(fake_rom(2, 0)).single_image()), 0x10000)

    def test_single_image_raises_for_uxrom(self):
        with self.assertRaises(ValueError):
            Rom(fake_rom(4, 2)).single_image()

    def test_banks_iteration(self):
        banks = list(Rom(fake_rom(4, 2)).banks())
        self.assertEqual(len(banks), 4)
        self.assertTrue(banks[-1].is_fixed_only)
        self.assertFalse(banks[0].is_fixed_only)

    def test_supported_mappers_list(self):
        for m in SUPPORTED_MAPPERS:
            try:
                rom_to_images(fake_rom(2, m))
            except NotImplementedError:
                self.fail(f"mapper {m} should be supported")


if __name__ == "__main__":
    unittest.main()
