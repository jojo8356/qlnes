"""NMI emulation. Architecture step 20.6.

NES music drivers run from the NMI handler at 60.0988 Hz (NTSC).
py65 has no built-in NMI; we manually push the interrupt frame and
jump to a target address. Then the runner steps the CPU until RTI
restores PC.

The standard 6502 NMI sequence is:
    push PCH
    push PCL
    push P (with B=0, U=1)
    set I flag
    PC = target (usually [$FFFA] but optionally a caller-supplied addr)
    7 cycles charged

Two helpers:

- `trigger_nmi_to(mpu, mem, target_pc)` — jump to an explicit target.
  Used by `InProcessRunner.run_song` when the engine handler has
  identified the play_addr (story F.4).
- `trigger_nmi(mpu, mem)` — wraps `trigger_nmi_to` after reading the
  ROM's NMI vector at $FFFA-$FFFB. Used by `run_natural_boot` where
  we trust the ROM to have set up a valid NMI handler.
"""
from __future__ import annotations

NMI_VECTOR_LO = 0xFFFA
NMI_VECTOR_HI = 0xFFFB
NMI_HANDLER_CYCLES = 7

# NTSC: 1789773 Hz CPU / 60.0988 Hz NMI ≈ 29780.5 cycles per frame.
# We use 29780 (truncated) to stay deterministic; the cumulative drift
# is < 1 cycle per minute, well below APU audibility.
NTSC_CYCLES_PER_FRAME = 29780


def trigger_nmi_to(mpu, mem, target_pc: int) -> None:
    """Inject an NMI interrupt jumping to a caller-supplied target PC.

    Modifies mpu.sp, mpu.p, mpu.pc, mpu.processorCycles and writes 3
    bytes to the stack page via mem.__setitem__.
    """
    pc_hi = (mpu.pc >> 8) & 0xFF
    pc_lo = mpu.pc & 0xFF
    # B flag clear, U flag set on the pushed P (per 6502 reference)
    p_pushed = (mpu.p | 0x20) & ~0x10
    mem[0x0100 + mpu.sp] = pc_hi
    mpu.sp = (mpu.sp - 1) & 0xFF
    mem[0x0100 + mpu.sp] = pc_lo
    mpu.sp = (mpu.sp - 1) & 0xFF
    mem[0x0100 + mpu.sp] = p_pushed & 0xFF
    mpu.sp = (mpu.sp - 1) & 0xFF
    mpu.p |= 0x04  # mask further IRQs (NMIs are non-maskable)
    mpu.pc = target_pc & 0xFFFF
    mpu.processorCycles += NMI_HANDLER_CYCLES


def trigger_nmi(mpu, mem) -> None:
    """Inject an NMI jumping to the ROM's NMI vector at $FFFA-$FFFB."""
    target = mem[NMI_VECTOR_LO] | (mem[NMI_VECTOR_HI] << 8)
    trigger_nmi_to(mpu, mem, target)
