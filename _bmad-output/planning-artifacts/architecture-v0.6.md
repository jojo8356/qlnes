---
docType: architecture-amendment
parent_architecture: _bmad-output/planning-artifacts/architecture.md
parent_prd: _bmad-output/planning-artifacts/prd-no-fceux.md
date: 2026-05-04
status: draft
project_name: qlnes-no-fceux
user_name: Johan
amendmentLog: []
---

# Architecture Amendment — qlnes v0.6 (No-FCEUX Static-Walker Pipeline)

> **Relationship to v0.5 architecture.** This amendment is *additive*.
> v0.5 architecture (architecture.md, 19 steps, 20 ADRs, all decisions
> locked) remains the contract for the v0.5.x maintenance line. This
> amendment specifies the *delta* that lands in v0.6.0 — not a rewrite.

---

## Step 20 — Static Walker Pipeline Architecture

### 20.1 Pipeline diagram

```
                    +--------------------+
                    |  Rom (existing)    |
                    +---------+----------+
                              |
                              v
              +---------------+----------------+
              |  SoundEngineRegistry.detect()  |
              +---------------+----------------+
                              |
                +-------------+-------------+
                |                           |
                v                           v
      +-------------------+      +---------------------+
      | StaticWalker      |      | OracleEngine        |
      | (this amendment)  |      | (existing v0.5)     |
      | parses bytecode   |      | uses FCEUX trace    |
      +---------+---------+      +----------+----------+
                |                           |
                v                           v
      +---------+---------+      +----------+----------+
      | List[ApuWriteEvent]      |  ApuTrace (FCEUX)   |
      | (cycle, reg, val)        |  (cycle, reg, val)  |
      +---------+---------+      +----------+----------+
                |                           |
                +-------------+-------------+
                              |
                              v
                    +---------+----------+
                    |  ApuEmulator       |
                    |  (UNCHANGED)       |
                    +---------+----------+
                              |
                              v
                    +---------+----------+
                    |  PCM int16 LE      |
                    +--------------------+
```

The trick: both pipelines feed an **identical interface** to the APU
emulator. Whether the (cycle, register, value) triples come from FCEUX
or from a static walker is invisible to the emulator. Sample-equivalence
is therefore a property of the EMITTED TRACES, not of the rendering
engine.

### 20.2 New protocol — `StaticWalker`

Sub-protocol of `SoundEngine`. Engines that ship a static walker
implement this in addition to the v0.5 protocol:

```python
class StaticWalker(SoundEngine):
    """Engine handler that emits APU register-writes from bytecode alone."""

    has_static_walker: ClassVar[Literal[True]] = True

    @abc.abstractmethod
    def emit_apu_writes(
        self,
        rom: Rom,
        song: SongEntry,
        *,
        frames: int,
    ) -> Iterator[ApuWriteEvent]:
        """Yield (cpu_cycle, register, value) triples for `song`.

        Pure function over rom + song + frames. No subprocess, no I/O,
        no clock, no random source. Output is deterministic (NFR-REL-1).

        The emitted sequence MUST be byte-identical to what the engine
        would produce at runtime under FCEUX for the same (rom, song,
        frames) inputs. This is the canonical equivalence claim.
        """
```

Engines without a static walker keep `has_static_walker = False` (the
default) and fall through to the oracle path.

### 20.3 Pipeline selection — `--engine-mode` resolution

```
--engine-mode auto    (default)
   ↓
   if engine.has_static_walker:
       use StaticWalker.emit_apu_writes
   else:
       if fceux_available:
           use OracleEngine via FceuxOracle.trace
           emit warning: static_walker_missing (UX §6.5 class extension)
       else:
           raise QlnesError("unsupported_mapper", ..., suggest --engine-mode oracle)

--engine-mode static
   ↓
   if engine.has_static_walker:
       use StaticWalker.emit_apu_writes
   else:
       raise QlnesError("static_walker_missing")  # exit code 100, hard fail

--engine-mode oracle
   ↓
   use OracleEngine via FceuxOracle.trace  (v0.5 behavior)
```

`bad_format_arg` is the existing class for invalid `--engine-mode` values
(usage_error / 64).

### 20.4 ApuWriteEvent — the canonical interchange format

Replaces `qlnes.oracle.fceux.TraceEvent` as the *type* the renderer
consumes. Lives in `qlnes/audio/engine.py` next to the other ABC types.

```python
@dataclass(frozen=True)
class ApuWriteEvent:
    cpu_cycle: int    # absolute CPU cycle since song start (uint64-safe)
    register: int     # 0x4000..0x4017
    value: int        # 0..255
```

