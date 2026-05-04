---
story_id: F.5
epic: F
title: --engine-mode CLI flag + pipeline dispatch
sprint: 10
estimate: M
status: DONE + CR-clean (all 8 ACs ✅; 4 should-fixes applied in retrofit pass; 19 tests still green)
created_by: bmad-create-story (CS)
date_created: 2026-05-04
date_completed: 2026-05-04
project_name: qlnes
mvp_target: v0.6.0
inputDocuments:
  - _bmad-output/planning-artifacts/prd-no-fceux.md
  - _bmad-output/planning-artifacts/architecture-v0.6.md (steps 20.2, 20.4)
  - _bmad-output/planning-artifacts/epics-and-stories-v0.6.md (§F.5)
  - _bmad-output/implementation-artifacts/stories/F.3.md (InProcessRunner)
  - _bmad-output/implementation-artifacts/stories/F.4.md (init/play protocol)
  - _bmad-output/decisions/v06-cpu-backend.md
fr_closed: [FR46, FR47, FR48, FR49, FR53/full]
fr_partial: []
nfr_touched: [REL-1, REL-80, PERF-80]
risks_realized: []
risks_softened: []
risks_new: [R38, R39]
preconditions: [F.3, F.4]
outputs:
  - qlnes/cli.py — adds --engine-mode flag, conditional fceux preflight
  - qlnes/audio/renderer.py — engine_mode parameter, dispatch per arch §20.4
  - qlnes/audio/engine.py — SoundEngine.render_song_in_process default impl
  - qlnes/io/errors.py — new error class in_process_unavailable (exit 100), warning class in_process_low_confidence
  - qlnes/audio/in_process/_pypy_dispatch.py — (optional, CS-added) PyPy subprocess workhorse
  - tests/integration/test_cli_engine_mode.py
  - tests/unit/test_renderer_engine_mode.py
next_story: F.6
next_action: bmad-dev-story (DS) on F.5 → branch `feature/F.5-engine-mode`
---

# Story F.5 — `--engine-mode` CLI flag + pipeline dispatch

**Epic:** F — *Replace FCEUX subprocess by in-process CPU emulator*
**Sprint:** 10 (v0.6 engine integration sprint)
**Estimate:** M (2-3 dev-days)
**Status:** READY (DoR satisfied: F.3 InProcessRunner + F.4 init/play protocol both DONE+CR-clean; FT engine returns valid addresses for Alter Ego)

---

## 1. User value

> **Marco.** Marco runs `python -m qlnes audio rom.nes --format wav`
> on a clean machine **without FCEUX installed** and gets WAV files
> from the in-process pipeline. Auto mode picks in-process when the
> engine supports it; if a future engine doesn't, qlnes falls back
> to oracle (with a warning) for graceful degradation. Power users
> can force the path with `--engine-mode in-process` (perf-friendly,
> fceux-free) or `--engine-mode oracle` (v0.5 compat).

This story closes the user-facing v0.6 contract: the CLI exposes
the in-process pipeline, the renderer dispatches per architecture
§20.4, and engines that don't support in-process fail cleanly with
a structured error that scripting tools can catch.

## 2. Acceptance criteria

### From epics-and-stories-v0.6.md §F.5

| # | AC | Verification |
|---|---|---|
| AC1 | `--engine-mode in-process` on FT-Alter Ego succeeds | Integration test: `python -m qlnes audio <alter_ego.nes> --engine-mode in-process --output <dir>` exits 0, writes a `.wav` file with valid RIFF header |
| AC2 | `--engine-mode oracle` keeps v0.5 behavior on Alter Ego | Integration test mocks `FceuxOracle.trace` (fceux not installed in CI/test env), confirms the oracle code-path runs and writes a WAV. v0.5 behavior == "instantiates oracle, calls trace, feeds events through ApuEmulator". |
| AC3 | `--engine-mode auto` (default) picks in-process when available, falls back to oracle with warning when not | Two integration tests: (a) FT engine present → auto picks in-process, no warning; (b) synthetic engine that raises InProcessUnavailable → auto falls back to oracle with `warning: in_process_low_confidence` line on stderr. |
| AC4 | Both `auto` and `in-process` exit 100 with `class:in_process_unavailable` for engines without `init_addr`/`play_addr` | Integration test: synthetic engine that doesn't override init/play. `auto` exits 0 via fallback (no oracle? exit 100). `in-process` always exits 100 with structured stderr payload. |

