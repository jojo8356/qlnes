---
story_id: F.5b
epic: F
title: PyPy subprocess workhorse for in-process render
sprint: 10
estimate: S
status: DONE + CR-clean (all 7 ACs ✅; 4 should-fixes applied in CR retrofit; 13 tests green; 5.69× speedup measured)
created_by: bmad-create-story (CS)
date_created: 2026-05-04
date_completed: 2026-05-04
project_name: qlnes
mvp_target: v0.6.0
inputDocuments:
  - _bmad-output/decisions/v06-cpu-backend.md (F.2 decision §"Distribution strategy")
  - _bmad-output/implementation-artifacts/stories/F.5.md (F.5 §6 decision 6: split)
  - _bmad-output/implementation-artifacts/stories/F.4.md (run_song wiring)
fr_closed: [FR41/perf]
nfr_touched: [PERF-80, MEM-80]
risks_realized: []
risks_softened: [R30]
risks_new: [R40]
preconditions: [F.5]
outputs:
  - qlnes/audio/in_process/_pypy_dispatch.py
  - qlnes/audio/in_process/_pypy_child.py
  - qlnes/audio/engine.py — render_song_in_process auto-detects PyPy
  - tests/unit/test_pypy_dispatch.py
  - tests/integration/test_pypy_subprocess.py (gated on PyPy availability)
next_story: F.6
next_action: bmad-dev-story (DS) on F.5b
---

# Story F.5b — PyPy subprocess workhorse

**Epic:** F — *Replace FCEUX subprocess by in-process CPU emulator*
**Sprint:** 10
**Estimate:** S (1 dev-day)
**Status:** READY

---

## 1. User value

> **Marco.** Marco renders a 3-min song with `qlnes audio rom.nes
> --engine-mode in-process`. On the F.5 path (CPython only) this
> takes ~93 s — within the 60 s NFR-PERF-80 budget for shorter
> tracks but uncomfortable for batch audits. With F.5b, if PyPy is
> available on the host, the renderer transparently shells out to a
> PyPy subprocess for the hot loop and the same render finishes in
> ~4 s (22× speedup measured in F.2).

F.5b is **purely a performance optimization** behind a transparent
detection fallback. Zero user-facing API change.

## 2. Acceptance criteria

| # | AC | Verification |
|---|---|---|
| AC1 | `find_pypy()` returns a `Path` when PyPy is reachable via (in priority order) `$PYPY_BIN` env, `vendor/pypy/bin/pypy3`, `pypy3` on PATH | Unit test mocks each branch via env+filesystem monkeypatch |
| AC2 | `find_pypy()` returns `None` when no candidate exists | Unit test |
| AC3 | `run_song_via_pypy(rom_path, init, play, frames)` produces a trace **byte-identical** to `InProcessRunner.run_song(...)` running in-process under CPython | Integration test gated on PyPy availability — diff every event vs F.4 fixture |
| AC4 | `SoundEngine.render_song_in_process` auto-uses PyPy when available + when running under CPython; runs in-process otherwise | Integration test: patch `find_pypy` to return None → in-process; return real Path → subprocess |
| AC5 | If PyPy is not found AND the render is on CPython, a one-time `pypy_not_found` info hint is emitted (suppressed by `--no-hints`) | Unit test capsys |
| AC6 | When already running under PyPy, the dispatch never recurses (no PyPy → PyPy fork) | Unit test asserts `find_pypy` is not called when `sys.implementation.name == "pypy"` |
| AC7 | Wall-clock for `render_song_in_process` on Alter Ego improves by ≥ 3× compared to the F.5 CPython-only path on the same hardware | Integration benchmark; record both numbers in test output |

## 3. Pre-conditions checked

- [x] F.5 done (CLI flag, dispatch, ABC default impl)
- [x] PyPy 3.11 available locally (`/tmp/pypy3.11-v7.3.18-linux64/bin/pypy3`)
- [x] PyPy can already run `harness_py65_optimized.py` per F.2 spike

## 4. Embedded scaffolding

