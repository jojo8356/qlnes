"""RIFF WAV writer (PCM int16 LE, mono) with optional `'smpl'` loop chunk.

Architecture step 12 / story A.3. The `'smpl'` chunk encodes loop boundaries
per the Multimedia Programming Interface and Data Specifications 1.0
(Aug 1991, section 4.7), the same format every modern DAW + game audio
engine reads. When `LoopBoundary` is provided, we emit the chunk; consumers
that ignore unknown chunks (most decoders) still get the PCM correctly.

Atomic writes via qlnes.io.atomic (FR35 / NFR-REL-4).
"""

from __future__ import annotations

import struct
from pathlib import Path

from ..io.atomic import atomic_write_bytes
from .engine import LoopBoundary

SMPL_LOOP_TYPE_FORWARD = 0
SMPL_MIDI_UNITY_NOTE = 60  # middle C — conventional for un-pitched samples
SMPL_PLAY_COUNT_INFINITE = 0


def _smpl_chunk_bytes(loop: LoopBoundary, sample_rate: int) -> bytes:
    """Build a single-loop `smpl` RIFF chunk."""
    sample_period_ns = 1_000_000_000 // sample_rate
    sample_loops = 1
    sampler_data = 0
    header = struct.pack(
        "<IIIIIIIII",
        0,  # dwManufacturer
        0,  # dwProduct
        sample_period_ns,  # dwSamplePeriod
        SMPL_MIDI_UNITY_NOTE,  # dwMIDIUnityNote
        0,  # dwMIDIPitchFraction
        0,  # dwSMPTEFormat
        0,  # dwSMPTEOffset
        sample_loops,  # cSampleLoops
        sampler_data,  # cbSamplerData
    )
    loop_record = struct.pack(
        "<IIIIII",
        0,  # dwIdentifier
        SMPL_LOOP_TYPE_FORWARD,  # dwType
        loop.start_sample,  # dwStart
        loop.end_sample,  # dwEnd
        0,  # dwFraction
        SMPL_PLAY_COUNT_INFINITE,  # dwPlayCount
    )
    payload = header + loop_record
    return b"smpl" + struct.pack("<I", len(payload)) + payload


def build_wav_bytes(
    pcm_le16: bytes,
    sample_rate: int,
    channels: int = 1,
    loop: LoopBoundary | None = None,
) -> bytes:
    """Return a complete RIFF WAV blob for the given PCM payload.

    If `loop` is provided, an `smpl` chunk is appended after the data chunk.
    Public for unit tests + callers that need the bytes without a file.
    """
    if channels < 1:
        raise ValueError(f"channels must be >= 1, got {channels}")
    if sample_rate <= 0:
        raise ValueError(f"sample_rate must be positive, got {sample_rate}")
    if len(pcm_le16) % 2 != 0:
        raise ValueError(f"PCM length must be a multiple of 2 bytes (int16), got {len(pcm_le16)}")
    if loop is not None:
        n_samples = len(pcm_le16) // (2 * channels)
        if not (0 <= loop.start_sample < loop.end_sample <= n_samples):
            raise ValueError(
                f"loop boundary out of range: start={loop.start_sample}, "
                f"end={loop.end_sample}, total samples={n_samples}"
            )
    bits_per_sample = 16
    byte_rate = sample_rate * channels * bits_per_sample // 8
    block_align = channels * bits_per_sample // 8
    data_size = len(pcm_le16)
    smpl_chunk = _smpl_chunk_bytes(loop, sample_rate) if loop is not None else b""
    # RIFF size = total file size minus the 8-byte "RIFF<size>" header.
    riff_size = 4 + (8 + 16) + (8 + data_size) + len(smpl_chunk)
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
        smpl_chunk,
    ]
    return b"".join(parts)


def write_wav(
    path: Path | str,
    pcm_le16: bytes,
    sample_rate: int = 44_100,
    channels: int = 1,
    loop: LoopBoundary | None = None,
) -> None:
    """Write a RIFF WAV (PCM int16 LE) atomically. Optional `smpl` loop chunk."""
    atomic_write_bytes(path, build_wav_bytes(pcm_le16, sample_rate, channels, loop=loop))