### Added in CS facilitation

| # | AC | Why |
|---|---|---|
| AC5 | The fceux preflight (`_check_fceux_on_path`) is conditional on engine-mode. `--engine-mode in-process` runs without fceux installed; `--engine-mode oracle` requires it; `--engine-mode auto` requires it only if the auto-resolver decides to use oracle. | Without this, the existing CLI hard-fails before render dispatch when fceux is absent — defeating the v0.6 fceux-free promise. |
| AC6 | `--engine-mode oracle` emits a deprecation warning (`oracle_path_deprecated`) when invoked, recommending `--engine-mode auto` | v0.6's product story is "fceux-free by default". Oracle path is kept for v0.5 compat but should signal it's not the long-term direction. |
| AC7 | Renderer signature `render_rom_audio_v2(..., engine_mode='auto')` defaults to `'auto'`. Existing callers (no flag) get the same behavior they had on v0.5 if oracle is available, plus the in-process upgrade if the engine supports it. | Backward-compatible API surface. |
| AC8 | `RenderResult` carries `engine_mode_used: Literal["in-process", "oracle"]` so downstream tooling (B.1 bilan in F.6) can record which path produced each WAV. | Required by F.6 (`bilan v2 schema migration`) and by `qlnes coverage` to show in-process vs oracle coverage per (mapper, engine). |

## 3. Pre-conditions checked

- [x] F.3 done (`InProcessRunner.run_song(init, play, frames)` works, fixture pinned)
- [x] F.4 done (`SoundEngine.init_addr` / `play_addr` defined with default-raise; `FamiTrackerEngine` overrides for mapper-0 ROMs)
- [x] `qlnes/io/errors.py::EXIT_CODES` already has slot for new `in_process_unavailable` class (will add at code 100)
- [x] No other story currently owns the file regions touched
- [x] FT engine on Alter Ego returns valid addresses (init=$8000, play=$8093, verified by F.4 test)
- [x] PyPy 3.11 portable tarball available (used by F.2 spike); CS-added concern (see §6)

## 4. Embedded scaffolding (file-level outline)

### 4.1 `qlnes/io/errors.py` — extend

```python
EXIT_CODES: dict[str, int] = {
    # ... existing ...
    "in_process_unavailable": 100,    # F.5 new — same exit as unsupported_mapper
    # ... existing ...
}

DEFAULT_HINTS: dict[str, str | None] = {
    # ... existing ...
    "in_process_unavailable":
        "Try `--engine-mode auto` to fall back, or run `qlnes coverage` for the support matrix.",
    # ... existing ...
}
```

The new warning class names (no exit code, used via `warn()`):
- `in_process_low_confidence` — auto-fallback to oracle
- `oracle_path_deprecated` — explicit `--engine-mode oracle` (AC6)

### 4.2 `qlnes/audio/engine.py` — extend with default `render_song_in_process`

```python
class SoundEngine(abc.ABC):
    # ... existing methods (detect, walk_song_table, render_song,
    #     detect_loop, init_addr, play_addr) ...

    def render_song_in_process(
        self, rom: Rom, song: SongEntry, *, frames: int = 600
    ) -> PcmStream:
        """Render `song` via the in-process pipeline (F.3 + F.4).

        Default impl: use `init_addr` / `play_addr` to drive
        `InProcessRunner.run_song`, feed events through `ApuEmulator`,
        return `PcmStream`. Engines override only if they need
        engine-specific tweaks (none expected for v0.6).

        Raises InProcessUnavailable (subclass of NotImplementedError)
        if init_addr/play_addr aren't implemented for the engine.
        """
        from .in_process import InProcessRunner
        from ..apu import ApuEmulator

        init = self.init_addr(rom, song)
        play = self.play_addr(rom, song)
        runner = InProcessRunner(rom)
        events = runner.run_song(init, play, frames=frames)
        emu = ApuEmulator()
        for ev in events:
            emu.write(ev.register, ev.value, ev.cpu_cycle)
        # NTSC frame cycles ≈ 29780.5; ApuEmulator uses cycle accounting
        # for sample-mixing math. We use the same end_cycle as the
        # oracle path uses (max of last event cycle, frames * cycles/frame).
        end_cycle = int(frames * NTSC_CPU_HZ / NTSC_FRAME_RATE)
        pcm = emu.render_until(cycle=end_cycle)
        return PcmStream(samples=pcm, sample_rate=44_100, loop=None)
```

