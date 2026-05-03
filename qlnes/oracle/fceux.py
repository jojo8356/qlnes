"""FCEUX subprocess oracle — captures APU traces and reference PCM.

This is the only project component that talks to FCEUX. Every other module
consumes its outputs (`ApuTrace`, optionally a reference WAV path).

Spec compliance: parses the `qlnes-trace v1` format produced by
`qlnes/audio_trace.lua`. A schema bump in the Lua script must bump
`TRACE_SCHEMA_VERSION` here and grow the parser's switch.

Determinism: every FCEUX invocation passes `--no-config 1` to escape user
locale and per-host preferences. The captured trace is host-independent for
identical (rom, fceux_version, frame_count) tuples.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from ..io.errors import QlnesError

LUA_SCRIPT_PATH: Path = Path(__file__).resolve().parent.parent / "audio_trace.lua"

TRACE_SCHEMA_VERSION = "1"
TRACE_HEADER = f"# qlnes-trace v{TRACE_SCHEMA_VERSION}"

# Locked invocation arguments. See architecture step 10 for rationale.
FCEUX_DEFAULT_ARGS: tuple[str, ...] = (
    "--no-config",
    "1",  # ignore ~/.fceux preferences
    "--frameskip",
    "0",  # capture every frame's APU writes
)


@dataclass(frozen=True)
class TraceEvent:
    """One APU register write. addr ∈ [0x4000, 0x4017]."""

    frame: int
    cycle: int
    addr: int
    value: int


@dataclass
class ApuTrace:
    events: list[TraceEvent] = field(default_factory=list)
    end_cycle: int = 0
    reference_wav_path: Path | None = None

    @property
    def n_events(self) -> int:
        return len(self.events)


def parse_trace_file(path: Path) -> ApuTrace:
    """Parse a qlnes-trace v1 TSV file. Public so unit tests can call it on fixtures."""
    text = Path(path).read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines:
        raise QlnesError(
            "internal_error",
            f"trace file {path} is empty",
            extra={"path": str(path)},
        )
    header = lines[0]
    if header != TRACE_HEADER:
        raise QlnesError(
            "internal_error",
            f"unexpected trace schema header: {header!r}",
            extra={"path": str(path), "expected": TRACE_HEADER, "got": header},
        )
    events: list[TraceEvent] = []
    end_cycle = 0
    for raw in lines[1:]:
        if not raw or raw.startswith("#"):
            continue
        parts = raw.split("\t")
        if len(parts) != 4:
            raise QlnesError(
                "internal_error",
                f"malformed trace row in {path}: {raw!r}",
                extra={"path": str(path), "row": raw},
            )
        frame_s, cycle_s, addr_hex, value_hex = parts
        ev = TraceEvent(
            frame=int(frame_s),
            cycle=int(cycle_s),
            addr=int(addr_hex, 16),
            value=int(value_hex, 16),
        )
        events.append(ev)
        if ev.cycle > end_cycle:
            end_cycle = ev.cycle
    return ApuTrace(events=events, end_cycle=end_cycle)


class FceuxOracle:
    """Wraps the fceux subprocess + Lua trace round-trip."""

    def __init__(self, fceux_path: str | None = None, *, timeout_seconds: float = 60.0) -> None:
        resolved = fceux_path or shutil.which("fceux")
        if resolved is None:
            raise QlnesError(
                "internal_error",
                "fceux binary not found on PATH",
                hint="Install fceux >= 2.6.6, or pass fceux_path explicitly.",
                extra={"detail": "missing_dependency", "dep": "fceux"},
            )
        self.fceux_path: str = resolved
        self.timeout_seconds = timeout_seconds

    def trace(
        self,
        rom: Path,
        *,
        frames: int = 600,
        capture_reference_wav: bool = False,
    ) -> ApuTrace:
        """Run fceux against `rom` and capture the APU register-write trace.

        If `capture_reference_wav` is True, fceux's own audio output is recorded
        alongside; the WAV path is returned in `ApuTrace.reference_wav_path`.
        """
        rom = Path(rom)
        if not rom.exists():
            raise QlnesError(
                "missing_input",
                f"ROM not found: {rom}",
                extra={"path": str(rom)},
            )

        with tempfile.TemporaryDirectory(prefix="qlnes-trace-") as td:
            tdp = Path(td)
            trace_out = tdp / "trace.tsv"
            ref_wav: Path | None = None
            env = self._build_env(trace_out, frames, capture_reference_wav, tdp)
            if capture_reference_wav:
                ref_wav = tdp / "reference.wav"

            res = self._run_fceux(rom, env)

            # fceux 2.6.5 SIGSEGVs on `emu.exit()` even after writing a complete
            # trace — we treat exit-code as advisory: fail only if the trace
            # file is missing or malformed. Architecture step 10 pinned 2.6.6+
            # but lower versions are tolerated here.
            trace_present = trace_out.exists() and trace_out.stat().st_size > 0
            if not trace_present:
                raise QlnesError(
                    "internal_error",
                    f"fceux exited {res.returncode} and produced no trace",
                    extra={
                        "fceux_exit": res.returncode,
                        "expected": str(trace_out),
                        "stderr": res.stderr.decode("utf-8", "replace")[:500],
                    },
                )

            apu_trace = parse_trace_file(trace_out)

            # Reference WAV must outlive the temp dir — copy to a stable
            # location chosen by the caller (out-of-tree). For now we copy to a
            # second temp file the caller is responsible for cleaning up.
            if capture_reference_wav and ref_wav is not None and ref_wav.exists():
                stable = Path(tempfile.mkstemp(suffix=".wav", prefix="qlnes-ref-")[1])
                stable.write_bytes(ref_wav.read_bytes())
                apu_trace.reference_wav_path = stable

            return apu_trace

    def reference_pcm(self, rom: Path, *, frames: int = 600) -> bytes:
        """Capture FCEUX's reference PCM rendering as raw int16 LE bytes.

        Reads back the WAV captured during `trace()` and strips the RIFF
        header to leave just the PCM payload.
        """
        result = self.trace(rom, frames=frames, capture_reference_wav=True)
        if result.reference_wav_path is None:
            raise QlnesError(
                "internal_error",
                "fceux did not produce a reference WAV",
                extra={"detail": "sound.recordstart_failed"},
            )
        try:
            return _wav_pcm_payload(result.reference_wav_path)
        finally:
            with contextlib.suppress(OSError):
                result.reference_wav_path.unlink(missing_ok=True)

    def _build_env(
        self,
        trace_out: Path,
        frames: int,
        capture_reference_wav: bool,
        tdp: Path,
    ) -> dict[str, str]:
        env = dict(os.environ)
        env["QLNES_TRACE_OUT"] = str(trace_out)
        env["QLNES_FRAMES"] = str(frames)
        if capture_reference_wav:
            env["QLNES_REFERENCE_WAV"] = str(tdp / "reference.wav")
        # Defensive: drop the ambient QLNES_* keys that aren't ours.
        for k in list(env):
            if k.startswith("QLNES_") and k not in (
                "QLNES_TRACE_OUT",
                "QLNES_FRAMES",
                "QLNES_REFERENCE_WAV",
            ):
                del env[k]
        return env

    def _run_fceux(self, rom: Path, env: dict[str, str]) -> subprocess.CompletedProcess[bytes]:
        """Run fceux. Returns the CompletedProcess; caller decides how to
        handle non-zero exit (fceux 2.6.5 SIGSEGVs after `emu.exit()` even
        on successful traces — we only fail later if no trace was written).
        """
        cmd = [
            self.fceux_path,
            *FCEUX_DEFAULT_ARGS,
            "--loadlua",
            str(LUA_SCRIPT_PATH),
            str(rom),
        ]
        try:
            return subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as e:
            raise QlnesError(
                "internal_error",
                f"fceux timed out after {self.timeout_seconds}s",
                extra={"detail": "timeout", "timeout_seconds": self.timeout_seconds},
            ) from e


def _wav_pcm_payload(path: Path) -> bytes:
    """Strip the RIFF/WAVE header and return raw PCM bytes.

    We don't validate full RIFF compliance — fceux writes a standard
    PCM int16 LE file, and we trust that. If it doesn't look like PCM
    we fail loudly instead of silently returning garbage.
    """
    import wave

    with wave.open(str(path), "rb") as wf:
        if wf.getsampwidth() != 2:
            raise QlnesError(
                "internal_error",
                f"reference WAV at {path} has sampwidth={wf.getsampwidth()}, expected 2",
                extra={"path": str(path), "sampwidth": wf.getsampwidth()},
            )
        n_frames = wf.getnframes()
        return wf.readframes(n_frames)
