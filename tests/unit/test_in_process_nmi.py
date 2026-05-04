"""Unit tests for qlnes.audio.in_process.nmi.trigger_nmi / trigger_nmi_to."""
from __future__ import annotations

from qlnes.audio.in_process.memory import NROMMemory
from qlnes.audio.in_process.nmi import (
    NMI_HANDLER_CYCLES,
    NTSC_CYCLES_PER_FRAME,
    trigger_nmi,
    trigger_nmi_to,
)


class _FakeMpu:
    """Minimal py65-like MPU: just the attributes trigger_nmi mutates."""

    def __init__(self, pc=0x1234, sp=0xFF, p=0x24, cycles=0):
        self.pc = pc
        self.sp = sp
        self.p = p
        self.processorCycles = cycles


def _prg_with_nmi_vector(target: int) -> bytes:
    """32 KB PRG whose $FFFA-$FFFB hold `target` little-endian."""
    prg = bytearray(0x8000)
    # $FFFA in CPU = offset 0x7FFA in PRG; $FFFB = 0x7FFB
    prg[0x7FFA] = target & 0xFF
    prg[0x7FFB] = (target >> 8) & 0xFF
    return bytes(prg)


def test_pc_set_to_nmi_vector():
    mem = NROMMemory(_prg_with_nmi_vector(0x9080))
    mpu = _FakeMpu(pc=0x1234)
    trigger_nmi(mpu, mem)
    assert mpu.pc == 0x9080


def test_three_bytes_pushed_to_stack():
    mem = NROMMemory(_prg_with_nmi_vector(0x8000))
    mpu = _FakeMpu(pc=0x1234, sp=0xFF, p=0x24)
    trigger_nmi(mpu, mem)
    # Stack grows downward from $01FF; sp lands at FF - 3 = FC
    assert mpu.sp == 0xFC
    # PCH at $01FF, PCL at $01FE, P at $01FD (in push order)
    assert mem[0x01FF] == 0x12  # PC high
    assert mem[0x01FE] == 0x34  # PC low
    # Pushed P: B clear, U set → (0x24 | 0x20) & ~0x10 = 0x24
    assert mem[0x01FD] == 0x24


def test_pushed_p_has_b_clear_and_u_set():
    """Even if B was set in the running flags, the pushed copy clears B."""
    mem = NROMMemory(_prg_with_nmi_vector(0x8000))
    mpu = _FakeMpu(p=0x10)  # B flag set
    trigger_nmi(mpu, mem)
    pushed_p = mem[0x01FD]
    assert pushed_p & 0x10 == 0  # B clear
    assert pushed_p & 0x20 == 0x20  # U set


def test_i_flag_set_after_trigger():
    mem = NROMMemory(_prg_with_nmi_vector(0x8000))
    mpu = _FakeMpu(p=0x00)
    trigger_nmi(mpu, mem)
    assert mpu.p & 0x04 == 0x04


def test_seven_cycles_charged():
    mem = NROMMemory(_prg_with_nmi_vector(0x8000))
    mpu = _FakeMpu(cycles=1000)
    trigger_nmi(mpu, mem)
    assert mpu.processorCycles == 1000 + NMI_HANDLER_CYCLES


def test_sp_wraps_correctly():
    """If sp starts at $02 the third push lands at $00 then wraps to $FF."""
    mem = NROMMemory(_prg_with_nmi_vector(0x8000))
    mpu = _FakeMpu(sp=0x01)
    trigger_nmi(mpu, mem)
    # 0x01 → push at 0x101, sp=0x00
    # → push at 0x100, sp=0xFF
    # → push at 0x1FF, sp=0xFE
    assert mpu.sp == 0xFE


def test_ntsc_cycles_per_frame_constant():
    # 1789773 Hz / 60.0988 Hz ≈ 29780.5
    assert NTSC_CYCLES_PER_FRAME == 29780


# ---- trigger_nmi_to (F.4) -------------------------------------------------


def test_trigger_nmi_to_sets_pc_to_explicit_target():
    """trigger_nmi_to lands PC at the caller-supplied target,
    NOT at the ROM's $FFFA-$FFFB vector."""
    # ROM vector points to $8000, but we pass an entirely different target
    mem = NROMMemory(_prg_with_nmi_vector(0x8000))
    mpu = _FakeMpu(pc=0x1234)
    trigger_nmi_to(mpu, mem, target_pc=0xC0DE)
    assert mpu.pc == 0xC0DE


def test_trigger_nmi_to_pushes_same_3_bytes_as_trigger_nmi():
    """Stack semantics are identical between trigger_nmi and trigger_nmi_to."""
    mem = NROMMemory(_prg_with_nmi_vector(0x8000))
    mpu = _FakeMpu(pc=0x1234, sp=0xFF, p=0x24)
    trigger_nmi_to(mpu, mem, target_pc=0x9090)
    assert mpu.sp == 0xFC
    assert mem[0x01FF] == 0x12  # PC high
    assert mem[0x01FE] == 0x34  # PC low
    assert mem[0x01FD] == 0x24  # P (B clear, U set)
    assert mpu.p & 0x04 == 0x04
    assert mpu.processorCycles == NMI_HANDLER_CYCLES


def test_trigger_nmi_target_pc_masked_to_16_bits():
    """target_pc is masked to 16 bits — passing 0x12345 lands at 0x2345."""
    mem = NROMMemory(_prg_with_nmi_vector(0x8000))
    mpu = _FakeMpu()
    trigger_nmi_to(mpu, mem, target_pc=0x12345)
    assert mpu.pc == 0x2345


def test_trigger_nmi_wraps_trigger_nmi_to():
    """trigger_nmi reads ROM vector then delegates to trigger_nmi_to.
    Verify by comparing post-state when both are called with equivalent
    inputs."""
    mem_a = NROMMemory(_prg_with_nmi_vector(0xABCD))
    mpu_a = _FakeMpu(pc=0x4242, sp=0xF0, p=0x30)
    trigger_nmi(mpu_a, mem_a)

    mem_b = NROMMemory(_prg_with_nmi_vector(0x0000))  # vector irrelevant
    mpu_b = _FakeMpu(pc=0x4242, sp=0xF0, p=0x30)
    trigger_nmi_to(mpu_b, mem_b, target_pc=0xABCD)

    assert mpu_a.pc == mpu_b.pc == 0xABCD
    assert mpu_a.sp == mpu_b.sp
    assert mpu_a.p == mpu_b.p
    assert mpu_a.processorCycles == mpu_b.processorCycles
    # Pushed bytes equal at the relevant stack slots
    for slot in (0x01F0, 0x01EF, 0x01EE):
        assert mem_a[slot] == mem_b[slot]
