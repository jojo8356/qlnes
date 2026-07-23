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

import json
import shutil
import wave
from itertools import pairwise
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


def _build_synthetic_nrom_with_a440_pulse() -> bytes:
    """Mapper-0 NROM-128 that produces an audible Pulse 1 A4 tone.

    The reset handler configures Pulse 1 once, then stays in a stable loop.
    The renderer's in-process path keeps the APU running until the requested
    frame count.
    Timer 253 gives CPU / (16 * (253 + 1)) = ~440.40 Hz on NTSC.
    """
    header = b"NES\x1a" + bytes([1, 0, 0, 0]) + bytes(8)
    prg = bytearray(0x4000)
    code = bytes(
        [
            0x78,  # SEI
            0xD8,  # CLD
            0xA9,
            0x01,
            0x8D,
            0x15,
            0x40,  # LDA #$01 ; STA $4015 (enable pulse 1)
            0xA9,
            0xBF,
            0x8D,
            0x00,
            0x40,  # LDA #$BF ; STA $4000 (50% duty, halt, const vol 15)
            0xA9,
            0x00,
            0x8D,
            0x01,
            0x40,  # LDA #$00 ; STA $4001 (sweep off)
            0xA9,
            0xFD,
            0x8D,
            0x02,
            0x40,  # LDA #$FD ; STA $4002 (timer low)
            0xA9,
            0x08,
            0x8D,
            0x03,
            0x40,  # LDA #$08 ; STA $4003 (timer high=0, length load)
            0x4C,
            0x1B,
            0x80,  # JMP $801B (stable loop after init)
        ]
    )
    prg[0 : len(code)] = code
    sig = b"FamiTracker"
    prg[0x100 : 0x100 + len(sig)] = sig
    # Reset vector -> $8000; NMI/IRQ use an RTI stub.
    prg[0x0200] = 0x40  # RTI
    prg[0x3FFA] = 0x00
    prg[0x3FFB] = 0x82
    prg[0x3FFC] = 0x00
    prg[0x3FFD] = 0x80
    prg[0x3FFE] = 0x00
    prg[0x3FFF] = 0x82
    return header + bytes(prg)


def _pulse_init_routine(timer: int) -> bytes:
    return bytes(
        [
            0x78,  # SEI
            0xD8,  # CLD
            0xA9,
            0x01,
            0x8D,
            0x15,
            0x40,  # LDA #$01 ; STA $4015
            0xA9,
            0xBF,
            0x8D,
            0x00,
            0x40,  # LDA #$BF ; STA $4000
            0xA9,
            0x00,
            0x8D,
            0x01,
            0x40,  # LDA #$00 ; STA $4001
            0xA9,
            timer & 0xFF,
            0x8D,
            0x02,
            0x40,  # LDA #timer_lo ; STA $4002
            0xA9,
            0x08 | ((timer >> 8) & 0x07),
            0x8D,
            0x03,
            0x40,  # LDA #timer_hi + length ; STA $4003
            0x60,  # RTS
        ]
    )


def _build_synthetic_nrom_with_two_metadata_songs() -> bytes:
    """Mapper-0 fixture with two independently selectable song init routines."""
    header = b"NES\x1a" + bytes([1, 0, 0, 0]) + bytes(8)
    prg = bytearray(0x4000)
    prg[0x0000 : 0x0000 + 28] = _pulse_init_routine(253)  # ~440.40 Hz
    prg[0x0040 : 0x0040 + 28] = _pulse_init_routine(213)  # ~522.72 Hz
    prg[0x0200] = 0x60  # shared play routine: RTS, APU keeps ringing
    sig = b"FamiTracker"
    prg[0x100 : 0x100 + len(sig)] = sig
    payload = {
        "songs": [
            {
                "index": 0,
                "label": "a4",
                "referenced": True,
                "init_addr": 0x8000,
                "play_addr": 0x8200,
                "loop": {"start_sample": 100, "end_sample": 1000},
            },
            {
                "index": 1,
                "label": "c5",
                "referenced": False,
                "init_addr": 0x8040,
                "play_addr": 0x8200,
            },
        ]
    }
    blob = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    metadata = b"QLNESFTMETA1\x00" + len(blob).to_bytes(2, "little") + blob
    prg[0x0300 : 0x0300 + len(metadata)] = metadata
    prg[0x3FFA] = 0x00
    prg[0x3FFB] = 0x82
    prg[0x3FFC] = 0x00
    prg[0x3FFD] = 0x80
    prg[0x3FFE] = 0x00
    prg[0x3FFF] = 0x82
    return header + bytes(prg)


