---
prdType: secondary
parent_prd: _bmad-output/planning-artifacts/prd.md
projectType: cli_tool+developer_tool
project_name: qlnes-no-fceux
user_name: Johan
date: 2026-05-04
status: draft
amendmentLog: []
inputDocuments:
  - _bmad-output/planning-artifacts/prd.md
  - _bmad-output/planning-artifacts/architecture.md
  - _bmad-output/planning-artifacts/ux-design.md
  - _bmad-output/planning-artifacts/epics-and-stories.md
relatedRisks: [R1, R2, R3, R10]
---

# qlnes — Product Requirements Document: No-FCEUX Music Extraction

**Author:** Johan Polsinelli
**Date:** 2026-05-04
**Status:** Draft v1 — proposed evolution of the music workstream MVP.

> **Relationship to the primary PRD.** This document does not replace the
> v0.5 music-MVP PRD. It proposes a *successor* path that removes the
> FCEUX subprocess dependency from qlnes's audio extraction. The MVP
> ships first; this PRD's work begins after `v0.5.0` is tagged. The two
> PRDs share the same product vision (clean NES audio artifacts, strict
> equivalence guarantees) but differ on the toolchain.

---

## Executive Summary

qlnes today extracts NES audio via a three-step pipeline: FCEUX subprocess
runs the ROM under emulation, a Lua trace records APU register writes per
CPU cycle, and qlnes's own APU emulator replays the trace to produce
sample-equivalent PCM. The FCEUX dependency is the load-bearing piece of
the architecture (locked decision Q1, ADR-03) and is the source of three
of the project's top risks (R1/R2/R3 from the architecture risk register):
upstream FCEUX changes that break the trace API, version-pinning friction
for sample-equivalence claims, and per-host environmental brittleness
(SDL audio drivers, headless servers, GUI window systems).

**This PRD proposes removing FCEUX entirely.** Music extraction becomes a
pure static-analysis pipeline:

1. **Static song-table walking.** Per-engine handlers parse the ROM's
   sound bytecode directly — no CPU emulation. The FT pointer table,
   Capcom note-event table, KGen pattern table, etc. are decoded by
   reading the PRG bytes.
2. **Algorithmic APU register-write generation.** Each engine handler
   *emits* the sequence of APU register writes that the engine *would*
   make at runtime, given its bytecode + the song state machine, without
   running the CPU.
3. **PCM rendering via the existing qlnes APU emulator.** Unchanged
   from the current architecture (architecture step 8 — own APU
   implementation). The APU emulator continues to be the canonical
   PCM-rendering engine; what feeds it changes.

The output is byte-identical to the current FCEUX-driven path on covered
engines, with a substantially smaller dependency footprint (no FCEUX
binary, no Lua, no subprocess), faster runtime (no fork+wait per render),
and a stricter determinism story (one less subprocess in the equivalence
chain).

The cost is **engine-specific reverse-engineering work** at a higher
fidelity than the current "static trace ⇒ replay" path: the static
analyzer must understand each engine's bytecode dialect well enough to
*emit* the same APU writes the engine *would* perform under a real CPU.
This work is gated by per-engine equivalence on the existing test corpus.

The user-visible result: `qlnes audio rom.nes` works on machines without
FCEUX installed, produces byte-identical output, and runs ~10× faster.

---

## Project Classification

- **Project Type:** CLI tool. Same surface as the current music-MVP
  (`python -m qlnes audio`, `verify`, `audit`, `coverage`). No new public
  command introduced.
- **Project Lineage:** Successor to the v0.5 music-MVP (this repo's
  current PRD). Builds on the current architecture's APU emulator
  (architecture step 8), engine plugin registry (step 9), and bilan
  schema (step 12). Replaces the FCEUX oracle (step 10).
- **Distribution model:** Same — solo developer, MIT licensed, hashes-
  only test corpus.
