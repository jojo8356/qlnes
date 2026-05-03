"""APU lookup tables (NTSC 2A03).

Sources: NESdev wiki — APU_Length_Counter, APU_Noise, APU_Pulse, APU_DMC, APU_Mixer.
All values are integers; no floats are used by the runtime mixer (NFR-REL-1).
"""

from __future__ import annotations

# Length counter lookup, indexed by the 5-bit value from $4003/$4007/$400B/$400F bits 7..3.
# Reference: NESdev wiki / APU Length Counter.
LENGTH_TABLE: tuple[int, ...] = (
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

# Pulse duty-cycle waveforms (8 steps each). Bit at step n is the channel's
# binary output for that APU half-cycle. NESdev: APU_Pulse.
PULSE_DUTY: tuple[tuple[int, ...], ...] = (
    (0, 1, 0, 0, 0, 0, 0, 0),  # 12.5%
    (0, 1, 1, 0, 0, 0, 0, 0),  # 25%
    (0, 1, 1, 1, 1, 0, 0, 0),  # 50%
    (1, 0, 0, 1, 1, 1, 1, 1),  # 25% negated
)

# Triangle 32-step sequence (4-bit unsigned amplitudes 0..15..0). NESdev: APU_Triangle.
TRIANGLE_SEQUENCE: tuple[int, ...] = (
    15,
    14,
    13,
    12,
    11,
    10,
    9,
    8,
    7,
    6,
    5,
    4,
    3,
    2,
    1,
    0,
    0,
    1,
    2,
    3,
    4,
    5,
    6,
    7,
    8,
    9,
    10,
    11,
    12,
    13,
    14,
    15,
)

# Noise channel timer-period table, NTSC. NESdev: APU_Noise.
NOISE_PERIOD_NTSC: tuple[int, ...] = (
    4,
    8,
    16,
    32,
    64,
    96,
    128,
    160,
    202,
    254,
    380,
    508,
    762,
    1016,
    2034,
    4068,
)

# DMC period table, NTSC. Stubbed in MVP (channel ignored) but kept here for the
# orchestrator's register dispatch to remain spec-compliant.
DMC_PERIOD_NTSC: tuple[int, ...] = (
    428,
    380,
    340,
    320,
    286,
    254,
    226,
    214,
    190,
    160,
    142,
    128,
    106,
    84,
    72,
    54,
)

# 2A03 nonlinear mixer LUTs (Q15 fixed-point, range [0, 32767]).
#   pulse_table[i] = round((95.88 / ((8128 / i) + 100)) * 32767)   for i in 1..30
#   tnd_table[j]   = round((163.67 / ((24329 / j) + 100)) * 32767) for j in 1..202
# Index 0 is exact zero. Reference: NESdev_wiki / APU_Mixer.
# These LUTs are precomputed once at import time using Python's standard math —
# the float arithmetic is in *table construction*, not in the runtime mix path.
# After this module loads, `PULSE_MIX` and `TND_MIX` are tuples of int, fully
# deterministic and shareable across hosts.


def _build_pulse_table() -> tuple[int, ...]:
    out = [0] * 31
    for i in range(1, 31):
        v = 95.88 / ((8128.0 / i) + 100.0)
        out[i] = round(v * 32767)
    return tuple(out)


def _build_tnd_table() -> tuple[int, ...]:
    out = [0] * 203
    for j in range(1, 203):
        v = 163.67 / ((24329.0 / j) + 100.0)
        out[j] = round(v * 32767)
    return tuple(out)


PULSE_MIX: tuple[int, ...] = _build_pulse_table()
TND_MIX: tuple[int, ...] = _build_tnd_table()
