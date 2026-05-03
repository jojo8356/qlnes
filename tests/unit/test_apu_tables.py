"""Spec-compliance tests for APU lookup tables.

These tests verify table contents against the NESdev wiki specification.
They do NOT test sample-equivalence to FCEUX — that's phase 7.3+ (needs corpus
ROM + FCEUX trace fixture).
"""

from qlnes.apu.tables import (
    DMC_PERIOD_NTSC,
    LENGTH_TABLE,
    NOISE_PERIOD_NTSC,
    PULSE_DUTY,
    PULSE_MIX,
    TND_MIX,
    TRIANGLE_SEQUENCE,
)


def test_length_table_size_and_first_entries():
    assert len(LENGTH_TABLE) == 32
    # NESdev: idx 0 = 10, idx 1 = 254.
    assert LENGTH_TABLE[0] == 10
    assert LENGTH_TABLE[1] == 254


def test_length_table_full_spec():
    expected = (
        10,
        254,
        20,
        2,
        40,
        4,
        80,
        6,
        160,
        8,
        60,
        10,
        14,
        12,
        26,
        14,
        12,
        16,
        24,
        18,
        48,
        20,
        96,
        22,
        192,
        24,
        72,
        26,
        16,
        28,
        32,
        30,
    )
    assert expected == LENGTH_TABLE


def test_pulse_duty_shapes():
    assert len(PULSE_DUTY) == 4
    for seq in PULSE_DUTY:
        assert len(seq) == 8
        assert all(b in (0, 1) for b in seq)


def test_pulse_duty_specific_waveforms():
    # NESdev: 12.5%, 25%, 50%, 25% negated.
    assert PULSE_DUTY[0] == (0, 1, 0, 0, 0, 0, 0, 0)
    assert PULSE_DUTY[1] == (0, 1, 1, 0, 0, 0, 0, 0)
    assert PULSE_DUTY[2] == (0, 1, 1, 1, 1, 0, 0, 0)
    assert PULSE_DUTY[3] == (1, 0, 0, 1, 1, 1, 1, 1)


def test_triangle_sequence_size_and_extrema():
    assert len(TRIANGLE_SEQUENCE) == 32
    assert TRIANGLE_SEQUENCE[0] == 15
    assert TRIANGLE_SEQUENCE[15] == 0
    assert TRIANGLE_SEQUENCE[16] == 0
    assert TRIANGLE_SEQUENCE[31] == 15
    assert max(TRIANGLE_SEQUENCE) == 15
    assert min(TRIANGLE_SEQUENCE) == 0


def test_noise_period_table_size():
    assert len(NOISE_PERIOD_NTSC) == 16
    assert NOISE_PERIOD_NTSC[0] == 4
    assert NOISE_PERIOD_NTSC[-1] == 4068
    assert all(NOISE_PERIOD_NTSC[i] < NOISE_PERIOD_NTSC[i + 1] for i in range(15))


def test_dmc_period_table_size():
    assert len(DMC_PERIOD_NTSC) == 16
    assert DMC_PERIOD_NTSC[0] == 428
    assert DMC_PERIOD_NTSC[-1] == 54


def test_pulse_mix_zero_at_zero():
    assert PULSE_MIX[0] == 0


def test_pulse_mix_monotone_nondecreasing():
    for i in range(30):
        assert PULSE_MIX[i] <= PULSE_MIX[i + 1]


def test_pulse_mix_max_within_q15():
    assert max(PULSE_MIX) <= 32767


def test_tnd_mix_zero_at_zero():
    assert TND_MIX[0] == 0


def test_tnd_mix_monotone_nondecreasing():
    for i in range(202):
        assert TND_MIX[i] <= TND_MIX[i + 1]


def test_tnd_mix_max_within_q15():
    assert max(TND_MIX) <= 32767


def test_pulse_mix_size():
    assert len(PULSE_MIX) == 31  # indices 0..30


def test_tnd_mix_size():
    assert len(TND_MIX) == 203  # indices 0..202


def test_pulse_mix_known_value():
    # i=15 → 95.88 / ((8128/15) + 100) = 95.88 / (541.87 + 100) = 0.1493
    # 0.1493 * 32767 = 4895
    assert PULSE_MIX[15] == 4895


def test_tnd_mix_known_value():
    # j=100 → 163.67 / ((24329/100) + 100) = 163.67 / 343.29 = 0.4767
    # 0.4767 * 32767 = 15622
    assert TND_MIX[100] == 15622
