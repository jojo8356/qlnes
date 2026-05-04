---
docType: epics-amendment
parent_epics: _bmad-output/planning-artifacts/epics-and-stories.md
parent_prd: _bmad-output/planning-artifacts/prd-no-fceux.md
parent_architecture: _bmad-output/planning-artifacts/architecture-v0.6.md
date: 2026-05-04
status: draft v2 (post-pivot)
project_name: qlnes-no-fceux
user_name: Johan
mvp_target: v0.6.0 (in-process CPU emulator replaces FCEUX subprocess)
amendmentLog:
  - "2026-05-04: pivot from per-engine static walker to in-process CPU emulator. Story list rewritten."
---

# Epics & Stories — qlnes v0.6 (Amendment, revised)

> **Pivot 2026-05-04.** Stories F.1-F.7 from the previous draft (static
> walker per engine) are superseded by F.1-F.10 below (in-process CPU
> emulator). See PRD §0 + architecture-v0.6.md amendmentLog.

---

## Epic F — Replace FCEUX subprocess by in-process CPU emulator

**User value.** Marco runs `qlnes audio rom.nes` on a clean machine
without FCEUX installed and gets sample-equivalent WAV. Lin's pipeline
drops 80 MB of FCEUX/SDL/xvfb deps. Both Journeys 1 and 2 complete
without subprocess overhead, ~16x less RAM.

**FRs closed.** FR41-FR53 (PRD v0.6).

**Risks tracked.** R30 (py65 too slow), R31 (PPU state in init), R32
(NMI timing), R33 (mapper bank-switching in py65), R34 (cynes lacks
APU-write hook).

---

## Stories — ordered, ready for sprint planning

### F.1 — Salvage v0.6 scaffolding (already on master)

**Status.** ✓ Done (commit 5cf2c36).

**What's kept.** `qlnes/audio/static/apu_event.py::ApuWriteEvent`
remains the canonical interchange type — used by both the
in-process pipeline (this PRD) and future per-engine static walkers
if anyone ever pursues them.

**What's deprecated.** `qlnes/audio/static/walker.py::StaticWalker`
ABC stays in tree but is not subclassed by any v0.6 story. A docstring
note marks it as deprecated/exploratory. Removing it is a future story
if it gathers no users.

**Acceptance criteria.** None (already done). Move on to F.2.

---

### F.2 — Performance spike: py65 vs cynes

**User value.** Decision artifact for which CPU emulator backs the
in-process pipeline. NFR-PERF-80 enforces ≤ 60 s for a 3-min song;
spike measures whether py65 makes that budget.

**Estimate.** **S** (1 dev-day time-boxed).

**Pre-conditions.** F.1.

**Approach.**

1. Pick one v0.5 corpus FT ROM (Alter Ego — already in `corpus/roms/`).
2. Build a minimal harness that runs the music driver via py65:
   - load PRG into ObservableMemory
   - subscribe_to_write on $4000-$4017
   - JSR init_addr (assumed = $8000 for the ROM under test for the spike)
   - manually trigger NMI every 29780 cycles, run 600 frames (10 s)
   - measure wall-clock, count APU writes, sanity-check first
     ~50 events match the FCEUX trace
3. If py65 → ≤ 60 s for the 10 s sample's-worth: ✓ commit to py65.
4. Otherwise: repeat with cynes if it's hookable (R34); if cynes
   doesn't work either, decision document in `_bmad-output/decisions/`
   recommending a fallback path.

**Acceptance criteria.**

- AC1 — Decision artifact `_bmad-output/decisions/v06-cpu-backend.md`
  written, recommending py65 OR cynes OR a custom mini-CPU.
- AC2 — Spike code lives in `_bmad-output/spikes/v06-cpu-perf/` (not
  committed to qlnes/, just for posterity).
- AC3 — Trace-comparison sanity: at least the first 10 APU writes
  emitted by the spike match the FCEUX trace's first 10 writes (cycle
  may differ; register and value must match).

---

### F.3 — InProcessRunner module (NROM-only, single mapper)

**User value.** Foundation. Equivalent to v0.5's A.1 for the new
pipeline. End-to-end FCEUX-free render of one mapper-0 FT ROM.

**Estimate.** **L** (1 dev-week).

**Pre-conditions.** F.2 done; CPU backend chosen.

**Embedded scaffolding.**

- `qlnes/audio/in_process/__init__.py` — re-exports.
- `qlnes/audio/in_process/runner.py` — `InProcessRunner` (architecture
  step 20.2).
- `qlnes/audio/in_process/memory.py` — observable NROM memory map
  (PRG mirroring + APU observer + PPU stub).
- `qlnes/audio/in_process/nmi.py` — NMI trigger helper (architecture
  step 20.6).
- Tests in `tests/unit/test_in_process_runner.py` and
  `tests/integration/test_in_process_alter_ego.py`.

