---
prdType: secondary
parent_prd: _bmad-output/planning-artifacts/prd.md
projectType: cli_tool+developer_tool
project_name: qlnes-no-fceux
user_name: Johan
date: 2026-05-04
status: draft (revised after research findings — see §0)
amendmentLog:
  - "2026-05-04: pivot from per-engine static walker to in-process CPU emulator (option C). See §0."
inputDocuments:
  - _bmad-output/planning-artifacts/prd.md
  - _bmad-output/planning-artifacts/architecture.md
  - _bmad-output/planning-artifacts/ux-design.md
  - _bmad-output/planning-artifacts/epics-and-stories.md
relatedRisks: [R1, R2, R3, R10]
---

# qlnes — PRD v0.6: Replace FCEUX subprocess by in-process CPU emulator

**Author:** Johan Polsinelli
**Date:** 2026-05-04
**Status:** Draft v2 (post-research pivot).

> **Relationship to v0.5 PRD.** Same product, same FRs 1-40 carry forward.
> This PRD adds 13 FRs (FR41-FR53) and 6 NFRs (NFR-*-80+) targeting a
> v0.6.0 release. v0.5.0 ships first; v0.6 work begins after that tag.

---

## §0. Pivot notice — research findings (2026-05-04)

This PRD originally proposed a **per-engine static walker** that would
parse engine bytecode (FT, Capcom, KGen, ...) directly without any CPU
emulation. **That approach is abandoned** based on the following
findings from a web-search and tool-survey pass on 2026-05-04:

1. **No general-purpose static NES music extractor exists.** All
   community tools (nsf2midi, NSFImport, vgmtoolbox, GME, NSFPlay,
   Mesen audio dump) **internally emulate the 6502 CPU** to capture
   APU register writes, then convert. Quote (NESdev forum): *"the
   conversion process requires emulating the NES processor, rendering
   the nsf file through that emulator, and capturing the resultant
   channel data as appropriate MIDI messages."*
2. **Per-engine static analysis is craft, not engineering.** Per
   nesdev community: *"there is no universal automated converter from
   arbitrary NES driver sequences"* and *"many games use custom sound
   drivers with nonstandard effects."* Hand-curated MIDI rips exist
   for specific games (Castlevania, Mega Man) but each is a one-off
   reverse-engineering project, not a reusable framework.
3. **Static walker's per-engine cost is prohibitive.** Each engine
   = ~5 dev-days of bytecode RE per the original v0.6 plan. Coverage
   would never reach the v0.5 oracle path's universality.

**Pivot.** The problem the user actually wants solved is *RAM/footprint*
and *subprocess elimination*, not "no emulator at all". An **in-process
CPU emulator** (using `py65` — already in qlnes deps for round-trip —
or `cynes` — already in qlnes deps for dynamic discovery) replaces the
FCEUX subprocess. RAM goes from ~80 MB (FCEUX + SDL + xvfb) to ~5-10 MB
(Python CPU emulator). No subprocess fork. Coverage stays universal.

The static walker is dropped from this PRD's scope. The F.1 scaffolding
(StaticWalker ABC + ApuWriteEvent) committed earlier on 2026-05-04 is
**partially salvageable** — `ApuWriteEvent` is the canonical interchange
type regardless of how events are produced, kept. `StaticWalker` ABC is
unused in v0.6 plan and **deprecated**; it stays in tree as a future
extension point for a per-game-craft path if anyone ever wants it, but
ships no concrete subclass.

---

## Executive Summary

qlnes today extracts NES audio via a three-step pipeline: FCEUX
subprocess emulates the ROM, a Lua trace records APU register writes
per CPU cycle, qlnes's own APU emulator replays the trace into PCM.
The FCEUX dependency is the load-bearing piece (architecture step 10,
ADR-03) and the source of three top risks (R1/R2/R3): upstream FCEUX
API churn, version-pinning friction, and per-host environmental
brittleness (SDL, X11, audio drivers, headless servers).

**This PRD replaces FCEUX with an in-process Python 6502 emulator.**
The new pipeline:

1. **Parse the iNES ROM** (existing — `qlnes/rom.py`).
2. **Locate the music driver entry points** — `init_addr` and
   `play_addr` per song, the same fields NSF format encodes. The
   existing `SoundEngine` plugin returns these.
3. **Boot a Python 6502 emulator** in process — `py65` (pure Python,
   already a qlnes dep). Map PRG banks to CPU memory, install an
   APU-register write observer.
