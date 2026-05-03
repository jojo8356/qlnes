"""2A03 pulse channel ($4000-$4003 for pulse 1, $4004-$4007 for pulse 2).

Contains envelope generator, sweep unit, length counter, duty-cycle sequencer
and timer divider. All state is integer; output is 4-bit unsigned (0..15).

Spec: NESdev wiki — APU_Pulse, APU_Envelope, APU_Sweep, APU_Length_Counter.
The two pulse channels differ only in sweep "negate" rounding: channel 1 uses
ones'-complement (subtract one extra), channel 2 uses two's-complement.
"""

from __future__ import annotations

from .tables import LENGTH_TABLE, PULSE_DUTY


class PulseChannel:
    def __init__(self, channel: int) -> None:
        if channel not in (0, 1):
            raise ValueError(f"channel must be 0 (pulse1) or 1 (pulse2), got {channel}")
        self.channel = channel

        # $4000 — DDLC VVVV
        self.duty = 0  # bits 7..6
        self.length_halt = False  # bit 5 (also envelope loop)
        self.constant_volume = False  # bit 4
        self.volume_or_period = 0  # bits 3..0

        # $4001 — EPPP NSSS sweep
        self.sweep_enable = False
        self.sweep_period = 0  # 0..7; divider reloads with this+1
        self.sweep_negate = False
        self.sweep_shift = 0
        self.sweep_reload = False
        self.sweep_divider = 0

        # $4002, $4003 — timer (11-bit) + length-counter load
        self.timer_period = 0  # 11-bit timer reload
        self.timer = 0  # current counter
        self.duty_step = 0  # 0..7 sequencer position
        self.length_counter = 0

        # Envelope generator
        self.envelope_start = False
        self.envelope_divider = 0
        self.envelope_decay = 0

        self.enabled = False

    # ---- register writes -------------------------------------------------

    def register_write(self, reg_index: int, value: int) -> None:
        value &= 0xFF
        if reg_index == 0:
            self.duty = (value >> 6) & 0x03
            self.length_halt = bool(value & 0x20)
            self.constant_volume = bool(value & 0x10)
            self.volume_or_period = value & 0x0F
        elif reg_index == 1:
            self.sweep_enable = bool(value & 0x80)
            self.sweep_period = (value >> 4) & 0x07
            self.sweep_negate = bool(value & 0x08)
            self.sweep_shift = value & 0x07
            self.sweep_reload = True
        elif reg_index == 2:
            self.timer_period = (self.timer_period & 0x700) | value
        elif reg_index == 3:
            self.timer_period = (self.timer_period & 0x0FF) | ((value & 0x07) << 8)
            if self.enabled:
                length_idx = (value >> 3) & 0x1F
                self.length_counter = LENGTH_TABLE[length_idx]
            self.duty_step = 0
            self.envelope_start = True

    def set_enable(self, enabled: bool) -> None:
        self.enabled = enabled
        if not enabled:
            self.length_counter = 0

    # ---- per-APU-clock tick ---------------------------------------------

    def tick(self) -> None:
        if self.timer == 0:
            self.timer = self.timer_period
            self.duty_step = (self.duty_step + 1) & 0x07
        else:
            self.timer -= 1

    # ---- frame-counter clocks -------------------------------------------

    def clock_envelope(self) -> None:
        """Quarter-frame tick: envelope + linear (linear is triangle-only)."""
        if self.envelope_start:
            self.envelope_start = False
            self.envelope_decay = 15
            self.envelope_divider = self.volume_or_period
        else:
            if self.envelope_divider == 0:
                self.envelope_divider = self.volume_or_period
                if self.envelope_decay > 0:
                    self.envelope_decay -= 1
                elif self.length_halt:
                    self.envelope_decay = 15
            else:
                self.envelope_divider -= 1

    def clock_length_and_sweep(self) -> None:
        """Half-frame tick: length counter + sweep."""
        if self.length_counter > 0 and not self.length_halt:
            self.length_counter -= 1
        self._clock_sweep()

    # ---- sweep -----------------------------------------------------------

    def _target_period(self) -> int:
        delta = self.timer_period >> self.sweep_shift
        if self.sweep_negate:
            delta = -delta
            if self.channel == 0:
                # Pulse 1 uses ones' complement: negate-1.
                delta -= 1
        target = self.timer_period + delta
        return target

    def _is_sweep_muting(self) -> bool:
        if self.timer_period < 8:
            return True
        target = self._target_period()
        return target > 0x7FF

    def _clock_sweep(self) -> None:
        if (
            self.sweep_divider == 0
            and self.sweep_enable
            and not self._is_sweep_muting()
            and self.sweep_shift > 0
        ):
            self.timer_period = max(0, self._target_period())
        if self.sweep_divider == 0 or self.sweep_reload:
            self.sweep_divider = self.sweep_period
            self.sweep_reload = False
        else:
            self.sweep_divider -= 1

    # ---- output ----------------------------------------------------------

    def output(self) -> int:
        if not self.enabled:
            return 0
        if self.length_counter == 0:
            return 0
        if self._is_sweep_muting():
            return 0
        if PULSE_DUTY[self.duty][self.duty_step] == 0:
            return 0
        return self.volume_or_period if self.constant_volume else self.envelope_decay
