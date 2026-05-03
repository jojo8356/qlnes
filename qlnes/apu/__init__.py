"""2A03 APU emulator — orchestrates 4 channels (pulse1, pulse2, triangle, noise)
plus a stubbed DMC, runs the frame counter, and feeds the mixer/resampler.

Spec: NESdev wiki — APU, APU_Frame_Counter.

Cycle accuracy. The CPU runs at 1_789_773 Hz NTSC. The APU is clocked every
*two* CPU cycles for pulse/noise/DMC channels (894_886.5 Hz), and every CPU
cycle for the triangle channel. The orchestrator drives both rates from a
single CPU-cycle counter so register writes can be timestamped at full CPU
resolution.

Frame counter. 4-step mode emits q/h/q/h ticks every ~7457 CPU cycles in a
4-event loop. 5-step mode emits q/h/q/h/(none) at the same period. We use the
mode-aware step table to keep the counter logic small.

DMC. Stubbed per ADR-18 (MVP). Bit 4 of $4015 reads 0; writes to $4010-$4013
are recorded in DmcChannelStub for trace fidelity but do not produce output.
"""

from __future__ import annotations

from .dmc import DmcChannelStub
from .mixer import DEFAULT_SAMPLE_RATE, Mixer
from .noise import NoiseChannel
from .pulse import PulseChannel
from .triangle import TriangleChannel

NTSC_CPU_HZ = 1_789_773

# Frame-counter step boundaries in CPU cycles (4-step mode).
# Per spec the events fire at 3729, 7457, 11186, 14915 CPU cycles after the
# counter resets, with the cycle pattern: q, q+h, q, q+h+irq.
# We use those exact half-step counts so triangle (clocked every CPU cycle)
# and pulse/noise (every other CPU cycle) tick at the same rate as on hardware.
FRAME_STEPS_4 = (3729, 7457, 11186, 14915)
# 5-step mode — same first 4 events but no IRQ; final cycle 18641 fires q+h.
FRAME_STEPS_5 = (3729, 7457, 11186, 14915, 18641)

# Each entry is (q_tick, h_tick, irq) — what to clock at the matching cycle.
FRAME_EVENTS_4 = (
    (True, False, False),
    (True, True, False),
    (True, False, False),
    (True, True, True),
)
FRAME_EVENTS_5 = (
    (True, True, False),
    (True, False, False),
    (True, True, False),
    (True, False, False),
    (False, False, False),
)


