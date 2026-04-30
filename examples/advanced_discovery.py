"""Démo des 3 features de discovery avancée :
1. Multi-duration (5/10/20f) — distinguer linéaire vs saturation
2. Composed scenarios — détecter ordre / indépendance / interaction
3. Find transitions — détecter game-over / level-up via reset frame_counter
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.test_setup import build_game_synth_rom_path
from qlnes.emu import Discoverer, Scenario


STATIC_NAMES = {0x10: "frame_counter", 0x20: "controller1_state"}


def main() -> int:
    import cynes

    print("═" * 60)
    print(" 1. MULTI-DURATION DISCOVERY (5/10/20f)")
    print("═" * 60)
    print("ROM linéaire (sans game-over) : tous les boutons doivent être")
    print("classifiés avec une rate constante ⇒ confiance 0.95+")
    print()
    rom_path = build_game_synth_rom_path(with_game_over=False)
    try:
        d = Discoverer(rom_path, static_names=STATIC_NAMES)
        for label, btn in [
            ("press_a", cynes.NES_INPUT_A),
            ("press_b", cynes.NES_INPUT_B),
            ("press_start", cynes.NES_INPUT_START),
        ]:
            print(f"--- {label} ---")
            for v in d.discover_multi_duration(label, btn, durations=(5, 10, 20))[:3]:
                print(
                    f"  0x{v.addr:04X} → {v.name:12s} "
                    f"conf={v.confidence:.2f}  | {v.why}"
                )
            print()
    finally:
        os.unlink(rom_path)

    print("ROM avec game-over : lives n'est plus linéaire à cause du reset,")
    print("le classifier réduit la confiance et change le label.")
    print()
    rom_path = build_game_synth_rom_path(with_game_over=True)
    try:
        d = Discoverer(rom_path, static_names=STATIC_NAMES)
        for v in d.discover_multi_duration(
            "press_a", cynes.NES_INPUT_A, durations=(3, 8, 25)
        )[:3]:
            print(
                f"  0x{v.addr:04X} → {v.name:25s} "
                f"conf={v.confidence:.2f}  | {v.why}"
            )
    finally:
        os.unlink(rom_path)

    print()
    print("═" * 60)
    print(" 2. COMPOSED SCENARIOS (A vs B)")
    print("═" * 60)
    print("Pour chaque adresse modifiée, on regarde 4 deltas :")
    print("  A seul, B seul, A puis B, B puis A")
    print("⇒ independent si A+B = AB = BA")
    print("⇒ order_dependent si AB ≠ BA")
    print("⇒ interactive si AB ≠ A+B")
    print()
    rom_path = build_game_synth_rom_path(with_game_over=False)
    try:
        d = Discoverer(rom_path, static_names=STATIC_NAMES)
        inter = d.discover_composed(
            "press_a", cynes.NES_INPUT_A, 5,
            "press_b", cynes.NES_INPUT_B, 5,
        )
        for addr in sorted(inter):
            ir = inter[addr]
            print(
                f"  0x{addr:04X}  A={ir.a_alone:+3d}  B={ir.b_alone:+3d}  "
                f"A→B={ir.a_then_b:+3d}  B→A={ir.b_then_a:+3d}  → {ir.label()}"
            )
    finally:
        os.unlink(rom_path)

    print()
    print("═" * 60)
    print(" 3. FIND TRANSITIONS (game-over via reset frame_counter)")
    print("═" * 60)
    print("On surveille le frame_counter pendant un long scénario.")
    print("À chaque fc[t] < fc[t-1] : transition de jeu détectée.")
    print()
    rom_path = build_game_synth_rom_path(with_game_over=True)
    try:
        d = Discoverer(rom_path, static_names=STATIC_NAMES)
        sc = Scenario("die_repeatedly").hold(
            cynes.NES_INPUT_A | cynes.NES_INPUT_B, 20
        )
        transitions = d.find_transitions(0x10, sc)
        print(f"{len(transitions)} transitions détectées dans le scénario :")
        for t in transitions:
            changed = ", ".join(
                f"0x{a:04X}:{b}→{x}"
                for a, (b, x) in sorted(t.ram_diff.items())[:5]
            )
            print(
                f"  frame={t.frame:3d}  fc {t.fc_before}→{t.fc_after}  "
                f"({len(t.ram_diff)} changes)  | {changed}"
            )
        print()
        state = d.transition_state_addrs(transitions)
        print(f"Adresses cohérentes ≥80% des transitions ⇒ game state :")
        for a, (b, x) in sorted(state.items()):
            print(f"  0x{a:04X}: reset {b} → {x}")
    finally:
        os.unlink(rom_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
