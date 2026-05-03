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


def test_supported_formats_a1_a2_are_wav_and_mp3():
    assert supported_formats() == ("wav", "mp3")


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


# ---- A.2: MP3 path -------------------------------------------------------


def test_render_mp3_writes_file_with_mp3_extension(tmp_path, fake_oracle):
    rom = tmp_path / "rom.nes"
    rom.write_bytes(_make_minimal_ines_rom_with_signature())
    out_dir = tmp_path / "tracks"
    result = render_rom_audio_v2(rom, out_dir, fmt="mp3", frames=30)
    assert len(result.output_paths) == 1
    p = result.output_paths[0]
    assert p.suffix == ".mp3"
    assert p.name == "rom.00.famitracker.mp3"


def test_render_mp3_produces_valid_frame_header(tmp_path, fake_oracle):
    """Output must start with an MP3 frame sync (0xFF 0xFx)."""
    rom = tmp_path / "rom.nes"
    rom.write_bytes(_make_minimal_ines_rom_with_signature())
    result = render_rom_audio_v2(rom, tmp_path / "out", fmt="mp3", frames=30)
    blob = result.output_paths[0].read_bytes()
    assert blob[0] == 0xFF
    assert (blob[1] & 0xF0) == 0xF0


def test_render_mp3_two_runs_byte_identical_when_pinned(tmp_path, fake_oracle):
    """Determinism on the pinned encoder version (NFR-REL-1 caveat)."""
    from qlnes.audio.mp3 import is_pinned_version

    if not is_pinned_version():
        pytest.skip("MP3 byte-determinism only guaranteed on the pinned lameenc version")
    rom = tmp_path / "rom.nes"
    rom.write_bytes(_make_minimal_ines_rom_with_signature())
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    render_rom_audio_v2(rom, out_a, fmt="mp3", frames=30)
    render_rom_audio_v2(rom, out_b, fmt="mp3", frames=30)
    assert (out_a / "rom.00.famitracker.mp3").read_bytes() == (
        out_b / "rom.00.famitracker.mp3"
    ).read_bytes()


def test_render_mp3_emits_version_warning_when_drifted(tmp_path, fake_oracle, monkeypatch, capsys):
    """M-1 (readiness pass-2): warn if installed lameenc is outside the 1.8.x range."""
    import qlnes.audio.mp3 as mp3_mod
    import qlnes.audio.renderer as renderer_mod

    monkeypatch.setattr(renderer_mod, "_LAMEENC_INSTALLED", "9.9.9")
    monkeypatch.setattr(mp3_mod, "INSTALLED_VERSION", "9.9.9")
    rom = tmp_path / "rom.nes"
    rom.write_bytes(_make_minimal_ines_rom_with_signature())
    render_rom_audio_v2(rom, tmp_path / "out", fmt="mp3", frames=30)
    err = capsys.readouterr().err
    assert "qlnes: warning:" in err
    assert "mp3_encoder_version" in err
    assert "9.9.9" in err


def test_render_mp3_no_warning_when_pinned(tmp_path, fake_oracle, capsys):
    """No noisy warning when encoder version matches EXPECTED_VERSION."""
    from qlnes.audio.mp3 import is_pinned_version

    if not is_pinned_version():
        pytest.skip("requires pinned lameenc version")
    rom = tmp_path / "rom.nes"
    rom.write_bytes(_make_minimal_ines_rom_with_signature())
    render_rom_audio_v2(rom, tmp_path / "out", fmt="mp3", frames=30)
    err = capsys.readouterr().err
    assert "mp3_encoder_version" not in err


def test_render_mp3_pre_flight_when_lameenc_missing(tmp_path, fake_oracle, monkeypatch):
    """If lameenc is unavailable at fmt=mp3 time → internal_error before fceux runs."""
    import qlnes.audio.mp3 as mp3_mod

    monkeypatch.setattr(mp3_mod, "INSTALLED_VERSION", None)
    rom = tmp_path / "rom.nes"
    rom.write_bytes(_make_minimal_ines_rom_with_signature())
    with pytest.raises(QlnesError) as exc:
        render_rom_audio_v2(rom, tmp_path / "out", fmt="mp3", frames=30)
    assert exc.value.cls == "internal_error"
    assert exc.value.extra["dep"] == "lameenc"


