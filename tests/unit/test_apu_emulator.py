"""ApuEmulator orchestrator tests — register dispatch, frame counter, render."""

import pytest

from qlnes.apu import ApuEmulator


def test_init_creates_4_channels_plus_dmc_stub():
    emu = ApuEmulator()
    assert emu.pulse1 is not None
    assert emu.pulse2 is not None
    assert emu.triangle is not None
    assert emu.noise is not None
    assert emu.dmc is not None


def test_status_register_4015_enables_each_channel():
    emu = ApuEmulator()
    emu.write(0x4015, 0x0F, cycle=0)  # pulse1+pulse2+tri+noise enabled
    assert emu.pulse1.enabled is True
    assert emu.pulse2.enabled is True
    assert emu.triangle.enabled is True
    assert emu.noise.enabled is True
    assert emu.dmc.enabled is False  # bit 4 = 0


def test_status_register_disable_zeros_lengths():
    emu = ApuEmulator()
    emu.write(0x4015, 0x01, cycle=0)
    emu.write(0x4003, 0x08, cycle=1)  # load pulse1 length
    assert emu.pulse1.length_counter > 0
    emu.write(0x4015, 0x00, cycle=2)  # disable
    assert emu.pulse1.length_counter == 0


def test_pulse1_register_dispatch_routes_4000_through_4003():
    emu = ApuEmulator()
    emu.write(0x4015, 0x01, cycle=0)
    emu.write(0x4000, 0x3F, cycle=1)
    emu.write(0x4001, 0x88, cycle=2)
    emu.write(0x4002, 0xFD, cycle=3)
    emu.write(0x4003, 0x08, cycle=4)
    assert emu.pulse1.duty == 0
    assert emu.pulse1.constant_volume is True
    assert emu.pulse1.volume_or_period == 15
    assert emu.pulse1.sweep_enable is True
    assert emu.pulse1.sweep_negate is True
    assert emu.pulse1.timer_period & 0xFF == 0xFD
    assert emu.pulse1.length_counter > 0


def test_pulse2_register_dispatch_routes_4004_through_4007():
    emu = ApuEmulator()
    emu.write(0x4015, 0x02, cycle=0)
    emu.write(0x4004, 0x3F, cycle=1)
    emu.write(0x4007, 0x08, cycle=2)
    assert emu.pulse2.duty == 0
    assert emu.pulse2.length_counter > 0
    assert emu.pulse1.length_counter == 0


def test_triangle_register_dispatch():
    emu = ApuEmulator()
    emu.write(0x4015, 0x04, cycle=0)
    emu.write(0x4008, 0xFF, cycle=1)
    emu.write(0x400B, 0x08, cycle=2)
    assert emu.triangle.control_flag is True
    assert emu.triangle.length_counter > 0


def test_noise_register_dispatch():
    emu = ApuEmulator()
    emu.write(0x4015, 0x08, cycle=0)
    emu.write(0x400C, 0x3F, cycle=1)
    emu.write(0x400E, 0x80, cycle=2)
    emu.write(0x400F, 0x08, cycle=3)
    assert emu.noise.constant_volume is True
    assert emu.noise.mode is True
    assert emu.noise.length_counter > 0


def test_dmc_writes_recorded_in_stub():
    emu = ApuEmulator()
    emu.write(0x4010, 0x0F, cycle=0)
    emu.write(0x4011, 0x40, cycle=1)
    assert emu.dmc.last_write[0] == 0x0F
    assert emu.dmc.last_write[1] == 0x40
    assert emu.dmc.output() == 0  # stub never emits


def test_4017_sets_frame_counter_mode():
    emu = ApuEmulator()
    emu.write(0x4017, 0x80, cycle=0)
    assert emu._frame_mode_5step is True
    emu.write(0x4017, 0x00, cycle=10)
    assert emu._frame_mode_5step is False


def test_render_until_emits_correct_sample_count():
    """50 ms NTSC ≈ 89 488 cycles → ~2205 samples at 44.1 kHz."""
    emu = ApuEmulator()
    pcm = emu.render_until(cycle=89_488)
    n_samples = len(pcm) // 2
    expected = 44_100 // 20  # 50ms
    assert abs(n_samples - expected) <= 2


def test_render_until_silence_produces_constant_dc():
    emu = ApuEmulator()
    pcm = emu.render_until(cycle=10_000)
    samples = [int.from_bytes(pcm[i : i + 2], "little", signed=True) for i in range(0, len(pcm), 2)]
    # Silent → all samples at the resampler's DC offset (-16384).
    assert all(s == -16384 for s in samples)


def test_write_at_past_cycle_raises():
    emu = ApuEmulator()
    emu.write(0x4015, 0x01, cycle=100)
    with pytest.raises(ValueError, match="predates"):
        emu.write(0x4000, 0x3F, cycle=50)


def test_render_pulse_produces_nonzero_audio():
    """Configure pulse1 at audible frequency and verify the output isn't constant."""
    emu = ApuEmulator()
    emu.write(0x4015, 0x01, cycle=0)
    emu.write(0x4000, 0xBF, cycle=1)  # duty 50%, halt, const vol 15
    emu.write(0x4002, 0xFD, cycle=2)
    emu.write(0x4003, 0x00, cycle=3)
    pcm = emu.render_until(cycle=178_977)  # 100ms NTSC
    samples = [int.from_bytes(pcm[i : i + 2], "little", signed=True) for i in range(0, len(pcm), 2)]
    assert len(set(samples)) > 1, "audio should vary across the buffer"


def test_two_consecutive_renders_are_byte_identical():
    """Determinism (NFR-REL-1) — same writes → same PCM."""

    def run() -> bytes:
        e = ApuEmulator()
        e.write(0x4015, 0x01, cycle=0)
        e.write(0x4000, 0xBF, cycle=1)
        e.write(0x4002, 0x10, cycle=2)
        e.write(0x4003, 0x08, cycle=3)
        return e.render_until(cycle=10_000)

    assert run() == run()


def test_reset_clears_state():
    emu = ApuEmulator()
    emu.write(0x4015, 0x0F, cycle=0)
    emu.write(0x4003, 0x08, cycle=1)
    emu.reset()
    assert emu.pulse1.enabled is False
    assert emu.pulse1.length_counter == 0
    assert emu._cpu_cycle == 0
