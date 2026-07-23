import json
import tempfile
import unittest
from pathlib import Path

from typer.testing import CliRunner

from qlnes.cli import app
from qlnes.graphics_calls import analyze_graphics_calls
from qlnes.ines import INES_MAGIC, parse_header
from qlnes.parser import Disasm
from tests.fixtures.synth_rom import build_image


class TestGraphicsCalls(unittest.TestCase):
    def test_detects_ppu_oam_palette_and_mapper_sites(self):
        asm = "\n".join(
            [
                "L_8000  LDA  #0x3F",
                "L_8002  STA  PPUADDR",
                "L_8005  LDA  #0x10",
                "L_8007  STA  PPUADDR",
                "L_800A  LDA  #0x30",
                "L_800C  STA  PPUDATA",
                "L_800F  STA  OAMDMA",
                "L_8012  STA  sprite_0_tile",
                "L_8015  STA  L_8000",
            ]
        )
        header = parse_header(INES_MAGIC + bytes([2, 1, 0x10, 0]) + bytes(8))

        report = analyze_graphics_calls(Disasm(asm), header)
        kinds = report.counts_by_kind

        self.assertEqual(kinds["palette_upload"], 1)
        self.assertEqual(kinds["oam_dma"], 1)
        self.assertEqual(kinds["oam_buffer_write"], 1)
        self.assertEqual(kinds["mapper_bank_switch"], 1)
        self.assertIn("palette_upload", report.to_markdown())

    def test_cli_writes_markdown_and_json(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rom = root / "synth.nes"
            rom.write_bytes(INES_MAGIC + bytes([2, 0, 0, 0]) + bytes(8) + build_image()[0x8000:])
            md = root / "graphics.md"
            js = root / "graphics.json"

            result = runner.invoke(
                app,
                [
                    "graphics-calls",
                    str(rom),
                    "-o",
                    str(md),
                    "--json-out",
                    str(js),
                    "-q",
                ],
            )

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("Analyse ASM graphique", md.read_text(encoding="utf-8"))
            data = json.loads(js.read_text(encoding="utf-8"))
            self.assertGreater(data["summary"]["calls"], 0)


if __name__ == "__main__":
    unittest.main()
