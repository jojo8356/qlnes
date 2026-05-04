"""StaticWalker ABC — engines that emit APU register writes from bytecode.

Architecture step 20.2 (architecture-v0.6.md amendment).

A StaticWalker is a SoundEngine that, in addition to the v0.5 protocol
(detect, walk_song_table, render_song, detect_loop), also implements
`emit_apu_writes` — a pure-Python static analyzer that walks the engine's
in-PRG bytecode and yields the APU register writes the engine *would*
produce at runtime, without running the CPU.

The renderer's `--engine-mode auto` resolves to the static path when the
detected engine has `has_static_walker = True` (set automatically by
this ABC).
"""

from __future__ import annotations

import abc
from collections.abc import Iterator
from typing import TYPE_CHECKING, ClassVar

from ..engine import SoundEngine
from .apu_event import ApuWriteEvent

if TYPE_CHECKING:
    from ...rom import Rom
    from ..engine import SongEntry


class StaticWalker(SoundEngine):
    """Engine handler that can emit APU register-writes from bytecode alone.

    Subclasses must implement `emit_apu_writes` AND the v0.5 SoundEngine
    surface (detect, walk_song_table, render_song, detect_loop).

    `has_static_walker` is set to True by this ABC so the renderer can
    detect static-capable engines via class-attribute inspection without
    importing this module.
    """

    has_static_walker: ClassVar[bool] = True

    @abc.abstractmethod
    def emit_apu_writes(
        self,
        rom: Rom,
        song: SongEntry,
        *,
        frames: int,
    ) -> Iterator[ApuWriteEvent]:
        """Yield APU register writes for `song`, frame-accurate.

        Pure function over (rom, song, frames). Must:
          - emit no I/O, no subprocess, no clock, no random source;
          - yield events in monotonic non-decreasing cpu_cycle order;
          - produce a sequence byte-identical to what FCEUX's trace
            captures for the same (rom, song, frames) inputs (the
            equivalence claim, NFR-REL-81).
        """
