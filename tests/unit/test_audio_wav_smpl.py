"""WAV `'smpl'` chunk tests — story A.3.

Verifies the chunk encoding against the Multimedia Programming Interface
spec (Aug 1991, section 4.7) without depending on any external WAV parser.
"""

from __future__ import annotations

import struct
import wave

import pytest

from qlnes.audio.engine import LoopBoundary
from qlnes.audio.wav import (
    SMPL_LOOP_TYPE_FORWARD,
    SMPL_MIDI_UNITY_NOTE,
    SMPL_PLAY_COUNT_INFINITE,
    build_wav_bytes,
    write_wav,
)

# ---- chunk walker helper ------------------------------------------------


def _walk_riff_chunks(blob: bytes) -> dict[str, bytes]:
    """Return a {chunk_id: payload_bytes} map by walking the RIFF stream."""
    assert blob[:4] == b"RIFF"
    riff_size = struct.unpack("<I", blob[4:8])[0]
    assert blob[8:12] == b"WAVE"
    out: dict[str, bytes] = {}
    pos = 12
    end = 8 + riff_size
    while pos < end:
        chunk_id = blob[pos : pos + 4].decode("ascii")
        chunk_size = struct.unpack("<I", blob[pos + 4 : pos + 8])[0]
        out[chunk_id] = blob[pos + 8 : pos + 8 + chunk_size]
        # Chunks are word-aligned (pad byte if size is odd).
        pos += 8 + chunk_size + (chunk_size % 2)
    return out


def _silence_pcm_bytes(n_samples: int = 44_100) -> bytes:
    return b"\x00\x00" * n_samples


# ---- presence/absence ---------------------------------------------------


def test_no_smpl_chunk_when_loop_is_none():
    blob = build_wav_bytes(_silence_pcm_bytes(), sample_rate=44_100, loop=None)
    chunks = _walk_riff_chunks(blob)
    assert "smpl" not in chunks
    assert "fmt " in chunks
    assert "data" in chunks


def test_smpl_chunk_present_when_loop_supplied():
    loop = LoopBoundary(start_sample=100, end_sample=200)
    blob = build_wav_bytes(_silence_pcm_bytes(), sample_rate=44_100, loop=loop)
    chunks = _walk_riff_chunks(blob)
    assert "smpl" in chunks


# ---- chunk content ------------------------------------------------------


def test_smpl_chunk_size_for_one_loop():
    """Header (36 bytes) + 1 loop record (24 bytes) = 60 bytes payload."""
    loop = LoopBoundary(start_sample=0, end_sample=100)
    blob = build_wav_bytes(_silence_pcm_bytes(), sample_rate=44_100, loop=loop)
    chunks = _walk_riff_chunks(blob)
    assert len(chunks["smpl"]) == 60


def test_smpl_chunk_decodes_boundaries():
    """dwStart and dwEnd in the loop record match the LoopBoundary."""
    loop = LoopBoundary(start_sample=12_345, end_sample=42_000)
    blob = build_wav_bytes(_silence_pcm_bytes(), sample_rate=44_100, loop=loop)
    smpl_payload = _walk_riff_chunks(blob)["smpl"]
    # Skip 36-byte header to reach the loop record.
    loop_record = smpl_payload[36:60]
    fields = struct.unpack("<IIIIII", loop_record)
    assert fields[0] == 0  # dwIdentifier
    assert fields[1] == SMPL_LOOP_TYPE_FORWARD
    assert fields[2] == 12_345  # dwStart
    assert fields[3] == 42_000  # dwEnd
    assert fields[4] == 0  # dwFraction
    assert fields[5] == SMPL_PLAY_COUNT_INFINITE


def test_smpl_chunk_sample_period_matches_sample_rate():
    """dwSamplePeriod = 1e9 / sample_rate (nanoseconds per sample)."""
    loop = LoopBoundary(start_sample=0, end_sample=100)
    blob = build_wav_bytes(_silence_pcm_bytes(), sample_rate=44_100, loop=loop)
    smpl = _walk_riff_chunks(blob)["smpl"]
    sample_period_ns = struct.unpack("<I", smpl[8:12])[0]
    assert sample_period_ns == 1_000_000_000 // 44_100