Both `FceuxOracle.trace` (v0.5) and `StaticWalker.emit_apu_writes` (v0.6)
produce iterators of these. Existing `TraceEvent` becomes an alias of
`ApuWriteEvent` for backward compat (one-line typedef in oracle/fceux.py).

### 20.5 Renderer wiring (delta)

```python
# qlnes/audio/renderer.py — pseudocode delta from v0.5

def render_rom_audio_v2(rom_path, output_dir, *, fmt, frames, force,
                        engine_mode="auto", oracle=None):
    rom = Rom.from_file(rom_path)
    engine, _detection = SoundEngineRegistry.detect(rom)
    songs = engine.walk_song_table(rom)

    pipeline = _resolve_engine_mode(engine_mode, engine)
    # pipeline is "static" or "oracle"

    for song, target in zip(songs, targets, strict=True):
        if pipeline == "static":
            events = list(engine.emit_apu_writes(rom, song, frames=frames))
        else:  # "oracle"
            if oracle is None:
                oracle = FceuxOracle()
            trace = oracle.trace(rom_path, frames=frames)
            events = trace.events
        pcm = _replay_events_through_apu(events, frames=frames)
        # ...write WAV/MP3 as in v0.5...
```

The two-arm switch is the only architectural change in the renderer.
Everything downstream (APU emulator, WAV writer, MP3 encoder, atomic
writes, refuse-overwrite, dir-level rollback) is unchanged.

---

## Step 21 — FamiTracker Static Walker (MVP focus)

### 21.1 What FT's player does

The FamiTracker / 0CC-FamiTracker / FamiTone runtime, compiled into the
ROM, is a 6502 routine called from the NMI handler (every NTSC frame).
Per frame, it:

1. Reads the **song-pointer table** at a known offset to find the
   current song's pattern data.
2. Walks the pattern bytecode at the song's current row.
3. For each active channel (pulse 1, pulse 2, triangle, noise, DMC),
   computes the APU register values for this frame based on:
   - Current note (pitch → period), or pitch-bend / vibrato state.
   - Volume envelope progress.
   - Arpeggio / instrument state.
4. Writes those values to `$4000`–`$4013` and the channel-enable
   register `$4015`.
5. Advances the row counter; advances pattern when end-of-pattern
   sentinel is hit; loops back to song start on master-loop sentinel
   (`Bxx` opcode) — same loop semantics A.3 commits to encode in WAV
   `'smpl'` chunks.

The static walker reproduces this **without running the 6502**. It
needs:

- The **song-pointer table**'s location in PRG (engine-specific offset
  pattern; FT keeps it at a stable layout).
- The **pattern bytecode format** for each channel (FT's "effect column"
  encoding — Cxx, Dxx, Bxx, Vxx, etc.).
- The **instrument table** for envelope shapes.
- A **mini state machine** for envelopes (volume decay, arpeggio
  oscillation, vibrato).

### 21.2 Module layout

```
qlnes/audio/static/                  NEW (this amendment)
├── __init__.py                      (StaticWalker ABC re-export)
├── apu_event.py                     (ApuWriteEvent + helpers)
└── engines/
    ├── __init__.py
    ├── famitracker_static.py        (this MVP — the load-bearing module)
    ├── famitracker_format.py        (FT pattern bytecode parser)
    ├── famitracker_state.py         (per-channel state machine)
    └── famitracker_emit.py          (state → APU writes per frame)
```

Total target: ~600-800 LOC for the FT static walker (per NFR-LIFE-80
budget of ≤500 LOC handler + glue).

### 21.3 Per-frame emission contract

```python
def emit_apu_writes(rom: Rom, song: SongEntry, *, frames: int) -> Iterator[ApuWriteEvent]:
    """Pure-Python static emission — no CPU emulation, no subprocess.

    Algorithm:
      1. Locate FT's player data structures in PRG (song table, instrument
         table, pattern data).
      2. Initialize per-channel state for the requested song.
      3. For frame in [0, frames):
           cpu_cycle = frame * CYCLES_PER_NTSC_FRAME  (= 29780)
           For each channel:
               advance state by one frame (envelope tick, pattern row, ...)
               for each register that changed:
                   yield ApuWriteEvent(cpu_cycle + cycle_offset, reg, value)
    """
```