- **External-dependency strategy:** **Zero hard external system binaries
  in the audio path.** `cynes` remains feature-gated for static dataflow
  discovery (not audio); `lameenc` remains a Python wheel; FCEUX is
  removed entirely from the audio extraction code path. (FCEUX may
  still be referenced as a *historical* equivalence anchor — see FR47.)

---

## Success Criteria

| Goal | Definition of done | Verification |
|---|---|---|
| **Audio works on FCEUX-free hosts** | `qlnes audio rom.nes --format wav` succeeds on a clean install of qlnes (`pip install qlnes`) without FCEUX present on the host. Pre-flight does not check for FCEUX in this path. | Integration test in a Docker image with no FCEUX installed. |
| **Byte-identical to v0.5 output** | For every ROM in the v0.5 test corpus that had a tier-1 sample-equivalent FCEUX-anchored result, the no-FCEUX path produces byte-identical PCM. SHA-256 match. | `tests/invariants/test_pcm_equivalence_no_fceux.py` parametrized on the `[[reference]]` table from `corpus/manifest.toml`. |
| **Faster** | A 3-minute song renders ≥ 5× faster than the FCEUX-driven path. | `tests/integration/test_audio_perf_no_fceux.py` benchmark. |
| **Deterministic** | NFR-REL-1 invariants from the v0.5 PRD remain valid. No floats added. No new sources of non-determinism. | All existing determinism tests pass; the no-FCEUX path adds no new failures. |
| **Per-engine coverage growth** | Engines covered by the no-FCEUX path: FamiTracker (MVP), Capcom (MVP+1), Konami KGen (Growth), Sunsoft 5B (Growth), Namco 163 (Growth). At least 3 engines tier-1 by v0.6. | `bilan.json` per-engine sub-map shows `tier-1-static` for ≥ 3 engines. |

**Reference equivalence.** For ROMs whose engine has a no-FCEUX handler,
the output is sample-equivalent to the old FCEUX-driven output (and
therefore, transitively, to FCEUX itself). For ROMs whose engine *lacks*
a no-FCEUX handler, the old FCEUX-driven path remains available behind
a flag (FR48). Coverage extends one engine at a time.

---

## Product Scope

### In scope (this PRD)

- A new pipeline that static-analyzes a ROM's audio engine bytecode
  and emits the APU register-write sequence the engine would produce
  at runtime, per song.
- Per-engine "static walker" handlers, one per supported engine,
  paralleling the existing `SoundEngine` ABC but with a different
  contract: `emit_apu_writes(rom, song) → list[ApuWriteEvent]` instead
  of `render_song(rom, song, oracle) → PcmStream`.
- A new `--engine-mode static|oracle|auto` CLI flag that selects the
  pipeline (default: `auto` — prefer static when available, fall back
  to oracle when not).
- Updates to `bilan.json` schema (v2) to add `tier-1-static` /
  `tier-1-oracle` distinctions per engine.
- The APU emulator (qlnes/apu/) is **unchanged** — it remains the only
  place PCM is generated.

### Out of scope (this PRD)

- A new APU implementation. The existing one is the contract.
- MIDI / MML / score-format export — different product (Vision-tier).
- Removing the FCEUX oracle code from the codebase. It stays for the
  `--engine-mode oracle` path and for new-engine bring-up (the static
  walker for a new engine is validated against the oracle's output
  during development).
