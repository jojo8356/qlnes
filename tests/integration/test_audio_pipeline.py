"""End-to-end audio pipeline tests with REAL fceux subprocess.

Uses a synthetic minimal NROM-128 ROM (FamiTracker signature embedded so
detection succeeds, code = `JMP $8000` infinite loop). fceux runs it for the
requested frame count, the trace TSV captures zero APU writes (the ROM does
nothing), the renderer produces silence — but the **pipeline** is exercised
end-to-end: subprocess invocation, Lua trace parsing, APU replay, WAV write.

Tests skip gracefully when fceux isn't available or when the subprocess
fails (e.g. headless host with no DISPLAY). Sample-equivalence tests against
real ROMs live in tests/invariants/test_pcm_equivalence.py and parametrize on
`corpus/manifest.toml` (B.3 lands the corpus).
"""

from __future__ import annotations

import shutil
import wave
from pathlib import Path

import pytest

from qlnes.audio.renderer import render_rom_audio_v2
from qlnes.io.errors import QlnesError


def _build_synthetic_nrom_with_ft_signature() -> bytes:
    """Mapper-0 NROM-128 (16KB PRG) with FT signature + infinite-loop code."""
    header = b"NES\x1a" + bytes([1, 0, 0, 0]) + bytes(8)
    prg = bytearray(0x4000)
    # 6502 boot code at $8000: SEI, CLD, LDX #$FF, TXS, JMP $8004 (loop forever).
    code = bytes(
        [
            0x78,  # SEI
            0xD8,  # CLD
            0xA2,
            0xFF,  # LDX #$FF
            0x9A,  # TXS
            0x4C,
            0x04,
            0x80,  # JMP $8004 (infinite loop on TXS-after)
        ]
    )
    prg[0 : len(code)] = code
    # FamiTracker ASCII signature at offset 0x100 — high enough to not collide
    # with code, low enough that any signature scanner finds it quickly.
    sig = b"FamiTracker"
    prg[0x100 : 0x100 + len(sig)] = sig
    # Reset vector at PRG offset 0x3FFC (CPU $FFFC after NROM-128 mirroring) →
    # points to $8000.
    prg[0x3FFC] = 0x00
    prg[0x3FFD] = 0x80
    # IRQ/NMI vectors → also $8000 to satisfy fceux's NMI-driven loop start.
    prg[0x3FFA] = 0x00
    prg[0x3FFB] = 0x80
    prg[0x3FFE] = 0x00
    prg[0x3FFF] = 0x80
    return header + bytes(prg)


def _has_fceux() -> bool:
    return shutil.which("fceux") is not None


pytestmark = pytest.mark.skipif(
    not _has_fceux(),
    reason="fceux not on PATH — install fceux >= 2.6.6 to run e2e audio tests",
)


@pytest.fixture
def synthetic_rom(tmp_path):
    rom_path = tmp_path / "synthetic.nes"
    rom_path.write_bytes(_build_synthetic_nrom_with_ft_signature())
    return rom_path


def _render_or_skip(rom_path: Path, output_dir: Path, **kwargs):
    """Run the renderer; skip the test if fceux subprocess fails for env
    reasons (no DISPLAY, locked audio device, etc.)."""
    try:
        return render_rom_audio_v2(rom_path, output_dir, **kwargs)
    except QlnesError as e:
        if e.cls == "internal_error" and "fceux" in e.reason.lower():
            pytest.skip(f"fceux subprocess failed: {e.reason}")
        raise


# ---- e2e pipeline ----------------------------------------------------


def test_pipeline_runs_end_to_end_on_synthetic_rom(synthetic_rom, tmp_path):
    out_dir = tmp_path / "tracks"
    result = _render_or_skip(synthetic_rom, out_dir, fmt="wav", frames=60)
    assert result.engine_name == "famitracker"
    assert result.tier == 1
    assert len(result.output_paths) == 1
    assert result.output_paths[0].exists()


def test_filenames_deterministic_format(synthetic_rom, tmp_path):
    out_dir = tmp_path / "tracks"
    result = _render_or_skip(synthetic_rom, out_dir, fmt="wav", frames=60)
    p = result.output_paths[0]
    assert p.name == "synthetic.00.famitracker.wav"


def test_produced_wav_is_valid_riff(synthetic_rom, tmp_path):
    out_dir = tmp_path / "tracks"
    result = _render_or_skip(synthetic_rom, out_dir, fmt="wav", frames=60)
    with wave.open(str(result.output_paths[0]), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 44_100
        # 60 NTSC frames ≈ 1 s ≈ 44_100 samples (±100 for resampler boundary).
        assert abs(wf.getnframes() - 44_100) < 200


def test_silence_rom_produces_silence_pcm(synthetic_rom, tmp_path):
    """Synthetic NOP ROM has no APU writes → all-silence DC offset."""
    out_dir = tmp_path / "tracks"
    result = _render_or_skip(synthetic_rom, out_dir, fmt="wav", frames=60)
    with wave.open(str(result.output_paths[0]), "rb") as wf:
        n = wf.getnframes()
        raw = wf.readframes(n)
    samples = [int.from_bytes(raw[i : i + 2], "little", signed=True) for i in range(0, len(raw), 2)]
    # All samples should be the resampler's DC offset (-16384). If fceux
    # injected any APU writes via init code we can't predict, allow tiny drift.
    distinct = len(set(samples))
    assert distinct <= 5, f"expected near-silent output, got {distinct} distinct sample values"


def test_render_creates_output_dir(synthetic_rom, tmp_path):
    out_dir = tmp_path / "newly" / "deep" / "dir"
    _render_or_skip(synthetic_rom, out_dir, fmt="wav", frames=60)
    assert out_dir.exists()


def test_force_overwrites_existing_output(synthetic_rom, tmp_path):
    out_dir = tmp_path / "tracks"
    out_dir.mkdir()
    target = out_dir / "synthetic.00.famitracker.wav"
    target.write_bytes(b"old content")
    _render_or_skip(synthetic_rom, out_dir, fmt="wav", frames=60, force=True)
    assert target.read_bytes()[:4] == b"RIFF"


def test_no_force_refuses_to_overwrite(synthetic_rom, tmp_path):
    out_dir = tmp_path / "tracks"
    out_dir.mkdir()
    target = out_dir / "synthetic.00.famitracker.wav"
    target.write_bytes(b"x" * 100)
    with pytest.raises(QlnesError) as exc:
        _render_or_skip(synthetic_rom, out_dir, fmt="wav", frames=60)
    assert exc.value.cls == "cant_create"
    assert target.read_bytes() == b"x" * 100
