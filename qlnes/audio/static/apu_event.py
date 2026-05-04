"""ApuWriteEvent — canonical interchange format for APU register writes.

Both the v0.5 FCEUX oracle and the v0.6 static walkers ultimately produce
APU register writes. v0.5 used `qlnes.oracle.fceux.TraceEvent` (4 fields:
frame, cycle, addr, value — `frame` is bookkeeping for the trace TSV
format). v0.6 uses this 3-field type, the lean canonical shape consumed
by the APU emulator.

The two coexist; `from_trace_event(t)` converts. The renderer migrates
to ApuWriteEvent as the canonical type in F.2 (engine-mode wiring).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...oracle.fceux import TraceEvent


@dataclass(frozen=True)
class ApuWriteEvent:
    """One APU register write timestamped at an absolute CPU cycle.

    Attributes:
        cpu_cycle: Cycles since song start. Monotonic non-decreasing per
            song. uint64-safe (we don't expect more than ~10^11 for very
            long captures).
        register: APU register address in [0x4000, 0x4017].
        value: Byte written, in [0, 255].
    """

    cpu_cycle: int
    register: int
    value: int

    def __post_init__(self) -> None:
        if not 0x4000 <= self.register <= 0x4017:
            raise ValueError(f"register {self.register:#x} out of APU range $4000-$4017")
        if not 0 <= self.value <= 0xFF:
            raise ValueError(f"value {self.value} out of byte range 0-255")
        if self.cpu_cycle < 0:
            raise ValueError(f"cpu_cycle {self.cpu_cycle} must be non-negative")

    @classmethod
    def from_trace_event(cls, ev: TraceEvent) -> ApuWriteEvent:
        """Convert a v0.5 fceux TraceEvent (frame, cycle, addr, value) to
        the v0.6 ApuWriteEvent shape. `frame` is dropped — it's derivable
        from cpu_cycle by `cycle // CYCLES_PER_FRAME` if needed."""
        return cls(cpu_cycle=ev.cycle, register=ev.addr, value=ev.value)
