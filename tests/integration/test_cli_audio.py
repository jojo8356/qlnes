"""End-to-end CLI tests for `qlnes audio` — Lin's subprocess pattern.

Spawns the qlnes CLI as a subprocess (matches how Lin's pipeline integrates
qlnes per UX §11.3). Parses stderr's trailing JSON to validate the structured
error contract.

These tests do NOT require fceux: the unsupported-mapper path triggers before
the renderer constructs FceuxOracle, and the missing-input path triggers in
pre-flight. The fceux-required path lives in test_audio_pipeline_e2e.py
(phase 7.6).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_qlnes(*args: str, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ}
    # Strip ambient QLNES_* vars that could perturb config-loader behavior.
    for k in list(env):
        if k.startswith("QLNES_"):
            del env[k]
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-m", "qlnes", *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
        timeout=30,
    )


def _parse_trailing_json(stderr: str) -> dict:
    """Lin's pipeline pattern: parse the LAST line of stderr as JSON."""
    lines = [ln for ln in stderr.strip().splitlines() if ln]
    return json.loads(lines[-1])


def _make_minimal_ines_rom_with_signature(prg_size: int = 0x4000) -> bytes:
    header = b"NES\x1a" + bytes([1, 0, 0, 0]) + bytes(8)
    prg = bytearray(prg_size)
    prg[0x100 : 0x100 + len(b"FamiTracker")] = b"FamiTracker"
    return header + bytes(prg)


# ---- exit-code contract --------------------------------------------------


def test_audio_help_exits_zero():
    """`audio --help` must exit 0 (Typer convention)."""
    res = _run_qlnes("audio", "--help")
    assert res.returncode == 0
    assert "Rend l'audio" in res.stdout


def test_audio_missing_rom_exits_66(tmp_path):
    res = _run_qlnes("audio", str(tmp_path / "nope.nes"), "-o", str(tmp_path / "out"))
    assert res.returncode == 66
    payload = _parse_trailing_json(res.stderr)
    assert payload["class"] == "missing_input"
    assert payload["code"] == 66
    assert "path" in payload


def test_audio_missing_rom_emits_hint_by_default(tmp_path):
    res = _run_qlnes("audio", str(tmp_path / "nope.nes"), "-o", str(tmp_path / "out"))
    assert "hint:" in res.stderr


def test_audio_missing_rom_no_hints_strips_hint(tmp_path):
    res = _run_qlnes(
        "audio",
        str(tmp_path / "nope.nes"),
        "-o",
        str(tmp_path / "out"),
        "--no-hints",
    )
    assert "hint:" not in res.stderr
    payload = _parse_trailing_json(res.stderr)
    assert payload["class"] == "missing_input"


def test_audio_bad_format_exits_64(tmp_path):
    rom = tmp_path / "rom.nes"
    rom.write_bytes(_make_minimal_ines_rom_with_signature())
    res = _run_qlnes("audio", str(rom), "-o", str(tmp_path / "out"), "--format", "ogg")
    assert res.returncode == 64
    payload = _parse_trailing_json(res.stderr)
    assert payload["class"] == "bad_format_arg"
    assert payload["format"] == "ogg"


def test_audio_unsupported_mapper_exits_100(tmp_path):
    """ROM without FT signature → SoundEngineRegistry has no match → exit 100."""
    rom = tmp_path / "rom.nes"
    # Valid iNES header, no FT signature in PRG → no engine matches.
    header = b"NES\x1a" + bytes([1, 0, 0, 0]) + bytes(8)
    rom.write_bytes(header + bytes(0x4000))
    # Skip pre-flight fceux check by passing PATH that has fceux if available.
    # If fceux isn't installed, we land in internal_error (70) before mapper
    # detection — which means this test depends on the environment.
    if not _has_fceux():
        pytest.skip("fceux not installed; mapper check happens after fceux check")
    res = _run_qlnes("audio", str(rom), "-o", str(tmp_path / "out"))
    assert res.returncode == 100
    payload = _parse_trailing_json(res.stderr)
    assert payload["class"] == "unsupported_mapper"
    assert payload["mapper"] == 0
    assert payload["artifact"] == "audio"