def test_smpl_chunk_midi_unity_note_is_middle_c():
    loop = LoopBoundary(start_sample=0, end_sample=100)
    blob = build_wav_bytes(_silence_pcm_bytes(), sample_rate=44_100, loop=loop)
    smpl = _walk_riff_chunks(blob)["smpl"]
    midi_unity_note = struct.unpack("<I", smpl[12:16])[0]
    assert midi_unity_note == SMPL_MIDI_UNITY_NOTE == 60


def test_smpl_chunk_n_loops_is_one():
    loop = LoopBoundary(start_sample=0, end_sample=100)
    blob = build_wav_bytes(_silence_pcm_bytes(), sample_rate=44_100, loop=loop)
    smpl = _walk_riff_chunks(blob)["smpl"]
    n_loops = struct.unpack("<I", smpl[28:32])[0]
    assert n_loops == 1


# ---- validation ---------------------------------------------------------


def test_loop_with_start_after_end_is_rejected():
    pcm = _silence_pcm_bytes(1000)
    loop = LoopBoundary(start_sample=500, end_sample=100)
    with pytest.raises(ValueError, match="loop boundary out of range"):
        build_wav_bytes(pcm, sample_rate=44_100, loop=loop)


def test_loop_end_beyond_pcm_length_is_rejected():
    pcm = _silence_pcm_bytes(1000)
    loop = LoopBoundary(start_sample=0, end_sample=2000)
    with pytest.raises(ValueError, match="loop boundary out of range"):
        build_wav_bytes(pcm, sample_rate=44_100, loop=loop)


def test_loop_with_equal_start_and_end_is_rejected():
    pcm = _silence_pcm_bytes(1000)
    loop = LoopBoundary(start_sample=100, end_sample=100)
    with pytest.raises(ValueError, match="loop boundary out of range"):
        build_wav_bytes(pcm, sample_rate=44_100, loop=loop)


# ---- compatibility with stdlib wave ------------------------------------


def test_wav_with_smpl_chunk_is_still_readable_by_stdlib_wave(tmp_path):
    """stdlib `wave` ignores unknown chunks — pcm should still decode."""
    p = tmp_path / "out.wav"
    pcm = _silence_pcm_bytes(1000)
    write_wav(p, pcm, sample_rate=44_100, loop=LoopBoundary(0, 500))
    with wave.open(str(p), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 44_100
        assert wf.getnframes() == 1000
        assert wf.readframes(1000) == pcm


# ---- determinism --------------------------------------------------------


def test_wav_with_smpl_two_runs_byte_identical():
    pcm = _silence_pcm_bytes(500)
    loop = LoopBoundary(start_sample=10, end_sample=400)
    a = build_wav_bytes(pcm, sample_rate=44_100, loop=loop)
    b = build_wav_bytes(pcm, sample_rate=44_100, loop=loop)
    assert a == b


def test_wav_riff_size_includes_smpl_chunk():
    """The RIFF size header must account for the smpl chunk too."""
    pcm = _silence_pcm_bytes(100)
    blob_no_loop = build_wav_bytes(pcm, sample_rate=44_100)
    blob_with_loop = build_wav_bytes(pcm, sample_rate=44_100, loop=LoopBoundary(0, 50))
    riff_size_no = struct.unpack("<I", blob_no_loop[4:8])[0]
    riff_size_yes = struct.unpack("<I", blob_with_loop[4:8])[0]
    # smpl chunk = 8 (header) + 60 (payload) = 68 bytes.
    assert riff_size_yes - riff_size_no == 68


# ---- write_wav file-path API -------------------------------------------


def test_write_wav_with_loop_writes_atomically(tmp_path):
    p = tmp_path / "out.wav"
    write_wav(p, _silence_pcm_bytes(1000), sample_rate=44_100, loop=LoopBoundary(0, 100))
    assert p.exists()
    blob = p.read_bytes()
    assert "smpl" in _walk_riff_chunks(blob)
    # No leftover .tmp file.
    leftover = [x for x in tmp_path.iterdir() if x.name.startswith(".out.wav.")]
    assert leftover == []