def _build_synthetic_nrom_with_famitone2_table() -> bytes:
    """Mapper-0 fixture with a raw FamiTone2 music-data table only."""
    header = b"NES\x1a" + bytes([1, 0, 0, 0]) + bytes(8)
    prg = bytearray(0x4000)
    table = 0x0100
    prg[table] = 2
    prg[table + 1 : table + 3] = (0x8300).to_bytes(2, "little")
    prg[table + 3 : table + 5] = (0x83FD).to_bytes(2, "little")
    prg[0x0300] = 0x30
    prg[0x0400] = 0x00

    note_codes = [46, 49]  # A4, C5 in FamiTone2's C1-based note numbering.
    for song, note_code in enumerate(note_codes):
        base = table + 5 + song * 14
        for channel in range(5):
            pointer = 0x8500 + song * 0x100 + channel * 0x10
            prg[base + channel * 2 : base + channel * 2 + 2] = pointer.to_bytes(
                2, "little"
            )
            stream = pointer - 0x8000
            if channel == 0:
                prg[stream : stream + 4] = bytes(
                    [note_code << 1, 0xFD, pointer & 0xFF, pointer >> 8]
                )
            else:
                prg[stream : stream + 4] = bytes([0, 0xFD, pointer & 0xFF, pointer >> 8])
        prg[base + 10 : base + 12] = (307).to_bytes(2, "little")
        prg[base + 12 : base + 14] = (256).to_bytes(2, "little")

    prg[0:3] = bytes([0x4C, 0x00, 0x80])
    prg[0x3FFA] = 0x00
    prg[0x3FFB] = 0x80
    prg[0x3FFC] = 0x00
    prg[0x3FFD] = 0x80
    prg[0x3FFE] = 0x00
    prg[0x3FFF] = 0x80
    return header + bytes(prg)


def _build_synthetic_nrom_with_famitone2_note_change() -> bytes:
    rom = bytearray(_build_synthetic_nrom_with_famitone2_table())
    prg_start = 16
    stream0 = prg_start + 0x0500
    # A4 for row 0 plus four empty rows at speed 6 (~0.5 s), then C5 loop.
    rom[stream0 : stream0 + 6] = bytes([46 << 1, 0x87, 49 << 1, 0xFD, 0x02, 0x85])
    return bytes(rom)


def _build_synthetic_nrom_with_famitone2_pulse2_only() -> bytes:
    rom = bytearray(_build_synthetic_nrom_with_famitone2_table())
    prg_start = 16
    song0_ch0 = prg_start + 0x0500
    song0_ch1 = prg_start + 0x0510
    rom[song0_ch0 : song0_ch0 + 4] = bytes([0, 0xFD, 0x00, 0x85])
    rom[song0_ch1 : song0_ch1 + 4] = bytes([49 << 1, 0xFD, 0x10, 0x85])
    return bytes(rom)


def _build_synthetic_nrom_with_famitone2_triangle_only() -> bytes:
    rom = bytearray(_build_synthetic_nrom_with_famitone2_table())
    prg_start = 16
    song0_ch0 = prg_start + 0x0500
    song0_ch1 = prg_start + 0x0510
    song0_ch2 = prg_start + 0x0520
    rom[song0_ch0 : song0_ch0 + 4] = bytes([0, 0xFD, 0x00, 0x85])
    rom[song0_ch1 : song0_ch1 + 4] = bytes([0, 0xFD, 0x10, 0x85])
    rom[song0_ch2 : song0_ch2 + 4] = bytes([49 << 1, 0xFD, 0x20, 0x85])
    return bytes(rom)


