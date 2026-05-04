---
docType: epics-amendment
parent_epics: _bmad-output/planning-artifacts/epics-and-stories.md
parent_prd: _bmad-output/planning-artifacts/prd-no-fceux.md
parent_architecture: _bmad-output/planning-artifacts/architecture-v0.6.md
date: 2026-05-04
project_name: qlnes-no-fceux
user_name: Johan
mvp_target: v0.6.0 (FCEUX-free FT static walker)
---

# Epics & Stories — qlnes v0.6 (Amendment)

> **Relationship to v0.5 epics doc.** This amendment adds **Epic F** and
> 7 stories (F.1–F.7) on top of the v0.5 plan. Epics A–E are unchanged.
> v0.6 work begins after `v0.5.0` is tagged (end of v0.5 sprint 8).

---

## Epic F — FCEUX-free music extraction

**User value.** Marco runs `qlnes audio rom.nes --engine-mode static`
on a clean machine without FCEUX installed and gets sample-equivalent
WAV. Lin's Docker pipeline drops the FCEUX/SDL/xvfb stanza.

**FRs closed.** FR41 (FCEUX-free FT extraction), FR42 (byte-equivalence
to v0.5 oracle output), FR43 (FT mappers 0/1/4), FR44 (per-song
determinism), FR46 (`--engine-mode` flag), FR47 (fail fast on missing
walker), FR48 (oracle path preserved), FR49 (warn on auto fallback),
FR50–FR52 (`bilan.json` schema v2), FR53 (pip install without FCEUX),
FR55–FR57 (backward compat).

**Risks tracked.** R20 (static-vs-oracle divergence), R21 (RE harder
than estimated), R22 (v1→v2 schema migration).

---

### Story F.1 — Scaffold the static walker package + ABC

**User value.** Foundation only. Equivalent to v0.5's A.1 for v0.6 —
no end-user feature lands here, but every subsequent story builds on
this scaffold.

**FRs closed.** Partial F.* infrastructure; no FR finalized.

