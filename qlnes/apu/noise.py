"""2A03 noise channel ($400C-$400F).

15-bit LFSR with two feedback modes. Output is the volume (envelope or constant)
when bit 0 of the LFSR is 0, else 0 — meaning bit 0 acts as a *gate*, not a
sample value. NESdev: APU_Noise, APU_Envelope, APU_Length_Counter.
"""

from __future__ import annotations

from .tables import LENGTH_TABLE, NOISE_PERIOD_NTSC


class NoiseChannel:
    def __init__(self) -> None:
        # $400C — --LC VVVV
        self.length_halt = False
        self.constant_volume = False
        self.volume_or_period = 0

        # $400E — M--- PPPP (mode + period index)
        self.mode = False  # True ⇒ short-period (loop) feedback bit = bit 6
        self.period_index = 0
        self.timer_period = NOISE_PERIOD_NTSC[0]
        self.timer = 0

        # Length counter
        self.length_counter = 0

        # Envelope generator (same shape as pulse)
        self.envelope_start = False
        self.envelope_divider = 0
        self.envelope_decay = 0

        # 15-bit LFSR — power-up state per spec is 1.
        self.lfsr = 1

        self.enabled = False

    def register_write(self, reg_index: int, value: int) -> None:
        value &= 0xFF
        if reg_index == 0:
            self.length_halt = bool(value & 0x20)
            self.constant_volume = bool(value & 0x10)
            self.volume_or_period = value & 0x0F
        elif reg_index == 1:
            pass  # $400D unused
        elif reg_index == 2:
            self.mode = bool(value & 0x80)
            self.period_index = value & 0x0F
            self.timer_period = NOISE_PERIOD_NTSC[self.period_index]
        elif reg_index == 3:
            if self.enabled:
                length_idx = (value >> 3) & 0x1F
                self.length_counter = LENGTH_TABLE[length_idx]
            self.envelope_start = True

    def set_enable(self, enabled: bool) -> None:
        self.enabled = enabled
        if not enabled:
            self.length_counter = 0

    def tick(self) -> None:
        if self.timer == 0:
            self.timer = self.timer_period
            self._step_lfsr()
        else:
            self.timer -= 1

    def _step_lfsr(self) -> None:
        bit_other = (self.lfsr >> 6) & 1 if self.mode else (self.lfsr >> 1) & 1
        feedback = (self.lfsr & 1) ^ bit_other
        self.lfsr = (self.lfsr >> 1) | (feedback << 14)

    def clock_envelope(self) -> None:
        """Quarter-frame tick (identical to pulse)."""
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

    def clock_length(self) -> None:
        if self.length_counter > 0 and not self.length_halt:
            self.length_counter -= 1

    def output(self) -> int:
        if not self.enabled:
            return 0
        if self.length_counter == 0:
            return 0
        if (self.lfsr & 1) != 0:
            return 0
        return self.volume_or_period if self.constant_volume else self.envelope_decay
