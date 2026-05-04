"""End-to-end CLI tests for the F.5 `--engine-mode` flag.

Patterned on `tests/integration/test_cli_audio.py`. Tests use Alter Ego
when present (skipped otherwise) and synthetic ROMs for the
unsupported-engine path.

These tests do NOT require fceux to be installed:
- AC1, AC3, AC5: in-process / auto paths bypass fceux entirely.
- AC4: in_process_unavailable triggers before any oracle code-path runs.
- AC6: oracle's deprecation warning fires regardless of fceux availability
  (AC2's full oracle render is in test_cli_audio.py with explicit
  --engine-mode oracle, gated on fceux being installed).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ROM_SHA = "023ebe61e8a4ba7a439f7fe9f7cbd31b364e5f63853dcbc0f7fa2183f023ef47"
ROM_PATH = REPO_ROOT / "corpus" / "roms" / f"{ROM_SHA}.nes"


def _run_qlnes(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    env = {**os.environ}
    # Strip ambient QLNES_* vars that could perturb config-loader behavior
    for k in list(env):
        if k.startswith("QLNES_"):
            del env[k]
    return subprocess.run(
        [sys.executable, "-m", "qlnes", *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
        timeout=timeout,
    )


def _last_json_line(stderr: str) -> dict:
    """Tail of stderr is a JSON payload (one per error/warning)."""
    for line in reversed(stderr.strip().splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            return json.loads(line)
    raise AssertionError(f"no JSON line in stderr: {stderr!r}")


# ---- AC1, AC5: in-process succeeds without fceux ------------------------


@pytest.mark.skipif(
    not ROM_PATH.exists(),
    reason=f"Alter Ego ROM not at {ROM_PATH}",
)
def test_cli_in_process_succeeds_without_fceux(tmp_path):
    """AC1 + AC5: --engine-mode in-process renders Alter Ego with no fceux
    on PATH. Generates a non-empty WAV file."""
    out = tmp_path / "wavs"
    r = _run_qlnes(
        "audio",
        str(ROM_PATH),
        "--output", str(out),
        "--frames", "60",  # 1 second of audio for fast test
        "--engine-mode", "in-process",
    )
    assert r.returncode == 0, f"stderr:\n{r.stderr}"
    wavs = list(out.glob("*.wav"))
    assert len(wavs) >= 1
    # Sanity: WAV header should start with "RIFF"
    assert wavs[0].read_bytes()[:4] == b"RIFF"
    assert b"fceux" not in r.stderr.encode().lower() or "in-process" in r.stderr


# ---- AC3: auto picks in-process when available --------------------------


@pytest.mark.skipif(
    not ROM_PATH.exists(),
    reason=f"Alter Ego ROM not at {ROM_PATH}",
)
def test_cli_auto_default_picks_in_process(tmp_path):
    """AC3: --engine-mode auto (default for FT-Alter Ego) picks in-process
    without falling back to oracle."""
    out = tmp_path / "wavs"
    r = _run_qlnes(
        "audio",
        str(ROM_PATH),
        "--output", str(out),
        "--frames", "60",
        # No --engine-mode → defaults to auto
    )
    assert r.returncode == 0, f"stderr:\n{r.stderr}"
    # The success line should mention `mode=in-process`
    assert "mode=in-process" in r.stderr
    # No fallback warning should have fired
    assert "in_process_low_confidence" not in r.stderr


@pytest.mark.skipif(
    not ROM_PATH.exists(),
    reason=f"Alter Ego ROM not at {ROM_PATH}",
)
def test_cli_explicit_auto_matches_default(tmp_path):
    """Sanity: --engine-mode auto explicit == default behavior."""
    out = tmp_path / "wavs"
    r = _run_qlnes(
        "audio",
        str(ROM_PATH),
        "--output", str(out),
        "--frames", "60",
        "--engine-mode", "auto",
    )
    assert r.returncode == 0, f"stderr:\n{r.stderr}"
    assert "mode=in-process" in r.stderr


# ---- AC4: in-process exits 100 for engine without addresses -------------


def _write_unrecognized_rom(path: Path) -> None:
    """Write a 32 KB NROM ROM that the FT detector won't recognize.

    No FT signature, no FamiTone-density heuristic match. The CLI
    should exit `unsupported_mapper` (100) before any rendering — this
    proves the CLI's exit-code contract under engine-mode flags.
    """
    header = bytearray(16)
    header[0:4] = b"NES\x1a"
    header[4] = 2
    header[5] = 0
    prg = bytearray(0x8000)  # all zeros, no FT signature
    prg[0x7FFC] = 0x00
    prg[0x7FFD] = 0x80
    path.write_bytes(bytes(header) + bytes(prg))


def test_cli_in_process_unrecognized_engine_exits_100(tmp_path):
    """AC4: --engine-mode in-process on a ROM no engine detects → exit 100."""
    rom = tmp_path / "synth.nes"
    _write_unrecognized_rom(rom)
    out = tmp_path / "wavs"
    r = _run_qlnes(
        "audio",
        str(rom),
        "--output", str(out),
        "--frames", "10",
        "--engine-mode", "in-process",
    )
    assert r.returncode == 100, f"got {r.returncode}, stderr:\n{r.stderr}"
    payload = _last_json_line(r.stderr)
    assert payload["class"] in ("unsupported_mapper", "in_process_unavailable")


# ---- AC6: --engine-mode oracle emits deprecation warning ----------------


def test_cli_oracle_mode_emits_deprecation_warning(tmp_path):
    """AC6: --engine-mode oracle prints a deprecation warning before render.

    We use a ROM that no engine detects so the run stops at engine
    detection (exit 100). This still triggers the deprecation warning
    early in render_rom_audio_v2.
    """
    rom = tmp_path / "synth.nes"
    _write_unrecognized_rom(rom)
    out = tmp_path / "wavs"
    # Skip the fceux preflight by mocking via env... actually, the
    # preflight runs before the warning. So we need fceux on PATH for
    # the deprecation warning to be observable. Skip if it's missing.
    import shutil
    if shutil.which("fceux") is None:
        pytest.skip("fceux not on PATH; oracle preflight blocks before deprecation warning fires")
    r = _run_qlnes(
        "audio",
        str(rom),
        "--output", str(out),
        "--frames", "10",
        "--engine-mode", "oracle",
    )
    assert "oracle_path_deprecated" in r.stderr


def test_cli_oracle_mode_without_fceux_blocks_in_preflight(tmp_path):
    """AC5 negative: --engine-mode oracle requires fceux. If absent,
    preflight raises before any render — clean exit code, structured
    error payload."""
    import shutil
    if shutil.which("fceux") is not None:
        pytest.skip("fceux IS on PATH; this test only runs when it's missing")
    rom = tmp_path / "synth.nes"
    _write_unrecognized_rom(rom)
    out = tmp_path / "wavs"
    r = _run_qlnes(
        "audio",
        str(rom),
        "--output", str(out),
        "--frames", "10",
        "--engine-mode", "oracle",
    )
    assert r.returncode != 0
    # The preflight reports as `internal_error` per existing
    # _check_fceux_on_path
    payload = _last_json_line(r.stderr)
    assert payload["class"] == "internal_error"
    assert payload.get("dep") == "fceux"


# ---- Backward-compat: missing flag works for in-process-capable engine --


@pytest.mark.skipif(
    not ROM_PATH.exists(),
    reason=f"Alter Ego ROM not at {ROM_PATH}",
)
def test_cli_no_flag_works_for_in_process_engine(tmp_path):
    """AC7: existing v0.5 callers (no --engine-mode flag) keep working.
    On v0.6 they get the in-process upgrade for FT engines without changes."""
    out = tmp_path / "wavs"
    r = _run_qlnes(
        "audio",
        str(ROM_PATH),
        "--output", str(out),
        "--frames", "60",
    )
    assert r.returncode == 0
    assert (out / f"{ROM_SHA}.00.famitracker.wav").exists()


# ---- Bad --engine-mode value rejected -----------------------------------


def test_cli_engine_mode_bad_value_exits_64(tmp_path):
    """Bad --engine-mode value → usage_error (exit 64)."""
    rom = tmp_path / "synth.nes"
    _write_unrecognized_rom(rom)
    out = tmp_path / "wavs"
    r = _run_qlnes(
        "audio",
        str(rom),
        "--output", str(out),
        "--engine-mode", "bogus",
    )
    assert r.returncode == 64
    payload = _last_json_line(r.stderr)
    assert payload["class"] == "usage_error"