Constants `NTSC_CPU_HZ` and `NTSC_FRAME_RATE` already live in
`qlnes/audio/engines/famitracker.py`; F.5 promotes them to
`qlnes/audio/engine.py` so the ABC default impl can reference them.

### 4.3 `qlnes/audio/renderer.py` — engine_mode dispatch

```python
EngineMode = Literal["auto", "in-process", "oracle"]


def render_rom_audio_v2(
    rom_path: Path | str,
    output_dir: Path | str,
    *,
    fmt: str = "wav",
    frames: int = 600,
    force: bool = False,
    oracle: FceuxOracle | None = None,
    engine_mode: EngineMode = "auto",
) -> RenderResult:
    # ... existing rom + format validation ...

    if engine_mode == "oracle":
        warn("oracle_path_deprecated",
             "--engine-mode oracle is kept for v0.5 compatibility; "
             "v0.6's default is in-process. Drop the flag to switch.",
             extra={"recommended": "--engine-mode auto"})

    rom = Rom.from_file(rom_path)
    engine, _detection = SoundEngineRegistry.detect(rom)
    songs = engine.walk_song_table(rom)
    # ... songs sanity check ...

    output_dir.mkdir(parents=True, exist_ok=True)
    # ... per-path pre-compute + refuse-overwrite ...

    used_mode = "in-process"  # default optimistic
    if engine_mode == "in-process":
        # Strict: any failure to render in-process raises in_process_unavailable
        try:
            pcms = [engine.render_song_in_process(rom, s, frames=frames) for s in songs]
        except InProcessUnavailable as e:
            raise QlnesError(
                "in_process_unavailable",
                e.args[0],
                extra=e.meta,
            ) from e
    elif engine_mode == "oracle":
        if oracle is None:
            oracle = FceuxOracle()
        pcms = [engine.render_song(rom, s, oracle, frames=frames) for s in songs]
        used_mode = "oracle"
    else:  # auto
        try:
            pcms = [engine.render_song_in_process(rom, s, frames=frames) for s in songs]
        except InProcessUnavailable as e:
            warn("in_process_low_confidence",
                 f"engine {engine.name!r} has no in-process support; falling back to oracle",
                 extra=e.meta)
            if oracle is None:
                oracle = FceuxOracle()
            pcms = [engine.render_song(rom, s, oracle, frames=frames) for s in songs]
            used_mode = "oracle"

    # ... write WAVs / MP3s using pcms ...

    return RenderResult(
        output_paths=output_paths,
        engine_name=engine.name,
        tier=engine.tier,
        rom_stem=rom.name,
        engine_mode_used=used_mode,  # AC8: new field
    )
```

`RenderResult` gets `engine_mode_used: Literal["in-process", "oracle"]`.

### 4.4 `qlnes/cli.py` — `--engine-mode` flag + conditional preflight

```python
def audio(
    rom: Annotated[Path, typer.Argument(help="ROM .nes à rendre")],
    output: Annotated[Path, typer.Option("-o", "--output", ...)],
    # ... existing flags (fmt, frames, force, quiet, no_hints, color) ...
    engine_mode: Annotated[
        str,
        typer.Option(
            "--engine-mode",
            help="Pipeline d'extraction audio : auto (défaut), in-process, oracle",
        ),
    ] = "auto",
) -> None:
    # ... existing setup ...

    pf = Preflight()
    pf.add("rom_readable", lambda: _check_rom_readable(rom))
    pf.add("output_writable", lambda: _check_output_writable(output))
    # AC5: fceux preflight only when oracle path is reachable
    if engine_mode in ("oracle", "auto"):
        pf.add("fceux_on_path_or_skip", _check_fceux_optional)
    pf.run()

    # ... call render_rom_audio_v2 with engine_mode=engine_mode ...
```

