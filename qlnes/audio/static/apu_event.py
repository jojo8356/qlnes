"""ApuWriteEvent — canonical interchange format for APU register writes.

Three potential producers feed this type:
  - v0.5 FCEUX oracle (`qlnes.oracle.fceux`) — historical; v0.6 ships
    fceux-free per PRD §0 and the F.2 pass-2 decision.
  - v0.6 in-process runner (`qlnes.audio.in_process.NROMMemory`)
    — the production path. py65 + observable memory captures every
    write to $4000-$4017 as `ApuWriteEvent`.
  - Future StaticWalkers (`qlnes.audio.static.walker.StaticWalker`)
    — abandoned per-engine bytecode walkers, kept as extension point.

v0.5 used `qlnes.oracle.fceux.TraceEvent` (4 fields: frame, cycle,
addr, value — `frame` was bookkeeping for the trace TSV format).
v0.6 uses this 3-field type as the lean canonical shape consumed by
the APU emulator. `from_trace_event(t)` converts the legacy oracle
events; F.5 (engine-mode dispatch) gates whether the oracle path is
still reachable.
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