The `cycle_offset` per write within a frame matches what FT's NMI
handler does at runtime: writes are emitted in a fixed order
(pulse 1 → pulse 2 → triangle → noise → status), so each write gets a
deterministic small offset. The exact timing isn't critical for sample-
equivalence (the APU emulator's per-cycle granularity smooths it), but
the emission *order* must match FCEUX's order.

### 21.4 RE methodology

For each engine, the bring-up path is:

1. **Reference capture.** Generate the FCEUX trace for one corpus ROM
   under the v0.5 oracle path: `qlnes audio rom.nes --engine-mode oracle
   --debug` writes the (cycle, register, value) sequence to a debug log.
2. **Bytecode RE.** Disassemble the FT player code in PRG (`qlnes
   analyze --asm`), study the open-source FT runtime
   (https://github.com/HertzDevil/0CC-FamiTracker — GPL-3 source — for
   reference *only*; we don't copy code).
3. **Walker draft.** Implement `emit_apu_writes`. Initial pass aims for
   the first 60 frames.
4. **Diff.** Compare the static walker's output against the FCEUX
   reference trace. First mismatched (cycle, register, value) is the
   "divergence frame" reported by `--debug`. Fix the walker. Iterate.
5. **Equivalence gate.** Walker ships when the corpus subset for its
   engine hits 100 % byte-equivalence between static and oracle paths.

---

## Step 22 — `bilan.json` Schema v2

### 22.1 Diff from v1

```diff
 {
-  "schema_version": "1",
+  "schema_version": "2",
   "results": {
     "0": {
       "audio": {
         "engines": {
           "famitracker": {
-            "status": "pass",
-            "rom_count": 15,
-            "fail_count": 0
+            "tier-1-static": {"status": "pass", "rom_count": 15, "fail_count": 0},
+            "tier-1-oracle": {"status": "pass", "rom_count": 15, "fail_count": 0}
           }
         }
       }
     }
   }
 }
```

### 22.2 Migration

- `BilanStore.read(path)` detects `schema_version` and dispatches:
  - v1: unchanged behavior (kept for older `audit`-produced bilans).
  - v2: new shape; reader extracts both static and oracle status.
- A v1 bilan can be upgraded in place by `qlnes audit --refresh`
  (which always overwrites). No standalone migrator.
- v1 readers (qlnes < 0.6) reading a v2 bilan log a warning class
  `bilan_schema_version` and skip the `engines` sub-map. Coverage
  table renders empty engine columns. Documented in changelog.

### 22.3 `coverage` table (v2)

```
mapper  artifact  status      pass     total   static_engines   oracle_engines
0       analyze   ✓ pass        15/15
0       audio     ✓ pass        15/15            famitracker:15  famitracker:15
1       audio     ⚠ partial      8/12            famitracker:8   famitracker:12
                                                  konami:0/4 (no static)
4       audio       missing                       (no engine handler)
```

The `static_engines` column shows what the static walker covers; the
`oracle_engines` column shows what the FCEUX oracle covers. A user can
read at a glance: "this engine is static-covered" vs "this engine still
needs FCEUX".

---

## Step 23 — ADRs

This amendment introduces three new ADRs.

| ADR | Decision | Reverse cost |
|---|---|---|
| **ADR-21** | Static-walker pipeline coexists with the FCEUX-oracle pipeline behind `--engine-mode {auto,static,oracle}` (default `auto`). Both produce `ApuWriteEvent` iterators that feed the same APU emulator. | Low — additive. Removing static-walker pipeline rolls back to v0.5 semantics with no API break. |
| **ADR-22** | The static walker's output is the byte-equivalence anchor against the FCEUX-oracle trace (not against FCEUX directly). FCEUX remains the *historical* equivalence anchor, but day-to-day equivalence checks compare static-vs-oracle within qlnes. | Medium — re-anchoring against FCEUX directly is possible but requires running the oracle path during test setup; today's tests would migrate. |
| **ADR-23** | `bilan.json` schema bumps to v2 with `tier-1-static` / `tier-1-oracle` per-engine sub-keys. v1 readers fall through to `unknown` status (graceful). | Low — schema-versioning is the established pattern (v0.5 ADR-10). |

---

## Step 24 — NFR Mapping (delta)

| NFR (this amendment) | Mechanism | Verification |
|---|---|---|
| NFR-PERF-80 (≤30s for 3-min song) | Static walker is pure Python, no subprocess, no PCM round-trip | `tests/integration/test_audio_perf_no_fceux.py` |
| NFR-PERF-81 (≤100ms startup) | No fceux fork, no Lua load | Same test, separate timing assertion |
| NFR-PERF-82 (≤1s/ROM audit) | Static path renders in-process | `tests/invariants/test_audit_perf_static.py` (sprint-9 scope) |
| NFR-REL-81 (byte-eq static vs oracle) | Shared `ApuWriteEvent` interchange + shared APU emulator | `tests/invariants/test_static_oracle_equivalence.py` (parametrized on corpus FT subset) |
| NFR-PORT-81 (Windows portable) | No fceux, no SDL, no X11 | CI matrix gain (sprint 9 scope) |
| NFR-DEP-80 (zero hard externals) | Static-only path imports nothing system-binary-dependent | `tests/integration/test_no_fceux_environment.py` (PATH stripped of fceux) |

---

## Step 25 — Risk Register Delta

The v0.5 risk register (architecture step 16) is carried forward. This
amendment updates two entries and adds three.

| ID | Status delta |
|---|---|
| R1 | Unchanged. APU emulator stays the equivalence anchor. |
| R2 | **Significantly softened.** FCEUX is now an in-development reference, not a runtime dependency for static-covered engines. A FCEUX deprecation no longer breaks production users on those engines. |
| R3 | Unchanged. lameenc dep is unrelated to the FCEUX/static change. |
| R10 | Unchanged. Loop detection runs on the static-emitted trace as well — same semantics. |
| **R20** (new) | Static walker for engine X produces APU writes that diverge from FCEUX at frame N. Mitigation: per-walker corpus equivalence test gates the engine's release; `--debug` dumps the divergence frame. |
| **R21** (new) | Engine RE work is harder than estimated. Mitigation: time-boxed RE spike per engine (24-48 h) before committing to a story; if it fails, the engine stays oracle-only. |
| **R22** (new) | New v2 `bilan.json` schema breaks v0.5 readers. Mitigation: graceful degradation (v1 readers see `unknown` status, log warning); changelog migration note. |

---

## Step 26 — Phasing & Story Seams (input to `bmad-create-epics-and-stories`)

The v0.6 work decomposes into one new epic in addition to v0.5 epics A-E:

### Epic F — *FCEUX-free music extraction* (this amendment)

**User value.** Marco runs `qlnes audio rom.nes` on a clean machine
with no FCEUX installed and gets sample-equivalent WAV. Lin's pipeline
drops the FCEUX/SDL stanza from the Dockerfile. Both Journeys 1 and 2
complete without subprocess overhead.

**FRs closed** — FR41–FR57 (MVP-tier subset).

**Suggested story slicing** (input to `CE`, not authoritative):

- F.1 — Scaffold `qlnes/audio/static/` package, `StaticWalker` ABC,
  `ApuWriteEvent`, registry plumbing. *No engine handler yet — this
  is the structural commit. Like A.1 was for v0.5.*
- F.2 — `--engine-mode {auto,static,oracle}` flag in CLI + renderer
  pipeline-selection logic. `static_walker_missing` warning + JSON
  class. `bilan.json` schema-bump to v2 with backward-compat read.
- F.3 — FamiTracker static walker (FT format parser + per-channel
  state machine + emit). Mapper 0 only. Equivalence test against the
  FT corpus subset on mapper 0. **L story** — bytecode RE work.
- F.4 — Extend FT static walker to mapper 1 (MMC1 banking complicates
  pattern lookup for songs spanning bank boundaries). M story.
- F.5 — Extend FT static walker to mapper 4 (MMC3 banking + IRQ).
  M story.
- F.6 — `coverage` table v2 rendering (static/oracle columns); CI
  workflow gain (Windows + macOS in matrix; FCEUX-free test job).
- F.7 — Documentation (README — "How to install qlnes without
  FCEUX") + changelog migration note for v1 → v2 bilan.

### Sprint Sequencing Suggestion

Insert *after* v0.5.0 tag (sprint 8 of the current plan):

- **Sprint 9** — F.1 + F.2 (scaffolding + CLI surface). Half a sprint
  is RE-spike on FT pattern format (R21 mitigation).
- **Sprint 10** — F.3 (FT mapper 0 walker, the L story).
- **Sprint 11** — F.4 + F.5 (mapper 1 + 4).
- **Sprint 12** — F.6 + F.7 (polish + docs).

Total: ~4 weeks of solo dev for FT-only coverage. Capcom / KGen / others
are subsequent stories at the same cadence.

---

## Step 27 — Sign-off

This amendment is **READY** for `bmad-create-epics-and-stories` (CE) at
the v0.6 tier.

The v0.5 architecture stays the production architecture through v0.5.x.
v0.6 starts after `v0.5.0` is tagged and represents an evolution, not a
fork.

**Author:** Claude (Opus 4.7), drafting under `bmad-create-architecture`.
**Date:** 2026-05-04.

---

*End of Architecture Amendment — qlnes v0.6 (2026-05-04)*
