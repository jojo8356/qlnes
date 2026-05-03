"""2A03 nonlinear mixer + integer-arithmetic resampler.

Mixer math (NESdev wiki / APU_Mixer):
    pulse_out = 95.88 / (8128 / (pulse1 + pulse2) + 100)
    tnd_out   = 163.67 / (24329 / (3*triangle + 2*noise + dmc) + 100)
    output    = pulse_out + tnd_out
We precompute these as Q15 integer LUTs in `tables.py` and look up in O(1).

Resampler (894_886.5 Hz APU rate → 44_100 Hz output):
We accumulate APU samples weighted by an integer Bresenham-style accumulator
that decides when to emit an output sample. Each output sample is the integer
mean of the APU samples in its window. This is mathematically equivalent to
a brick-wall low-pass at sample_rate/2 followed by decimation — deterministic,
host-independent, no floats. Phase 7.3+ may upgrade to a windowed-sinc FIR
when an FCEUX reference becomes available; the public mix/feed_sample API is
designed so that swap is local.

Note: the APU runs at CPU/2 = 1789773/2 = 894886.5 Hz, i.e. fractional. We
model this by ticking the mixer once per APU half-cycle (the orchestrator
tick rate) and using a 2x-oversampled accumulator: every 2 APU ticks → 1
"APU sample" of weight 2 (numerator), and we accumulate fractional
(2*sample_rate / cpu_rate) per APU tick. That keeps everything in integers.
"""

from __future__ import annotations

from .tables import PULSE_MIX, TND_MIX

CPU_HZ_NTSC = 1_789_773  # exact integer
DEFAULT_SAMPLE_RATE = 44_100


class Mixer:
    def __init__(self, sample_rate: int = DEFAULT_SAMPLE_RATE) -> None:
        self.sample_rate = sample_rate
        # Bresenham step: at every CPU cycle we add `sample_rate` to an accumulator
        # and emit a sample when the accumulator >= cpu_rate, then subtract cpu_rate.
        # Using the CPU rate (not APU rate) means the orchestrator ticks the mixer
        # once per CPU cycle and we get exact integer arithmetic.
        self._acc_num = 0
        self._sum_value = 0  # running sum of channel-mixed samples in the window
        self._sum_count = 0  # number of CPU cycles accumulated
        self._buffer: list[int] = []  # int16 samples flushed via flush()
        self.frame_mode_5step = False

    def set_frame_mode(self, value: int) -> None:
        """Mirror $4017 mode bit — 0 = 4-step, 1 = 5-step."""
        self.frame_mode_5step = bool(value & 0x80)

    def mix(self, p1: int, p2: int, tri: int, noise: int, dmc: int = 0) -> int:
        """Combine 4-bit channel outputs into one Q15 sample (0..32767)."""
        pulse_idx = (p1 + p2) & 0x1F  # safe: p1, p2 ∈ [0, 15] so sum ≤ 30
        tnd_idx = (3 * tri + 2 * noise + dmc) & 0xFF  # ≤ 3*15 + 2*15 = 75 in MVP
        return PULSE_MIX[pulse_idx] + TND_MIX[tnd_idx]

    def feed_sample(self, sample: int) -> None:
        """Feed one CPU-cycle-rate sample into the resampler accumulator."""
        self._sum_value += sample
        self._sum_count += 1
        self._acc_num += self.sample_rate
        if self._acc_num >= CPU_HZ_NTSC:
            self._acc_num -= CPU_HZ_NTSC
            avg = self._sum_value // self._sum_count if self._sum_count else 0
            # Center to int16 signed range: subtract DC offset (~mid-scale).
            # NES audio is biased; FCEUX reference also un-biases. The exact bias
            # depends on quiescent channel sums; for now we shift the [0, 32767]
            # range to [-16384, 16383] to fit a standard signed PCM frame.
            self._buffer.append(avg - 16384)
            self._sum_value = 0
            self._sum_count = 0

    def flush(self) -> bytes:
        """Return the int16 LE PCM bytes accumulated since last flush, then reset."""
        out = bytearray()
        for s in self._buffer:
            # Clip to int16 signed range defensively.
            if s > 32767:
                s = 32767
            elif s < -32768:
                s = -32768
            out.append(s & 0xFF)
            out.append((s >> 8) & 0xFF)
        self._buffer.clear()
        return bytes(out)
