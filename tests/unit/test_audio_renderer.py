"""End-to-end renderer tests with a mocked oracle.

These tests verify the full pipeline (ROM load → engine detect → song walk →
render → write_wav) without spawning fceux. Real fceux exercises live in
tests/integration (phase 7.6).
"""

from __future__ import annotations

import wave

import pytest

from qlnes.audio.renderer import RenderResult, render_rom_audio_v2, supported_formats
from qlnes.io.errors import QlnesError
from qlnes.oracle.fceux import ApuTrace, TraceEvent


def _make_minimal_ines_rom_with_signature(prg_size: int = 0x4000) -> bytes:
    """Build a valid 16KB-PRG mapper-0 iNES ROM containing the FamiTracker
    ASCII signature so the registry detects it."""
    header = (
        b"NES\x1a"  # magic
        + bytes([1])  # 16KB PRG
        + bytes([0])  # no CHR
        + bytes([0])  # flags6: mapper-0 lower
        + bytes([0])  # flags7
        + bytes(8)
    )
    prg = bytearray(prg_size)
    sig = b"FamiTracker"
    prg[0x100 : 0x100 + len(sig)] = sig
    return header + bytes(prg)


@pytest.fixture
def fake_oracle(monkeypatch):
    """Patch FceuxOracle so render_rom_audio uses a fake one."""
    captured: dict = {}

    class _FakeOracle:
        def __init__(self, *a, **kw):
            captured["init"] = (a, kw)

        def trace(self, rom_path, frames=600):
            captured.setdefault("traces", []).append((rom_path, frames))
            return ApuTrace(
                events=[
                    TraceEvent(0, 0, 0x4015, 0x01),
                    TraceEvent(0, 1, 0x4000, 0xBF),
                    TraceEvent(0, 2, 0x4002, 0xFD),
                    TraceEvent(0, 3, 0x4003, 0x00),
                ],
                end_cycle=3,
            )

    monkeypatch.setattr("qlnes.audio.renderer.FceuxOracle", _FakeOracle)
    return captured


def test_supported_formats_a1_is_wav_only():
    assert supported_formats() == ("wav",)


def test_render_missing_rom_raises_missing_input(tmp_path):
    with pytest.raises(QlnesError) as exc:
        render_rom_audio_v2(tmp_path / "nope.nes", tmp_path / "out", oracle=None)
    assert exc.value.cls == "missing_input"


def test_render_unsupported_format_raises_bad_format_arg(tmp_path):
    rom = tmp_path / "rom.nes"
    rom.write_bytes(_make_minimal_ines_rom_with_signature())
    with pytest.raises(QlnesError) as exc:
        render_rom_audio_v2(rom, tmp_path / "out", fmt="ogg", oracle=None)
    assert exc.value.cls == "bad_format_arg"
    assert "ogg" in exc.value.reason


def test_render_unrecognized_engine_raises_unsupported_mapper(tmp_path, fake_oracle):
    """A ROM without any FT signature should fail engine detection."""
    rom = tmp_path / "rom.nes"
    # ROM with valid header but no FT signature in PRG.
    header = b"NES\x1a" + bytes([1, 0, 0, 0]) + bytes(8)
    rom.write_bytes(header + bytes(0x4000))
    with pytest.raises(QlnesError) as exc:
        render_rom_audio_v2(rom, tmp_path / "out", fmt="wav")
    assert exc.value.cls == "unsupported_mapper"


def test_render_writes_one_wav_per_song_with_deterministic_filenames(tmp_path, fake_oracle):
    rom = tmp_path / "metalstorm.nes"
    rom.write_bytes(_make_minimal_ines_rom_with_signature())
    out_dir = tmp_path / "tracks"
    result = render_rom_audio_v2(rom, out_dir, fmt="wav", frames=30)
    assert isinstance(result, RenderResult)
    assert result.engine_name == "famitracker"
    assert result.tier == 1
    assert len(result.output_paths) == 1
    p = result.output_paths[0]
    assert p.name == "metalstorm.00.famitracker.wav"
    assert p.exists()


def test_render_creates_output_dir_if_missing(tmp_path, fake_oracle):
    rom = tmp_path / "rom.nes"
    rom.write_bytes(_make_minimal_ines_rom_with_signature())
    out_dir = tmp_path / "deep" / "nested" / "out"
    render_rom_audio_v2(rom, out_dir, fmt="wav", frames=30)
    assert out_dir.exists()


def test_render_refuses_to_overwrite_without_force(tmp_path, fake_oracle):
    rom = tmp_path / "rom.nes"
    rom.write_bytes(_make_minimal_ines_rom_with_signature())
    out_dir = tmp_path / "tracks"
    out_dir.mkdir()
    expected = out_dir / "rom.00.famitracker.wav"
    expected.write_bytes(b"old content")
    with pytest.raises(QlnesError) as exc:
        render_rom_audio_v2(rom, out_dir, fmt="wav", frames=30)
    assert exc.value.cls == "cant_create"
    assert exc.value.extra["cause"] == "exists"
    assert expected.read_bytes() == b"old content"


def test_render_force_overwrites_existing(tmp_path, fake_oracle):
    rom = tmp_path / "rom.nes"
    rom.write_bytes(_make_minimal_ines_rom_with_signature())
    out_dir = tmp_path / "tracks"
    out_dir.mkdir()
    target = out_dir / "rom.00.famitracker.wav"
    target.write_bytes(b"old content")
    result = render_rom_audio_v2(rom, out_dir, fmt="wav", frames=30, force=True)
    assert result.output_paths[0] == target
    # New content has a RIFF header, not "old content".
    assert target.read_bytes()[:4] == b"RIFF"


def test_render_produced_wav_is_valid_riff(tmp_path, fake_oracle):
    rom = tmp_path / "rom.nes"
    rom.write_bytes(_make_minimal_ines_rom_with_signature())
    result = render_rom_audio_v2(rom, tmp_path / "out", fmt="wav", frames=30)
    p = result.output_paths[0]
    with wave.open(str(p), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 44100
        # 30 NTSC frames ≈ 0.5s ≈ 22050 samples.
        assert abs(wf.getnframes() - 22050) < 200


def test_render_two_consecutive_runs_byte_identical(tmp_path, fake_oracle):
    rom = tmp_path / "rom.nes"
    rom.write_bytes(_make_minimal_ines_rom_with_signature())
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    render_rom_audio_v2(rom, out_a, fmt="wav", frames=30)
    render_rom_audio_v2(rom, out_b, fmt="wav", frames=30)
    a = (out_a / "rom.00.famitracker.wav").read_bytes()
    b = (out_b / "rom.00.famitracker.wav").read_bytes()
    assert a == b


def test_render_passes_frames_to_oracle(tmp_path, fake_oracle):
    rom = tmp_path / "rom.nes"
    rom.write_bytes(_make_minimal_ines_rom_with_signature())
    render_rom_audio_v2(rom, tmp_path / "out", fmt="wav", frames=120)
    assert fake_oracle["traces"][0][1] == 120


def test_render_uses_provided_oracle_instance(tmp_path):
    """If caller passes oracle=..., FceuxOracle() is not constructed."""
    rom = tmp_path / "rom.nes"
    rom.write_bytes(_make_minimal_ines_rom_with_signature())

    class _MyOracle:
        def __init__(self):
            self.calls = 0

        def trace(self, rom_path, frames=600):
            self.calls += 1
            return ApuTrace(events=[], end_cycle=0)

    oracle = _MyOracle()
    render_rom_audio_v2(rom, tmp_path / "out", fmt="wav", frames=30, oracle=oracle)
    assert oracle.calls == 1