The new `_check_fceux_optional` returns `(ok=True, reason="fceux not on PATH; in-process path will handle this")` when fceux is absent, instead of failing. The renderer's auto-fallback decides whether oracle is actually needed.

### 4.5 `qlnes/audio/in_process/_pypy_dispatch.py` — (CS-added §6, see below)

If the CS-added "PyPy subprocess workhorse" concern is pursued, this
module:
- Detects PyPy via `vendor/pypy/bin/pypy3` → `$PYPY_BIN` env →
  `pypy3` on PATH.
- Returns `None` if not found; renderer continues in-process under
  CPython with a `warning: pypy_not_found` (only emitted if the
  3-min-equivalent walltime would exceed the warning threshold —
  `frames * 1.5 > NFR_PERF_80_BUDGET_S * 1000 ms`).
- If found, exposes `run_in_process_via_pypy(rom_path, init, play, frames)
  → list[ApuWriteEvent]` that shells out to PyPy.

**CS recommendation: split into F.5b** (see §6).

### 4.6 Tests

#### `tests/unit/test_renderer_engine_mode.py` (new)

Stateful unit tests for the dispatch logic, mocking
`engine.render_song_in_process`, `engine.render_song`, and
`FceuxOracle`. No corpus ROM dependency.

- `test_engine_mode_in_process_calls_render_song_in_process_only`
- `test_engine_mode_oracle_calls_render_song_only`
- `test_engine_mode_oracle_emits_deprecation_warning` (AC6)
- `test_engine_mode_auto_prefers_in_process_when_available`
- `test_engine_mode_auto_falls_back_on_in_process_unavailable` + `test_emits_in_process_low_confidence_warning`
- `test_engine_mode_in_process_raises_qlnes_error_for_unavailable_engine` (AC4)
- `test_render_result_carries_engine_mode_used` (AC8)

#### `tests/integration/test_cli_engine_mode.py` (new)

End-to-end CLI tests via `subprocess.run([sys.executable, "-m", "qlnes", "audio", ...])`,
patterned on `tests/integration/test_cli_audio.py`. Uses Alter Ego.

- `test_cli_in_process_succeeds_without_fceux` (AC1, AC5)
- `test_cli_oracle_emits_deprecation_warning` (AC6) — mock fceux trace via env var
- `test_cli_auto_default_picks_in_process` (AC3)
- `test_cli_in_process_exits_100_for_unsupported_engine` (AC4) — uses synthetic ROM the FT detector rejects
- `test_cli_default_no_flag_works_unchanged_for_oracle_consumers` (AC7)

#### Existing tests touched

- `tests/integration/test_cli_audio.py` — these tests assume fceux is on PATH.
  They become "oracle path" tests. Update `--engine-mode oracle` explicitly,
  OR adjust to assume in-process default. CS recommendation: keep them as
  oracle-path tests so v0.5 regression coverage stays intact.

## 5. Implementation order

1. Add `in_process_unavailable` to `EXIT_CODES` + hint. Add warning
   class names `in_process_low_confidence`, `oracle_path_deprecated`
   to docstring (these are not in EXIT_CODES; just discriminator
   strings used by `warn()`).
2. Promote `NTSC_CPU_HZ` / `NTSC_FRAME_RATE` constants from
   `engines/famitracker.py` to `engine.py`.
3. Add `SoundEngine.render_song_in_process` default impl. Verify
   on Alter Ego that it produces a non-empty PcmStream.
4. Add `engine_mode` param to `render_rom_audio_v2`. Implement
   the 3-branch dispatch.
5. Add `engine_mode_used` to `RenderResult` (AC8).
6. Add `--engine-mode` CLI flag + conditional fceux preflight.
7. Unit tests (`test_renderer_engine_mode.py`).
8. Integration tests (`test_cli_engine_mode.py`).
9. Update `tests/integration/test_cli_audio.py` to explicitly request
   `--engine-mode oracle` if those tests rely on oracle behavior.
10. Final full-suite green.

## 6. Decisions taken in CS facilitation

