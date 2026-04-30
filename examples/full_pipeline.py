"""Démo end-to-end : analyse statique (qlnes) + discovery dynamique (qlnes.emu).

Workflow :
1. Génère le ROM synthétique réactif (lives, score, level pilotés par boutons)
2. PASSE STATIQUE : QL6502 + annotate → noms hardware/OAM/dataflow
3. PASSE DYNAMIQUE : Discoverer avec scenarios (press A/B/Start) → game vars
4. Combine et affiche le rapport final unifié
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qlnes import QL6502, Rom, annotate
from qlnes.emu import Discoverer, Scenario


def main() -> int:
    from tests.fixtures.game_synth import build_rom

    rom_bytes = build_rom()
    tmp_path = Path("/tmp/_qlnes_demo.nes")
    tmp_path.write_bytes(rom_bytes)

    try:
        print("=" * 60)
        print("PASSE 1 : ANALYSE STATIQUE (QL6502 + heuristiques)")
        print("=" * 60)
        rom = Rom(rom_bytes, name="game_synth")
        image = rom.single_image()
        asm = QL6502().load_image(image).mark_blank(0x0000, 0x7FFF).generate_asm()
        annotated, static_report = annotate(asm, image=image)
        print(json.dumps(static_report.to_dict()["summary"], indent=2))
        print()
        print("Variables nommées par analyse statique :")
        meaningful = {}
        meaningful.update(static_report.hardware)
        meaningful.update(static_report.oam)
        meaningful.update(static_report.dataflow)
        ram_static = {a: n for a, n in meaningful.items() if a < 0x0800}
        for a in sorted(ram_static):
            print(f"  0x{a:04X}: {ram_static[a]}")
        print()

        print("=" * 60)
        print("PASSE 2 : DISCOVERY DYNAMIQUE (cynes + diff comportemental)")
        print("=" * 60)
        import cynes

        discoverer = Discoverer(tmp_path, static_names=ram_static)
        scenarios = [
            Scenario("press_a").hold(cynes.NES_INPUT_A, 10),
            Scenario("press_b").hold(cynes.NES_INPUT_B, 10),
            Scenario("press_start").hold(cynes.NES_INPUT_START, 10),
        ]
        dyn_result = discoverer.discover(scenarios, idle_frames=10)

        print(f"Adresses excluses (statique) : {len(ram_static)}")
        print(f"Bruit dynamique (RNG/timing): {len(dyn_result.noise)}")
        print()
        for sc_name, findings in dyn_result.by_scenario.items():
            print(f"--- scénario {sc_name} ---")
            for v in findings:
                print(
                    f"  0x{v.addr:04X} → {v.name:15s} "
                    f"Δ={v.delta:+4d}  conf={v.confidence:.2f}  | {v.why}"
                )
            print()

        print("=" * 60)
        print("MAP UNIFIÉE static ∪ dynamique")
        print("=" * 60)
        all_names = dict(ram_static)
        all_names.update(dyn_result.names())
        for a in sorted(all_names):
            print(f"  0x{a:04X}: {all_names[a]}")
        return 0
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


if __name__ == "__main__":
    sys.exit(main())
