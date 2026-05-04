"""Static-walker pipeline (v0.6) — emits APU register writes from engine
bytecode without spawning FCEUX.

Architecture step 20 (architecture-v0.6.md amendment). The public API is:

  - StaticWalker — ABC sub-protocol of SoundEngine. Engines that ship a
    static walker subclass this and implement `emit_apu_writes`.
  - ApuWriteEvent — frozen dataclass; the canonical interchange format
    between trace producers (FCEUX oracle OR static walker) and the
    APU emulator.

Both this module and qlnes.oracle.fceux yield iterators of ApuWriteEvent
that feed qlnes.apu.ApuEmulator. Sample-equivalence is therefore a
property of the EMITTED TRACES, not of the rendering engine.
"""

from .apu_event import ApuWriteEvent
from .walker import StaticWalker

__all__ = ["ApuWriteEvent", "StaticWalker"]