def test_render_unsupported_format_now_lists_wav_and_mp3_in_error(tmp_path, fake_oracle):
    """The bad_format_arg message should reflect the current `supported_formats()`."""
    rom = tmp_path / "rom.nes"
    rom.write_bytes(_make_minimal_ines_rom_with_signature())
    with pytest.raises(QlnesError) as exc:
        render_rom_audio_v2(rom, tmp_path / "out", fmt="ogg")
    assert "wav" in exc.value.reason
    assert "mp3" in exc.value.reason


# ---- A.3: loop boundaries flow through to WAV `smpl` chunk -------------


def test_render_with_engine_loop_emits_smpl_chunk(tmp_path, fake_oracle, monkeypatch):
    """When engine.detect_loop returns a LoopBoundary, the WAV gets `smpl`."""
    import struct

    from qlnes.audio.engine import LoopBoundary, SoundEngineRegistry

    # Patch FT engine's detect_loop to return a known loop.
    eng_cls = next(e for e in SoundEngineRegistry._engines if e.name == "famitracker")
    monkeypatch.setattr(
        eng_cls,
        "detect_loop",
        lambda self, song, pcm: LoopBoundary(start_sample=10, end_sample=200),
    )

    rom = tmp_path / "rom.nes"
    rom.write_bytes(_make_minimal_ines_rom_with_signature())
    result = render_rom_audio_v2(rom, tmp_path / "out", fmt="wav", frames=30)
    blob = result.output_paths[0].read_bytes()
    assert b"smpl" in blob
    # Verify dwStart/dwEnd by walking RIFF chunks.
    pos = 12  # skip "RIFF<size>WAVE"
    while pos < len(blob):
        chunk_id = blob[pos : pos + 4]
        size = struct.unpack("<I", blob[pos + 4 : pos + 8])[0]
        if chunk_id == b"smpl":
            payload = blob[pos + 8 : pos + 8 + size]
            loop_record = payload[36:60]
            fields = struct.unpack("<IIIIII", loop_record)
            assert fields[2] == 10  # dwStart
            assert fields[3] == 200  # dwEnd
            break
        pos += 8 + size + (size % 2)


def test_render_without_engine_loop_emits_no_smpl(tmp_path, fake_oracle):
    """FT.detect_loop returns None in A.1 → WAV must NOT have `smpl`."""
    rom = tmp_path / "rom.nes"
    rom.write_bytes(_make_minimal_ines_rom_with_signature())
    result = render_rom_audio_v2(rom, tmp_path / "out", fmt="wav", frames=30)
    blob = result.output_paths[0].read_bytes()
    assert b"smpl" not in blob


# ---- D.1: --force interaction with other pre-flight checks ------------


def test_force_does_not_bypass_other_preflight_checks(tmp_path, fake_oracle):
    """--force only skips refuse-to-overwrite; bad ROM still raises bad_rom etc."""
    bad_rom = tmp_path / "rom.nes"
    bad_rom.write_bytes(b"NOT_INES")  # invalid magic
    with pytest.raises(QlnesError) as exc:
        render_rom_audio_v2(bad_rom, tmp_path / "out", fmt="wav", frames=30, force=True)
    # The renderer raises unsupported_mapper when no engine matches; the
    # important property is that --force does not silence this.
    assert exc.value.cls in ("unsupported_mapper", "bad_rom")


def test_force_does_not_bypass_missing_input(tmp_path, fake_oracle):
    """A missing ROM still raises missing_input even with --force."""
    with pytest.raises(QlnesError) as exc:
        render_rom_audio_v2(
            tmp_path / "nope.nes",
            tmp_path / "out",
            fmt="wav",
            frames=30,
            force=True,
        )
    assert exc.value.cls == "missing_input"


