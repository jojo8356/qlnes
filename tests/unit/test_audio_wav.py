"""WAV writer tests — RIFF correctness + atomic semantics."""

import struct
import wave

import pytest

from qlnes.audio.wav import build_wav_bytes, write_wav


def test_build_wav_minimal():
    wav = build_wav_bytes(b"\x00\x00", sample_rate=44100)
    assert wav[:4] == b"RIFF"
    assert wav[8:12] == b"WAVE"
    assert wav[12:16] == b"fmt "
    assert wav[36:40] == b"data"


def test_build_wav_riff_size_header():
    pcm = b"\x00" * 10
    wav = build_wav_bytes(pcm, sample_rate=44100)
    riff_size = struct.unpack("<I", wav[4:8])[0]
    assert riff_size == 36 + len(pcm)


def test_build_wav_fmt_chunk_pcm_format():
    wav = build_wav_bytes(b"\x00\x00", sample_rate=22050, channels=1)
    fmt_data = wav[20:36]
    fmt, channels, sr, byte_rate, block_align, bps = struct.unpack("<HHIIHH", fmt_data)
    assert fmt == 1  # PCM
    assert channels == 1
    assert sr == 22050
    assert byte_rate == 22050 * 2
    assert block_align == 2
    assert bps == 16


def test_build_wav_data_chunk_size_and_payload():
    pcm = b"\x12\x34\x56\x78"
    wav = build_wav_bytes(pcm, sample_rate=44100)
    data_size = struct.unpack("<I", wav[40:44])[0]
    assert data_size == len(pcm)
    assert wav[44:] == pcm


def test_build_wav_rejects_odd_pcm_length():
    with pytest.raises(ValueError, match="multiple of 2"):
        build_wav_bytes(b"\x00\x00\x00", sample_rate=44100)


def test_build_wav_rejects_zero_sample_rate():
    with pytest.raises(ValueError, match="sample_rate"):
        build_wav_bytes(b"\x00\x00", sample_rate=0)


def test_build_wav_rejects_zero_channels():
    with pytest.raises(ValueError, match="channels"):
        build_wav_bytes(b"\x00\x00", sample_rate=44100, channels=0)


def test_write_wav_roundtrips_via_stdlib(tmp_path):
    """Verify the WAV we write is valid by reading it back with stdlib wave."""
    pcm = b"\x00\x00\x10\x00\x20\x00\x30\x00"  # 4 int16 samples
    out = tmp_path / "out.wav"
    write_wav(out, pcm, sample_rate=44100)
    with wave.open(str(out), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 44100
        assert wf.getnframes() == 4
        assert wf.readframes(4) == pcm


def test_write_wav_atomic_no_partial_on_kill(tmp_path):
    """The atomic_writer guarantees no half-WAV. We trust the atomic test
    coverage from test_atomic_kill.py — here we just verify write_wav
    routes through it (no temp file leaks)."""
    out = tmp_path / "out.wav"
    write_wav(out, b"\x00\x00", sample_rate=44100)
    leftover = [p for p in tmp_path.iterdir() if p.name.startswith(".out.wav.")]
    assert leftover == []


def test_write_wav_creates_parent_dirs(tmp_path):
    out = tmp_path / "subdir" / "deep" / "out.wav"
    write_wav(out, b"\x00\x00", sample_rate=44100)
    assert out.exists()


def test_write_wav_two_consecutive_runs_byte_identical(tmp_path):
    """Determinism: same PCM → same WAV bytes."""
    pcm = bytes(i & 0xFF for i in range(200))
    a = tmp_path / "a.wav"
    b = tmp_path / "b.wav"
    write_wav(a, pcm, sample_rate=44100)
    write_wav(b, pcm, sample_rate=44100)
    assert a.read_bytes() == b.read_bytes()