4. **Run the music driver:**
   - Call `init_addr` once per song.
   - Call `play_addr` once per NTSC frame (60 Hz) for `frames` frames.
   - The observer collects every $4000–$4017 write with its CPU cycle.
5. **Feed events to the qlnes APU emulator** — unchanged. Same PCM,
   byte-identical to the current FCEUX-driven path on covered engines.

User-visible result: `qlnes audio rom.nes` works on machines without
FCEUX installed, produces byte-identical output, runs ~5-10× faster
(no subprocess, no PCM round-trip), uses ~16× less RAM (~5 MB vs ~80 MB).

---

## Project Classification

- **Project Type:** CLI tool. Same surface as v0.5.
- **Lineage:** Successor to v0.5 music-MVP. Reuses APU emulator (step
  8), engine plugin registry (step 9), bilan schema (step 12). Replaces
  FCEUX oracle (step 10) with `qlnes/audio/in_process/` subpackage.
- **External-dependency strategy:** Zero hard system binaries in the
  audio path. `py65` (already a Python wheel), `cynes` (already in
  deps), `lameenc` (already in deps). No SDL, no X11, no Lua, no
  fceux subprocess.

---

## Success Criteria

| Goal | Definition of done | Verification |
|---|---|---|
| Audio works on FCEUX-free hosts | `qlnes audio rom.nes --format wav` succeeds on a clean install (`pip install qlnes`) without FCEUX present. | Docker integration test, no fceux installed. |
| Byte-identical to v0.5 output | For every ROM in the v0.5 corpus, the in-process path produces byte-identical PCM to the FCEUX-anchored reference. SHA-256 match. | `tests/invariants/test_in_process_oracle_equivalence.py` parametrized on `corpus/manifest.toml`. |
| 5x+ faster | A 3-min song renders ≤ 60s wall-clock (vs ≤6 min with FCEUX). | `tests/integration/test_audio_perf_in_process.py`. |
| 16x less RAM | Peak resident memory for a 3-min render ≤ 10 MB (vs ~80 MB for FCEUX subprocess). | `tests/invariants/test_memory_ceiling.py` (uses `resource.getrusage`). |
| Universal coverage | Works on any iNES ROM with a recognized engine, same as v0.5. No per-engine RE. | All v0.5 corpus pass under `--engine-mode in-process`. |

---

## Product Scope

### In scope

- New `qlnes/audio/in_process/` subpackage that wraps a Python 6502
  CPU emulator (`py65` first; `cynes` if perf needs it), drives the
  music driver via init/play JSRs, captures APU writes.
- Per-engine `init_addr(rom, song) → int` and `play_addr(rom, song)
  → int` methods on `SoundEngine` (NSF-format-style addresses).
- `--engine-mode {auto,in-process,oracle}` CLI flag — `auto` defaults
  to in-process when available, falls back to oracle if not, errors
  if neither.
- `bilan.json` schema v2 with `tier-1-in-process` / `tier-1-oracle`
  per-engine sub-keys.
- The qlnes APU emulator stays unchanged — it remains the only place
  PCM is generated.

### Out of scope

- Static walker per-engine (abandoned per §0).
- New APU implementation.
- MIDI/MML score export.
- Removing FCEUX oracle from the codebase — kept for fallback +
  for new-engine bring-up validation.
- Expansion-audio chip support beyond v0.5.

### Anti-goals (will NOT do)

- "Best-effort" emission for unrecognized engines. The auto path
  falls through to the oracle (same coverage as v0.5) or fails
  cleanly.
- Approximations that trade fidelity for simplicity.
- A standalone NSF player (qlnes is a ROM analysis tool; NSF playback
  is downstream tooling territory).

---

## User Journeys

### Journey 1 — Marco, the porter (offline)

Marco's flight is six hours. No FCEUX installed. He runs:
```
python -m qlnes audio rom.nes --format wav --output tracks/
```
qlnes loads the ROM, the engine handler returns `init_addr` and
`play_addr` for each song, the in-process CPU emulator runs the music
driver code in-process (no fork, no subprocess), captures APU writes,
feeds the qlnes APU emulator, writes per-track WAVs. Six-hour flight,
three OSTs done. **Capabilities revealed:** no FCEUX dep on host,
faster renders, identical output bytes.

### Journey 2 — Lin, the pipeline integrator (subprocess-free)