def test_multi_file_refuse_triggers_pre_flight_no_writes(tmp_path, fake_oracle, monkeypatch):
    """D.1: when ANY expected output exists and not --force, fail BEFORE writing
    any file. Pre-flight pass over all targets, dir-level atomicity guarantee."""
    from qlnes.audio.engine import SongEntry, SoundEngineRegistry

    eng_cls = next(e for e in SoundEngineRegistry._engines if e.name == "famitracker")
    monkeypatch.setattr(
        eng_cls,
        "walk_song_table",
        lambda self, rom: [
            SongEntry(index=0),
            SongEntry(index=1),
            SongEntry(index=2),
        ],
    )

    rom = tmp_path / "rom.nes"
    rom.write_bytes(_make_minimal_ines_rom_with_signature())
    out_dir = tmp_path / "tracks"
    out_dir.mkdir()

    # Pre-create the SECOND output file only — first is free.
    second = out_dir / "rom.01.famitracker.wav"
    second.write_bytes(b"existing")

    with pytest.raises(QlnesError) as exc:
        render_rom_audio_v2(rom, out_dir, fmt="wav", frames=30)
    assert exc.value.cls == "cant_create"
    assert "rom.01.famitracker.wav" in exc.value.extra["path"]
    # Dir-level atomicity: NO file should have been written this run.
    assert not (out_dir / "rom.00.famitracker.wav").exists()
    # Pre-existing file is untouched.
    assert second.read_bytes() == b"existing"


def test_dir_level_rollback_on_mid_render_failure(tmp_path, fake_oracle, monkeypatch):
    """D.1: if rendering fails mid-loop, files written earlier in THIS run are
    deleted. Pre-existing files at unrelated paths are not touched."""
    from qlnes.audio.engine import SongEntry, SoundEngineRegistry

    eng_cls = next(e for e in SoundEngineRegistry._engines if e.name == "famitracker")
    monkeypatch.setattr(
        eng_cls,
        "walk_song_table",
        lambda self, rom: [SongEntry(index=0), SongEntry(index=1), SongEntry(index=2)],
    )

    # Make render_song raise on the 2nd song (index 1).
    real_render = eng_cls.render_song
    call_count = {"n": 0}

    def flaky_render(self, rom, song, oracle, *, frames=600):
        call_count["n"] += 1
        if song.index == 1:
            raise RuntimeError("simulated render failure on song 1")
        return real_render(self, rom, song, oracle, frames=frames)

    monkeypatch.setattr(eng_cls, "render_song", flaky_render)

    rom = tmp_path / "rom.nes"
    rom.write_bytes(_make_minimal_ines_rom_with_signature())
    out_dir = tmp_path / "tracks"
    out_dir.mkdir()
    # Pre-existing unrelated file in same dir — must survive.
    (out_dir / "unrelated.txt").write_bytes(b"keep me")

    with pytest.raises(RuntimeError, match="simulated"):
        render_rom_audio_v2(rom, out_dir, fmt="wav", frames=30)

    # Song 0 was rendered + written, then song 1 failed → song 0's WAV must
    # have been rolled back.
    assert not (out_dir / "rom.00.famitracker.wav").exists()
    assert not (out_dir / "rom.01.famitracker.wav").exists()
    assert not (out_dir / "rom.02.famitracker.wav").exists()
    # Unrelated file untouched.
    assert (out_dir / "unrelated.txt").read_bytes() == b"keep me"


def test_render_mp3_drops_loop_info_silently(tmp_path, fake_oracle, monkeypatch):
    """MP3 has no `smpl` equivalent; loop info is dropped without error."""
    from qlnes.audio.engine import LoopBoundary, SoundEngineRegistry

    eng_cls = next(e for e in SoundEngineRegistry._engines if e.name == "famitracker")
    monkeypatch.setattr(
        eng_cls,
        "detect_loop",
        lambda self, song, pcm: LoopBoundary(start_sample=10, end_sample=200),
    )

    rom = tmp_path / "rom.nes"
    rom.write_bytes(_make_minimal_ines_rom_with_signature())
    result = render_rom_audio_v2(rom, tmp_path / "out", fmt="mp3", frames=30)
    blob = result.output_paths[0].read_bytes()
    # MP3 frame sync — sane MP3 file, loop info silently dropped.
    assert blob[0] == 0xFF
    assert (blob[1] & 0xF0) == 0xF0
