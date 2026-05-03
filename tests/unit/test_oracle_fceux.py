"""Oracle subprocess wrapper + trace parser tests.

These tests avoid spawning fceux. The trace parser is exercised on inline
text fixtures; the subprocess path is exercised via an injected fceux_path
that points at a fake binary, with subprocess.run monkey-patched.

End-to-end tests against a real fceux + fixture ROM live in tests/integration
(phase 7.6).
"""

from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import pytest

from qlnes.io.errors import QlnesError
from qlnes.oracle.fceux import (
    FCEUX_DEFAULT_ARGS,
    LUA_SCRIPT_PATH,
    TRACE_HEADER,
    FceuxOracle,
    parse_trace_file,
)

# ---- parse_trace_file --------------------------------------------------


def test_parse_trace_minimal_valid(tmp_path):
    p = tmp_path / "t.tsv"
    p.write_text(f"{TRACE_HEADER}\n# columns: frame\\tcycle\\taddr_hex\\tvalue_hex\n")
    trace = parse_trace_file(p)
    assert trace.n_events == 0
    assert trace.end_cycle == 0


def test_parse_trace_one_event(tmp_path):
    p = tmp_path / "t.tsv"
    p.write_text(f"{TRACE_HEADER}\n0\t100\t4015\t0F\n")
    trace = parse_trace_file(p)
    assert trace.n_events == 1
    ev = trace.events[0]
    assert ev.frame == 0
    assert ev.cycle == 100
    assert ev.addr == 0x4015
    assert ev.value == 0x0F
    assert trace.end_cycle == 100


def test_parse_trace_multiple_events_track_end_cycle(tmp_path):
    p = tmp_path / "t.tsv"
    p.write_text(f"{TRACE_HEADER}\n0\t10\t4000\tBF\n0\t20\t4002\tFD\n1\t1800\t4015\t01\n")
    trace = parse_trace_file(p)
    assert trace.n_events == 3
    assert trace.end_cycle == 1800
    assert [e.addr for e in trace.events] == [0x4000, 0x4002, 0x4015]


def test_parse_trace_skips_comment_and_empty_lines(tmp_path):
    p = tmp_path / "t.tsv"
    p.write_text(
        f"{TRACE_HEADER}\n# comment\n\n0\t10\t4000\tBF\n# another comment\n1\t20\t4015\t01\n"
    )
    trace = parse_trace_file(p)
    assert trace.n_events == 2


def test_parse_trace_empty_file_raises(tmp_path):
    p = tmp_path / "t.tsv"
    p.write_text("")
    with pytest.raises(QlnesError) as exc:
        parse_trace_file(p)
    assert "empty" in exc.value.reason


def test_parse_trace_wrong_header_raises(tmp_path):
    p = tmp_path / "t.tsv"
    p.write_text("# qlnes-trace v999\n0\t10\t4000\tBF\n")
    with pytest.raises(QlnesError) as exc:
        parse_trace_file(p)
    assert "schema" in exc.value.reason


def test_parse_trace_malformed_row_raises(tmp_path):
    p = tmp_path / "t.tsv"
    p.write_text(f"{TRACE_HEADER}\n0\t10\t4000\n")  # only 3 columns
    with pytest.raises(QlnesError) as exc:
        parse_trace_file(p)
    assert "malformed" in exc.value.reason


def test_parse_trace_hex_values(tmp_path):
    """Verify hex parsing: addr_hex 4 chars, value_hex 2 chars."""
    p = tmp_path / "t.tsv"
    p.write_text(f"{TRACE_HEADER}\n0\t0\t4017\tFF\n0\t1\t4000\t00\n")
    trace = parse_trace_file(p)
    assert trace.events[0].addr == 0x4017
    assert trace.events[0].value == 0xFF
    assert trace.events[1].addr == 0x4000
    assert trace.events[1].value == 0x00


# ---- FceuxOracle init --------------------------------------------------


def test_oracle_init_raises_when_fceux_missing(monkeypatch):
    monkeypatch.setenv("PATH", "/nonexistent")
    with pytest.raises(QlnesError) as exc:
        FceuxOracle()
    assert exc.value.cls == "internal_error"
    assert "fceux" in exc.value.reason


def test_oracle_init_accepts_explicit_path(tmp_path):
    fake = tmp_path / "fceux"
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(0o755)
    oracle = FceuxOracle(fceux_path=str(fake))
    assert oracle.fceux_path == str(fake)


# ---- FceuxOracle.trace -------------------------------------------------


def test_trace_raises_on_missing_rom(tmp_path):
    fake = tmp_path / "fceux"
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(0o755)
    oracle = FceuxOracle(fceux_path=str(fake))
    missing = tmp_path / "nope.nes"
    with pytest.raises(QlnesError) as exc:
        oracle.trace(missing)
    assert exc.value.cls == "missing_input"


def test_trace_calls_fceux_with_locked_args(monkeypatch, tmp_path):
    """Ensure FCEUX_DEFAULT_ARGS + --loadlua + ROM path are passed verbatim."""
    fake = tmp_path / "fceux"
    fake.write_text("")
    fake.chmod(0o755)
    rom = tmp_path / "rom.nes"
    rom.write_bytes(b"NES\x1a")

    captured: dict = {}

    def fake_run(cmd, env=None, capture_output=False, timeout=None):
        captured["cmd"] = cmd
        captured["env"] = env
        # Mock the trace file the Lua script would have produced.
        trace_out = env["QLNES_TRACE_OUT"]
        Path(trace_out).write_text(f"{TRACE_HEADER}\n0\t10\t4015\t0F\n")
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)

    oracle = FceuxOracle(fceux_path=str(fake))
    trace = oracle.trace(rom, frames=300)
    assert trace.n_events == 1
    assert captured["cmd"][0] == str(fake)
    for arg in FCEUX_DEFAULT_ARGS:
        assert arg in captured["cmd"]
    assert "--loadlua" in captured["cmd"]
    assert str(LUA_SCRIPT_PATH) in captured["cmd"]
    assert str(rom) in captured["cmd"]
    assert captured["env"]["QLNES_FRAMES"] == "300"


