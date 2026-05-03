---
story_id: A.1
epic: A
title: Render one mapper-0 FamiTracker ROM to sample-equivalent WAV
sprint: 1
estimate: L
status: READY
created_by: bmad-create-story (CS)
date_created: 2026-05-03
project_name: qlnes
mvp_target: v0.5.0
inputDocuments:
  - _bmad-output/planning-artifacts/prd.md
  - _bmad-output/planning-artifacts/ux-design.md
  - _bmad-output/planning-artifacts/architecture.md
  - _bmad-output/planning-artifacts/epics-and-stories.md
  - _bmad-output/implementation-artifacts/sprint-status.md
fr_closed: [FR6, FR9, FR11/tier-1, FR8/wav, FR10/ref]
fr_partial: [FR8, FR10]
nfr_touched: [PERF-2, REL-1, REL-2, REL-4]
risks: [R1, R10]
preconditions: []
next_story: E.1
next_action: bmad-dev-story (DS) on A.1 → branch `feature/A.1-mapper0-ft-wav`
---

# Story A.1 — Render one mapper-0 FamiTracker ROM to sample-equivalent WAV

**Epic:** A — *Get music out of a ROM*
**Sprint:** 1 (entry node — first story of the MVP)
**Estimate:** L (1 dev-week ≈ 5 dev-days)
**Status:** READY (DoR satisfied: no dependencies; H-1 fix already applied at SP time; M-1/M-2/M-3/M-4 fixes scheduled in later sprints, none blocking A.1)

---

## 1. User value

> **Marco.** Marco picks one mapper-0 ROM whose audio engine is FamiTracker, runs `python -m qlnes audio rom.nes --format wav --output tracks/`, and gets one or more `.wav` files whose PCM is bit-identical to FCEUX's reference render.

This is the foundational story of the MVP. It lands the cross-cutting scaffold (atomic writes, structured errors, pre-flight, layered config, determinism utils) **inside** the first user-visible audio-rendering story — so the infrastructure is exercised end-to-end rather than authored in isolation.

---

## 2. FRs closed (and partials)

| FR | PRD wording (one line) | Closed by A.1 |
|---|---|---|
| FR6 | Per-track WAV with loop boundaries preserved | Partial — WAV produced; loop `'smpl'` chunk lands in A.3 |
| FR8 | `--format {wav,mp3,nsf}` flag, one per invocation | Partial — `--format wav` only; `mp3` in A.2, `nsf` in C.1 |
| FR9 | Deterministic per-track output filenames | **Closed** |
| FR10 | Exhaustive song-table walk including unreferenced songs | Partial — referenced songs only in A.1; unreferenced in A.4 (Capcom-shaped tables) and A.5 (generic tier-2) |
| FR11 | Tier-1 sample-equivalence for recognized engines + tier-2 frame-accurate for others | Partial — tier-1 FT only; Capcom in A.4; generic fallback in A.5 |
| FR33 | Sysexits-aligned exit codes | **Closed** (taxonomy + emitter land here) |
| FR34 | Structured JSON `stderr` payload | **Closed** |
| FR35 | Atomic writes | **Closed** |
| FR36 | Pre-flight validation | Partial — minimal predicates (rom-readable, output-writable, fceux-on-path); refuse-overwrite predicate in D.1; full set across all commands by D.2 |
| FR27 | Layered config (defaults / TOML / env / CLI) | Partial — minimal loader covering `[default]` + `[audio]` only; full schema in D.4 |

---

## 3. NFRs touched

| NFR | Mechanism this story implements | Verification test |
|---|---|---|
| NFR-PERF-2 | Pure-Python integer-arithmetic APU emulator + integer FIR resampler | `tests/integration/test_audio_perf.py::test_render_under_2x_realtime` |
| NFR-REL-1 | Integer math in APU; `det.canonical_json`; `det.deterministic_track_filename`; sorted iteration | `tests/invariants/test_pcm_equivalence.py::test_apu_vs_fceux_per_channel`, `tests/invariants/test_determinism.py::test_render_twice_identical` |
| NFR-REL-2 | No `datetime.now()` / `os.uname()` / `getlogin()` in any artifact-writer | `tests/invariants/test_determinism.py::test_no_wallclock_in_artifact` |
| NFR-REL-4 | `qlnes/io/atomic.py` used by every writer; `os.fsync` before rename | `tests/invariants/test_atomic_kill.py` |

---

## 4. Acceptance Criteria

Each AC has a test target that DS must make green before handing off to CR.

### AC1 — Deterministic filenames

**Given** a mapper-0 FT fixture ROM with N referenced songs, **when** the user runs `python -m qlnes audio <fixture>.nes --format wav --output <tmp>/`, **then** N files appear in `<tmp>/` named `<rom-stem>.<song-index-2-digit>.famitracker.wav`. Filenames are byte-identical across runs.

**Test target.** `tests/integration/test_audio_pipeline.py::test_filenames_deterministic`.

### AC2 — Sample-equivalence to FCEUX

For every produced WAV, the embedded PCM stream is byte-identical (SHA-256 match) to the FCEUX reference for the same ROM × song-index pair, captured via `qlnes/audio_trace.lua` against fceux ≥ 2.6.6.

**Test target.** `tests/invariants/test_pcm_equivalence.py::test_apu_vs_fceux_per_channel[<fixture-fname>]`.

### AC3 — Performance budget

Rendering a 3-minute FT song completes in under 6 minutes on the canonical hardware (NFR-PERF-2 budget = ≤ 2× real time).

**Test target.** `tests/integration/test_audio_perf.py::test_render_under_2x_realtime`.

### AC4 — Atomic writes survive SIGKILL

Killing the process with SIGKILL mid-render leaves `<tmp>/` empty (no `.wav` artifacts written, no `.tmp` orphans).

**Test target.** `tests/invariants/test_atomic_kill.py::test_kill_mid_render_leaves_no_partial`.

### AC5 — Missing input or bad ROM exits with structured JSON

Running `qlnes audio` against a non-readable file exits 66 (`missing_input`) or 65 (`bad_rom`); stderr is prefixed with `qlnes: error: <reason>`, then a `hint:` line, then a single-line JSON payload starting with `{"code":...,"class":"..."}`.

**Test target.** `tests/integration/test_cli_audio.py::test_missing_input_exits_66_with_json`, `test_bad_rom_exits_65_with_json`.

### AC6 — Refuse-to-overwrite by default

Running `qlnes audio --output <existing-file>.wav` without `--force` exits 73 (`cant_create`); stderr JSON includes `"cause":"exists"`. Adding `--force` overwrites cleanly.

**Test target.** `tests/integration/test_cli_audio.py::test_refuse_overwrite_exits_73`, `test_force_overwrites`.

### AC7 — Two consecutive runs produce byte-identical output

Two consecutive runs with the same flags produce byte-identical output files.

**Test target.** `tests/invariants/test_determinism.py::test_render_twice_identical`.

### AC8 — No host info in artifacts

Output files contain no wall-clock timestamp, hostname, username, locale, or path. Verified by grepping the artifact bytes for `LANG`, `USER`, today's date in common formats.

**Test target.** `tests/invariants/test_determinism.py::test_no_wallclock_in_artifact`.

---

## 5. Pre-conditions (verified at story creation)

