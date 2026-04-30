"""Mini programme 6502 fait à la main + désassemblage + annotation NES."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qlnes import QL6502, annotate


def make_image() -> bytes:
    image = bytearray(0x10000)
    code = bytes(
        [
            0xA9, 0x03,            # LDA #3
            0x85, 0x10,            # STA $10
            0xA9, 0x00,            # LDA #0
            0x85, 0x11,            # STA $11
            0x85, 0x12,            # STA $12
            0xAD, 0x16, 0x40,      # LDA $4016        (controller read)
            0x29, 0x01,            # AND #$01
            0x8D, 0x00, 0x02,      # STA $0200        (sprite_0_y)
            0xA2, 0x00,            # LDX #0
            0xE8,                  # INX              (frame loop)
            0x8E, 0x05, 0x20,      # STX $2005
            0xAD, 0x02, 0x20,      # LDA $2002
            0x4C, 0x14, 0x80,      # JMP $8014
        ]
    )
    image[0x8000 : 0x8000 + len(code)] = code
    image[0xFFFC] = 0x00
    image[0xFFFD] = 0x80
    image[0xFFFA] = 0x14
    image[0xFFFB] = 0x80
    return bytes(image)


def main() -> int:
    image = make_image()
    raw_asm = (
        QL6502()
        .load_image(image, "test.bin")
        .mark_blank(0x0000, 0x7FFF)
        .generate_asm()
    )
    print("=== RAW QL6502 OUTPUT ===")
    code_block = "\n".join(
        line for line in raw_asm.splitlines() if line.startswith("L_8")
    )
    print(code_block[:1200])
    print()

    annotated, report = annotate(raw_asm)
    print("=== ANNOTATED ===")
    annotated_block = "\n".join(
        line for line in annotated.splitlines() if line.startswith(("L_8", "P", "J", "A", "O", "z", "r", "s"))
    )
    print(annotated_block[:1200])
    print()

    print("=== REPORT ===")
    print(json.dumps(report.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
