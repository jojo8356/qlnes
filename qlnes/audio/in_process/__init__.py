"""In-process music renderer (v0.6).

Replaces the v0.5 FCEUX-subprocess oracle with a Python-side CPU
emulator (py65) + observable memory map. Yields ApuWriteEvent
identically to the FCEUX path, so the downstream APU emulator and
WAV/MP3 encoders are unchanged.

See architecture-v0.6.md §20 for the full spec.
"""
from .memory import Memory, NROMMemory
from .nmi import NTSC_CYCLES_PER_FRAME, trigger_nmi, trigger_nmi_to
from .runner import InProcessRunner, render_rom

__all__ = [
    "InProcessRunner",
    "Memory",
    "NROMMemory",
    "NTSC_CYCLES_PER_FRAME",
    "render_rom",
    "trigger_nmi",
    "trigger_nmi_to",
]
