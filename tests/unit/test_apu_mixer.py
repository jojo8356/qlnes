"""Mixer + resampler tests."""

from qlnes.apu.mixer import CPU_HZ_NTSC, DEFAULT_SAMPLE_RATE, Mixer


def test_mix_zero_when_all_channels_silent():
    m = Mixer()
    assert m.mix(0, 0, 0, 0, 0) == 0


def test_mix_only_pulse_uses_pulse_lut():
    from qlnes.apu.tables import PULSE_MIX

    m = Mixer()
    assert m.mix(15, 15, 0, 0, 0) == PULSE_MIX[30]
    assert m.mix(7, 8, 0, 0, 0) == PULSE_MIX[15]


def test_mix_only_tnd_uses_tnd_lut():
    from qlnes.apu.tables import TND_MIX

    m = Mixer()
    # 3*tri + 2*noise + dmc with tri=10 → idx=30
    assert m.mix(0, 0, 10, 0, 0) == TND_MIX[30]
    # tri=0, noise=15, dmc=0 → idx=30
    assert m.mix(0, 0, 0, 15, 0) == TND_MIX[30]


def test_mix_combines_pulse_and_tnd():
    from qlnes.apu.tables import PULSE_MIX, TND_MIX

    m = Mixer()
    out = m.mix(15, 15, 10, 15, 0)
    assert out == PULSE_MIX[30] + TND_MIX[60]


def test_resampler_emits_correct_sample_count_for_one_second():
    """Feeding CPU_HZ_NTSC samples should yield ~sample_rate output samples."""
    m = Mixer(sample_rate=DEFAULT_SAMPLE_RATE)
    for _ in range(CPU_HZ_NTSC):
        m.feed_sample(0)
    pcm = m.flush()
    n_samples = len(pcm) // 2
    # Allow ±1 sample tolerance due to integer accumulator boundary.
    assert abs(n_samples - DEFAULT_SAMPLE_RATE) <= 1


def test_resampler_emits_correct_count_for_50ms():
    m = Mixer(sample_rate=DEFAULT_SAMPLE_RATE)
    cycles = CPU_HZ_NTSC // 20  # 50ms
    for _ in range(cycles):
        m.feed_sample(0)
    pcm = m.flush()
    n_samples = len(pcm) // 2
    assert abs(n_samples - DEFAULT_SAMPLE_RATE // 20) <= 1


def test_resampler_silence_produces_dc_offset():
    """All-zero channel sums map to mixer LUT index 0 → 0; the resampler
    centers around -16384 by default to fit signed PCM. This test pins that
    behavior so phase 7.3+ knows what to expect."""
    m = Mixer()
    for _ in range(1000):
        m.feed_sample(0)
    pcm = m.flush()
    # Each sample is int16 LE. Decode the first one.
    s0 = int.from_bytes(pcm[0:2], "little", signed=True)
    assert s0 == -16384


def test_resampler_constant_signal_produces_constant_output():
    m = Mixer()
    for _ in range(1000):
        m.feed_sample(20000)
    pcm = m.flush()
    samples = [int.from_bytes(pcm[i : i + 2], "little", signed=True) for i in range(0, len(pcm), 2)]
    # All output samples should equal 20000 - 16384 = 3616.
    assert all(s == 3616 for s in samples)


def test_flush_clears_buffer():
    m = Mixer()
    for _ in range(100000):
        m.feed_sample(0)
    out1 = m.flush()
    out2 = m.flush()
    assert len(out1) > 0
    assert out2 == b""


def test_resampler_deterministic_across_runs():
    """Same input sequence → byte-identical output."""

    def run() -> bytes:
        m = Mixer()
        for i in range(10000):
            m.feed_sample(i & 0x7FFF)
        return m.flush()

    assert run() == run()
