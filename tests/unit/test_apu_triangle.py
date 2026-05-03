"""Triangle channel spec-compliance tests."""

from qlnes.apu.tables import LENGTH_TABLE, TRIANGLE_SEQUENCE
from qlnes.apu.triangle import TriangleChannel


def test_register0_decodes_control_and_reload_value():
    t = TriangleChannel()
    t.register_write(0, 0xFF)  # control=1, linear=0x7F
    assert t.control_flag is True
    assert t.linear_reload_value == 0x7F


def test_register2_3_set_timer_and_length_and_reload_flag():
    t = TriangleChannel()
    t.set_enable(True)
    t.register_write(2, 0xFD)
    t.register_write(3, 0x08)  # length idx=1, timer hi=0
    assert t.timer_period == 0xFD
    assert t.length_counter == LENGTH_TABLE[1]
    assert t.linear_reload is True


def test_set_enable_false_zeros_length():
    t = TriangleChannel()
    t.set_enable(True)
    t.register_write(3, 0x08)
    assert t.length_counter > 0
    t.set_enable(False)
    assert t.length_counter == 0


def test_output_zero_when_disabled():
    t = TriangleChannel()
    assert t.output() == 0


def test_output_zero_when_length_zero():
    t = TriangleChannel()
    t.set_enable(True)
    t.linear_counter = 1
    assert t.output() == 0


def test_output_zero_when_linear_zero():
    t = TriangleChannel()
    t.set_enable(True)
    t.length_counter = 1
    t.linear_counter = 0
    assert t.output() == 0


def test_output_returns_sequence_value_when_active():
    t = TriangleChannel()
    t.set_enable(True)
    t.length_counter = 1
    t.linear_counter = 1
    t.sequence_step = 0
    assert t.output() == TRIANGLE_SEQUENCE[0]
    t.sequence_step = 16
    assert t.output() == TRIANGLE_SEQUENCE[16]


def test_linear_reload_loads_value_then_clears_unless_control_set():
    t = TriangleChannel()
    t.linear_reload_value = 5
    t.linear_reload = True
    t.control_flag = False
    t.clock_linear()
    assert t.linear_counter == 5
    assert t.linear_reload is False  # cleared because control=False


def test_linear_reload_persists_when_control_set():
    t = TriangleChannel()
    t.linear_reload_value = 5
    t.linear_reload = True
    t.control_flag = True
    t.clock_linear()
    assert t.linear_counter == 5
    assert t.linear_reload is True


def test_linear_decrements_when_not_reloading():
    t = TriangleChannel()
    t.linear_counter = 3
    t.linear_reload = False
    t.clock_linear()
    assert t.linear_counter == 2


def test_length_counter_decrements_on_half_clock():
    t = TriangleChannel()
    t.set_enable(True)
    t.register_write(3, 0x08)
    initial = t.length_counter
    t.clock_length()
    assert t.length_counter == initial - 1


def test_length_counter_does_not_decrement_when_control_set():
    t = TriangleChannel()
    t.set_enable(True)
    t.register_write(0, 0x80)  # control=1
    t.register_write(3, 0x08)
    initial = t.length_counter
    t.clock_length()
    assert t.length_counter == initial


def test_timer_decrements_each_cpu_tick():
    t = TriangleChannel()
    t.timer_period = 5
    t.timer = 5
    t.tick()
    assert t.timer == 4


def test_sequence_step_advances_only_when_both_counters_nonzero():
    t = TriangleChannel()
    t.timer_period = 0
    t.timer = 0
    t.length_counter = 1
    t.linear_counter = 1
    t.sequence_step = 0
    t.tick()
    assert t.sequence_step == 1


def test_sequence_step_frozen_when_linear_is_zero():
    t = TriangleChannel()
    t.timer_period = 0
    t.timer = 0
    t.length_counter = 1
    t.linear_counter = 0
    t.sequence_step = 5
    t.tick()
    assert t.sequence_step == 5


def test_sequence_step_wraps_at_32():
    t = TriangleChannel()
    t.timer_period = 0
    t.timer = 0
    t.length_counter = 1
    t.linear_counter = 1
    t.sequence_step = 31
    t.tick()
    assert t.sequence_step == 0
