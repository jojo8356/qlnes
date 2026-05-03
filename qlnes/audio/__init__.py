"""qlnes.audio — audio rendering package.

A.1 ships the new pipeline (engine ABC + FT handler + APU-driven renderer)
alongside the legacy ffmpeg-based path. The legacy path is preserved here as
`_legacy` so `cli.py audio()` keeps working until phase 7.5 migrates it
to `renderer.render_rom_audio_v2`. The legacy module is deleted in A.6.
"""

from ._legacy import (
    AudioResult,
    record_apu_trace,
    render_rom_audio,
    synthesize_wav,
    wav_to_mp3,
)
from .engine import (
    DetectionResult,
    LoopBoundary,
    PcmStream,
    SongEntry,
    SoundEngine,
    SoundEngineRegistry,
)
from .mp3 import Mp3Encoder
from .renderer import RenderResult, render_rom_audio_v2, supported_formats
from .wav import build_wav_bytes, write_wav

__all__ = [
    "AudioResult",
    "DetectionResult",
    "LoopBoundary",
    "Mp3Encoder",
    "PcmStream",
    "RenderResult",
    "SongEntry",
    "SoundEngine",
    "SoundEngineRegistry",
    "build_wav_bytes",
    "record_apu_trace",
    "render_rom_audio",
    "render_rom_audio_v2",
    "supported_formats",
    "synthesize_wav",
    "wav_to_mp3",
    "write_wav",
]