**NFRs touched.** NFR-LIFE-80 (≤500 LOC handler budget — established
by the ABC's surface area).

**Pre-conditions.** v0.5.0 tagged. `qlnes/audio/engine.py` (v0.5
SoundEngine ABC) exists.

**Embedded scaffolding.**

- `qlnes/audio/static/__init__.py` — re-exports `StaticWalker`,
  `ApuWriteEvent`.
- `qlnes/audio/static/apu_event.py` — `ApuWriteEvent` frozen dataclass.
- `qlnes/audio/static/walker.py` — `StaticWalker` ABC sub-protocol of
  `SoundEngine`, with abstract `emit_apu_writes` method.
- `qlnes/oracle/fceux.py::TraceEvent` — converted to a deprecated
  alias of `ApuWriteEvent` (one-line typedef + DeprecationWarning).
- Tests: `tests/unit/test_static_walker_abc.py` — ABC contract,
  registry visibility, `has_static_walker` flag default.

**Acceptance criteria.**

- AC1 — Importing `qlnes.audio.static` returns the new public API
  (`StaticWalker`, `ApuWriteEvent`).
- AC2 — A `class FakeWalker(StaticWalker)` that does not implement
  `emit_apu_writes` raises `TypeError` at instantiation (ABC enforcement).
- AC3 — A correctly-implemented `FakeWalker` registered via
  `@SoundEngineRegistry.register` shows up in
  `SoundEngineRegistry.list_registered()` AND has `has_static_walker is True`.
- AC4 — `qlnes.oracle.fceux.TraceEvent` still imports cleanly from its
  v0.5 location and is a `qlnes.audio.static.apu_event.ApuWriteEvent`
  alias (`TraceEvent is ApuWriteEvent`).

**Estimate.** **S** — 1 dev-day. Pure ABC + tests, no logic.

---

### Story F.2 — `--engine-mode {auto,static,oracle}` flag + bilan v2

**User value.** Marco can pick the pipeline. `auto` (default) prefers
static when available; `oracle` keeps v0.5 behavior; `static` is a
hard-fail mode for FCEUX-free environments.

**FRs closed.** FR46, FR47, FR48, FR49, FR50, FR57.

**NFRs touched.** None directly.

**Pre-conditions.** F.1.

**Embedded scaffolding.**

- `qlnes/cli.py audio` — adds `--engine-mode` option (Annotated typer
  pattern), parses to enum literal.
- `qlnes/audio/renderer.py::render_rom_audio_v2` — adds
  `engine_mode: Literal["auto","static","oracle"] = "auto"` parameter.
  Resolution branch (architecture step 20.3) selects the pipeline.
- `qlnes/io/errors.py` — new error class `static_walker_missing` (exit
  100, hint "Install fceux >=2.6.6, or wait for the static walker for
  this engine"). Warning class `static_walker_missing` (when `auto`
  falls back).
- `qlnes/audit/bilan.py` — `BilanStore.read` detects `schema_version`
  and dispatches v1 vs v2; new `BilanStore.write` always writes v2.
- v1→v2 in-place upgrade on `audit --refresh`.

**Acceptance criteria.**

- AC1 — `qlnes audio --help` shows `--engine-mode {auto,static,oracle}`
  with default `auto`.
- AC2 — `--engine-mode oracle` on an FT ROM works exactly like v0.5
  (same WAV bytes, same exit code, same JSON shape on errors).
- AC3 — `--engine-mode static` on a ROM with no static walker exits
  100 with `class:static_walker_missing` JSON, hint pointing at the
  oracle fallback flag.
- AC4 — `--engine-mode auto` on a ROM with no static walker BUT FCEUX
  installed: emits `qlnes: warning: static_walker_missing` to stderr,
  proceeds via oracle. Exit 0 if oracle succeeds.
- AC5 — `--engine-mode auto` on a ROM with no static walker AND no
  FCEUX: exits 100 with `class:static_walker_missing` (same as
  `--engine-mode static`).
- AC6 — `bilan.json` written by v0.6 has `schema_version: "2"` and
  the `tier-1-static` / `tier-1-oracle` per-engine sub-keys.
- AC7 — A v0.5 reader (qlnes 0.5.x) reading a v0.6 bilan logs
  `bilan_schema_version` warning, renders engines as "unknown" but
  doesn't crash.

**Estimate.** **M** — 2-3 dev-days.

---

### Story F.3 — FamiTracker static walker (mapper 0)

**User value.** The load-bearing story of v0.6. End-to-end
FCEUX-free render of an FT ROM on the simplest mapper.

**FRs closed.** FR41 (full), FR42 (full), FR43 (mapper-0 subset),
FR44, FR53.

**NFRs touched.** NFR-PERF-80, NFR-PERF-81, NFR-PORT-81, NFR-DEP-80,
NFR-REL-81.

**Pre-conditions.** F.1, F.2. **Pre-sprint RE spike (24-48 h)
mandatory** — see R21 mitigation.

**Embedded scaffolding.**

- `qlnes/audio/static/engines/__init__.py`.
- `qlnes/audio/static/engines/famitracker_static.py` — public
  `FamiTrackerStaticWalker` class, subclasses
  `FamiTrackerEngine` (v0.5 detection logic) AND `StaticWalker`.
- `qlnes/audio/static/engines/famitracker_format.py` — pattern
  bytecode parser (Cxx volume, Bxx loop, Dxx pattern jump, …, full
  FT effect column).
- `qlnes/audio/static/engines/famitracker_state.py` — per-channel
  state machine (envelope, vibrato, arpeggio, instrument).
- `qlnes/audio/static/engines/famitracker_emit.py` — state →
  ApuWriteEvent emitter (per-frame ordered registers).
- `tests/invariants/test_static_oracle_equivalence.py` — parametrized
  on `corpus/manifest.toml` mapper-0 FT subset; asserts
  `static_apu_writes == oracle_apu_writes` byte-for-byte.

**Acceptance criteria.**

- AC1 — `qlnes audio <ft-mapper-0-rom> --engine-mode static --output
  tracks/` succeeds on a host with no FCEUX installed.
- AC2 — For each ROM in the FT-mapper-0 corpus subset, the static
  walker's `(cycle, register, value)` emission is byte-for-byte
  identical to the FCEUX trace (architecture step 20.4 contract).
- AC3 — The PCM output (after APU emulator + WAV writer) is byte-
  identical between `--engine-mode static` and `--engine-mode oracle`
  for the same ROM.
- AC4 — Render time on the canonical hardware: ≤30 s for a
  3-minute song (NFR-PERF-80).
- AC5 — No subprocess spawned during the render. Verified by mocking
  `subprocess.run` to assert it's not called.

**Estimate.** **L** — 1 dev-week. Bytecode RE is the dominant cost.

**Risk callout (R21).** If the RE spike (pre-sprint) shows the FT
format takes more than 4 dev-days to model end-to-end, F.3 splits:
- F.3a — pattern parser only (mapper-0 NROM-128 subset, single song).
- F.3b — instrument/envelope state machine + per-frame emit.
- F.3c — multi-pattern songs + master loop.

---

### Story F.4 — Extend FT static walker to mapper 1 (MMC1)

**User value.** FT ROMs on MMC1 (most NES homebrew published 2010+
falls in this category) work without FCEUX.

**FRs closed.** Partial FR43 (mapper 1 added).

**NFRs touched.** NFR-REL-81 carries forward (byte-eq invariant).

**Pre-conditions.** F.3 done. MMC1 banking model needs the existing
`Rom.banks()` iterator.

**Embedded scaffolding.**

- `famitracker_static.py` — extends song-table lookup to span MMC1
  bank boundaries (FT pattern data may live in different PRG banks
  than the player code).
- Corpus expansion: ≥3 FT-driven MMC1 ROMs added to manifest.

**Acceptance criteria.**

- AC1 — `qlnes audio <ft-mmc1-rom> --engine-mode static` produces
  byte-identical PCM to the oracle path.
- AC2 — `bilan.json` shows `tier-1-static: pass` for the FT engine
  on mapper 1 after `audit`.

**Estimate.** **M** — 2-3 dev-days. Banking is the new wrinkle; the
core walker from F.3 is reused.

---

### Story F.5 — Extend FT static walker to mapper 4 (MMC3)

**User value.** FT ROMs on MMC3 (Battle Kid, certain NES Maker games)
work without FCEUX.

**FRs closed.** Closes FR43.

**Pre-conditions.** F.4 done.

**Embedded scaffolding.**

- `famitracker_static.py` — MMC3-specific banking. MMC3 also has IRQ
  scanline counter that the FT player rarely uses but might affect
  per-frame timing on edge cases.

**Acceptance criteria.**

- AC1 — `qlnes audio <ft-mmc3-rom> --engine-mode static` produces
  byte-identical PCM to the oracle path on the FT-MMC3 corpus subset.
- AC2 — Static-vs-oracle `tier-1-static` rate hits 100 % on FT for
  mappers 0, 1, 4.

**Estimate.** **M** — 2-3 dev-days.

---

### Story F.6 — `coverage` v2 rendering + CI matrix expansion

**User value.** Marco/Lin/Sara see at a glance which engines are
static-covered vs oracle-only. CI catches Windows / macOS regressions.

**FRs closed.** FR51, FR52.

**NFRs touched.** NFR-PORT-81 (CI matrix gains macOS-13 + windows-2022).

**Pre-conditions.** F.2 (schema v2) + F.3 (so static-covered engines
exist in bilan).

**Embedded scaffolding.**

- `qlnes/coverage/render.py` — table format with `static_engines` /
  `oracle_engines` columns.
- `.github/workflows/test.yml` — matrix expansion: ubuntu-22.04,
  macos-13, windows-2022. The Windows job runs only the
  static-walker tests (no FCEUX install).
- New job in `.github/workflows/test.yml`: "fceux-free" — runs on
  Ubuntu but with `apt remove fceux` first. Asserts the static path
  works without FCEUX.

**Acceptance criteria.**

- AC1 — `qlnes coverage` (v2 table) shows the static/oracle split.
- AC2 — `qlnes coverage --format json` emits the v2 schema.
- AC3 — CI Windows job is green on F.3+F.4+F.5 stories (FT mapper
  0/1/4 static walker works on Windows).
- AC4 — CI fceux-free job: `apt remove fceux && pytest tests/unit
  tests/integration -k 'not oracle'` is green.

**Estimate.** **M** — 2-3 dev-days.

---

### Story F.7 — Documentation + changelog migration note

**User value.** Users upgrading from v0.5 read the changelog and know
what changed. New users read the README and pick the right install path.

**FRs closed.** None directly; closes the v0.6 epic by polishing.

**Pre-conditions.** F.6 done.

**Embedded scaffolding.**

- `README.md` — section "Install" with two paths: "minimal" (no
  FCEUX, static-only engines) and "full" (with FCEUX for oracle
  fallback).
- `CHANGELOG.md` — v0.6.0 entry with bilan v1→v2 migration note +
  `--engine-mode` documentation + per-engine static-coverage table.
- `_bmad-output/planning-artifacts/architecture-v0.6.md` — sign-off
  marker (this amendment becomes the v0.6 architecture's source of
  truth alongside the v0.5 doc).

**Acceptance criteria.**

- AC1 — README's "Install" section explicitly mentions FCEUX is
  optional in v0.6.
- AC2 — CHANGELOG documents the bilan schema bump + the new
  `--engine-mode` flag.
- AC3 — `qlnes coverage` output is showcased in the README with a
  sample table demonstrating static/oracle columns.

**Estimate.** **S** — 1 dev-day.

---

## Sprint Plan Update

Insert *after* sprint 8 (v0.5.0 tag).

| Sprint | Goal | Stories | Estimate (d) |
|---|---|---|---|
| 9 | Foundation + RE spike | F.1, F.2 + FT RE spike | 5 + 1.5 (spike) |
| 10 | FT mapper 0 walker | F.3 (the L story) | 5 |
| 11 | FT mapper 1 + 4 | F.4, F.5 | 6 |
| 12 | Polish + docs + tag | F.6, F.7 + v0.6.0 release | 4 |
| **Total** | | **7 stories** | **~22 dev-days = ~4 weeks** |

Sprint 9 includes a dedicated 12-hour RE spike on the FT player driver
(R21 mitigation). The spike's deliverable is a written technical note
that decides F.3's exact bytecode-parser scope before sprint 10 starts.

---

## FR Coverage Matrix (v0.6)

The v0.6 PRD has 17 FRs (FR41-FR57). Mapping:

| FR | Story | Notes |
|---|---|---|
| FR41 | F.1 + F.3 | F.1 lands the framework; F.3 is the first end-to-end |
| FR42 | F.3 | Byte-equivalence corpus test |
| FR43 | F.3 (m0), F.4 (m1), F.5 (m4) | Mapper-by-mapper coverage |
| FR44 | F.3 | Determinism test |
| FR45 | (Growth) | Out of v0.6 MVP scope |
| FR46 | F.2 | `--engine-mode` flag |
| FR47 | F.2 | `static_walker_missing` exit-100 path |
| FR48 | F.2 | Backward-compat oracle path |
| FR49 | F.2 | Auto-fallback warning |
| FR50 | F.2 | bilan v2 schema |
| FR51 | F.6 | Coverage v2 rendering |
| FR52 | F.6 | Release gate |
| FR53 | F.3 | pip install without FCEUX |
| FR54 | (Vision) | Out of v0.6 MVP scope |
| FR55 | F.2 + F.3 | Backward-compat (auto mode) |
| FR56 | F.2 | Backward-compat (oracle mode) |
| FR57 | F.2 | bilan v1 reader graceful degradation |

13 FRs explicitly mapped to v0.6 MVP stories. 2 FRs deferred (FR45
Growth, FR54 Vision). FR coverage = 13/13 in v0.6 MVP scope.

---

## Sign-off

This amendment is **READY** to feed into sprint planning when v0.5.0
is tagged. Sprint 9 starts the v0.6 work; F.1+F.2+RE-spike are the
sprint-9 entry stories.

The v0.5 sprint plan (sprints 1-8) is unchanged. v0.6 sprints (9-12)
are appended.

**Author:** Claude (Opus 4.7), drafting under
`bmad-create-epics-and-stories`.
**Date:** 2026-05-04.
