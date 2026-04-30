"""Génère un ROM 6502 64K synthétique exerçant toutes les patterns à détecter.

Layout :
- $8000  : reset handler   (init + JSR oam_setup + JSR pointer_use + JMP main_loop)
- $8040  : main_loop       (LDA PPUSTATUS ; JMP main_loop)
- $8050  : NMI handler     (INC frame_counter ; JSR controller_read ; OAMDMA ; rti)
- $8080  : controller_read (8 ROL controller1 + 8 ROL controller2)
- $8100  : oam_setup       (LDX index, STA $0200,X, RTS)
- $8120  : pointer_use     (LDA (ptr_lo),Y, JMP ($ptr_lo) via JMP indirect)
- $FFFA  : NMI vector → $8050
- $FFFC  : RESET → $8000
- $FFFE  : IRQ  → $8000
"""

from typing import Dict


ZP_FRAME_COUNTER = 0x10
ZP_LIVES = 0x11
ZP_SCORE = 0x12
ZP_CONTROLLER1 = 0x20
ZP_CONTROLLER2 = 0x21
ZP_OAM_INDEX = 0x30
ZP_PTR_LO = 0x40
ZP_PTR_HI = 0x41


def build_image() -> bytes:
    image = bytearray(0x10000)

    reset = bytes(
        [
            0x78,                                # SEI
            0xD8,                                # CLD
            0xA9, 0x03, 0x85, ZP_LIVES,          # LDA #3 ; STA lives
            0xA9, 0x00, 0x85, ZP_SCORE,          # LDA #0 ; STA score
            0xA9, 0x02, 0x8D, 0x14, 0x40,        # LDA #$02 ; STA OAMDMA
            0xA2, 0x00, 0x86, ZP_OAM_INDEX,      # LDX #0 ; STX oam_index
            0xA9, 0x40, 0x85, ZP_PTR_LO,         # LDA #$40 ; STA ptr_lo
            0xA9, 0x80, 0x85, ZP_PTR_HI,         # LDA #$80 ; STA ptr_hi
            0x20, 0x00, 0x81,                    # JSR oam_setup
            0x20, 0x20, 0x81,                    # JSR pointer_use
            0x4C, 0x40, 0x80,                    # JMP main_loop
        ]
    )
    image[0x8000 : 0x8000 + len(reset)] = reset

    main_loop = bytes(
        [
            0xAD, 0x02, 0x20,                    # LDA PPUSTATUS
            0x4C, 0x40, 0x80,                    # JMP main_loop
        ]
    )
    image[0x8040 : 0x8040 + len(main_loop)] = main_loop

    nmi = bytes(
        [
            0x48,                                # PHA
            0xE6, ZP_FRAME_COUNTER,              # INC frame_counter
            0x20, 0x80, 0x80,                    # JSR controller_read
            0xA9, 0x02, 0x8D, 0x14, 0x40,        # LDA #2 ; STA OAMDMA
            0x68, 0x40,                          # PLA ; RTI
        ]
    )
    image[0x8050 : 0x8050 + len(nmi)] = nmi

    cr = []
    cr += [0xA9, 0x01, 0x8D, 0x16, 0x40]         # LDA #1 ; STA $4016
    cr += [0xA9, 0x00, 0x8D, 0x16, 0x40]         # LDA #0 ; STA $4016
    for _ in range(8):
        cr += [0xAD, 0x16, 0x40, 0x4A, 0x26, ZP_CONTROLLER1]
    for _ in range(8):
        cr += [0xAD, 0x17, 0x40, 0x4A, 0x26, ZP_CONTROLLER2]
    cr += [0x60]
    image[0x8080 : 0x8080 + len(cr)] = bytes(cr)

    oam_setup = bytes(
        [
            0xA6, ZP_OAM_INDEX,                  # LDX oam_index
            0xA9, 0x40, 0x9D, 0x00, 0x02,        # LDA #$40 ; STA $0200,X
            0xE8, 0x9D, 0x00, 0x02,              # INX ; STA $0200,X
            0xE8, 0x86, ZP_OAM_INDEX,            # INX ; STX oam_index
            0x60,                                # RTS
        ]
    )
    image[0x8100 : 0x8100 + len(oam_setup)] = oam_setup

    pointer_use = bytes(
        [
            0xA0, 0x00,                          # LDY #0
            0xB1, ZP_PTR_LO,                     # LDA (ptr_lo),Y
            0xA0, 0x01,                          # LDY #1
            0xB1, ZP_PTR_LO,                     # LDA (ptr_lo),Y
            0x60,                                # RTS
        ]
    )
    image[0x8120 : 0x8120 + len(pointer_use)] = pointer_use

    image[0xFFFA] = 0x50
    image[0xFFFB] = 0x80
    image[0xFFFC] = 0x00
    image[0xFFFD] = 0x80
    image[0xFFFE] = 0x00
    image[0xFFFF] = 0x80

    return bytes(image)


EXPECTED_NAMES: Dict[int, str] = {
    ZP_FRAME_COUNTER: "frame_counter",
    ZP_CONTROLLER1: "controller1_state",
    ZP_CONTROLLER2: "controller2_state",
    ZP_OAM_INDEX: "oam_index",
    ZP_PTR_LO: "ptr0_lo",
    ZP_PTR_HI: "ptr0_hi",
    0x0200: "oam_dma_page",
}


if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/synth.bin"
    open(out, "wb").write(build_image())
    print(f"wrote {out}")