**Acceptance criteria.**

- AC1 — `InProcessRunner(rom).run_song(init_addr, play_addr,
  frames=600)` yields ApuWriteEvent iterator on Alter Ego (the corpus
  fixture).
- AC2 — Resulting PCM (after qlnes APU emulator) is byte-identical
  to the FCEUX-driven render of Alter Ego at 600 frames.
- AC3 — No subprocess spawned: `subprocess.run` mocked to assert
  `call_count == 0` during the entire render.
- AC4 — Wall-clock ≤ 60 s for 600-frame render on canonical hardware
  (NFR-PERF-80).
- AC5 — Peak RSS ≤ 10 MB (NFR-MEM-80).
- AC6 — Two consecutive runs produce byte-identical output
  (NFR-REL-1).

---

### F.4 — SoundEngine init/play address protocol

**User value.** Engine handlers expose the addresses the in-process
runner needs. FT handler returns the addresses for Alter Ego (and any
other FT-driven ROM the existing detection covers).

**Estimate.** **M** (2-3 dev-days).

**Pre-conditions.** F.3.

**Embedded scaffolding.**

- `qlnes/audio/engine.py::SoundEngine` ABC gains `init_addr(rom,
  song) -> int` and `play_addr(rom, song) -> int` methods. Default:
  `raise NotImplementedError("engine has no in-process support")`.
- `qlnes/audio/engines/famitracker.py` implements both. For Alter
  Ego specifically, locate the FamiTone init/play vectors via
  signature scan or known-offset heuristic.
- `tests/unit/test_engine_init_play.py`.

**Acceptance criteria.**

- AC1 — `FamiTrackerEngine.init_addr(rom, song)` returns a valid
  CPU address ($8000-$FFFF range) for Alter Ego.
- AC2 — `play_addr(rom, song)` similarly for Alter Ego.
- AC3 — Default `SoundEngine.init_addr` raises NotImplementedError
  with `class:in_process_unavailable` JSON-friendly extra.

---

### F.5 — `--engine-mode` CLI flag + pipeline dispatch

**User value.** User picks the pipeline. `auto` default does the
right thing.

**Estimate.** **M** (2-3 dev-days).

**Pre-conditions.** F.3, F.4.

**Embedded scaffolding.**

- `qlnes/cli.py audio` — adds `--engine-mode {auto,in-process,oracle}`.
- `qlnes/audio/renderer.py` — `engine_mode` parameter, resolution
  branch (architecture step 20.4).
- `qlnes/io/errors.py` — new error class `in_process_unavailable`
  (exit 100), warning class `in_process_low_confidence`.
- Tests in `tests/integration/test_cli_engine_mode.py`.

**Acceptance criteria.**

- AC1 — `--engine-mode in-process` on FT-Alter Ego succeeds.
- AC2 — `--engine-mode oracle` keeps v0.5 behavior on Alter Ego.
- AC3 — `--engine-mode auto` (default) picks in-process when
  available, falls back to oracle with warning when not.
- AC4 — Both `auto` and `in-process` exit 100 with
  `class:in_process_unavailable` for engines without
  `init_addr`/`play_addr`.

---

### F.6 — bilan v2 schema migration

**User value.** Coverage matrix shows in-process vs oracle separately
per (mapper, engine) pair.

**Estimate.** **S** (1 dev-day).

**Pre-conditions.** F.3 (so we have data to populate v2 fields).

**Embedded scaffolding.**

- `qlnes/audit/bilan.py` — schema_version dispatch (v1 reader vs v2
  reader).
- v1→v2 in-place upgrade on `audit --refresh`.
- v0.5 readers reading v2 log warning, render unknown engine status.

**Acceptance criteria.**

- AC1 — `qlnes audit` produces a v2 bilan with both
  `tier-1-in-process` and `tier-1-oracle` per-engine sub-keys.
- AC2 — A v0.5 (qlnes 0.5.x) reader reading a v0.6 bilan logs
  `bilan_schema_version` warning + falls through to "unknown" status
  per engine.

---

### F.7 — In-process oracle equivalence test

**User value.** Per-release gate that the in-process path produces
byte-identical output to the FCEUX oracle on the v0.5 corpus.

**Estimate.** **S** (1 dev-day).

**Pre-conditions.** F.3, F.4, F.5.

**Embedded scaffolding.**

- `tests/invariants/test_in_process_oracle_equivalence.py` —
  parametrized on `corpus/manifest.toml` FT subset. Each test:
  render via `--engine-mode in-process` AND `--engine-mode oracle`,
  assert PCM bytes equal.

**Acceptance criteria.**

- AC1 — Test passes for Alter Ego (FT mapper-0).
- AC2 — Test infrastructure parametrizes correctly: adding a new
  ROM to the manifest auto-creates a new test case.

---

### F.8 — Multi-mapper support (MMC1, MMC3)