- Expansion-audio chip support beyond what the APU emulator already
  handles (MMC5/VRC6/VRC7/N163/FME-7 stay in the same status as the
  primary PRD's Growth tier).
- Per-track metadata enrichment beyond what the song-pointer table
  exposes today (track titles, BPM detection, etc.).

### Anti-goals (will NOT do)

- "Best-effort" emission for ROMs whose engine isn't recognized. There
  is no `unverified` tier-2 in the static path. Either the engine is
  known and tier-1, or the user falls back to `--engine-mode oracle`
  for the primary PRD's tier-2 generic-fallback handler.
- Approximations that trade fidelity for simplicity. The static path
  must produce identical APU writes; if it can't, the engine is not
  yet covered.
- A static walker that ships behind `[Vision]` until proven on a real
  ROM. Each engine handler ships only when it passes byte-equivalence
  on its corpus subset (mirrors the v0.5 release gate).

---

## User Journeys

### Journey 1 — Marco, the porter (offline)

**Persona.** Marco from PRD primary Journey 1 — same character. He's
porting another classic to PC, this time on a flight with no internet
and no pre-installed FCEUX.

**Opening scene.** Marco's flight is six hours. He wants to use the
time to extract the OST of the next ROM in his backlog. His laptop
has Python and a venv with qlnes, but FCEUX isn't installed and he
can't install it without internet (apt, brew, etc.).

**Rising action.** Marco runs:

```
python -m qlnes audio rom.nes --format wav --output tracks/
```

qlnes auto-detects that the ROM uses FamiTracker, picks the static
walker (no `--engine-mode` needed — `auto` is default), parses the
song-pointer table, emits APU register-writes for each song, runs them
through the in-process APU emulator, writes per-track WAVs.

**Climax.** No subprocess spawns. No "fceux not found" error. Renders
finish in ~30 seconds for 23 tracks (vs ~5 minutes with FCEUX).

**Resolution.** Marco's six-hour flight produces three OSTs.

**Capabilities revealed:**
- No FCEUX dependency on the host.
- Faster renders (no subprocess overhead, no PCM capture round-trip).
- Same deterministic per-track filenames, same WAV format.

### Journey 2 — Lin, the pipeline integrator (subprocess-free)

**Persona.** Lin from PRD primary Journey 3 — same character. Her
HD-2D remastering pipeline is now containerized for cloud workers.

**Opening scene.** Lin's pipeline runs in a Docker image. Adding
FCEUX bloats the image by ~80 MB plus its SDL/X11 deps; FCEUX requires
a virtual framebuffer (xvfb) to run headless. Each per-ROM job spawns a
subprocess that takes ~3 seconds to start — a non-trivial fixed cost
across thousands of ROMs.

**Rising action.** Lin upgrades to qlnes v0.6. Her Dockerfile drops the
FCEUX/SDL/xvfb stanza:

```diff
- RUN apt install -y fceux xvfb libsdl2-2.0-0
- ENTRYPOINT xvfb-run python -m my_pipeline
+ ENTRYPOINT python -m my_pipeline
```

**Climax.** Image shrinks by 80 MB. Per-job wall-clock drops from
~8 s (3 s startup + 5 s render) to ~1 s (in-process render). Pipeline
throughput on her 4-vCPU worker triples.

**Resolution.** Lin contributes back a corpus of MMC3 ROMs (now that
no FCEUX install is needed on her workers) and a fixture for one bug
she hits.

**Capabilities revealed:**
- Zero subprocess in the audio render path.
- Smaller distribution footprint.
- Higher cloud-pipeline throughput.

### Journey 3 — Marco, edge case: engine not yet ported to static

**Persona.** Marco again. His new ROM uses a Konami KGen engine that
is not yet in the static-walker registry (FT and Capcom are; KGen is
Growth-tier here too).

**Opening scene.** He runs the usual command. The engine detects as
KGen. The static walker registry has no KGen handler yet.

**Rising action.** qlnes prints:

```
qlnes: warning: engine KGen has no static walker yet; falling back to FCEUX oracle.
hint: Install fceux >= 2.6.6, or wait for the KGen static walker to ship.
{"class":"static_walker_missing","engine":"konami_kgen","fallback":"oracle"}
```

If FCEUX is installed: render proceeds via the oracle path (same as
v0.5). If FCEUX is not installed: exit 100 (`unsupported_mapper`) with
the same hint pointing at the static-walker roadmap.

**Climax.** Marco files a coverage-extension issue with the ROM's hash.

**Resolution.** The next qlnes release ships the KGen static walker
once it passes equivalence on a corpus subset.

**Capabilities revealed:**
- Per-engine coverage matrix exposed (the same `qlnes coverage`
  surface from v0.5, with new `tier-1-static` / `tier-1-oracle`
  buckets).
- Graceful degradation when static is missing and oracle is available.
- Hard failure when both are missing (no silent corruption).

---

## CLI Tool — Specific Requirements

### Project-Type Overview

`qlnes` remains a Typer-based Python CLI invoked via
`python -m qlnes <command>`. The CLI surface is the project's stable
contract (UX P4); this PRD's changes are **additive** — one new flag
(`--engine-mode`), one new warning class, schema-bumped `bilan.json`.

### Command Structure

No new commands. Existing commands gain:

- `audio --engine-mode {auto,static,oracle}` — defaults to `auto`.
- `verify --audio --engine-mode {auto,static,oracle}` — same flag,
  selects which engine path to verify.
- `coverage` shows tier-1 split between `tier-1-static` and
  `tier-1-oracle` per (mapper, engine) pair.

### Configuration — Layered Model

The four-layer config (v0.5 FR27) gains an `engine_mode` key in
`[default]` and `[audio]`. Default `auto`. Env: `QLNES_ENGINE_MODE`.

### `bilan.json` — Schema v2

Schema version 2 adds:

```json
{
  "schema_version": "2",
  "results": {
    "0": {
      "audio": {
        "engines": {
          "famitracker": {
            "tier-1-static": {"status": "pass", "rom_count": 15, "fail_count": 0},
            "tier-1-oracle": {"status": "pass", "rom_count": 15, "fail_count": 0}
          },
          "konami_kgen": {
            "tier-1-static": {"status": "missing", "rom_count": 4, "fail_count": 4},
            "tier-1-oracle": {"status": "pass", "rom_count": 4, "fail_count": 0}
          }
        }
      }
    }
  }
}
```

A reader written for v1 schema sees `engines.<name>.<status>` shapes
that don't match its expected keys → falls back to "unknown" status.
A reader written for v2 reads `tier-1-static` and `tier-1-oracle`
separately. Schema migration documented in the architecture's data-
model section.

---

## Project Scoping & Phased Development

### MVP Strategy

**Problem-solving MVP, narrowed to a single workstream:** the
**FamiTracker static walker**. Mirrors the v0.5 strategy
(narrow-MVP-music-workstream); proves the entire architecture on one
engine before scaling.

### MVP Feature Set (Phase 1 — FamiTracker static walker)

**Core user journey supported:** Marco, the porter (offline) on a
mapper-0 FamiTracker ROM. End-to-end, FCEUX-free, byte-identical to
the v0.5 output.

**Must-have capabilities:**

- Static song-pointer-table walker for FamiTracker on mapper 0/1/4/66.
- Bytecode → APU-register-write emitter that produces a sequence
  byte-identical to the FCEUX trace (the v0.5 oracle output).
- `--engine-mode auto|static|oracle` CLI flag.
- `--engine-mode static` skips FCEUX entirely (no fceux pre-flight,
  no oracle import).
- `bilan.json` schema v2 with `tier-1-static` distinction.
- `qlnes coverage` rendering of v2 schema (table + JSON).
- Equivalence test: for each FT corpus ROM, qlnes-static PCM ==
  qlnes-oracle PCM, byte-for-byte. Pass rate gate at 100% (mirrors
  v0.5 FR26).

**Music-MVP-II out-of-scope (deferred to Growth or later):**

- Capcom static walker (Growth — v0.6.x).
- Konami KGen static walker (Growth — v0.7.x).
- Other engine static walkers (Vision).
- Per-channel introspection (which channels are active, which patterns
  are looping, etc.) — debug surface only, not user-visible.
- A "static-only" build that omits the FCEUX oracle code from the
  package — keep oracle in-tree for fallback + new-engine bring-up.

### Phased Development Tiers

- **`[v0.5-MVP]`** — current. FCEUX-only audio extraction. **Done at
  the time this PRD is authored** (modulo phase 7.7 fixture work).
- **`[v0.6-MVP]`** — this PRD's MVP. FamiTracker static walker. Single
  engine, single mapper-tier. Exit criteria: FT corpus 100% byte-eq
  static-vs-oracle, three covered mappers (0, 1, 4).
- **`[Growth]`** — Capcom, KGen, FME-7 static walkers (engine-by-engine).
  `--engine-mode static` becomes the default (`auto` still falls back
  to oracle for missing engines).
- **`[Vision]`** — Static-only build (fceux oracle removed from the
  package). Score export (MIDI/MML). Multi-engine RE'd from one
  reference framework.

---

## Functional Requirements

The functional requirements below extend the v0.5 PRD's FR list
(starting at FR41 to avoid collision). FRs from the v0.5 PRD are
unchanged unless explicitly amended below.

### 7. Static Walker — FamiTracker (MVP focus)

- **FR41.** `[v0.6-MVP]` User can extract audio from a recognized
  FamiTracker ROM via static analysis, with no FCEUX subprocess
  spawned: `qlnes audio rom.nes --engine-mode static --format wav`
  succeeds on a host without FCEUX installed.
- **FR42.** `[v0.6-MVP]` The static walker emits an APU register-write
  sequence for each song that is byte-identical to the FCEUX-driven
  v0.5 trace (per song, per mapper covered).
- **FR43.** `[v0.6-MVP]` Static walker covers FamiTracker on mappers
  0, 1, and 4 in the v0.6 MVP. Mapper 66 ships in v0.6.x.
- **FR44.** `[v0.6-MVP]` Per-song determinism: rendering the same
  song twice with the same qlnes version yields byte-identical APU
  write sequences and byte-identical PCM (NFR-REL-1 inheritance).
- **FR45.** `[Growth]` Static walker covers FamiTracker on every
  mapper the v0.5 oracle path supports.

### 8. Engine-Mode Surface

- **FR46.** `[v0.6-MVP]` User can select the audio pipeline via
  `--engine-mode {auto,static,oracle}`. Default `auto` selects static
  when an engine has a static walker, otherwise falls back to oracle.
- **FR47.** `[v0.6-MVP]` `--engine-mode static` fails fast (exit 100,
  `static_walker_missing` JSON class) when no static walker exists for
  the detected engine — no silent fallback, no degraded mode.
- **FR48.** `[v0.6-MVP]` `--engine-mode oracle` keeps the v0.5 FCEUX-
  driven path. Pre-flight checks for FCEUX as in v0.5.
- **FR49.** `[v0.6-MVP]` `--engine-mode auto` (default) emits a one-
  line warning to stderr when falling back to oracle for an engine
  that lacks a static walker — visible to humans, parseable by
  pipelines via the `static_walker_missing` JSON warning class.

### 9. Coverage Matrix v2

- **FR50.** `[v0.6-MVP]` `bilan.json` schema bumps to v2 with the
  `tier-1-static` and `tier-1-oracle` per-engine sub-keys (see
  *CLI Tool — Specific Requirements* above).
- **FR51.** `[v0.6-MVP]` `qlnes coverage` renders both static and
  oracle status for each (mapper, engine) pair. Default table format
  shows them as separate columns; JSON preserves the schema-v2 shape.
- **FR52.** `[v0.6-MVP]` Release gate (mirrors v0.5 FR26): tier-1-
  static must hit 100% pass rate on the static-covered subset of the
  test corpus before each release. Tier-1-oracle is independently
  release-gated as in v0.5.

### 10. Distribution & Footprint

- **FR53.** `[v0.6-MVP]` `pip install qlnes` does not require FCEUX
  on the host. Static-walker-covered engines work end-to-end with no
  external system binary.
- **FR54.** `[Vision]` A `qlnes-no-oracle` build profile (or extra
  `pip install qlnes[no-oracle]`) ships a binary distribution that
  excludes the FCEUX oracle code path entirely. v0.5 shippable
  artifacts coexist with this profile.

### 11. Backward Compatibility

- **FR55.** `[v0.6-MVP]` Every v0.5 CLI invocation that worked
  (rom + flags + env) produces the same output bytes in v0.6 with
  `--engine-mode auto` (default) when the engine has a static walker.
  Equivalence is byte-by-byte at the WAV/MP3 PCM level.
- **FR56.** `[v0.6-MVP]` v0.5 CLI invocations that worked under the
  oracle path keep working under `--engine-mode oracle` in v0.6, with
  the same exit codes, the same JSON shape, and the same WAV/MP3
  output bytes.
- **FR57.** `[v0.6-MVP]` `bilan.json` v1 readers (qlnes < 0.6) reading
  a v2 file see no breakage — they ignore unknown keys and report
  the engine as "unknown" status. Documented in the migration note.

---

## Non-Functional Requirements

The v0.5 NFR set (NFR-PERF-1..5, NFR-REL-1..5, NFR-PORT-1..4,
NFR-DEP-1..3) carries forward unchanged. This PRD adds NFRs in the
80+ range to avoid collisions.

### Performance

- **NFR-PERF-80.** `qlnes audio rom.nes --engine-mode static` renders
  a 3-minute song in **≤ 30 seconds** on the canonical hardware (vs
  the v0.5 `≤ 6 minutes` budget, which is dominated by the FCEUX
  subprocess).
- **NFR-PERF-81.** Static-walker startup time is **≤ 100 ms** from
  process launch to the first APU write emitted (vs the v0.5 oracle
  path's ~3 second FCEUX startup).
- **NFR-PERF-82.** Per-ROM `audit` cost is **≤ 1 second/ROM** for
  the static-walker subset of the corpus (vs ~30 s/ROM under the
  oracle path on a 4-vCPU CI host).

### Reliability & Determinism

- **NFR-REL-80.** Inherits all v0.5 NFR-REL invariants. The static
  walker introduces zero new sources of non-determinism (no float
  arithmetic, no time-of-day, no host-info leakage).
- **NFR-REL-81.** Static walker output is **byte-identical** to oracle
  walker output for the same ROM × song pair. This is the load-
  bearing equivalence claim of v0.6.

### Portability

- **NFR-PORT-80.** Static-walker-covered audio renders work on every
  host where Python ≥ 3.11 runs. No dependence on SDL, X11, Wayland,
  PulseAudio, or any audio device.
- **NFR-PORT-81.** Linux, macOS, **and Windows** are supported for
  the static path in v0.6-MVP. (Compare v0.5: Windows deferred
  because of FCEUX install friction.)

### External Dependencies

- **NFR-DEP-80.** `--engine-mode static` runs with **zero hard
  external system binaries** in the audio path. The `lameenc` Python
  wheel remains the only `==`-pinned audio dep; `cynes` remains
  feature-gated for non-audio use.
- **NFR-DEP-81.** A test that imports `qlnes.audio.renderer` with
  `fceux` removed from `PATH` and `qlnes.oracle.fceux` ImportError-
  guarded must succeed for an FT-recognized ROM under
  `--engine-mode static`.

### Maintenance / Lifecycle

- **NFR-LIFE-80.** Adding a new engine static walker is a self-
  contained PR: ≤ 500 LOC of handler code + ≤ 50 LOC of registry
  glue + a `[[reference]]` corpus entry. No core architecture change.
- **NFR-LIFE-81.** A static walker can be retired without breaking
  any release (downgrade an engine from `tier-1-static` to
  `tier-1-oracle` is a backward-compatible coverage matrix change,
  not a CLI-contract change).

---

## Open Questions for Architecture

Mirrors the v0.5 PRD's "Architecture-Phase Open Questions" pattern.
These are *design decisions* the PRD intentionally does not pre-empt.

1. **Static-walker contract design.** Does the static walker emit
   `(cpu_cycle, register, value)` triples (matching the FCEUX trace
   format), or a higher-level event stream the APU emulator consumes
   directly? Tradeoff: format compatibility vs runtime efficiency.
2. **Cycle-accurate timing.** The FCEUX trace records APU writes
   at exact CPU cycles. The static walker must reproduce that timing
   — it can't just emit "frame N gets these writes". How? Per-
   instruction cycle counts from the CPU spec? A smaller "static
   CPU" that runs only the audio path?
3. **State machines vs cycle-by-cycle.** Some FT bytecode is purely
   data-driven (the FT player walks a song-pointer table that emits
   note events on a frame timer). Some engines (Capcom) are more
   imperative (the engine code itself manipulates state in PRG-RAM).
   The static walker must handle both. Per-engine? Or a unified
   model?
4. **Test corpus impact.** The corpus currently records
   FCEUX-anchored references. Migration to v2: does it record both
   anchors? Or are static-anchor ROMs migrated to a separate
   `tier-1-static` reference?
5. **Backward-compat for `bilan.json` v1 → v2.** The v0.5 schema
   says `engines.<name>.{status, rom_count, fail_count, ...}`. v2
   wants `engines.<name>.tier-1-static.{...}`. Migration script
   needed? In-place upgrade on first `audit` after install?
6. **`--engine-mode auto` heuristic.** The default needs to pick
   "right" without surprising the user. Naive: prefer static when
   available. Edge case: user explicitly wants the oracle path
   for debugging — `--engine-mode oracle` overrides.

---

## Risks (carried forward + new)

The v0.5 architecture risk register applies. This PRD softens or
removes some risks and introduces new ones.

| ID | Risk | Status |
|---|---|---|
| R1 (carried) | APU emulator falls short of sample-equivalence | Unchanged. The APU emulator is unchanged from v0.5. |
| R2 (carried) | FCEUX 2.6.6 deprecated / new version produces different reference | **Significantly softened.** The static-walker corpus depends on FCEUX *only* during walker development (validation against the oracle). Production users' renders never touch FCEUX. |
| R3 (carried) | `lameenc` removed from PyPI | Unchanged. |
| R10 (carried) | Loop-boundary detection misclassifies | Unchanged. |
| **R20 (new)** | Static walker for engine X produces APU writes that diverge from FCEUX at frame N | High impact. Mitigation: per-walker corpus equivalence tests + a "divergence-frame" debug dump (`--debug` shows the first mismatched register write). |
| **R21 (new)** | Engine RE work is harder than estimated | High impact. Mitigation: time-boxed RE spike per engine before committing to a story. Corpus-driven validation catches "looks right but isn't" cases. |
| **R22 (new)** | New v2 `bilan.json` schema breaks v0.5 readers | Low impact. v0.5 readers ignore unknown keys per existing schema discipline; we add a one-time migration note in the changelog. |

---

## amendmentLog

(Empty — first revision of this PRD.)

---

## Final Note

This PRD proposes a substantial architectural evolution: replacing the
FCEUX oracle with a per-engine static-walker registry. The core APU
emulator (the project's value-bearing equivalence anchor) is
**unchanged**. The user-visible CLI is **additive** (one new flag,
one new warning class, schema-bumped bilan).

The MVP narrows to one engine (FamiTracker) on three mappers (0, 1, 4)
to prove the architecture on a single workstream — same strategy as
the v0.5 PRD. Engine-by-engine scaling follows the proven equivalence
gate: a walker ships only after it passes 100% byte-equivalence on
its corpus subset.

The v0.5 PRD remains the production target through v0.5.x. This PRD's
work begins after `v0.5.0` is tagged.

**Author:** Johan Polsinelli.
**Date:** 2026-05-04.