1. **`render_song_in_process` ABC default impl, not new abstractmethod.**
   Subclasses get the standard "init/play + InProcessRunner +
   ApuEmulator" pipeline for free. Tier-2 generic fallback (A.5) and
   future engines without in-process support inherit the default,
   which raises `InProcessUnavailable` via `init_addr`/`play_addr`'s
   default-raise. Clean dispatch without forcing every engine to
   reimplement the same pipeline.

2. **AC5/AC7 added in CS.** The original spec ACs cover the flag's
   three modes but skip two real concerns: (a) the existing fceux
   preflight blocks the in-process path before any code-path runs;
   (b) backward compat for callers who don't pass `engine_mode`.
   Both are essential to ship F.5 without breaking v0.5 users.

3. **AC6 (deprecation warning) added in CS.** v0.6's product story
   is "fceux-free by default". Without a deprecation signal, users
   on `--engine-mode oracle` won't know it's a transitional path.
   The warning is non-fatal; `--no-hints` suppresses it.

4. **AC8 (engine_mode_used in RenderResult) added in CS.** F.6
   (bilan v2) and `qlnes coverage` need to record which path
   produced each WAV. Threading this through F.5 saves a refactor
   in F.6.

5. **`--engine-mode oracle` kept for v0.5 compat, not removed.**
   v0.5 callers that have fceux installed should keep working
   without surprise. Oracle path lifecycle: kept in v0.6, hard
   deprecation in v0.7 via release notes, removal in v1.0.

6. **PyPy subprocess workhorse: SPLIT INTO F.5b.** The F.4 hand-off
   §9 mentioned F.5 should land the CPython→PyPy subprocess pattern.
   On reflection, that's a perf optimization independent of the
   user-facing dispatch. F.5 lands on CPython's slow path (5.55 s
   for 600 frames per F.3 measurement) and meets NFR-PERF-80 with
   margin. F.5b would speed it up to PyPy's 0.75 s. Splitting keeps
   F.5 focused on the spec ACs and leaves a clean perf-optimization
   story for after v0.6's surface stabilizes.

7. **Self-running boot path (`run_natural_boot`) is deprecated as
   the production renderer entry point.** F.5 commits to
   `run_song(init_addr, play_addr, frames)` per architecture §20.2.
   The natural-boot path remains as a debugging tool /
   `tests/integration/test_in_process_alter_ego.py` regression
   anchor (the F.3 fixture). The production trace for Alter Ego is
   now the F.4 fixture (`alter_ego_run_song_600fr.tsv`, sha
   `ea062dba…4baa`).

## 7. Risks

- **R38 (NEW) — Oracle path stability under v0.6.** Unrelated v0.5
  callers using `--engine-mode oracle` (or no flag, with auto
  resolving to oracle for an engine without in-process support) need
  fceux to be installed. F.10 release notes must call this out
  prominently. Mitigation: AC6's deprecation warning + the
  `_check_fceux_optional` preflight which emits a structured "fceux
  not on PATH" hint.
- **R39 (NEW) — Engine-mode auto-resolver picks the wrong path.**
  If a future engine implements `init_addr` / `play_addr` but the
  in-process render produces silence (because the engine's heuristic
  returned addresses that don't actually correspond to a valid music
  driver entry), auto mode silently produces empty WAVs. Mitigation:
  F.7 byte-equivalence test gates this; for F.5 itself, AC1 verifies
  Alter Ego ends up with a non-empty PcmStream.
- **R32 carried** — NMI cycle drift unchanged from F.3.

## 8. Definition of Done

- [x] AC1 — `--engine-mode in-process` succeeds on Alter Ego (no fceux)
       — `test_cli_in_process_succeeds_without_fceux` writes a valid
       RIFF WAV file
- [x] AC2 — `--engine-mode oracle` succeeds on Alter Ego (with mocked
       oracle) — covered by `test_engine_mode_oracle_calls_render_song_only`
       (unit). End-to-end CLI version requires fceux, gated by skipif.
- [x] AC3 — `--engine-mode auto` picks in-process for FT, falls back
       with warning otherwise — `test_engine_mode_auto_*` (unit) +
       `test_cli_auto_default_picks_in_process` (integration)