def test_trace_strips_ambient_qlnes_env_vars(monkeypatch, tmp_path):
    """Caller's QLNES_AUDIO_FORMAT etc. must not leak into fceux's env."""
    fake = tmp_path / "fceux"
    fake.write_text("")
    fake.chmod(0o755)
    rom = tmp_path / "rom.nes"
    rom.write_bytes(b"NES\x1a")
    monkeypatch.setenv("QLNES_AUDIO_FORMAT", "mp3")
    monkeypatch.setenv("QLNES_NOISY", "1")

    captured_env: dict[str, str] = {}

    def fake_run(cmd, env=None, capture_output=False, timeout=None):
        captured_env.update(env or {})
        trace_out = env["QLNES_TRACE_OUT"]
        Path(trace_out).write_text(f"{TRACE_HEADER}\n")
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    oracle = FceuxOracle(fceux_path=str(fake))
    oracle.trace(rom, frames=10)

    qlnes_keys = {k for k in captured_env if k.startswith("QLNES_")}
    assert qlnes_keys <= {"QLNES_TRACE_OUT", "QLNES_FRAMES", "QLNES_REFERENCE_WAV"}


def test_trace_raises_on_nonzero_exit(monkeypatch, tmp_path):
    fake = tmp_path / "fceux"
    fake.write_text("")
    fake.chmod(0o755)
    rom = tmp_path / "rom.nes"
    rom.write_bytes(b"NES\x1a")

    def fake_run(cmd, env=None, capture_output=False, timeout=None):
        return subprocess.CompletedProcess(cmd, 1, stdout=b"", stderr=b"oops")

    monkeypatch.setattr(subprocess, "run", fake_run)
    oracle = FceuxOracle(fceux_path=str(fake))
    with pytest.raises(QlnesError) as exc:
        oracle.trace(rom)
    assert exc.value.cls == "internal_error"
    assert exc.value.extra["fceux_exit"] == 1
    assert "oops" in exc.value.extra["stderr"]


def test_trace_raises_on_timeout(monkeypatch, tmp_path):
    fake = tmp_path / "fceux"
    fake.write_text("")
    fake.chmod(0o755)
    rom = tmp_path / "rom.nes"
    rom.write_bytes(b"NES\x1a")

    def fake_run(cmd, env=None, capture_output=False, timeout=None):
        raise subprocess.TimeoutExpired(cmd, timeout=timeout or 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    oracle = FceuxOracle(fceux_path=str(fake), timeout_seconds=0.5)
    with pytest.raises(QlnesError) as exc:
        oracle.trace(rom)
    assert exc.value.cls == "internal_error"
    assert exc.value.extra["detail"] == "timeout"


def test_trace_raises_when_no_trace_file_produced(monkeypatch, tmp_path):
    fake = tmp_path / "fceux"
    fake.write_text("")
    fake.chmod(0o755)
    rom = tmp_path / "rom.nes"
    rom.write_bytes(b"NES\x1a")

    def fake_run(cmd, env=None, capture_output=False, timeout=None):
        # Exit clean but write no trace.
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    oracle = FceuxOracle(fceux_path=str(fake))
    with pytest.raises(QlnesError) as exc:
        oracle.trace(rom)
    assert "produced no trace" in exc.value.reason


# ---- reference_pcm -----------------------------------------------------


def test_reference_pcm_strips_riff_header(monkeypatch, tmp_path):
    fake = tmp_path / "fceux"
    fake.write_text("")
    fake.chmod(0o755)
    rom = tmp_path / "rom.nes"
    rom.write_bytes(b"NES\x1a")

    def fake_run(cmd, env=None, capture_output=False, timeout=None):
        Path(env["QLNES_TRACE_OUT"]).write_text(f"{TRACE_HEADER}\n")
        # Lua writes the ref WAV; mock it with a real WAV file.
        ref_path = Path(env["QLNES_REFERENCE_WAV"])
        with wave.open(str(ref_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(44100)
            wf.writeframes(b"\x00\x00\xff\xff\x55\xaa")  # 3 sample frames
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    oracle = FceuxOracle(fceux_path=str(fake))
    pcm = oracle.reference_pcm(rom, frames=60)
    assert pcm == b"\x00\x00\xff\xff\x55\xaa"
    # Decoded as int16 LE: [0, -1, -21931]  (0xaa55 = -21931 signed)
    samples = [int.from_bytes(pcm[i : i + 2], "little", signed=True) for i in range(0, len(pcm), 2)]
    assert samples == [0, -1, -21931]


# ---- Lua script existence ----------------------------------------------


def test_lua_script_exists():
    assert LUA_SCRIPT_PATH.exists()
    text = LUA_SCRIPT_PATH.read_text(encoding="utf-8")
    # The Lua script writes the header it claims to write.
    assert TRACE_HEADER in text


def test_lua_script_writes_v1_header():
    text = LUA_SCRIPT_PATH.read_text(encoding="utf-8")
    assert "qlnes-trace v1" in text


def test_lua_script_supports_reference_wav_capture():
    text = LUA_SCRIPT_PATH.read_text(encoding="utf-8")
    assert "QLNES_REFERENCE_WAV" in text
    assert "sound.recordstart" in text