**User value.** Marco's MMC1/MMC3 homebrew ROMs work in-process,
not just oracle. FT covers more games.

**Estimate.** **L** (1 dev-week — likely requires switching to
cynes or hand-rolling mapper logic).

**Pre-conditions.** F.7.

**Risks.** R33 — bank-switching not supported in py65 natively.
Story may force the cynes switch; if cynes doesn't expose APU
writes (R34), this story splits or extends.

**Embedded scaffolding.**

- `qlnes/audio/in_process/mappers/{mmc1,mmc3}.py` — bank-switch
  observers if py65; or cynes wrapper if we switch.
- Corpus expansion: ≥3 FT-driven MMC1 ROMs, ≥3 FT-driven MMC3 ROMs.

**Acceptance criteria.**

- AC1 — `qlnes audio <ft-mmc1-rom> --engine-mode in-process` produces
  byte-identical PCM to oracle path.
- AC2 — Same for MMC3.

---

### F.9 — `coverage` v2 rendering + CI matrix expansion

**User value.** Marco/Lin/Sara see the static/oracle split. CI
catches Windows + macOS regressions. FCEUX-free CI job verifies the
hard-fail path.

**Estimate.** **M** (2-3 dev-days).

**Pre-conditions.** F.6 + F.7.

**Embedded scaffolding.**

- `qlnes/coverage/render.py` — v2 table format with in-process vs
  oracle columns.
- `.github/workflows/test.yml` — matrix gain (Linux + macOS-13 +
  windows-2022). New job `fceux-free` (Linux + `apt remove fceux`).

**Acceptance criteria.**

- AC1 — `qlnes coverage` v2 table shows the split.
- AC2 — `qlnes coverage --format json` emits v2 schema.
- AC3 — CI Windows job green on F.3+F.4+F.5 stories.
- AC4 — CI fceux-free job green: in-process path works without fceux.

---

### F.10 — Documentation + changelog + tag v0.6.0

**User value.** Users upgrading read the changelog. New users read
the README and pick the install path that fits.

**Estimate.** **S** (1 dev-day).

**Pre-conditions.** F.9.

**Embedded scaffolding.**

- `README.md` — section "Install" with two paths: minimal (no fceux)
  and full (with fceux fallback).
- `CHANGELOG.md` — v0.6.0 entry: `--engine-mode` flag, bilan v1→v2,
  in-process pipeline, FCEUX dependency now optional.
- Tag `v0.6.0`.

**Acceptance criteria.**

- AC1 — README documents install paths and the `--engine-mode` flag.
- AC2 — CHANGELOG documents bilan migration + new flag.
- AC3 — `git tag v0.6.0` pushed.

---

## Sprint plan update

(Inserted after sprint 8 / `v0.5.0` tag.)

| Sprint | Goal | Stories | Estimate (d) |
|---|---|---|---|
| 9 | Spike + InProcessRunner foundation | F.1 ✓ + F.2 + F.3 | 1 + 5 = 6 |
| 10 | Engine integration + dispatch | F.4 + F.5 + F.6 + F.7 | 7 |
| 11 | Multi-mapper support | F.8 | 5 |
| 12 | Polish + tag | F.9 + F.10 | 4 |
| **Total** | | **10 stories** | **~22 dev-days = ~4-5 weeks solo** |

Sprint 9 has the perf spike (F.2) before F.3 commits; if py65 is too
slow, the spike's decision artifact reorients F.3 onto cynes or an
alternative.

---

## FR coverage matrix (v0.6)

| FR | Story |
|---|---|
| FR41 (FCEUX-free) | F.3 + F.4 |
| FR42 (byte-equivalent) | F.7 |
| FR43 (CPU backend choice) | F.2 (spike), F.3 (commits) |
| FR44 (determinism) | F.3 AC6 |
| FR45 (Growth multi-mapper) | F.8 |
| FR46 (--engine-mode flag) | F.5 |
| FR47 (in-process hard fail) | F.5 |
| FR48 (oracle compat) | F.5 |
| FR49 (auto fallback warning) | F.5 |
| FR50 (bilan v2 schema) | F.6 |
| FR51 (coverage v2 table) | F.9 |
| FR52 (release gate) | F.7 |
| FR53 (pip install no-fceux) | F.3 + F.5 |

13 FRs explicitly mapped. 2 FRs deferred (Vision-tier, FR54-equiv).

---

## Sign-off

This amendment is **READY** for sprint 9 to begin once `v0.5.0` is
tagged.

The v0.5 sprint plan (sprints 1-8) is unchanged. v0.6 sprints (9-12)
are appended. Story F.1 is already done (commit 5cf2c36); sprint 9
starts at F.2.

**Author:** Claude (Opus 4.7), under `bmad-create-epics-and-stories`.
**Date:** 2026-05-04 (revised).
