"""Minimal RIFF WAV writer (PCM int16 LE, mono).

Intentionally lean — no `'smpl'` chunk yet (A.3 lands the loop chunk).
Routes every write through `qlnes.io.atomic.atomic_write_bytes` so a crash
mid-render leaves no half-file (FR35 / NFR-REL-4).
"""

from __future__ import annotations

import struct
from pathlib import Path

from ..io.atomic import atomic_write_bytes


def build_wav_bytes(pcm_le16: bytes, sample_rate: int, channels: int = 1) -> bytes:
    """Return a complete RIFF WAV blob for the given PCM payload.

    Public for unit tests + callers that need the bytes without a file.
    """
    if channels < 1:
        raise ValueError(f"channels must be ≥ 1, got {channels}")
    if sample_rate <= 0:
        raise ValueError(f"sample_rate must be positive, got {sample_rate}")
    if len(pcm_le16) % 2 != 0:
        raise ValueError(f"PCM length must be a multiple of 2 bytes (int16), got {len(pcm_le16)}")
    bits_per_sample = 16
    byte_rate = sample_rate * channels * bits_per_sample // 8
    block_align = channels * bits_per_sample // 8
    data_size = len(pcm_le16)
    riff_size = 36 + data_size  # 'WAVE' + 'fmt ' chunk (24 bytes) + 'data' header (8) - 8

    parts = [
        b"RIFF",
        struct.pack("<I", riff_size),
        b"WAVE",
        b"fmt ",
        struct.pack("<I", 16),
        struct.pack(
            "<HHIIHH",
            1,  # PCM format
            channels,
            sample_rate,
            byte_rate,
            block_align,
            bits_per_sample,
        ),
        b"data",
        struct.pack("<I", data_size),
        pcm_le16,
    ]
    return b"".join(parts)


def write_wav(
    path: Path | str,
    pcm_le16: bytes,
    sample_rate: int = 44_100,
    channels: int = 1,
) -> None:
    """Write a minimal RIFF WAV (PCM int16 LE) atomically."""
    atomic_write_bytes(path, build_wav_bytes(pcm_le16, sample_rate, channels))