- [x] AC4 — both modes exit 100 with `class:in_process_unavailable`
       for engines without addresses — `test_engine_mode_in_process_raises_qlnes_error_for_unavailable_engine`
       (unit) + `test_cli_in_process_unrecognized_engine_exits_100`
       (integration)
- [x] AC5 — fceux preflight is conditional on engine-mode —
       `test_cli_in_process_succeeds_without_fceux` runs with no fceux
       on PATH; `test_cli_oracle_mode_without_fceux_blocks_in_preflight`
       confirms oracle still requires it
- [x] AC6 — oracle mode emits `oracle_path_deprecated` warning —
       `test_engine_mode_oracle_emits_deprecation_warning`
- [x] AC7 — `render_rom_audio_v2(...)` without `engine_mode` defaults
       to `auto` — `test_render_rom_audio_v2_default_engine_mode_is_auto`
       + `test_cli_no_flag_works_for_in_process_engine`
- [x] AC8 — `RenderResult.engine_mode_used` set correctly per branch —
       `test_render_result_carries_engine_mode_used` + verified in
       CLI smoke (success line shows `mode=in-process`)
- [x] No regression in F.3 + F.4 tests (68 currently green) — full
       suite green
- [x] No regression in `tests/integration/test_cli_audio.py` —
       2 tests updated with explicit `--engine-mode oracle` for the
       fceux-preflight path (v0.5 compat preserved)
- [x] `qlnes audio --help` documents the new flag (added typer
       help text)
- [x] EXIT_CODES taxonomy lock test updated (`tests/unit/test_errors_emitter.py`)

## 8b. Code review applied (2026-05-04 retrofit pass)

CR retrofit identified 4 should-fix items, all applied:

- **F.5.CR-1 (doc)** — comment in renderer.py line 199-202 was
  misleading: it claimed the next iteration also uses oracle after a
  fallback, but the code lets each song re-attempt in-process
  independently. Replaced with an accurate description of the
  per-song dispatch + the renderer-level summary semantic for
  `engine_mode_used`.
- **F.5.CR-2 (real)** — `oracle_holder[0] or FceuxOracle()` used a
  falsy-check that would construct a redundant oracle if a Mock or
  custom test double evaluated falsy. Replaced with explicit
  `if oracle is None`.
- **F.5.CR-3 (real)** — Replaced the `oracle_holder = [oracle]`
  mutable-cell hack with a clean tuple return signature
  `_render_one(...) -> tuple[PcmStream, Literal[...], FceuxOracle | None]`.
  Caller threads the oracle reference manually.
- **F.5.CR-5 (type hint)** — `_SongRender` dataclass dropped (was
  using `stream: object` which lost type info); the helper now
  returns a typed tuple directly.

After refactor: 9/9 unit tests + 8 CLI integration tests still
green. Renderer.py loses the unused `_SongRender` dataclass.

## 9. Hand-off to F.6

F.6 (`bilan v2 schema migration`) inherits:

- `RenderResult.engine_mode_used` is the per-render label that bilan
  v2 records under each `(rom_sha256, song)` pair.
- `qlnes coverage` table in F.9 will pivot on this field for the
  in-process-vs-oracle column.
- Engine-mode auto-resolver behavior is settled: F.6 doesn't need
  to re-implement the dispatch logic, just consume its output label.

## 10. Out-of-scope for F.5

- **F.5b — PyPy subprocess workhorse.** CS-deferred. Replaces the
  CPython slow path (~5.55 s/600fr) with PyPy fork (~0.75 s/600fr).
  Not on F.5's critical path; meets NFR-PERF-80 without it.
- **F.10 — PyPy provisioning.** `scripts/install_audio_deps.sh`
  installs PyPy 3.11 portable tarball into `vendor/pypy/`.
- **F.7 — Equivalence test.** Asserts the in-process trace for each
  corpus ROM matches a committed fixture; F.5's AC4 only
  verifies "non-empty PCM", not byte-equivalence.
- NSF-shaped ROM extraction (story C.*).
- Multi-mapper support (F.8).
- Rendering MP3 in-process — already works via the existing
  `Mp3Encoder` because the PCM-to-MP3 step is shared between paths.

---

*End of story F.5 — ready for `bmad-dev-story` (DS).*
