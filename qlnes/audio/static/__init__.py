"""APU-write event interchange + abandoned static-walker scaffolding.

**Status (2026-05-04, post F.2 pivot pass-2).** The v0.6 production
pipeline is `qlnes/audio/in_process/` — an in-process Python CPU
emulator (py65 + observable memory) running on PyPy 3.11. This
`static` module retains:

  - `ApuWriteEvent` — frozen dataclass, the canonical interchange
    format. Used by BOTH the legacy fceux oracle path
    (`qlnes/oracle/fceux.py`) and the new in-process pipeline
    (`qlnes/audio/in_process/memory.py`).
  - `StaticWalker` — ABC sub-protocol of SoundEngine. **No concrete
    subclass ships in v0.6.** Kept as an extension point for
    contributors who want to pursue the original per-engine bytecode-
    walker idea (community-style RE'd MIDI rippers); a working
    StaticWalker would feed the same ApuWriteEvent stream the
    in-process runner emits.

Sample-equivalence is therefore a property of the EMITTED TRACES,
not of the rendering engine — three potential producers (oracle,
in-process, future static walkers) feed one APU emulator.
"""

from .apu_event import ApuWriteEvent
from .walker import StaticWalker

__all__ = ["ApuWriteEvent", "StaticWalker"]
