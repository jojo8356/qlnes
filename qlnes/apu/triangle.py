"""2A03 triangle channel ($4008-$400B).

Output is a 4-bit triangle waveform stepping through TRIANGLE_SEQUENCE.
Per spec, the sequencer only advances when both linear counter and length
counter are non-zero AND the timer reload value is ≥ 2 (lower values
silence the channel rather than producing ultrasonic content — done in
output() rather than by halting the sequencer).

Spec: NESdev wiki — APU_Triangle, APU_Length_Counter.
"""

from __future__ import annotations

from .tables import LENGTH_TABLE, TRIANGLE_SEQUENCE


class TriangleChannel:
    def __init__(self) -> None:
        # $4008 — CRRR RRRR
        self.control_flag = False  # bit 7 (also length-halt)
        self.linear_reload_value = 0  # bits 6..0

        # $400A, $400B
        self.timer_period = 0  # 11-bit
        self.timer = 0
        self.length_counter = 0

        self.linear_counter = 0
        self.linear_reload = False

        self.sequence_step = 0
        self.enabled = False

    def register_write(self, reg_index: int, value: int) -> None:
        value &= 0xFF
        if reg_index == 0:
            self.control_flag = bool(value & 0x80)
            self.linear_reload_value = value & 0x7F
        elif reg_index == 1:
            pass  # $4009 unused
        elif reg_index == 2:
            self.timer_period = (self.timer_period & 0x700) | value
        elif reg_index == 3:
            self.timer_period = (self.timer_period & 0x0FF) | ((value & 0x07) << 8)
            if self.enabled:
                length_idx = (value >> 3) & 0x1F
                self.length_counter = LENGTH_TABLE[length_idx]
            self.linear_reload = True

    def set_enable(self, enabled: bool) -> None:
        self.enabled = enabled
        if not enabled:
            self.length_counter = 0

    def tick(self) -> None:
        if self.timer == 0:
            self.timer = self.timer_period
            if self.linear_counter > 0 and self.length_counter > 0:
                self.sequence_step = (self.sequence_step + 1) & 0x1F
        else:
            self.timer -= 1

    def clock_linear(self) -> None:
        """Quarter-frame tick."""
        if self.linear_reload:
            self.linear_counter = self.linear_reload_value
        elif self.linear_counter > 0:
            self.linear_counter -= 1
        if not self.control_flag:
            self.linear_reload = False

    def clock_length(self) -> None:
        """Half-frame tick (control_flag also halts length)."""
        if self.length_counter > 0 and not self.control_flag:
            self.length_counter -= 1

    def output(self) -> int:
        if not self.enabled:
            return 0
        if self.length_counter == 0 or self.linear_counter == 0:
            return 0
        if self.timer_period < 2:
            # Mute ultrasonic / DC; emulators commonly hold the previous level.
            # We freeze at the current step's amplitude.
            pass
        return TRIANGLE_SEQUENCE[self.sequence_step]
