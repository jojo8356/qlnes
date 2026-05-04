"""StaticWalker ABC — DEPRECATED scaffolding (kept as extension point).

**Status (2026-05-04): deprecated, no concrete subclass ships.**

This ABC was the foundation of the original v0.6 plan: per-engine static
walkers that parse engine bytecode (FT, Capcom, KGen, ...) directly to
emit APU register writes — no CPU emulation. After research
(`prd-no-fceux.md` §0), v0.6 pivots to an **in-process Python CPU
emulator** (`qlnes/audio/in_process/`) — universal across engines, no
per-engine RE.

This module stays in tree as an extension point: a contributor pursuing
the per-game-craft path (community-style RE'd MIDI rippers) can subclass
StaticWalker. ApuWriteEvent (the canonical interchange type next door
in apu_event.py) is used by both pipelines.
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
          - produce a sequence consistent with the v0.6 in-process
            runner's trace for the same (rom, song, frames) inputs.
            (v0.6 is fceux-free per F.2 pass-2; the in-process
            pipeline is the reference, and a future StaticWalker
            should match its committed fixtures byte-for-byte.)
        """