Lin's HD-2D pipeline is containerized. She drops `RUN apt install
fceux xvfb libsdl2-2.0-0` from her Dockerfile. Image shrinks 80 MB.
Per-job wall-clock drops from ~8 s (3 s startup + 5 s render) to ~1 s.
Pipeline throughput on her 4-vCPU worker triples.

### Journey 3 — Marco, fallback path

Marco hits a ROM whose engine has its `init/play` addresses
mis-detected (rare, but happens for non-FT engines without good
heuristics). Default `--engine-mode auto`: qlnes detects in-process
extraction will fail, falls back to FCEUX oracle automatically and
warns:

```
qlnes: warning: in-process extraction not confident for engine X; using FCEUX oracle.
{"class":"in_process_low_confidence","engine":"X","fallback":"oracle"}
```

If FCEUX is installed, render proceeds via oracle. If not, exit 100
with hint pointing at oracle install.

---

## Functional Requirements

The new FRs extend the v0.5 PRD's FR list (FR41+).

### 7. In-process CPU emulator (MVP focus)

- **FR41.** `[v0.6-MVP]` `qlnes audio rom.nes` succeeds on a host
  without FCEUX installed when the engine has identified `init_addr`
  + `play_addr` (most engines via the existing detection path).
- **FR42.** `[v0.6-MVP]` In-process emission produces APU register-
  write sequences byte-identical to FCEUX traces for the v0.5 corpus
  subset. Equivalence test gates each release.
- **FR43.** `[v0.6-MVP]` Default Python 6502 emulator: `py65`. If
  performance is insufficient (≤ 5x v0.5 oracle wall-clock per
  NFR-PERF-80), evaluate switching to `cynes` (Cython binding to a
  C NES emulator already in qlnes deps).
- **FR44.** `[v0.6-MVP]` Per-song determinism (NFR-REL-1 inheritance).
- **FR45.** `[Growth]` Multi-mapper support (mapper-1 MMC1, mapper-4
  MMC3) in the in-process path. v0.5's NROM-only `cynes` constraint
  goes away if `cynes` becomes the engine — extends to all v0.5
  oracle-supported mappers.

### 8. Engine-Mode Surface

- **FR46.** `[v0.6-MVP]` `--engine-mode {auto,in-process,oracle}`
  CLI flag. Default `auto`.
- **FR47.** `[v0.6-MVP]` `--engine-mode in-process` fails fast (exit
  100, JSON `class:in_process_unavailable`) when the engine lacks
  `init/play` addresses.
- **FR48.** `[v0.6-MVP]` `--engine-mode oracle` keeps v0.5 behavior.
- **FR49.** `[v0.6-MVP]` `--engine-mode auto` falls back to oracle
  with `warning: in_process_unavailable` JSON when in-process can't
  extract; fails clean if FCEUX also missing.

### 9. Coverage Matrix v2

- **FR50.** `[v0.6-MVP]` `bilan.json` schema v2:
  `engines.<name>.tier-1-in-process` and
  `engines.<name>.tier-1-oracle` per-engine sub-keys.
- **FR51.** `[v0.6-MVP]` `qlnes coverage` table v2 with separate
  in-process / oracle columns.
- **FR52.** `[v0.6-MVP]` Release gate: tier-1-in-process at 100%
  pass on its corpus subset. Tier-1-oracle independently gated as in
  v0.5.

### 10. Distribution

- **FR53.** `[v0.6-MVP]` `pip install qlnes` does not require FCEUX.
  In-process-covered engines work end-to-end with no system binary.

### 11. Backward Compatibility

(Same as v0.5 BC discipline; FR55-FR57 from prior draft kept
verbatim, see initial PRD draft if needed.)

---

## Non-Functional Requirements

The v0.5 NFR set carries forward unchanged. New NFRs:

| NFR | Budget | Notes |
|---|---|---|
| NFR-PERF-80 | ≤ 60 s wall-clock for 3-min song | vs ≤ 6 min v0.5 |
| NFR-PERF-81 | ≤ 100 ms startup | No subprocess fork |
| NFR-MEM-80 | ≤ 10 MB peak RSS | vs ~80 MB v0.5 (16x reduction) |
| NFR-PORT-80 | Linux + macOS + **Windows** | No SDL/X11/PulseAudio dep |
| NFR-DEP-80 | Zero hard system binaries | Python wheels only |
| NFR-REL-80 | Byte-equiv to v0.5 oracle | Test gate per release |

---

## Open Questions for Architecture

1. **Performance.** `py65` runs the full NES CPU at ~50K cycles/sec
   pure-Python (vs 1.79M target). Music driver only runs ~120K
   cycles/sec of CPU (~7%), so realistic perf for a 3-min song:
   ~430s — over budget. Mitigation: switch to `cynes` (C-backed,
   ~10x faster) or PyPy. Spike before MVP commit.
2. **Engine init/play address detection.** v0.5 SoundEngine doesn't
   expose these. New protocol method or new ABC subclass? FT engine
   typically has init at song-table-base + offset; Capcom different.
3. **PPU dependency.** Music drivers usually don't read PPU state,
   but some games' init paths poll PPU vblank flag. If we don't
   provide PPU mock, init may hang. Mitigation: stub PPU register
   reads with sane defaults (vblank=1 always after a few cycles).
4. **NMI emulation.** NES music driver runs from NMI handler at 60Hz.
   Our wrapper must trigger NMI on schedule (push PC+SR, jump to
   NMI vector) every 29780 CPU cycles.
5. **Mapper support.** NROM (mapper 0) is trivial. MMC1/MMC3 require
   bank-switch handling on writes to specific PRG addresses. py65
   has no built-in mapper support — we'd need our own. cynes has
   mapper support natively.
6. **Crash recovery.** If the music driver enters an infinite loop
   without ever advancing to the play vector, our wrapper must
   detect + abort cleanly (cycle budget).

---

## Risks (carried + new)

| ID | Status |
|---|---|
| R1 (carried) | Unchanged. APU emulator is the equivalence anchor. |
| R2 (carried) | Significantly softened. FCEUX is now a fallback, not the primary path. |
| R3 (carried) | Unchanged. |
| R10 (carried) | Unchanged. |
| **R30 (new)** | py65 too slow → fall back to cynes. Spike-de-risked before story F.3 commits. |
| **R31 (new)** | Music driver init path reads from PPU state qlnes doesn't simulate. Mitigation: stub PPU registers; if a driver still hangs, mark engine as oracle-only for that ROM. |
| **R32 (new)** | NMI emulation timing diverges from FCEUX by a few cycles. Mitigation: byte-equiv test catches; tune NMI trigger schedule. |
| **R33 (new)** | Mapper bank-switching breaks under py65 (no native mapper support). Mitigation: prefer cynes for non-NROM mappers. |

---

## Steps to do (TODO list, ordered)

The v0.6 work decomposes into the following ordered tasks. Mapped to
stories in `epics-and-stories-v0.6.md`.

1. **F.1 — Salvage scaffolding.** `ApuWriteEvent` kept. `StaticWalker`
   ABC marked deprecated/abandoned in code (not deleted — keeps the
   per-game-craft door open if anyone ever wants it).
2. **F.2 — Perf spike: py65 vs cynes.** Time-boxed 1 dev-day.
   Benchmark: replay one v0.5 corpus FT trace via py65 in-process,
   measure wall-clock. If > 60s for 3-min song budget → switch to
   cynes. **Decision artifact.** No long-term commitment yet.
3. **F.3 — In-process CPU emulator wrapper.** New module
   `qlnes/audio/in_process/`. Wraps the chosen emulator, exposes
   `run_song(rom, init_addr, play_addr, frames) → list[ApuWriteEvent]`.
   Mapper-0 only. ~300-500 LOC.
4. **F.4 — Engine init/play address protocol.** Extend `SoundEngine`
   ABC with `init_addr(rom, song) -> int` and `play_addr(rom, song)
   -> int`. FamiTracker handler implements them.
5. **F.5 — Renderer pipeline-mode dispatch.** `--engine-mode` flag,
   resolution logic, fallback warnings.
6. **F.6 — Bilan schema v2.** Migration logic for v1 readers.
7. **F.7 — Equivalence corpus test.** Byte-eq vs v0.5 oracle output
   on `corpus/manifest.toml` FT subset.
8. **F.8 — Multi-mapper support.** Mapper-1, mapper-4 in in-process
   path (likely requires cynes if mapper switching is intrusive).
9. **F.9 — Coverage v2 rendering + CI matrix expansion** (Linux +
   macOS + Windows; FCEUX-free job).
10. **F.10 — Documentation + changelog migration note** + tag v0.6.0.

---

## Sign-off

This PRD is **READY** for the next BMad workflow step
(`bmad-create-architecture` for the v0.6 architecture amendment) at
the maintainer's discretion. v0.5 ships first.

**Author:** Johan Polsinelli + Claude (Opus 4.7).
**Date:** 2026-05-04.