class ApuEmulator:
    """Replays APU register writes into a sample buffer.

    Usage:
        emu = ApuEmulator()
        emu.write(0x4015, 0x0F, cycle=0)       # enable channels
        emu.write(0x4000, 0x3F, cycle=10)      # configure pulse1
        # ... more writes ...
        pcm = emu.render_until(cycle=89488)    # 50ms NTSC
    """

    def __init__(self, sample_rate: int = DEFAULT_SAMPLE_RATE) -> None:
        self.sample_rate = sample_rate
        self.pulse1 = PulseChannel(channel=0)
        self.pulse2 = PulseChannel(channel=1)
        self.triangle = TriangleChannel()
        self.noise = NoiseChannel()
        self.dmc = DmcChannelStub()
        self.mixer = Mixer(sample_rate=sample_rate)

        self._cpu_cycle = 0
        self._frame_cycle = 0
        self._frame_step = 0
        self._frame_irq_inhibit = False
        self._frame_mode_5step = False

    # ---- public write API -----------------------------------------------

    def write(self, register: int, value: int, cycle: int) -> None:
        """Schedule an APU register write at the given absolute CPU cycle."""
        if cycle < self._cpu_cycle:
            raise ValueError(f"write at cycle {cycle} predates current cycle {self._cpu_cycle}")
        self._advance_to(cycle)
        self._dispatch_write(register, value)

    def render_until(self, cycle: int) -> bytes:
        """Advance to `cycle` and flush all PCM samples accumulated so far."""
        self._advance_to(cycle)
        return self.mixer.flush()

    def reset(self) -> None:
        self.pulse1 = PulseChannel(channel=0)
        self.pulse2 = PulseChannel(channel=1)
        self.triangle = TriangleChannel()
        self.noise = NoiseChannel()
        self.dmc = DmcChannelStub()
        self.mixer = Mixer(sample_rate=self.sample_rate)
        self._cpu_cycle = 0
        self._frame_cycle = 0
        self._frame_step = 0
        self._frame_irq_inhibit = False
        self._frame_mode_5step = False

    # ---- internal --------------------------------------------------------

    def _dispatch_write(self, register: int, value: int) -> None:
        v = value & 0xFF
        if 0x4000 <= register <= 0x4003:
            self.pulse1.register_write(register - 0x4000, v)
        elif 0x4004 <= register <= 0x4007:
            self.pulse2.register_write(register - 0x4004, v)
        elif 0x4008 <= register <= 0x400B:
            self.triangle.register_write(register - 0x4008, v)
        elif 0x400C <= register <= 0x400F:
            self.noise.register_write(register - 0x400C, v)
        elif 0x4010 <= register <= 0x4013:
            self.dmc.register_write(register - 0x4010, v)
        elif register == 0x4015:
            self.pulse1.set_enable(bool(v & 0x01))
            self.pulse2.set_enable(bool(v & 0x02))
            self.triangle.set_enable(bool(v & 0x04))
            self.noise.set_enable(bool(v & 0x08))
            self.dmc.set_enable(bool(v & 0x10))
        elif register == 0x4017:
            self._frame_mode_5step = bool(v & 0x80)
            self._frame_irq_inhibit = bool(v & 0x40)
            self._frame_cycle = 0
            self._frame_step = 0
            self.mixer.set_frame_mode(v)
            # 5-step mode: clock quarter+half immediately on write.
            if self._frame_mode_5step:
                self._clock_quarter()
                self._clock_half()

    def _advance_to(self, target_cycle: int) -> None:
        # Hot loop — pure-Python overhead dominates here. We bind every
        # per-cycle attribute and method to a local, and inline the mixer
        # lookups, to cut Python's attribute-resolution cost. NFR-PERF-2.
        delta = target_cycle - self._cpu_cycle
        if delta <= 0:
            return

        from .tables import PULSE_MIX as _PULSE_MIX
        from .tables import TND_MIX as _TND_MIX

        p1 = self.pulse1
        p2 = self.pulse2
        tri = self.triangle
        noi = self.noise
        mix = self.mixer

        p1_tick = p1.tick
        p2_tick = p2.tick
        tri_tick = tri.tick
        noi_tick = noi.tick
        p1_out = p1.output
        p2_out = p2.output
        tri_out = tri.output
        noi_out = noi.output
        feed = mix.feed_sample

        cycle = self._cpu_cycle
        frame_cycle = self._frame_cycle
        frame_step = self._frame_step
        steps = FRAME_STEPS_5 if self._frame_mode_5step else FRAME_STEPS_4
        events = FRAME_EVENTS_5 if self._frame_mode_5step else FRAME_EVENTS_4
        n_steps = len(steps)

        for _ in range(delta):
            tri_tick()
            if cycle & 1 == 0:
                p1_tick()
                p2_tick()
                noi_tick()
            # Frame counter — inlined.
            if frame_step < n_steps and frame_cycle == steps[frame_step]:
                q, h, _irq = events[frame_step]
                if q:
                    self._clock_quarter()
                if h:
                    self._clock_half()
                frame_step += 1
                if frame_step >= n_steps:
                    frame_step = 0
                    frame_cycle = 0
            # Mixer — inlined LUT access.
            sample = _PULSE_MIX[p1_out() + p2_out()] + _TND_MIX[3 * tri_out() + 2 * noi_out()]
            feed(sample)
            cycle += 1
            frame_cycle += 1

        self._cpu_cycle = cycle
        self._frame_cycle = frame_cycle
        self._frame_step = frame_step

    def _step_frame_counter(self) -> None:
        steps = FRAME_STEPS_5 if self._frame_mode_5step else FRAME_STEPS_4
        events = FRAME_EVENTS_5 if self._frame_mode_5step else FRAME_EVENTS_4
        if self._frame_step >= len(steps):
            return
        if self._frame_cycle == steps[self._frame_step]:
            q, h, _irq = events[self._frame_step]
            if q:
                self._clock_quarter()
            if h:
                self._clock_half()
            # IRQ: not surfaced in MVP; FCEUX is the CPU.
            self._frame_step += 1
            if self._frame_step >= len(steps):
                # Reset for next frame loop.
                self._frame_step = 0
                self._frame_cycle = 0

    def _clock_quarter(self) -> None:
        self.pulse1.clock_envelope()
        self.pulse2.clock_envelope()
        self.triangle.clock_linear()
        self.noise.clock_envelope()

    def _clock_half(self) -> None:
        self.pulse1.clock_length_and_sweep()
        self.pulse2.clock_length_and_sweep()
        self.triangle.clock_length()
        self.noise.clock_length()