def _dominant_frequency(samples: list[int], sample_rate: int) -> float:
    """Estimate dominant frequency from rising zero crossings.

    The synthetic fixture is a stable 50% duty pulse wave with a DC offset,
    so zero-crossing period measurement is enough and avoids adding numpy.
    """
    mean = sum(samples) / len(samples)
    centered = [s - mean for s in samples]
    crossings: list[int] = []
    for i in range(1, len(centered)):
        if centered[i - 1] <= 0 < centered[i]:
            crossings.append(i)
    periods = [b - a for a, b in pairwise(crossings) if b > a]
    if not periods:
        return 0.0
    periods = periods[len(periods) // 10 : -(len(periods) // 10) or None]
    avg_period = sum(periods) / len(periods)
    return sample_rate / avg_period


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


@pytest.fixture
def synthetic_a440_rom(tmp_path):
    rom_path = tmp_path / "synthetic_a440.nes"
    rom_path.write_bytes(_build_synthetic_nrom_with_a440_pulse())
    return rom_path


@pytest.fixture
def synthetic_two_song_rom(tmp_path):
    rom_path = tmp_path / "synthetic_two_song.nes"
    rom_path.write_bytes(_build_synthetic_nrom_with_two_metadata_songs())
    return rom_path


@pytest.fixture
def synthetic_famitone2_rom(tmp_path):
    rom_path = tmp_path / "synthetic_famitone2.nes"
    rom_path.write_bytes(_build_synthetic_nrom_with_famitone2_table())
    return rom_path


@pytest.fixture
def synthetic_famitone2_note_change_rom(tmp_path):
    rom_path = tmp_path / "synthetic_famitone2_change.nes"
    rom_path.write_bytes(_build_synthetic_nrom_with_famitone2_note_change())
    return rom_path


@pytest.fixture
def synthetic_famitone2_pulse2_rom(tmp_path):
    rom_path = tmp_path / "synthetic_famitone2_pulse2.nes"
    rom_path.write_bytes(_build_synthetic_nrom_with_famitone2_pulse2_only())
    return rom_path


@pytest.fixture
def synthetic_famitone2_triangle_rom(tmp_path):
    rom_path = tmp_path / "synthetic_famitone2_triangle.nes"
    rom_path.write_bytes(_build_synthetic_nrom_with_famitone2_triangle_only())
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


def test_rendered_music_is_longer_than_one_second_and_matches_expected_frequency(
    synthetic_a440_rom, tmp_path
):
    out_dir = tmp_path / "tracks"
    result = render_rom_audio_v2(
        synthetic_a440_rom,
        out_dir,
        fmt="wav",
        frames=90,
        engine_mode="in-process",
    )
    with wave.open(str(result.output_paths[0]), "rb") as wf:
        sample_rate = wf.getframerate()
        frame_count = wf.getnframes()
        raw = wf.readframes(frame_count)
    samples = [
        int.from_bytes(raw[i : i + 2], "little", signed=True)
        for i in range(0, len(raw), 2)
    ]
    duration = frame_count / sample_rate
    peak_to_peak = max(samples) - min(samples)
    measured_hz = _dominant_frequency(samples[sample_rate // 10 :], sample_rate)

    assert duration > 1.0
    assert peak_to_peak > 1000
    assert measured_hz == pytest.approx(440.4, abs=2.0)


def test_metadata_song_table_renders_all_songs_with_distinct_expected_frequencies(
    synthetic_two_song_rom, tmp_path
):
    out_dir = tmp_path / "tracks"
    result = render_rom_audio_v2(
        synthetic_two_song_rom,
        out_dir,
        fmt="wav",
        frames=90,
        engine_mode="in-process",
    )
    assert [p.name for p in result.output_paths] == [
        "synthetic_two_song.00.famitracker.wav",
        "synthetic_two_song.01.famitracker.wav",
    ]

    measured: list[float] = []
    for path in result.output_paths:
        with wave.open(str(path), "rb") as wf:
            sample_rate = wf.getframerate()
            frame_count = wf.getnframes()
            raw = wf.readframes(frame_count)
        samples = [
            int.from_bytes(raw[i : i + 2], "little", signed=True)
            for i in range(0, len(raw), 2)
        ]
        assert frame_count / sample_rate > 1.0
        assert max(samples) - min(samples) > 1000
        measured.append(_dominant_frequency(samples[sample_rate // 10 :], sample_rate))

    assert measured[0] == pytest.approx(440.4, abs=2.0)
    assert measured[1] == pytest.approx(522.7, abs=2.0)
    assert b"smpl" in result.output_paths[0].read_bytes()
    assert b"smpl" not in result.output_paths[1].read_bytes()


def test_famitone2_table_renders_all_detected_songs_with_expected_frequencies(
    synthetic_famitone2_rom, tmp_path
):
    result = render_rom_audio_v2(
        synthetic_famitone2_rom,
        tmp_path / "tracks",
        fmt="wav",
        frames=90,
        engine_mode="in-process",
    )
    assert [p.name for p in result.output_paths] == [
        "synthetic_famitone2.00.famitracker.wav",
        "synthetic_famitone2.01.famitracker.wav",
    ]
    assert [track.status for track in result.tracks] == ["unverified", "unverified"]

    measured: list[float] = []
    for path in result.output_paths:
        with wave.open(str(path), "rb") as wf:
            sample_rate = wf.getframerate()
            frame_count = wf.getnframes()
            raw = wf.readframes(frame_count)
        samples = [
            int.from_bytes(raw[i : i + 2], "little", signed=True)
            for i in range(0, len(raw), 2)
        ]
        assert frame_count / sample_rate > 1.0
        assert max(samples) - min(samples) > 1000
        measured.append(_dominant_frequency(samples[sample_rate // 10 :], sample_rate))

    assert measured[0] == pytest.approx(440.0, abs=2.0)
    assert measured[1] == pytest.approx(523.25, abs=2.0)


def test_famitone2_static_render_follows_note_changes(
    synthetic_famitone2_note_change_rom, tmp_path
):
    result = render_rom_audio_v2(
        synthetic_famitone2_note_change_rom,
        tmp_path / "tracks",
        fmt="wav",
        frames=90,
        engine_mode="in-process",
    )
    with wave.open(str(result.output_paths[0]), "rb") as wf:
        sample_rate = wf.getframerate()
        frame_count = wf.getnframes()
        raw = wf.readframes(frame_count)
    samples = [
        int.from_bytes(raw[i : i + 2], "little", signed=True)
        for i in range(0, len(raw), 2)
    ]
    first_segment = samples[int(sample_rate * 0.15) : int(sample_rate * 0.45)]
    second_segment = samples[int(sample_rate * 0.75) : int(sample_rate * 1.25)]

    assert frame_count / sample_rate > 1.0
    assert _dominant_frequency(first_segment, sample_rate) == pytest.approx(440.0, abs=2.0)
    assert _dominant_frequency(second_segment, sample_rate) == pytest.approx(523.25, abs=2.0)


def test_famitone2_static_render_uses_pulse2_when_pulse1_is_silent(
    synthetic_famitone2_pulse2_rom, tmp_path
):
    result = render_rom_audio_v2(
        synthetic_famitone2_pulse2_rom,
        tmp_path / "tracks",
        fmt="wav",
        frames=90,
        engine_mode="in-process",
    )
    with wave.open(str(result.output_paths[0]), "rb") as wf:
        sample_rate = wf.getframerate()
        frame_count = wf.getnframes()
        raw = wf.readframes(frame_count)
    samples = [
        int.from_bytes(raw[i : i + 2], "little", signed=True)
        for i in range(0, len(raw), 2)
    ]

    assert frame_count / sample_rate > 1.0
    assert max(samples) - min(samples) > 1000
    assert result.tracks[0].song_metadata["first_note_channel"] == 1
    assert result.tracks[0].song_metadata["expected_frequency_hz"] == pytest.approx(
        523.25, abs=0.01
    )
    assert _dominant_frequency(samples[sample_rate // 10 :], sample_rate) == pytest.approx(
        523.25, abs=2.0
    )


def test_famitone2_static_render_uses_triangle_when_pulses_are_silent(
    synthetic_famitone2_triangle_rom, tmp_path
):
    result = render_rom_audio_v2(
        synthetic_famitone2_triangle_rom,
        tmp_path / "tracks",
        fmt="wav",
        frames=90,
        engine_mode="in-process",
    )
    with wave.open(str(result.output_paths[0]), "rb") as wf:
        sample_rate = wf.getframerate()
        frame_count = wf.getnframes()
        raw = wf.readframes(frame_count)
    samples = [
        int.from_bytes(raw[i : i + 2], "little", signed=True)
        for i in range(0, len(raw), 2)
    ]

    assert frame_count / sample_rate > 1.0
    assert max(samples) - min(samples) > 1000
    assert result.tracks[0].song_metadata["first_note_channel"] == 2
    assert result.tracks[0].song_metadata["expected_frequency_hz"] == pytest.approx(
        523.25, abs=0.01
    )
    assert _dominant_frequency(samples[sample_rate // 10 :], sample_rate) == pytest.approx(
        523.25, abs=2.0
    )