- ✓ No story dependencies (A.1 is the entry node).
- ✓ Brownfield baseline is green: existing `tests/test_*.py` pass; existing `qlnes/cli.py` audio command works against the fixture ROM via the legacy `audio.py` ffmpeg path.
- ✓ Fixture ROM identified: a legally-redistributable mapper-0 NROM-128 FamiTracker homebrew or public-domain track. **Action item for Johan: choose & commit the fixture before DS starts.** Recommended candidates: `nesdev.org`'s `2A03_FamiTracker_test_*.nes` (public domain) — see §11.
- ✓ FCEUX ≥ 2.6.6 available on PATH.
- ✓ H-1 from readiness pass-2 already resolved in `epics-and-stories.md` §A.2 AC2 (does not affect A.1 directly but unblocks A.2 in sprint 2).

---

## 6. Files created or modified (file-level inventory)

### 6.1 New files (created by A.1)

```
qlnes/
├── det.py                            new
├── io/
│   ├── __init__.py                   new (empty re-export)
│   ├── atomic.py                     new
│   ├── errors.py                     new
│   └── preflight.py                  new
├── config/
│   ├── __init__.py                   new (empty re-export)
│   └── loader.py                     new
├── apu/
│   ├── __init__.py                   new (ApuEmulator + public exports)
│   ├── pulse.py                      new
│   ├── triangle.py                   new
│   ├── noise.py                      new
│   ├── dmc.py                        new (stub — bit 4 of $4015 reads 0)
│   ├── mixer.py                      new
│   └── tables.py                     new (length, period, FIR coefficients)
├── audio/
│   ├── __init__.py                   new
│   ├── engine.py                     new (SoundEngine ABC + registry)
│   ├── renderer.py                   new (engine → APU → PCM → WAV pipeline)
│   ├── wav.py                        new (RIFF writer; no 'smpl' chunk yet — that's A.3)
│   └── engines/
│       ├── __init__.py               new
│       └── famitracker.py            new (detect, walk_song_table, render_song, detect_loop=None for A.1)
├── oracle/
│   ├── __init__.py                   new
│   └── fceux.py                      new (subprocess + Lua trace + reference WAV capture)
└── audio_trace.lua                   modified (schema-versioned to v1: trace TSV + reference WAV)

tests/
├── conftest.py                       new (corpus fixture, oracle fixture, lameenc-version skip marker)
├── unit/
│   ├── __init__.py                   new
│   ├── test_apu_pulse.py             new
│   ├── test_apu_triangle.py          new
│   ├── test_apu_noise.py             new
│   ├── test_apu_mixer.py             new
│   ├── test_apu_resampler.py         new
│   ├── test_engine_famitracker.py    new
│   ├── test_atomic_writer.py         new
│   ├── test_errors_emitter.py        new
│   ├── test_det.py                   new
│   ├── test_config_loader.py         new
│   ├── test_preflight.py             new
│   └── test_wav_writer.py            new
├── integration/
│   ├── __init__.py                   new
│   ├── test_audio_pipeline.py        new
│   ├── test_audio_perf.py            new
│   └── test_cli_audio.py             new
├── invariants/
│   ├── __init__.py                   new
│   ├── test_pcm_equivalence.py       new (parametrized over corpus FT subset; A.1 ships with 1 ROM)
│   ├── test_atomic_kill.py           new
│   └── test_determinism.py           new
└── fixtures/
    └── <fixture-rom>.nes             new (committed; SHA-named)

requirements-dev.txt                  new (pytest, pytest-xdist, coverage, ruff, mypy, deptry — dev-only)
qlnes.toml.example                    new (canonical schema reference for FR27)
ruff.toml                             new (lint/format config — strict on new dirs)
mypy.ini                              new (strict on qlnes/io, qlnes/det, qlnes/config, qlnes/apu, qlnes/audio, qlnes/oracle; warning-only on legacy)
```

### 6.2 Modified files

- **`qlnes/cli.py`** — refactor `audio` command to route through `qlnes/audio/renderer.py`, `qlnes/io/errors.py::emit`, `qlnes/io/preflight.py::Preflight`, `qlnes/io/atomic.py::atomic_write_*`, `qlnes/config/loader.py::ConfigLoader.resolve`. The legacy `audio` body becomes a thin call into `renderer.render_rom_audio_v2(...)`. Other commands (`analyze`, `recompile`, `verify`, `nsf`) remain unchanged in A.1; they migrate to the same pattern in D.1, D.2 (refuse-overwrite, --strict polish) and during E.* (regression net).
- **`qlnes/audio.py`** — kept as a thin compatibility shim that delegates to `qlnes/audio/renderer.py`. Will be deleted in A.6 once `verify --audio` is the last caller migrated.
- **`qlnes/audio_trace.lua`** — schema-versioned (`# qlnes-trace v1` comment), refined to also capture a reference WAV via FCEUX's `sound.get` API.
- **`requirements.txt`** — unchanged in A.1. (lameenc lands in A.2; pytest is in `requirements-dev.txt`.)
- **`scripts/install_audio_deps.sh`** — light touch: confirm `fceux` install procedure documented; lameenc install added in A.2.
- **`.gitignore`** — add `corpus/roms/`, `corpus/references/` (forward-compat for B.3); add `.venv*`, `bin/`, `__pycache__/`, `.mypy_cache/`, `.ruff_cache/`, `.pytest_cache/` if not already present.

### 6.3 Deleted files

(None in A.1.)

---

## 7. Implementation order (recommended for DS)

The order below minimizes back-tracking. Each layer can be tested in isolation before the next layer is built.

### Phase 7.1 — Cross-cutting primitives (~0.5 dev-day)

1. **`qlnes/det.py`** — pure functions, no deps. Test first.
   - Tests: `tests/unit/test_det.py`.
2. **`qlnes/io/atomic.py`** — `atomic_writer`, `atomic_write_bytes`, `atomic_write_text`.
   - Tests: `tests/unit/test_atomic_writer.py`, `tests/invariants/test_atomic_kill.py`.
3. **`qlnes/io/errors.py`** — `QlnesError`, `EXIT_CODES`, `DEFAULT_HINTS`, `emit`.
   - Tests: `tests/unit/test_errors_emitter.py`.
4. **`qlnes/io/preflight.py`** — `Preflight.add()` / `run()`.
   - Tests: `tests/unit/test_preflight.py`.
5. **`qlnes/config/loader.py`** — minimal schema (`[default]` + `[audio]` only); 4-layer resolver.
   - Tests: `tests/unit/test_config_loader.py`.

### Phase 7.2 — APU emulator (~1.5 dev-days)

6. **`qlnes/apu/tables.py`** — length-counter LUT, period table, noise period table, FIR coefficients (24-tap). Pure data, no logic.
7. **`qlnes/apu/pulse.py`** — `PulseChannel` (envelope, sweep, length, duty). Pure-Python integer math.
   - Tests: `tests/unit/test_apu_pulse.py` — per-register-write fixtures from NESdev wiki canonical cases.
8. **`qlnes/apu/triangle.py`** — `TriangleChannel` (linear counter, length, period).
   - Tests: `tests/unit/test_apu_triangle.py`.
9. **`qlnes/apu/noise.py`** — `NoiseChannel` (mode, period table, length, envelope).
   - Tests: `tests/unit/test_apu_noise.py`.
