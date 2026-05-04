"""Unit tests for the F.5 engine-mode dispatch in render_rom_audio_v2.

Mocks the engine + oracle so these tests don't depend on the corpus
ROM or on fceux being installed. Exercises the 3-branch dispatch:
  - in-process: only render_song_in_process called
  - oracle: only render_song called, oracle constructed lazily
  - auto: in-process first; on InProcessUnavailable falls back to oracle
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from qlnes.audio.engine import (
    DetectionResult,
    InProcessUnavailable,
    LoopBoundary,
    PcmStream,
    SongEntry,
    SoundEngine,
    SoundEngineRegistry,
)
from qlnes.audio.renderer import RenderResult, render_rom_audio_v2
from qlnes.io.errors import QlnesError
from qlnes.rom import Rom


def _make_rom(tmp_path: Path) -> Path:
    """Synthetic 32 KB NROM ROM written to disk so render_rom_audio_v2
    can call Rom.from_file."""
    header = bytearray(16)
    header[0:4] = b"NES\x1a"
    header[4] = 2   # 2 × 16 KB PRG
    header[5] = 0
    prg = bytearray(0x8000)
    # Reset vector → $8000, NMI vector → $8000 (halt loop at $8000)
    prg[0x0000] = 0x4C  # JMP abs $8000
    prg[0x0001] = 0x00
    prg[0x0002] = 0x80
    prg[0x7FFC] = 0x00
    prg[0x7FFD] = 0x80
    prg[0x7FFA] = 0x00
    prg[0x7FFB] = 0x80
    rom_path = tmp_path / "synth.nes"
    rom_path.write_bytes(bytes(header) + bytes(prg))
    return rom_path


@pytest.fixture(autouse=True)
def _isolated_registry():
    """Each test gets a fresh registry so the engines we register here
    don't leak into other test files (and FT engine doesn't compete
    with our test stubs)."""
    saved = SoundEngineRegistry._engines.copy()
    SoundEngineRegistry._engines.clear()
    try:
        yield
    finally:
        SoundEngineRegistry._engines.clear()
        SoundEngineRegistry._engines.extend(saved)


def _silent_pcm() -> PcmStream:
    return PcmStream(samples=b"\x00\x00" * 1000, sample_rate=44_100, loop=None)


def _register_test_engine(
    *,
    in_process_supported: bool,
    in_process_call_log: list,
    oracle_call_log: list,
):
    """Build + register a SoundEngine that records which path was called."""

    class _StubEngine(SoundEngine):
        name = "stub"
        tier = 1
        target_mappers = frozenset()

        def detect(self, rom):
            return DetectionResult(confidence=1.0)

        def walk_song_table(self, rom):
            return [SongEntry(index=0)]

        def render_song(self, rom, song, oracle, *, frames=600):
            oracle_call_log.append((rom, song, oracle, frames))
            return _silent_pcm()

        def render_song_in_process(self, rom, song, *, frames=600):
            in_process_call_log.append((rom, song, frames))
            if not in_process_supported:
                raise InProcessUnavailable(self.name)
            return _silent_pcm()

        def detect_loop(self, song, pcm):
            return None

    SoundEngineRegistry._engines.append(_StubEngine)
    return _StubEngine


def test_engine_mode_in_process_calls_render_song_in_process_only(tmp_path):
    in_log: list = []
    or_log: list = []
    _register_test_engine(in_process_supported=True,
                          in_process_call_log=in_log,
                          oracle_call_log=or_log)
    rom_path = _make_rom(tmp_path)
    out = tmp_path / "out"
    result = render_rom_audio_v2(rom_path, out, engine_mode="in-process", frames=10)
    assert len(in_log) == 1
    assert len(or_log) == 0
    assert result.engine_mode_used == "in-process"


def test_engine_mode_oracle_calls_render_song_only(tmp_path):
    in_log: list = []
    or_log: list = []
    _register_test_engine(in_process_supported=True,
                          in_process_call_log=in_log,
                          oracle_call_log=or_log)
    # Oracle must be passed in (real FceuxOracle would shell out to fceux)
    fake_oracle = MagicMock()
    rom_path = _make_rom(tmp_path)
    out = tmp_path / "out"
    result = render_rom_audio_v2(
        rom_path, out, engine_mode="oracle", frames=10, oracle=fake_oracle
    )
    assert len(in_log) == 0
    assert len(or_log) == 1
    assert or_log[0][2] is fake_oracle
    assert result.engine_mode_used == "oracle"


def test_engine_mode_oracle_emits_deprecation_warning(tmp_path, capsys):
    """AC6: --engine-mode oracle prints `warning: oracle_path_deprecated` on stderr."""
    in_log: list = []
    or_log: list = []
    _register_test_engine(in_process_supported=True,
                          in_process_call_log=in_log,
                          oracle_call_log=or_log)
    rom_path = _make_rom(tmp_path)
    out = tmp_path / "out"
    render_rom_audio_v2(
        rom_path, out, engine_mode="oracle", frames=10, oracle=MagicMock()
    )
    captured = capsys.readouterr()
    assert "oracle_path_deprecated" in captured.err


def test_engine_mode_auto_prefers_in_process_when_available(tmp_path):
    in_log: list = []
    or_log: list = []
    _register_test_engine(in_process_supported=True,
                          in_process_call_log=in_log,
                          oracle_call_log=or_log)
    rom_path = _make_rom(tmp_path)
    out = tmp_path / "out"
    result = render_rom_audio_v2(rom_path, out, engine_mode="auto", frames=10)
    assert len(in_log) == 1
    assert len(or_log) == 0
    assert result.engine_mode_used == "in-process"


def test_engine_mode_auto_falls_back_on_in_process_unavailable(tmp_path, capsys):
    """AC3: auto with engine missing in-process support → oracle path + warning."""
    in_log: list = []
    or_log: list = []
    _register_test_engine(in_process_supported=False,
                          in_process_call_log=in_log,
                          oracle_call_log=or_log)
    rom_path = _make_rom(tmp_path)
    out = tmp_path / "out"
    fake_oracle = MagicMock()
    result = render_rom_audio_v2(
        rom_path, out, engine_mode="auto", frames=10, oracle=fake_oracle
    )
    assert len(in_log) == 1   # tried first
    assert len(or_log) == 1   # then fell back
    assert result.engine_mode_used == "oracle"
    captured = capsys.readouterr()
    assert "in_process_low_confidence" in captured.err


def test_engine_mode_in_process_raises_qlnes_error_for_unavailable_engine(tmp_path):
    """AC4: --engine-mode in-process on engine without addresses → exit 100."""
    in_log: list = []
    or_log: list = []
    _register_test_engine(in_process_supported=False,
                          in_process_call_log=in_log,
                          oracle_call_log=or_log)
    rom_path = _make_rom(tmp_path)
    out = tmp_path / "out"
    with pytest.raises(QlnesError) as exc_info:
        render_rom_audio_v2(rom_path, out, engine_mode="in-process", frames=10)
    assert exc_info.value.cls == "in_process_unavailable"
    assert exc_info.value.code == 100
    assert exc_info.value.extra.get("class") == "in_process_unavailable"
    assert exc_info.value.extra.get("engine") == "stub"


def test_render_result_carries_engine_mode_used(tmp_path):
    """AC8: RenderResult.engine_mode_used set per branch."""
    in_log: list = []
    or_log: list = []
    _register_test_engine(in_process_supported=True,
                          in_process_call_log=in_log,
                          oracle_call_log=or_log)
    rom_path = _make_rom(tmp_path)
    out = tmp_path / "out"
    r1 = render_rom_audio_v2(rom_path, out, engine_mode="in-process", frames=10)
    assert isinstance(r1, RenderResult)
    assert r1.engine_mode_used == "in-process"

    out2 = tmp_path / "out2"
    r2 = render_rom_audio_v2(
        rom_path, out2, engine_mode="oracle", frames=10, oracle=MagicMock()
    )
    assert r2.engine_mode_used == "oracle"


def test_engine_mode_invalid_value_raises_usage_error(tmp_path):
    """Bad --engine-mode value → QlnesError(usage_error)."""
    in_log: list = []
    or_log: list = []
    _register_test_engine(in_process_supported=True,
                          in_process_call_log=in_log,
                          oracle_call_log=or_log)
    rom_path = _make_rom(tmp_path)
    out = tmp_path / "out"
    with pytest.raises(QlnesError) as exc_info:
        render_rom_audio_v2(rom_path, out, engine_mode="bogus")  # type: ignore[arg-type]
    assert exc_info.value.cls == "usage_error"


def test_render_rom_audio_v2_default_engine_mode_is_auto(tmp_path):
    """AC7: missing engine_mode keyword → defaults to 'auto'."""
    in_log: list = []
    or_log: list = []
    _register_test_engine(in_process_supported=True,
                          in_process_call_log=in_log,
                          oracle_call_log=or_log)
    rom_path = _make_rom(tmp_path)
    out = tmp_path / "out"
    result = render_rom_audio_v2(rom_path, out, frames=10)
    # Auto picked in-process because engine supports it
    assert len(in_log) == 1
    assert len(or_log) == 0
    assert result.engine_mode_used == "in-process"