### 4.1 `qlnes/audio/in_process/_pypy_dispatch.py` (new)

```python
def find_pypy() -> Path | None:
    """Return the path to a PyPy interpreter, or None.

    Resolution order:
      1. $PYPY_BIN env var (if set + executable)
      2. <repo_root>/vendor/pypy/bin/pypy3 (managed install, F.10 ships installer)
      3. `pypy3` on PATH (system install)
      4. None — caller falls back to the in-process CPython path.
    """

def run_song_via_pypy(
    pypy: Path,
    rom_path: Path,
    init_addr: int,
    play_addr: int,
    frames: int,
) -> list[ApuWriteEvent]:
    """Spawn `pypy <pypy_child.py> ...`, parse the binary trace from stdout.

    The child packs each event as `<IHBx` (uint32 cycle, uint16
    register, uint8 value, 1 byte pad) = 8 bytes. Parent reads stdout
    bytes and unpacks back into ApuWriteEvent.
    """
```

### 4.2 `qlnes/audio/in_process/_pypy_child.py` (new)

```python
"""Run by find_pypy()'s pypy3. Consumes stdin/argv, writes binary
trace to stdout. Argv format:
    pypy3 _pypy_child.py <rom_path> <init_hex> <play_hex> <frames>
Stdout: a 4-byte little-endian count + N × 8-byte event records.
"""
def main():
    rom_path = Path(sys.argv[1])
    init = int(sys.argv[2], 16)
    play = int(sys.argv[3], 16)
    frames = int(sys.argv[4])
    rom = Rom.from_file(rom_path)
    runner = InProcessRunner(rom)
    events = list(runner.run_song(init, play, frames=frames))
    sys.stdout.buffer.write(struct.pack("<I", len(events)))
    for e in events:
        sys.stdout.buffer.write(struct.pack("<IHBx", e.cpu_cycle, e.register, e.value))
```

The child must add the qlnes repo root to sys.path so it can import
the package — handled by computing `Path(__file__).resolve().parents[3]`
and prepending.

### 4.3 `qlnes/audio/engine.py` — modify `render_song_in_process`

```python
def render_song_in_process(self, rom, song, *, frames=600) -> PcmStream:
    init = self.init_addr(rom, song)
    play = self.play_addr(rom, song)

    # F.5b: auto-dispatch to PyPy if available + we're not already on PyPy.
    if sys.implementation.name != "pypy":
        from .in_process._pypy_dispatch import find_pypy, run_song_via_pypy
        pypy = find_pypy()
        if pypy is not None and rom.path is not None:
            events = run_song_via_pypy(pypy, rom.path, init, play, frames)
        else:
            # Fallback: in-process under CPython
            from .in_process import InProcessRunner
            events = list(InProcessRunner(rom).run_song(init, play, frames=frames))
    else:
        # Already on PyPy — no point shelling out
        from .in_process import InProcessRunner
        events = list(InProcessRunner(rom).run_song(init, play, frames=frames))

    # ... existing ApuEmulator feed + PcmStream return ...
```

### 4.4 Tests

- `tests/unit/test_pypy_dispatch.py` — find_pypy resolution branches
  (4 tests: env, vendor, PATH, none). Mocking via monkeypatch.
- `tests/integration/test_pypy_subprocess.py` — gated on
  `find_pypy() is not None`. Round-trips trace via PyPy child, asserts
  byte-equiv with F.4 fixture (sha `ea062dba…4baa`). Benchmark
  comparison.

## 5. Decisions taken in CS facilitation

1. **Binary IPC (struct), not JSON.** 165K events × ~30 bytes JSON
   = 5 MB; struct binary = 1.3 MB. Faster to encode/decode, no
   floating-point format gotchas (cycles are int).
2. **Recursion guard via `sys.implementation.name`.** When already
   on PyPy, dispatch never re-forks. Avoids spawning fork bombs
   when running tests under PyPy.