10. **`qlnes/apu/dmc.py`** — **stub for A.1**: bit 4 of `$4015` reads 0; writes to `$4010`–`$4013` recorded but not played.
11. **`qlnes/apu/mixer.py`** — 2A03 nonlinear mixer + integer FIR resampler (894 886.5 Hz → 44 100 Hz).
    - Tests: `tests/unit/test_apu_mixer.py`, `tests/unit/test_apu_resampler.py`.
12. **`qlnes/apu/__init__.py`** — `ApuEmulator` orchestrator: register-write dispatch, frame counter (4-step), per-cycle tick, render to int16 LE PCM.

### Phase 7.3 — FCEUX oracle (~0.5 dev-day)

13. **`qlnes/audio_trace.lua`** — refine to v1 schema; capture trace TSV + reference WAV via `sound.get`.
14. **`qlnes/oracle/fceux.py`** — `FceuxOracle.trace(rom, frames) -> ApuTrace`, `FceuxOracle.reference_pcm(rom, frames) -> bytes`. Subprocess invocation with `DEFAULT_ARGS` from architecture step 10.
    - Tests: limited unit tests (mocked subprocess); real exercise happens in integration tests.

### Phase 7.4 — Audio pipeline (~1 dev-day)

15. **`qlnes/audio/engine.py`** — `SoundEngine` ABC + `SoundEngineRegistry` + dataclasses (`DetectionResult`, `SongEntry`, `LoopBoundary`, `PcmStream`).
16. **`qlnes/audio/wav.py`** — `write_wav(path, pcm: bytes, sample_rate: int)` — RIFF header, no `'smpl'` chunk yet. Routes through `atomic_write_bytes`.
    - Tests: `tests/unit/test_wav_writer.py`.
17. **`qlnes/audio/engines/famitracker.py`** — `FamiTrackerEngine`. `detect()` matches mapper-0 + FT-engine signatures. `walk_song_table()` walks the FT pointer table. `render_song()` re-plays the FCEUX trace through `ApuEmulator`. `detect_loop()` returns `None` for A.1 (loop opcode handling lands in A.3).
    - Tests: `tests/unit/test_engine_famitracker.py` (detection on fixture; song-table walk on fixture).
18. **`qlnes/audio/renderer.py`** — `render_rom_audio_v2(rom, *, format, output_dir, frames, force, ...)`. Orchestrates: ConfigLoader → Preflight → Rom → SoundEngineRegistry.detect → engine.walk_song_table → for each song: oracle.trace → engine.render_song → wav.write_wav → atomic_write_bytes.

### Phase 7.5 — CLI integration (~0.5 dev-day)

19. **`qlnes/cli.py`** — refactor `audio` command:
    - Build `ConfigLoader.resolve("audio", cli_kwargs)`.
    - Build `Preflight` predicates (`_check_rom_readable`, `_check_output_writable`, `_check_fceux_on_path`, `_check_mapper_supported_for_audio`).
    - Call `renderer.render_rom_audio_v2(...)`.
    - Wrap entire body in `try / except QlnesError as e: emit(e, ...) / except KeyboardInterrupt: emit(QlnesError("interrupted", "interrupted")) / except Exception as exc: ...` per architecture step 7.

### Phase 7.6 — Tests & fixtures (~1 dev-day)

