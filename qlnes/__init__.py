from ._version import __version__
from .annotate import AnnotationReport, annotate
from .dataflow import (
    Detection,
    detect_all,
    detect_controller_reads,
    detect_frame_counter,
    detect_oam_indices,
    detect_oamdma_buffer,
    detect_pointer_pairs,
)
from .ines import load_rom_to_image, rom_to_images, strip_ines
from .nes_hw import NES_REGS
from .parser import Disasm, Line
from .profile import HardwareUsage, IRQVector, RomProfile
from .ql6502 import QL6502, QL6502Error
from .rom import Bank, Rom

__all__ = [
    "NES_REGS",
    "QL6502",
    "AnnotationReport",
    "Bank",
    "Detection",
    "Disasm",
    "HardwareUsage",
    "IRQVector",
    "Line",
    "QL6502Error",
    "Rom",
    "RomProfile",
    "annotate",
    "detect_all",
    "detect_controller_reads",
    "detect_frame_counter",
    "detect_oam_indices",
    "detect_oamdma_buffer",
    "detect_pointer_pairs",
    "load_rom_to_image",
    "rom_to_images",
    "strip_ines",
]
