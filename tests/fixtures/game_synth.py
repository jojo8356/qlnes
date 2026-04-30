"""ROM 6502 NROM 16K avec game logic réactive aux contrôleurs.

Conçu pour la discovery par diff comportemental :
- A maintenu  → lives ($11) décrémenté chaque NMI
- B maintenu  → score_lo/hi ($12/$13) incrémenté chaque NMI (avec retenue)
- Start maint → level ($14) incrémenté chaque NMI
- toujours    → frame_counter ($10) incrémenté
- toujours    → controller1 ($20) à jour

GAME-OVER / TRANSITION : si lives wrappe de 0 → 0xFF (DEC sur lives=0),
on relance le jeu (lives=3, score=0, level=1, frame_counter=0). C'est le
signal de transition utilisé par find_transitions.

Le ROM est exporté en iNES mapper 0 (NROM-128 16KB), prêt à être
chargé par cynes via NES(rom_path).
"""

from pathlib import Path
from typing import Dict


ZP_FRAME_COUNTER = 0x10
ZP_LIVES = 0x11
ZP_SCORE_LO = 0x12
ZP_SCORE_HI = 0x13
ZP_LEVEL = 0x14
ZP_CONTROLLER1 = 0x20

INES_HEADER = bytes(
    [
        0x4E, 0x45, 0x53, 0x1A,
        0x01,
        0x00,
        0x00, 0x00,
        0, 0, 0, 0, 0, 0, 0, 0,
    ]
)


def _emit(prg: bytearray, offset: int, bs):
    prg[offset : offset + len(bs)] = bytes(bs)


def build_rom(with_game_over: bool = False) -> bytes:
    prg = bytearray(0x4000)

    reset_off = 0x0000
    reset_code = [
        0x78,                                  # SEI
        0xD8,                                  # CLD
        0xA2, 0xFF, 0x9A,                      # LDX #$FF ; TXS
        0xA9, 0x00, 0x8D, 0x00, 0x20,          # LDA #0 ; STA PPUCTRL
        0x8D, 0x01, 0x20,                      # STA PPUMASK
        0xA9, 0x03, 0x85, ZP_LIVES,            # LDA #3 ; STA lives
        0xA9, 0x00,
        0x85, ZP_FRAME_COUNTER,
        0x85, ZP_SCORE_LO,
        0x85, ZP_SCORE_HI,
        0x85, ZP_CONTROLLER1,
        0xA9, 0x01, 0x85, ZP_LEVEL,            # LDA #1 ; STA level
        0xAD, 0x02, 0x20,                      # LDA $2002 (clear vblank latch)
    ]
    wait1_off = reset_off + len(reset_code)
    reset_code += [
        0xAD, 0x02, 0x20,                      # LDA $2002
        0x10, 0xFB,                            # BPL -5  → wait1
        0xAD, 0x02, 0x20,                      # LDA $2002
        0x10, 0xFB,                            # BPL -5  → wait2
        0xA9, 0x80, 0x8D, 0x00, 0x20,          # LDA #$80 ; STA PPUCTRL  (enable NMI)
    ]
    main_off = reset_off + len(reset_code)
    main_addr = 0x8000 + main_off
    reset_code += [
        0x4C, main_addr & 0xFF, (main_addr >> 8) & 0xFF,
    ]
    _emit(prg, reset_off, reset_code)

    nmi_off = 0x0080
    nmi_code = [
        0x48, 0x8A, 0x48, 0x98, 0x48,          # PHA ; TXA ; PHA ; TYA ; PHA
        0xE6, ZP_FRAME_COUNTER,                # INC frame_counter
        0xA9, 0x01, 0x8D, 0x16, 0x40,          # LDA #1 ; STA $4016
        0xA9, 0x00, 0x8D, 0x16, 0x40,          # LDA #0 ; STA $4016
        0x85, ZP_CONTROLLER1,                  # STA controller1 (clear before ROL)
        0xA2, 0x08,                            # LDX #8
    ]
    read_loop_off_in_nmi = len(nmi_code)
    nmi_code += [
        0xAD, 0x16, 0x40,                      # LDA $4016
        0x4A,                                  # LSR A
        0x26, ZP_CONTROLLER1,                  # ROL controller1
        0xCA,                                  # DEX
        0xD0, (256 - 9) & 0xFF,                # BNE -9 → top of read loop (loop body = 9 bytes)
    ]
    if with_game_over:
        nmi_code += [
            0xA5, ZP_CONTROLLER1, 0x29, 0x80,      # LDA controller1 ; AND #$80
            0xF0, 0x16,                            # BEQ +22 (skip A handling)
            0xC6, ZP_LIVES,                        # DEC lives
            0x10, 0x12,                            # BPL +18 (lives ≥0, skip reset)
            0xA9, 0x03, 0x85, ZP_LIVES,            # LDA #3 ; STA lives
            0xA9, 0x00, 0x85, ZP_SCORE_LO,         # LDA #0 ; STA score_lo
            0x85, ZP_SCORE_HI,                     # STA score_hi
            0xA9, 0x01, 0x85, ZP_LEVEL,            # LDA #1 ; STA level
            0xA9, 0x00, 0x85, ZP_FRAME_COUNTER,    # LDA #0 ; STA frame_counter
        ]
    else:
        nmi_code += [
            0xA5, ZP_CONTROLLER1, 0x29, 0x80,      # LDA controller1 ; AND #$80
            0xF0, 0x02,                            # BEQ +2
            0xC6, ZP_LIVES,                        # DEC lives
        ]
    nmi_code += [
        0xA5, ZP_CONTROLLER1, 0x29, 0x40,      # LDA controller1 ; AND #$40
        0xF0, 0x06,                            # BEQ +6
        0xE6, ZP_SCORE_LO,                     # INC score_lo
        0xD0, 0x02,                            # BNE +2
        0xE6, ZP_SCORE_HI,                     # INC score_hi
    ]
    nmi_code += [
        0xA5, ZP_CONTROLLER1, 0x29, 0x10,      # LDA controller1 ; AND #$10 (Start)
        0xF0, 0x02,                            # BEQ +2
        0xE6, ZP_LEVEL,                        # INC level
    ]
    nmi_code += [
        0xA9, 0x02, 0x8D, 0x14, 0x40,          # LDA #2 ; STA OAMDMA
        0x68, 0xA8, 0x68, 0xAA, 0x68, 0x40,    # PLA ; TAY ; PLA ; TAX ; PLA ; RTI
    ]
    _emit(prg, nmi_off, nmi_code)

    nmi_addr = 0x8000 + nmi_off
    reset_addr = 0x8000 + reset_off
    prg[0x3FFA] = nmi_addr & 0xFF
    prg[0x3FFB] = (nmi_addr >> 8) & 0xFF
    prg[0x3FFC] = reset_addr & 0xFF
    prg[0x3FFD] = (reset_addr >> 8) & 0xFF
    prg[0x3FFE] = reset_addr & 0xFF
    prg[0x3FFF] = (reset_addr >> 8) & 0xFF

    return INES_HEADER + bytes(prg)


EXPECTED_GAME_VARS: Dict[int, str] = {
    ZP_FRAME_COUNTER: "frame_counter",
    ZP_LIVES: "lives",
    ZP_SCORE_LO: "score_lo",
    ZP_SCORE_HI: "score_hi",
    ZP_LEVEL: "level",
    ZP_CONTROLLER1: "controller1",
}


def write_to(path) -> Path:
    p = Path(path)
    p.write_bytes(build_rom())
    return p


if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/game_synth.nes"
    write_to(out)
    print(f"wrote {out}")