20. **`tests/fixtures/<fixture-rom>.nes`** — commit the legally-redistributable fixture ROM.
21. **`tests/conftest.py`** — `oracle` fixture (session-scoped `FceuxOracle()`); `lameenc_version` marker (defined for A.2 use); `corpus_root` fixture pointing at `tests/fixtures/`.
22. **`tests/integration/test_audio_pipeline.py`** — `test_filenames_deterministic`, `test_pcm_matches_fceux_reference` (one ROM).
23. **`tests/integration/test_audio_perf.py`** — `test_render_under_2x_realtime`.
24. **`tests/integration/test_cli_audio.py`** — subprocess Python pattern (Lin's pattern); covers AC5, AC6.
25. **`tests/invariants/test_pcm_equivalence.py`** — parametrized harness; A.1 ships with 1 ROM in the parameter list.
26. **`tests/invariants/test_atomic_kill.py`** — fork+kill subprocess test.
27. **`tests/invariants/test_determinism.py`** — `test_render_twice_identical`, `test_no_wallclock_in_artifact`.

### Phase 7.7 — Polish (~0.5 dev-day)

28. **`requirements-dev.txt`** — pin pytest≥8, pytest-xdist≥3, coverage≥7, ruff≥0.5, mypy≥1.10, deptry≥0.16.
29. **`qlnes.toml.example`** — minimal schema reference.
30. **`ruff.toml`** — `select = ["E","F","W","B","UP","SIM","I","RUF"]`; `target-version = "py311"`; line-length 100.
31. **`mypy.ini`** — `[mypy]` baseline `python_version = 3.11`; per-module overrides: `[mypy-qlnes.io.*]`, `[mypy-qlnes.det]`, `[mypy-qlnes.config.*]`, `[mypy-qlnes.apu.*]`, `[mypy-qlnes.audio.*]`, `[mypy-qlnes.oracle.*]` set `strict = True`.
32. **`.gitignore`** — additions per §6.2.
33. **CI hookup** — extend `.github/workflows/test.yml` (or create if absent) to run `ruff check && ruff format --check && mypy qlnes && pytest tests/unit tests/integration` on push/PR. (Full CI workflow design is B.4's scope; A.1 ships the minimum that gates merges.)

---

## 8. File-level specifications

The interfaces below are the contract for DS. Implementation details may evolve; signatures and invariants must hold.

### 8.1 `qlnes/det.py`

```python
"""Determinism utilities. Every output writer routes through these."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

CANONICAL_JSON_KW = {"sort_keys": True, "ensure_ascii": False, "separators": (",", ":")}


def canonical_json(obj: Any) -> str:
    """The only JSON serializer used in any artifact."""
    return json.dumps(obj, **CANONICAL_JSON_KW)


def canonical_json_bytes(obj: Any) -> bytes:
    return canonical_json(obj).encode("utf-8")


def sha256_file(path: Path, *, chunk: int = 1 << 16) -> str:
    """Lower-case hex SHA-256 of a file's bytes."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for buf in iter(lambda: f.read(chunk), b""):
            h.update(buf)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stable_iter[T](items: Iterable[T], *, key=None) -> list[T]:
    return sorted(items, key=key) if key is not None else sorted(items)


def deterministic_track_filename(
    rom_stem: str,
    song_index: int,
    engine: str,
    ext: str,
) -> str:
    """UX §10.3 contract: <rom>.<idx:02>.<engine>.<ext>"""
    return f"{rom_stem}.{song_index:02d}.{engine}.{ext}"
```

**Tests (sample)** in `tests/unit/test_det.py`:

```python
def test_canonical_json_sorts_keys():
    assert canonical_json({"b": 1, "a": 2}) == '{"a":2,"b":1}'

def test_deterministic_track_filename_zero_pads():
    assert deterministic_track_filename("game", 4, "famitracker", "wav") == "game.04.famitracker.wav"

def test_sha256_bytes_lowercase_hex():
    h = sha256_bytes(b"abc")
    assert h == h.lower()
    assert len(h) == 64
```

---

### 8.2 `qlnes/io/atomic.py`

```python
"""Atomic file writes (FR35). Crash-safe across the whole product."""
from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator


@contextmanager
def atomic_writer(target: Path, mode: str = "wb") -> Iterator[BinaryIO]:
    """Open a temp file in target's parent dir; rename on clean exit."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    try:
        with os.fdopen(fd, mode) as f:
            yield f
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def atomic_write_bytes(target: Path, data: bytes) -> None:
    with atomic_writer(target, "wb") as f:
        f.write(data)


def atomic_write_text(target: Path, text: str, encoding: str = "utf-8") -> None:
    with atomic_writer(target, "wb") as f:
        f.write(text.encode(encoding))
```

**Invariants enforced (testable):**

- Temp file in same directory as target (cross-FS rename would silently fall back to copy+unlink, breaking atomicity).
- Temp file hidden (`.`-prefix).
- `os.fsync` before rename (survives kernel crash, not just process crash).
- On exception, temp file unlinked; target untouched.

**Tests (sample)** in `tests/unit/test_atomic_writer.py` and `tests/invariants/test_atomic_kill.py`:

```python
def test_atomic_write_bytes_roundtrip(tmp_path):
    p = tmp_path / "out.bin"
    atomic_write_bytes(p, b"hello")
    assert p.read_bytes() == b"hello"

def test_atomic_writer_unlinks_temp_on_exception(tmp_path):
    p = tmp_path / "out.bin"
    with pytest.raises(RuntimeError):
        with atomic_writer(p, "wb") as f:
            f.write(b"partial")
            raise RuntimeError("boom")
    assert not p.exists()
    assert not list(tmp_path.glob(".out.bin.*"))

# tests/invariants/test_atomic_kill.py
def test_kill_mid_render_leaves_no_partial(tmp_path):
    """Spawn a child that writes via atomic_writer, kill it mid-write, assert no partial."""
    # implementation: subprocess + signal.SIGKILL after 100ms; assert tmp_path is empty.
```

---

### 8.3 `qlnes/io/errors.py`

```python
"""Sysexits-aligned error emitter with structured JSON stderr (FR33, FR34)."""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import Any, NoReturn

from .. import __version__ as _VERSION

# UX §6.2 — locked taxonomy.
EXIT_CODES: dict[str, int] = {
    "usage_error":         64,
    "bad_format_arg":      64,
    "bad_rom":             65,
    "missing_input":       66,
    "internal_error":      70,
    "cant_create":         73,
    "io_error":            74,
    "unsupported_mapper":  100,
    "equivalence_failed":  101,
    "missing_reference":   102,
    "interrupted":         130,
}

DEFAULT_HINTS: dict[str, str | None] = {
    "usage_error":         "Run the command with --help to see valid usage.",
    "bad_format_arg":      "Run the command with --help to see valid values.",
    "bad_rom":             "Verify the file is a .nes ROM, not .nsf or .zip.",
    "missing_input":       None,
    "internal_error":      "Re-run with --debug and open an issue.",
    "cant_create":         "Add --force, or pick a different --output path.",
    "io_error":            "Check disk space and permissions.",
    "unsupported_mapper":  "Run `qlnes coverage` for the support matrix.",
    "equivalence_failed":  "Re-run with --debug to dump the divergence frame.",
    "missing_reference":   "Generate the reference: see corpus/README.md.",
    "interrupted":         None,
}


@dataclass
class QlnesError(Exception):
    cls: str
    reason: str
    hint: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def code(self) -> int:
        return EXIT_CODES[self.cls]


def _ansi_red(s: str, on: bool) -> str:
    return f"\033[31;1m{s}\033[0m" if on else s


def emit(err: QlnesError, *, no_hints: bool = False, color: bool = False) -> NoReturn:
    sys.stderr.write(_ansi_red("qlnes: error: ", color) + err.reason + "\n")
    hint = err.hint if err.hint is not None else DEFAULT_HINTS.get(err.cls)
    if hint and not no_hints:
        sys.stderr.write("hint: " + hint + "\n")
    payload = {
        "code": err.code,
        "class": err.cls,
        "qlnes_version": _VERSION,
        **err.extra,
    }
    sys.stderr.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    sys.exit(err.code)


def warn(cls: str, reason: str, *, hint: str | None = None,
         extra: dict[str, Any] | None = None,
         no_hints: bool = False, color: bool = False) -> None:
    """Three-line warning shape — mirror of emit() without exiting."""
    sys.stderr.write(("\033[33m" if color else "") + "qlnes: warning: " +
                     ("\033[0m" if color else "") + reason + "\n")
    if hint and not no_hints:
        sys.stderr.write("hint: " + hint + "\n")
    payload = {"class": cls, "qlnes_version": _VERSION, **(extra or {})}
    sys.stderr.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
```

**Tests (sample)** in `tests/unit/test_errors_emitter.py`:

```python
def test_emit_writes_three_lines(capsys):
    with pytest.raises(SystemExit) as exc:
        emit(QlnesError("bad_rom", "not an iNES ROM"))
    assert exc.value.code == 65
    err = capsys.readouterr().err.splitlines()
    assert err[0].startswith("qlnes: error: not an iNES ROM")
    assert err[1].startswith("hint: ")
    payload = json.loads(err[-1])
    assert payload["code"] == 65 and payload["class"] == "bad_rom"

def test_emit_suppresses_hint_under_no_hints(capsys):
    with pytest.raises(SystemExit):
        emit(QlnesError("bad_rom", "not iNES"), no_hints=True)
    err = capsys.readouterr().err.splitlines()
    assert not any(line.startswith("hint:") for line in err)
```

---

### 8.4 `qlnes/io/preflight.py`

```python
"""Pre-flight validation runner (FR36)."""
from __future__ import annotations

from typing import Callable
from .errors import QlnesError


class Preflight:
    def __init__(self) -> None:
        self._checks: list[tuple[str, Callable[[], None]]] = []

    def add(self, name: str, check: Callable[[], None]) -> None:
        self._checks.append((name, check))

    def run(self) -> None:
        for name, check in self._checks:
            try:
                check()
            except QlnesError:
                raise
            except Exception as e:
                raise QlnesError(
                    "internal_error",
                    f"preflight {name!r} crashed: {e}",
                    extra={"check": name},
                ) from e
```

**Tests** in `tests/unit/test_preflight.py`: verify `add()` order is preserved; verify `run()` raises the first `QlnesError`; verify wrapped `Exception` becomes `internal_error`.

---

### 8.5 `qlnes/config/loader.py`

```python
"""Layered config (FR27 minimal in A.1; full in D.4)."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


class Layer(Enum):
    DEFAULT = 1
    TOML = 2
    ENV = 3
    CLI = 4


@dataclass(frozen=True)
class ResolvedConfig:
    section: str
    values: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Layer] = field(default_factory=dict)

    def __getitem__(self, key: str) -> Any:
        return self.values[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)


# A.1 minimal schema. D.4 will extend with [verify], [audit], [coverage] sections.
BUILTIN_DEFAULTS: dict[str, dict[str, Any]] = {
    "default": {
        "output_dir": ".",
        "quiet": False,
        "color": "auto",
        "hints": True,
        "progress": True,
    },
    "audio": {
        "format": "wav",
        "frames": 600,
        "reference_emulator": "fceux",
    },
}

ENV_PREFIX = "QLNES_"


class ConfigLoader:
    def __init__(self, *, config_path: Path | None = None,
                 cwd: Path | None = None) -> None:
        self._config_path = config_path
        self._cwd = cwd or Path.cwd()

    def resolve(self, command: str,
                cli_overrides: Mapping[str, Any]) -> ResolvedConfig:
        merged: dict[str, Any] = {}
        prov: dict[str, Layer] = {}
        # Layer 1
        defaults = {**BUILTIN_DEFAULTS["default"],
                    **BUILTIN_DEFAULTS.get(command, {})}
        for k, v in defaults.items():
            merged[k] = v
            prov[k] = Layer.DEFAULT
        # Layer 2
        for k, v in self._read_toml(command).items():
            merged[k] = v
            prov[k] = Layer.TOML
        # Layer 3
        for k, v in self._read_env(command).items():
            merged[k] = v
            prov[k] = Layer.ENV
        # Layer 4
        for k, v in cli_overrides.items():
            if v is None:
                continue
            merged[k] = v
            prov[k] = Layer.CLI
        return ResolvedConfig(command, merged, prov)

    def _read_toml(self, command: str) -> dict[str, Any]:
        for p in self._toml_search_path():
            if p and p.exists():
                with p.open("rb") as f:
                    doc = tomllib.load(f)
                return {**doc.get("default", {}), **doc.get(command, {})}
        return {}

    def _toml_search_path(self) -> list[Path | None]:
        return [
            self._config_path,
            self._cwd / "qlnes.toml",
        ]

    def _read_env(self, command: str) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, v in os.environ.items():
            if not k.startswith(ENV_PREFIX):
                continue
            stripped = k[len(ENV_PREFIX):].lower()
            # QLNES_AUDIO_FORMAT → ("audio", "format")
            if stripped.startswith(command + "_"):
                key = stripped[len(command) + 1:]
                out[key] = self._coerce(v)
            elif "_" not in stripped:
                # QLNES_QUIET → "default" key
                out[stripped] = self._coerce(v)
        return out

    @staticmethod
    def _coerce(v: str) -> Any:
        # Basic type coercion: bool / int / passthrough str.
        low = v.lower()
        if low in ("true", "yes", "1"):
            return True
        if low in ("false", "no", "0"):
            return False
        if v.isdigit() or (v.startswith("-") and v[1:].isdigit()):
            return int(v)
        return v
```

**Tests** in `tests/unit/test_config_loader.py`: defaults present; TOML overrides defaults; env overrides TOML; CLI overrides env; bool/int coercion of env values; missing TOML file falls through silently; unknown TOML key behaviour deferred to D.4 (just preserved into `merged` for now without warning — A.1's loader is non-strict).

---

### 8.6 `qlnes/apu/__init__.py` (`ApuEmulator`)

```python
"""Cycle-accurate 2A03 APU emulator. Pulse1, Pulse2, Triangle, Noise. DMC stubbed in MVP."""
from __future__ import annotations

from typing import Iterable

from .pulse import PulseChannel
from .triangle import TriangleChannel
from .noise import NoiseChannel
from .dmc import DmcChannelStub
from .mixer import Mixer

NTSC_CPU_HZ = 1_789_773
SAMPLE_RATE = 44_100


class ApuEmulator:
    """Replays APU register writes and emits int16 LE PCM at SAMPLE_RATE."""

    def __init__(self, sample_rate: int = SAMPLE_RATE) -> None:
        self.sample_rate = sample_rate
        self.pulse1 = PulseChannel(channel=0)
        self.pulse2 = PulseChannel(channel=1)
        self.triangle = TriangleChannel()
        self.noise = NoiseChannel()
        self.dmc = DmcChannelStub()
        self.mixer = Mixer(sample_rate=sample_rate)
        self._cycle = 0

    def write(self, register: int, value: int, cycle: int) -> None:
        """Schedule an APU register write at the given CPU cycle."""
        self._advance_to(cycle)
        if 0x4000 <= register <= 0x4003:
            self.pulse1.register_write(register - 0x4000, value)
        elif 0x4004 <= register <= 0x4007:
            self.pulse2.register_write(register - 0x4004, value)
        elif 0x4008 <= register <= 0x400B:
            self.triangle.register_write(register - 0x4008, value)
        elif 0x400C <= register <= 0x400F:
            self.noise.register_write(register - 0x400C, value)
        elif 0x4010 <= register <= 0x4013:
            self.dmc.register_write(register - 0x4010, value)
        elif register == 0x4015:
            # Channel enable; bit 4 (DMC) is ignored in MVP per ADR-18.
            self.pulse1.set_enable(bool(value & 0x01))
            self.pulse2.set_enable(bool(value & 0x02))
            self.triangle.set_enable(bool(value & 0x04))
            self.noise.set_enable(bool(value & 0x08))
        elif register == 0x4017:
            # Frame counter mode select.
            self.mixer.set_frame_mode(value)

    def render_until(self, cycle: int) -> bytes:
        """Render PCM samples up to (not including) `cycle`. Return int16 LE bytes."""
        self._advance_to(cycle)
        return self.mixer.flush()

    def _advance_to(self, target_cycle: int) -> None:
        delta = target_cycle - self._cycle
        if delta <= 0:
            return
        for _ in range(delta):
            self.pulse1.tick()
            self.pulse2.tick()
            self.triangle.tick()
            self.noise.tick()
            sample = self.mixer.mix(
                self.pulse1.output(),
                self.pulse2.output(),
                self.triangle.output(),
                self.noise.output(),
            )
            self.mixer.feed_sample(sample)
        self._cycle = target_cycle

    def reset(self) -> None:
        self.__init__(sample_rate=self.sample_rate)
```

**Per-channel module shapes** (`pulse.py`, `triangle.py`, `noise.py`, `dmc.py`, `mixer.py`, `tables.py`) are not fully spec'd here — the dev agent should follow the NESdev wiki canonical reference (linked in CONTRIBUTING / README). Constraints:

- **Integer arithmetic everywhere.** No floats in any channel or in the mixer's accumulator.
- **No state outside the class.** Every channel is fully encapsulated.
- **`output() -> int`** returns the channel's current 4-bit unsigned amplitude (0–15 for pulse/triangle/noise; 0 for DMC stub).
- **`register_write(reg_index: int, value: int) -> None`** is the only mutator (besides `tick()` and `set_enable()`).

**Tests** are exhaustive at the channel level: each NESdev canonical case (envelope decay, sweep mute, length-counter halt, triangle linear-counter reload, noise period table) gets a unit test.

---

### 8.7 `qlnes/apu/mixer.py` (FIR resampler highlights)

The mixer integrates two responsibilities: 2A03 nonlinear mix and 894886.5 Hz → 44100 Hz integer-rational decimation.

**Integer-rational ratio.**

```
1789773 CPU Hz / 2 = 894886.5 APU Hz
                                    ↓
                              poly-phase FIR
                              decimate by 894886.5 / 44100 ≈ 20.292
                                    ↓
                              44100 PCM Hz
```

Use a 24-tap windowed-sinc FIR with integer coefficients (Q15 fixed-point). Coefficients are precomputed in `tables.py` as a tuple of int16 — never recomputed at runtime (determinism invariant).

**Why integer math.** Floats are non-associative across hosts; cross-host bit-equivalence becomes platform-dependent. NFR-REL-1 demands integer math.

---

### 8.8 `qlnes/audio/engine.py` (ABC + registry)

```python
"""SoundEngine plugin contract."""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import ClassVar, Literal, Optional


@dataclass(frozen=True)
class DetectionResult:
    confidence: float
    evidence: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SongEntry:
    index: int
    label: Optional[str]
    referenced: bool
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class LoopBoundary:
    start_frame: int
    end_frame: int


@dataclass
class PcmStream:
    samples: bytes               # int16 LE
    sample_rate: int = 44_100
    loop: Optional[LoopBoundary] = None


class SoundEngine(abc.ABC):
    name: ClassVar[str]
    tier: ClassVar[Literal[1, 2]]
    target_mappers: ClassVar[frozenset[int]]   # empty = "any"

    @abc.abstractmethod
    def detect(self, rom) -> DetectionResult: ...
    @abc.abstractmethod
    def walk_song_table(self, rom) -> list[SongEntry]: ...
    @abc.abstractmethod
    def render_song(self, rom, song: SongEntry, oracle) -> PcmStream: ...
    @abc.abstractmethod
    def detect_loop(self, song: SongEntry, pcm: PcmStream) -> LoopBoundary | None: ...


class SoundEngineRegistry:
    _engines: list[type[SoundEngine]] = []

    @classmethod
    def register(cls, engine: type[SoundEngine]) -> type[SoundEngine]:
        cls._engines.append(engine)
        return engine

    @classmethod
    def detect(cls, rom, *, threshold: float = 0.6) -> tuple[SoundEngine, DetectionResult]:
        candidates = []
        for E in cls._engines:
            if E.target_mappers and rom.mapper not in E.target_mappers:
                continue
            inst = E()
            r = inst.detect(rom)
            if r.confidence >= threshold:
                candidates.append((inst, r))
        if not candidates:
            # Generic fallback ships in A.5; for A.1, raise.
            from ..io.errors import QlnesError
            raise QlnesError(
                "unsupported_mapper",
                f"no recognized audio engine for mapper {rom.mapper}",
                extra={"mapper": rom.mapper, "artifact": "audio"},
            )
        return max(candidates, key=lambda ir: ir[1].confidence)
```

**Note on A.1 vs A.5.** A.1 raises on unrecognized engine (no generic fallback yet); A.5 will replace the `raise` with a `return GenericEngine(), DetectionResult(0.0, ["no specific engine"], {})`.

---

### 8.9 `qlnes/audio/engines/famitracker.py`

```python
"""FamiTracker engine handler (tier-1 sample-equivalent)."""
from __future__ import annotations

from typing import ClassVar

from ..engine import (
    DetectionResult, SongEntry, LoopBoundary, PcmStream,
    SoundEngine, SoundEngineRegistry,
)
from ...apu import ApuEmulator


@SoundEngineRegistry.register
class FamiTrackerEngine(SoundEngine):
    name: ClassVar[str] = "famitracker"
    tier: ClassVar = 1
    target_mappers: ClassVar[frozenset[int]] = frozenset({0, 1, 4, 66})

    def detect(self, rom) -> DetectionResult:
        # Heuristics:
        # 1. Mapper match (cheap pre-filter, already done by registry).
        # 2. ASCII signature scan ("FT" / "FamiTracker" / "0CC-FamiTracker" in PRG).
        # 3. Pointer-table layout signature near reset vector.
        evidence = []
        confidence = 0.0
        if b"FamiTracker" in rom.prg_bytes() or b"0CC-FamiTracker" in rom.prg_bytes():
            evidence.append("ascii_signature_present")
            confidence += 0.5
        if self._has_song_pointer_table(rom):
            evidence.append("pointer_table_layout_match")
            confidence += 0.4
        return DetectionResult(min(confidence, 1.0), evidence, {})

    def walk_song_table(self, rom) -> list[SongEntry]:
        # Locate FT's song-pointer table (`song_list_l` / `song_list_h`),
        # walk pairs of low/high bytes until a sentinel or out-of-bank,
        # return SongEntry objects.
        ...

    def render_song(self, rom, song: SongEntry, oracle) -> PcmStream:
        trace = oracle.trace(rom, frames=600)         # default duration in A.1
        trace = self._filter_trace_to_song(trace, song)
        emu = ApuEmulator()
        for entry in trace.events:
            emu.write(entry.register, entry.value, entry.cycle)
        pcm = emu.render_until(trace.end_cycle)
        return PcmStream(samples=pcm)

    def detect_loop(self, song: SongEntry, pcm: PcmStream) -> LoopBoundary | None:
        # A.1 returns None (no loop chunk). A.3 implements FT's `Bxx` opcode parsing.
        return None

    # --- private helpers ---
    def _has_song_pointer_table(self, rom) -> bool: ...
    def _filter_trace_to_song(self, trace, song): ...
```

**Tests** (`tests/unit/test_engine_famitracker.py`):

```python
def test_detect_on_fixture_returns_high_confidence(fixture_rom):
    engine = FamiTrackerEngine()
    r = engine.detect(fixture_rom)
    assert r.confidence >= 0.6
    assert "ascii_signature_present" in r.evidence or \
           "pointer_table_layout_match" in r.evidence

def test_walk_song_table_returns_expected_count(fixture_rom):
    engine = FamiTrackerEngine()
    songs = engine.walk_song_table(fixture_rom)
    assert len(songs) == FIXTURE_EXPECTED_SONG_COUNT  # constant in conftest
```

---

### 8.10 `qlnes/audio/wav.py`

```python
"""RIFF WAV writer. No 'smpl' chunk in A.1 (A.3 lands the loop chunk)."""
from __future__ import annotations

import struct
from pathlib import Path

from ..io.atomic import atomic_write_bytes


def write_wav(path: Path, pcm_le16: bytes, sample_rate: int = 44_100, channels: int = 1) -> None:
    """Write a minimal RIFF WAV (PCM int16 LE)."""
    bits_per_sample = 16
    byte_rate = sample_rate * channels * bits_per_sample // 8
    block_align = channels * bits_per_sample // 8
    data_size = len(pcm_le16)
    riff_size = 36 + data_size

    parts = [
        b"RIFF", struct.pack("<I", riff_size), b"WAVE",
        b"fmt ", struct.pack("<I", 16),
        struct.pack("<HHIIHH", 1, channels, sample_rate, byte_rate, block_align, bits_per_sample),
        b"data", struct.pack("<I", data_size), pcm_le16,
    ]
    atomic_write_bytes(path, b"".join(parts))
```

**Tests** in `tests/unit/test_wav_writer.py`: `wave.open(path).getparams()` returns expected `(channels, sample_width, framerate, nframes, comptype, compname)`.

---

### 8.11 `qlnes/oracle/fceux.py`

```python
"""FCEUX subprocess oracle. Captures APU trace + reference PCM via Lua scripting."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from ..io.errors import QlnesError


LUA_SCRIPT = Path(__file__).resolve().parent.parent / "audio_trace.lua"

DEFAULT_FCEUX_ARGS = (
    "--no-config", "1",
    "--mute", "1",
    "--frameskip", "0",
    "--video", "0",
    "--sound", "0",
)


@dataclass(frozen=True)
class TraceEvent:
    cycle: int
    register: int
    value: int


@dataclass
class ApuTrace:
    events: list[TraceEvent] = field(default_factory=list)
    end_cycle: int = 0


class FceuxOracle:
    def __init__(self, fceux_path: str | None = None) -> None:
        self._fceux = fceux_path or shutil.which("fceux")
        if not self._fceux:
            raise QlnesError(
                "internal_error",
                "fceux binary not found on PATH",
                extra={"detail": "missing_dependency", "dep": "fceux"},
            )

    def trace(self, rom: Path, frames: int = 600) -> ApuTrace:
        with tempfile.TemporaryDirectory(prefix="qlnes-trace-") as td:
            trace_path = Path(td) / "trace.tsv"
            ref_wav_path = Path(td) / "reference.wav"
            env = {
                **os.environ,
                "QLNES_TRACE_PATH": str(trace_path),
                "QLNES_REFERENCE_WAV": str(ref_wav_path),
                "QLNES_FRAMES": str(frames),
            }
            res = subprocess.run(
                [self._fceux, *DEFAULT_FCEUX_ARGS,
                 "--loadlua", str(LUA_SCRIPT), str(rom)],
                env=env, capture_output=True, timeout=60,
            )
            if res.returncode != 0:
                raise QlnesError(
                    "internal_error",
                    f"fceux exited {res.returncode}",
                    extra={"fceux_exit": res.returncode,
                           "stderr": res.stderr.decode("utf-8", "replace")[:200]},
                )
            return self._parse_trace(trace_path)

    def reference_pcm(self, rom: Path, frames: int = 600) -> bytes:
        # Same Lua run captures both. For A.1, we re-run; later optimization can cache.
        ...

    @staticmethod
    def _parse_trace(path: Path) -> ApuTrace:
        events = []
        end_cycle = 0
        with path.open() as f:
            for line in f:
                if line.startswith("#") or not line.strip():
                    continue
                cycle, reg, val = (int(x) for x in line.strip().split("\t"))
                events.append(TraceEvent(cycle, reg, val))
                end_cycle = max(end_cycle, cycle)
        return ApuTrace(events=events, end_cycle=end_cycle)
```

---

### 8.12 `qlnes/audio_trace.lua` (refined)

```lua
-- qlnes audio trace v1
-- Captures every APU register write ($4000-$4017) with its CPU framecount,
-- plus a reference WAV via FCEUX's sound.get API.
--
-- Env vars consumed:
--   QLNES_TRACE_PATH    output TSV path
--   QLNES_REFERENCE_WAV output WAV path (reference render)
--   QLNES_FRAMES        number of frames to advance

local frames = tonumber(os.getenv("QLNES_FRAMES")) or 600
local trace_path = assert(os.getenv("QLNES_TRACE_PATH"), "QLNES_TRACE_PATH not set")
local ref_path = os.getenv("QLNES_REFERENCE_WAV")  -- optional

local trace_out = assert(io.open(trace_path, "w"))
trace_out:write("# qlnes-trace v1\n")

for addr = 0x4000, 0x4017 do
    memory.registerwrite(addr, 1, function(a, sz, v)
        trace_out:write(string.format("%d\t%d\t%d\n", emu.framecount(), a, v))
    end)
end

if ref_path then
    sound.recordstart(ref_path)  -- FCEUX 2.6.6+ records WAV
end

for i = 1, frames do
    emu.frameadvance()
end

if ref_path then
    sound.recordstop()
end

trace_out:close()
emu.exit()
```

---

### 8.13 `qlnes/audio/renderer.py`

```python
"""Audio rendering pipeline. ROM → engine detect → song walk → APU replay → WAV."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..config.loader import ConfigLoader, ResolvedConfig
from ..io.atomic import atomic_write_bytes
from ..io.errors import QlnesError
from ..io.preflight import Preflight
from ..det import deterministic_track_filename
from ..oracle.fceux import FceuxOracle
from ..rom import Rom
from .engine import SoundEngineRegistry, PcmStream
from .wav import write_wav

# Force FT engine registration:
from .engines import famitracker  # noqa: F401


@dataclass
class RenderResult:
    output_paths: list[Path]
    engine_name: str
    tier: int


def render_rom_audio_v2(
    rom_path: Path,
    *,
    output_dir: Path,
    fmt: str = "wav",
    frames: int = 600,
    force: bool = False,
    cfg: ResolvedConfig | None = None,
) -> RenderResult:
    """End-to-end audio rendering for one ROM. Per-track outputs."""
    rom = Rom.from_file(rom_path)
    engine, detection = SoundEngineRegistry.detect(rom)
    songs = engine.walk_song_table(rom)
    oracle = FceuxOracle()
    paths: list[Path] = []
    for song in songs:
        pcm = engine.render_song(rom, song, oracle)
        target = output_dir / deterministic_track_filename(
            rom_path.stem, song.index, engine.name, fmt,
        )
        if target.exists() and not force:
            raise QlnesError(
                "cant_create",
                f"cannot write {target}: file exists (use --force to overwrite)",
                extra={"path": str(target), "cause": "exists"},
            )
        if fmt == "wav":
            write_wav(target, pcm.samples, pcm.sample_rate)
        else:
            raise QlnesError(
                "bad_format_arg",
                f"--format {fmt!r} not yet supported in this story; use --format wav",
                extra={"format": fmt},
            )
        paths.append(target)
    return RenderResult(paths, engine.name, engine.tier)
```

---

### 8.14 `qlnes/cli.py` — `audio` command refactor

```python
# (existing imports + Typer app preserved; only the audio() function body changes)

@app.command()
def audio(
    rom: Path = typer.Argument(..., exists=True, file_okay=True, dir_okay=False, readable=True),
    output: Path = typer.Option(..., "-o", "--output"),
    format: str = typer.Option("wav", "--format"),
    frames: int = typer.Option(600, "--frames"),
    force: bool = typer.Option(False, "--force"),
    quiet: bool = typer.Option(False, "-q", "--quiet"),
    no_hints: bool = typer.Option(False, "--no-hints"),
    color: str = typer.Option("auto", "--color"),
):
    """Rend l'audio de la ROM (engine → APU → WAV)."""
    from .config.loader import ConfigLoader
    from .io.errors import QlnesError, emit
    from .io.preflight import Preflight
    from .audio.renderer import render_rom_audio_v2

    cli_overrides = {"format": format, "frames": frames, "output_dir": str(output)}
    cfg = ConfigLoader().resolve("audio", cli_overrides)

    use_color = (color == "always") or (color == "auto" and sys.stderr.isatty())

    try:
        pf = Preflight()
        pf.add("rom_readable",     lambda: _check_rom_readable(rom))
        pf.add("output_writable",  lambda: _check_output_writable(Path(output), force=force))
        pf.add("fceux_on_path",    lambda: _check_fceux_on_path())
        pf.run()

        result = render_rom_audio_v2(
            rom, output_dir=Path(output), fmt=cfg["format"],
            frames=cfg["frames"], force=force, cfg=cfg,
        )

        if not quiet:
            for p in result.output_paths:
                typer.echo(f"✓ {p}", err=True)
            typer.echo(
                f"✓ {len(result.output_paths)} WAV écrits  "
                f"(moteur={result.engine_name}, tier={result.tier})",
                err=True,
            )
    except QlnesError as e:
        emit(e, no_hints=no_hints, color=use_color)
    except KeyboardInterrupt:
        emit(QlnesError("interrupted", "interrupted"))
    except Exception as exc:
        emit(QlnesError(
            "internal_error",
            f"{type(exc).__name__}: {exc}",
            extra={"detail": type(exc).__name__},
        ))
```

(Full body in DS; the above is the spec.)

---

## 9. Test Plan (per AC)

| AC | Test target | Test file | Layer | Expected runtime |
|---|---|---|---|---|
| AC1 | `test_filenames_deterministic` | `tests/integration/test_audio_pipeline.py` | integration | < 30 s |
| AC2 | `test_apu_vs_fceux_per_channel[<fixture>]` | `tests/invariants/test_pcm_equivalence.py` | invariants | < 2 min |
| AC3 | `test_render_under_2x_realtime` | `tests/integration/test_audio_perf.py` | integration | < 6 min (worst case) |
| AC4 | `test_kill_mid_render_leaves_no_partial` | `tests/invariants/test_atomic_kill.py` | invariants | < 30 s |
| AC5 | `test_missing_input_exits_66_with_json`, `test_bad_rom_exits_65_with_json` | `tests/integration/test_cli_audio.py` | integration | < 5 s each |
| AC6 | `test_refuse_overwrite_exits_73`, `test_force_overwrites` | `tests/integration/test_cli_audio.py` | integration | < 30 s each |
| AC7 | `test_render_twice_identical` | `tests/invariants/test_determinism.py` | invariants | < 2 min |
| AC8 | `test_no_wallclock_in_artifact` | `tests/invariants/test_determinism.py` | invariants | < 5 s |

**CI schedule.** `tests/unit` + `tests/integration` run on every push (target < 5 min total). `tests/invariants` run on tag + weekly (`audit.yml`, B.4 scope). For A.1's merge, the developer runs `tests/invariants` locally before opening the merge.

---

## 10. Out-of-scope for A.1 (deferred to later stories)

The following items are explicitly **NOT** part of A.1, even though related work touches the same files:

- **MP3 output** → A.2.
- **Loop boundaries (`'smpl'` chunk in WAV)** → A.3.
- **Capcom engine** → A.4. A.1 ships only FT.
- **Generic tier-2 fallback** → A.5. A.1 raises `unsupported_mapper` for unrecognized engines.
- **`qlnes verify --audio`** → A.6.
- **`qlnes audit` + `bilan.json`** → epic B.
- **NSF output** → epic C.
- **`--strict`, `--no-progress`, `--debug`, full layered config schema** → epic D.
- **Removal of legacy `qlnes/audio.py`** → A.6.
- **CI workflow `audit.yml`** → B.4.
- **Corpus manifest + `generate_references.py`** → B.3.

---

## 11. Fixture ROM choice (action item for Johan before DS starts)

A.1 needs **one** mapper-0 (NROM) FamiTracker fixture ROM, legally redistributable, committed at `tests/fixtures/<sha>.nes`.

**Recommended candidates:**

1. **NESdev wiki test ROMs** (`http://www.nesdev.org/`) — public domain, widely used in emulator-test corpora. Many are mapper-0. Pick one with a small but multi-track FT-driven OST.
2. **0CC-FamiTracker example NSFs back-converted to NROM** — the FamiTracker community ships demo songs under permissive licenses.
3. **Johan's own test ROM** — if Johan has authored a tiny FT-driven NROM previously.

**Acceptance for the fixture:**

- License explicitly permits redistribution (PD, CC0, MIT, or similar).
- File ≤ 32 KB PRG + 8 KB CHR (NROM-128 layout).
- ≥ 2 distinct songs in the song-pointer table (lets AC1 verify multi-track filename generation).
- Plays cleanly in FCEUX 2.6.6+ for ≥ 600 frames without crash.
- SHA-256 recorded in `tests/conftest.py::FIXTURE_ROM_SHA`.

If no candidate is available before DS starts, A.1 can begin against a **commercial mapper-0 FT ROM that Johan has legally on his machine**, with the fixture committed to `.gitignore` for the spike, and the redistributable replacement landing as a follow-up housekeeping task before A.1 merges.

---

## 12. Definition of Done (story-level checklist)

DS hands off to CR when all boxes below are checked.

- [ ] All 8 ACs pass their named test targets.
- [ ] `pytest tests/unit tests/integration` green on dev machine.
- [ ] `pytest tests/invariants` green on dev machine (A.1's test parameter list).
- [ ] `ruff check qlnes tests` clean.
- [ ] `ruff format --check qlnes tests` clean.
- [ ] `mypy qlnes` clean (strict on new modules).
- [ ] No new wall-clock / hostname / username in any artifact (NFR-REL-2 verified).
- [ ] `qlnes audio --help` reflects the new flag set (shows `--format`, `--force`, `--no-hints`, `--color`, etc.).
- [ ] Fixture ROM committed at `tests/fixtures/` with SHA recorded in `conftest.py`.
- [ ] `requirements-dev.txt` committed; `requirements.txt` unchanged.
- [ ] `qlnes.toml.example` committed at repo root.
- [ ] `ruff.toml` and `mypy.ini` committed.
- [ ] `.gitignore` updated.
- [ ] `qlnes/audio.py` (legacy ffmpeg path) reduced to a thin shim that delegates to `qlnes/audio/renderer.py`. (Full deletion in A.6.)
- [ ] Existing tests (`tests/test_*.py` at top level, post-E.1 in `tests/unit/` or `tests/invariants/`) still green.
- [ ] PR description references this story file and the FRs/NFRs closed.
- [ ] Story status updated to **DONE** in `_bmad-output/implementation-artifacts/sprint-status.md` §4 after merge.

---

## 13. Sign-off

This story file is **READY for `bmad-dev-story` (DS)**.

### Required next action

**Run `bmad-dev-story` (DS) on this story file** (`_bmad-output/implementation-artifacts/stories/A.1.md`).

DS produces a feature branch (`feature/A.1-mapper0-ft-wav`) implementing every section above. Expect roughly 5 dev-days of focused work. CR runs after DS completes.

### Optional pre-DS action

- Choose & commit the fixture ROM (§11).
- Smoke-test FCEUX trace path: run `fceux --loadlua qlnes/audio_trace.lua <rom>.nes` manually with the env vars set; verify the TSV trace and reference WAV are produced.
- Confirm the dev environment is set up per sprint plan §10's smoke-test bash block.

### Story-creation notes

This is the largest story in the MVP and the most cross-cutting. It is L-estimated for a reason: A.1 lands ~30 new files. The implementation order in §7 is the recommended path because each layer is testable in isolation before the next layer is built — DS should not deviate from the order without recording why in §6 of the sprint plan (retrospective log).

The cross-cutting modules (`qlnes/io/*`, `qlnes/det.py`, `qlnes/config/loader.py`) are touched by every subsequent story. Their interfaces are the contract for the rest of the MVP; **changes to their public surface require updating the architecture document** (architecture step 7) and bumping the major version of the in-progress qlnes pre-release.

---

**Story author:** Claude (Opus 4.7), acting as `bmad-create-story` (CS).
**Date:** 2026-05-03 (afternoon session, post-SP).
**Next BMad action:** `bmad-dev-story` (DS) on `_bmad-output/implementation-artifacts/stories/A.1.md`.

---

*End of Story File — A.1 (qlnes Music-MVP, sprint 1)*