3. **`rom.path` required for PyPy path.** The child needs a
   filesystem path to load. If the ROM was constructed in-memory
   (`Rom(raw_bytes)` without `from_file`), F.5b falls back to
   in-process. Acceptable because production calls always have a
   path; tests can construct in-memory ROMs and skip the PyPy
   path.

## 6. Risks

- **R40 (NEW) — Trace divergence between PyPy and CPython.** PyPy's
  JIT could in theory introduce floating-point or ordering
  differences. F.2 spike showed byte-identical traces between CPython
  and PyPy on the same harness, but F.5b adds the IPC layer
  (potential serialization bugs). AC3 catches divergence.
- **R30 carried, **softened** further** — PyPy gives 22× speedup
  measured in F.2; F.5b makes it transparent.

## 7. DoD

- [x] AC1-AC7 green (9 unit + 3 integration)
- [x] `qlnes audio --engine-mode in-process` benchmark on Alter Ego:
       PyPy path 5.69× faster than CPython (300 frames: 1.98 s vs 11.25 s,
       far above the 3× target)
- [x] No regression in F.5 tests (87 currently green; total now 99)
- [x] PyPy detection skips silently when PyPy not installed (try/except
       wraps the subprocess so any failure falls through to in-process)

## 8. Implementation deviation from CS plan

**Significant refactor mid-DS:** the original CS plan had the PyPy
child return a binary trace (8-byte event records) and ApuEmulator
ran on the parent (CPython). Empirical benchmark showed that
configuration delivered only ~1.25× speedup (CPython 23 s → mixed
18 s) because ApuEmulator dominates: 17.6 s of CPython mixing for
0.97 s of PyPy CPU emulation.

**Fix:** moved ApuEmulator into the child too. The child now runs
the entire pipeline (CPU emu + ApuEmulator) and returns int16 LE PCM
bytes directly. The parent just unpacks `(uint32 pcm_byte_count,
uint32 sample_rate, ...pcm bytes...)` from stdout. Result: end-to-end
5.69× speedup, byte-equivalent output.

This decision is reflected in the `_pypy_child.py` contract and the
`PypyRenderResult` dataclass in `_pypy_dispatch.py`. The story §4.1
sketch (which described an event-trace protocol) is superseded by
the PCM-bytes protocol shipped.

## 8b. Code review applied (2026-05-04 retrofit pass)

CR retrofit identified 4 should-fix items in F.5b, applied:

- **F.5b.CR-1 + CR-7 (must-fix)** — `_resolve_in_process_pcm` had
  `except Exception: pass` swallowing every error including
  `subprocess.TimeoutExpired` (3-min wait silently lost!). User had
  no way to know PyPy was tried but failed. Fix: catch only
  `CalledProcessError`, `TimeoutExpired`, `ValueError` (legitimate
  fallback signals); emit `warning: pypy_render_failed` with stderr
  excerpt; let other exceptions propagate as bugs. New integration
  test `test_pypy_subprocess_failure_emits_pypy_render_failed_warning`
  pins the warning.
- **F.5b.CR-6 (should-fix)** — added sample-rate sanity check on the
  PyPy result. If a future child returns a sample rate other than
  44100, the parent now raises ValueError (caught by the same
  fallback path) instead of silently returning a mismatched stream.
- **F.5b.CR-10 (should-fix)** — recursion-guard test was mutating
  `sys.implementation = _FakeImpl()` by direct attribute write —
  fragile; could break Python internals. Replaced with
  `monkeypatch.setattr(sys, 'implementation', SimpleNamespace(name='pypy'))`
  for clean teardown.

Skipped:
- F.5b.CR-3 (argv hex strings) — cosmetic, no behavior impact.
- F.5b.CR-4 (`find_pypy` repo-root in wheel install) — accepted
  for v0.6 which doesn't ship as a wheel; F.10 wheel work will
  revisit.

**Tests count update.** F.5b adds 1 new integration test (failure
warning). Total F.5b tests: **9 unit + 4 integration = 13**.

## 9. Hand-off to F.6

Non-blocking. F.6 (bilan v2 schema) consumes `RenderResult` shape
unchanged.