def test_audio_no_fceux_exits_70(tmp_path):
    """If fceux is absent, pre-flight emits internal_error (70).

    F.5 made the fceux preflight conditional on `--engine-mode oracle`;
    we pass it explicitly so this v0.5-compat test still exercises the
    preflight path.
    """
    rom = tmp_path / "rom.nes"
    rom.write_bytes(_make_minimal_ines_rom_with_signature())
    # Hide fceux by setting PATH to a directory we know lacks it.
    res = _run_qlnes(
        "audio",
        str(rom),
        "-o",
        str(tmp_path / "out"),
        "--engine-mode", "oracle",
        env_extra={"PATH": str(tmp_path)},
    )
    assert res.returncode == 70
    payload = _parse_trailing_json(res.stderr)
    assert payload["class"] == "internal_error"
    assert payload["dep"] == "fceux"


def test_audio_no_hints_strips_hint_under_internal_error(tmp_path):
    rom = tmp_path / "rom.nes"
    rom.write_bytes(_make_minimal_ines_rom_with_signature())
    res = _run_qlnes(
        "audio",
        str(rom),
        "-o",
        str(tmp_path / "out"),
        "--engine-mode", "oracle",  # F.5: trigger fceux preflight
        "--no-hints",
        env_extra={"PATH": str(tmp_path)},
    )
    assert res.returncode == 70
    assert "hint:" not in res.stderr


# ---- output-writability pre-flight ---------------------------------------


def test_audio_output_path_is_existing_file_exits_73(tmp_path):
    rom = tmp_path / "rom.nes"
    rom.write_bytes(_make_minimal_ines_rom_with_signature())
    out = tmp_path / "out.wav"
    out.write_bytes(b"already a file")
    res = _run_qlnes("audio", str(rom), "-o", str(out))
    assert res.returncode == 73
    payload = _parse_trailing_json(res.stderr)
    assert payload["class"] == "cant_create"
    assert payload["cause"] == "not_a_directory"


def test_audio_output_parent_missing_exits_73(tmp_path):
    rom = tmp_path / "rom.nes"
    rom.write_bytes(_make_minimal_ines_rom_with_signature())
    nowhere = tmp_path / "no" / "such" / "dir"
    res = _run_qlnes("audio", str(rom), "-o", str(nowhere))
    assert res.returncode == 73
    payload = _parse_trailing_json(res.stderr)
    assert payload["class"] == "cant_create"
    assert payload["cause"] == "parent_missing"


# ---- structured stderr contract (Lin's J3 pattern) -----------------------


def test_audio_stderr_json_is_last_line(tmp_path):
    """The trailing line of stderr must be parseable JSON. Lin's pipeline
    does `result.stderr.splitlines()[-1] | json.loads`."""
    res = _run_qlnes("audio", str(tmp_path / "nope.nes"), "-o", str(tmp_path / "out"))
    assert res.returncode == 66
    last_line = res.stderr.strip().splitlines()[-1]
    payload = json.loads(last_line)
    assert "code" in payload
    assert "class" in payload
    assert "qlnes_version" in payload


def test_audio_stderr_payload_is_canonical_json(tmp_path):
    """No spaces between separators; sorted keys (NFR-REL-1, UX §6.3)."""
    res = _run_qlnes("audio", str(tmp_path / "nope.nes"), "-o", str(tmp_path / "out"))
    last_line = res.stderr.strip().splitlines()[-1]
    assert ", " not in last_line
    assert ": " not in last_line
    keys = list(json.loads(last_line).keys())
    assert keys == sorted(keys)


def test_audio_color_never_strips_ansi(tmp_path):
    res = _run_qlnes(
        "audio",
        str(tmp_path / "nope.nes"),
        "-o",
        str(tmp_path / "out"),
        "--color",
        "never",
    )
    assert "\033[" not in res.stderr


# ---- helpers -------------------------------------------------------------


def _has_fceux() -> bool:
    import shutil

    return shutil.which("fceux") is not None
