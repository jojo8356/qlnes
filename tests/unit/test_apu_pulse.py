"""Pulse channel spec-compliance tests.

Per-register-write effects, envelope decay, sweep mute, length counter halt.
NOT testing sample-equivalence to FCEUX — that's phase 7.3+.
"""

import pytest

from qlnes.apu.pulse import PulseChannel
from qlnes.apu.tables import LENGTH_TABLE


def test_init_rejects_invalid_channel():
    with pytest.raises(ValueError):
        PulseChannel(channel=2)


def test_register0_decodes_duty_and_volume():
    p = PulseChannel(channel=0)
    p.register_write(0, 0xBF)  # 1011 1111: duty=2, halt=1, const=1, vol=15
    assert p.duty == 2
    assert p.length_halt is True
    assert p.constant_volume is True
    assert p.volume_or_period == 15


def test_register1_sets_sweep_and_reload_flag():
    p = PulseChannel(channel=0)
    p.register_write(1, 0x88)  # 1000 1000: enable=1, period=0, negate=1, shift=0
    assert p.sweep_enable is True
    assert p.sweep_period == 0
    assert p.sweep_negate is True
    assert p.sweep_shift == 0
    assert p.sweep_reload is True


def test_register2_sets_timer_low_byte():
    p = PulseChannel(channel=0)
    p.register_write(2, 0xFD)
    assert p.timer_period == 0xFD


def test_register3_sets_timer_high_and_length():
    p = PulseChannel(channel=0)
    p.set_enable(True)
    p.register_write(3, 0x08)  # length idx=1, timer hi=0
    assert p.length_counter == LENGTH_TABLE[1]
    assert p.duty_step == 0
    assert p.envelope_start is True


def test_register3_does_not_load_length_when_disabled():
    p = PulseChannel(channel=0)
    p.set_enable(False)
    p.register_write(3, 0x08)
    assert p.length_counter == 0


def test_set_enable_false_zeros_length():
    p = PulseChannel(channel=0)
    p.set_enable(True)
    p.register_write(3, 0x08)
    assert p.length_counter > 0
    p.set_enable(False)
    assert p.length_counter == 0


def test_output_is_zero_when_disabled():
    p = PulseChannel(channel=0)
    p.register_write(0, 0x3F)  # const vol 15
    p.duty_step = 1  # would output 15 if enabled
    assert p.output() == 0


def test_output_is_zero_when_length_zero():
    p = PulseChannel(channel=0)
    p.set_enable(True)
    p.register_write(0, 0x3F)
    # length_counter remains 0
    assert p.output() == 0


def test_output_constant_volume_path():
    p = PulseChannel(channel=0)
    p.set_enable(True)
    p.register_write(0, 0x3F)  # duty=0, const=1, vol=15
    p.register_write(2, 0x10)  # timer ≥ 8 to avoid sweep mute
    p.register_write(3, 0x08)  # load length
    p.duty_step = 1  # PULSE_DUTY[0][1] == 1
    assert p.output() == 15


def test_output_envelope_path_pre_envelope_clock_returns_decay_zero():
    p = PulseChannel(channel=0)
    p.set_enable(True)
    p.register_write(0, 0x0F)  # duty=0, halt=0, const=0 (envelope), vol/period=15
    p.register_write(2, 0x10)
    p.register_write(3, 0x08)
    p.duty_step = 1
    # envelope_decay starts at 0 until first quarter-frame tick reloads to 15.
    assert p.output() == 0
    p.clock_envelope()
    assert p.envelope_decay == 15
    assert p.output() == 15


def test_envelope_decays_one_step_per_period_plus_one_clocks():
    p = PulseChannel(channel=0)
    p.set_enable(True)
    p.register_write(0, 0x05)  # const=0, vol/period=5
    p.register_write(2, 0x10)
    p.register_write(3, 0x08)
    p.duty_step = 1
    # First clock loads decay=15, divider=5.
    p.clock_envelope()
    assert p.envelope_decay == 15
    # Next 5 clocks just decrement the divider (no decay change).
    for _ in range(5):
        p.clock_envelope()
    assert p.envelope_decay == 15
    # 6th clock from "loaded" state decrements decay.
    p.clock_envelope()
    assert p.envelope_decay == 14


def test_envelope_loops_when_length_halt_set():
    p = PulseChannel(channel=0)
    p.set_enable(True)
    p.register_write(0, 0x20)  # halt=1, const=0, vol/period=0
    p.register_write(2, 0x10)
    p.register_write(3, 0x08)
    p.clock_envelope()  # load: decay=15
    # At period=0 each subsequent clock decrements decay by one. 15 clocks
    # bring decay to 0; the 16th wraps back to 15 because halt=1 (loop).
    for _ in range(15):
        p.clock_envelope()
    assert p.envelope_decay == 0
    p.clock_envelope()
    assert p.envelope_decay == 15


def test_length_counter_decrements_on_half_frame():
    p = PulseChannel(channel=0)
    p.set_enable(True)
    p.register_write(3, 0x08)  # length = LENGTH_TABLE[1] = 254
    initial = p.length_counter
    p.clock_length_and_sweep()
    assert p.length_counter == initial - 1


def test_length_counter_does_not_decrement_when_halt():
    p = PulseChannel(channel=0)
    p.set_enable(True)
    p.register_write(0, 0x20)  # halt = 1
    p.register_write(3, 0x08)
    initial = p.length_counter
    p.clock_length_and_sweep()
    assert p.length_counter == initial


def test_sweep_mutes_when_timer_period_below_8():
    p = PulseChannel(channel=0)
    p.set_enable(True)
    p.register_write(0, 0x3F)
    p.register_write(2, 0x05)  # timer = 5 < 8 → mute
    p.register_write(3, 0x08)
    p.duty_step = 1
    assert p.output() == 0


def test_sweep_mutes_when_target_overflows():
    p = PulseChannel(channel=0)
    p.set_enable(True)
    p.register_write(0, 0x3F)
    p.register_write(2, 0xFF)
    p.register_write(3, 0x07)  # timer_period = 0x7FF (max), shift forces overflow
    p.register_write(1, 0x80)  # sweep enable, no negate, shift=0
    p.duty_step = 1
    # Target = period + (period >> 0) = 2*period > 0x7FF when period > 0x3FF.
    assert p.output() == 0


def test_sweep_negate_pulse1_uses_ones_complement():
    # Pulse 1: target = period + (-(period >> shift) - 1)
    p = PulseChannel(channel=0)
    p.timer_period = 0x100
    p.sweep_shift = 1
    p.sweep_negate = True
    target = p._target_period()
    assert target == 0x100 + (-(0x100 >> 1) - 1)


def test_sweep_negate_pulse2_uses_twos_complement():
    p = PulseChannel(channel=1)
    p.timer_period = 0x100
    p.sweep_shift = 1
    p.sweep_negate = True
    target = p._target_period()
    assert target == 0x100 + -(0x100 >> 1)


def test_timer_decrements_each_apu_tick():
    p = PulseChannel(channel=0)
    p.timer_period = 5
    p.timer = 5
    p.tick()
    assert p.timer == 4


def test_timer_reloads_and_advances_duty_step_at_zero():
    p = PulseChannel(channel=0)
    p.timer_period = 5
    p.timer = 0
    p.duty_step = 3
    p.tick()
    assert p.timer == 5
    assert p.duty_step == 4


def test_duty_step_wraps_at_8():
    p = PulseChannel(channel=0)
    p.timer_period = 0
    p.timer = 0
    p.duty_step = 7
    p.tick()
    assert p.duty_step == 0
