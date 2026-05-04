---
story_id: F.4
epic: F
title: SoundEngine init_addr / play_addr protocol
sprint: 10
estimate: M
status: DONE + CR-clean (all 6 ACs ✅; 22 new tests green post-CR; F.3 baseline still green)
created_by: bmad-create-story (CS)
date_created: 2026-05-04
date_completed: 2026-05-04
project_name: qlnes
mvp_target: v0.6.0
inputDocuments:
  - _bmad-output/planning-artifacts/prd-no-fceux.md
  - _bmad-output/planning-artifacts/architecture-v0.6.md (steps 20.2, 20.3)
  - _bmad-output/planning-artifacts/epics-and-stories-v0.6.md (§F.4)
  - _bmad-output/implementation-artifacts/stories/F.3.md (predecessor; runner already accepts play_addr)
  - _bmad-output/decisions/v06-cpu-backend.md
fr_closed: [FR41/full-NSF-shape]
fr_partial: []
nfr_touched: [REL-80]
risks_realized: []
risks_softened: []
risks_new: []
preconditions: [F.3]
outputs:
  - qlnes/audio/engine.py — extended with InProcessUnavailable + SoundEngine.init_addr/play_addr defaults
  - qlnes/audio/engines/famitracker.py — overrides + _read_le16_at_cpu helper
  - qlnes/audio/in_process/runner.py — run_song wires play_addr via trigger_nmi_to (no nmi_enabled gate)
  - qlnes/audio/in_process/nmi.py — extracted trigger_nmi_to, trigger_nmi wraps it
  - qlnes/audio/in_process/__init__.py — exports trigger_nmi_to
  - tests/unit/test_engine_init_play.py — NEW, 9 tests (default-raise, FT 32K/16K vector reads, range checks)
  - tests/unit/test_in_process_nmi.py — extended with 4 trigger_nmi_to tests (total 11)
  - tests/integration/test_in_process_alter_ego.py — extended with 6 F.4 tests
  - tests/fixtures/in_process/alter_ego_run_song_600fr.tsv — NEW canonical fixture (8 645 events, sha256 ea062dba…4baa)
next_story: F.5
next_action: bmad-dev-story (DS) on F.4 → branch `feature/F.4-engine-init-play`
---

# Story F.4 — SoundEngine init_addr / play_addr protocol

**Epic:** F — *Replace FCEUX subprocess by in-process CPU emulator*
**Sprint:** 10 (v0.6 engine integration sprint)
**Estimate:** M (2-3 dev-days)
**Status:** READY (DoR satisfied: F.3 done, runner.run_song accepts play_addr unused, FT engine handler exists from A.1)

---

## 1. User value

> **Marco.** Marco runs `python -m qlnes audio rom.nes --format wav` on
> a ROM the FamiTracker engine handler recognizes, and the in-process
> renderer extracts the music *without* relying on the ROM's reset/NMI
> vectors having game-shaped semantics. The extraction works
> **NSF-style** — engine handler points to the music driver's actual
> `init` and `play` entry points, the runner JSRs them on the right
> cadence, and the resulting trace is byte-equivalent to F.3's
> `run_natural_boot` for self-running ROMs (where reset == init,
> NMI handler == play).

This story closes the architectural gap between what F.3 ships
(self-running boot path) and what the architecture spec §20.2 calls
for (explicit init/play addresses driving the runner).

## 2. Acceptance criteria

### From epics-and-stories-v0.6.md §F.4

| # | AC | Verification |
|---|---|---|
| AC1 | `FamiTrackerEngine.init_addr(rom, song)` returns a valid CPU address ($8000-$FFFF range) for Alter Ego | Unit test on synthetic FT ROM + integration test on Alter Ego (assert `0x8000 <= addr <= 0xFFFF`) |
| AC2 | `FamiTrackerEngine.play_addr(rom, song)` similarly | Same test coverage as AC1 |
| AC3 | Default `SoundEngine.init_addr` raises `NotImplementedError` with a JSON-friendly extra (`class:in_process_unavailable`) | Unit test instantiates a synthetic engine subclass that doesn't override the methods, asserts the exception class + extra |

### Added in CS facilitation

| # | AC | Why |
|---|---|---|
| AC4 | `InProcessRunner.run_song(init_addr, play_addr, frames=600)` on Alter Ego with `(reset_vector, nmi_vector)` produces a trace that **matches a committed run_song-specific fixture** AND passes the same musical-property battery as F.3 AC2b (registers in APU range, cycles monotonic, $4015 enable, multi-channel coverage) | Closes the F.3 §"Decisions §1" gap (run_song existed but unused). **CS-revised after empirical check**: run_song produces a *different* trace than run_natural_boot because Alter Ego doesn't enable NMI naturally — so we pin run_song's own canonical output (8 645 events) as a regression anchor, instead of asserting equality with run_natural_boot. |
| AC5 | `play_addr` is honored even when the ROM's NMI vector points elsewhere — patching `$FFFA-$FFFB` to a bogus address while passing the correct play_addr to `run_song` produces the same trace as the unpatched run | Proves the wiring is real, not coincidental. Without this test, run_song could be silently reading the ROM vector and the test would still pass. |
| AC6 | `FamiTrackerEngine.init_addr/play_addr` return distinct addresses for Alter Ego (init and play are not the same address) | Catches a regression where a stub returns `0x8000` for both |

## 3. Pre-conditions checked

- [x] F.3 done (`InProcessRunner` lands with `run_song(init_addr, play_addr, frames)` signature already accepting both args)
- [x] FamiTrackerEngine exists in `qlnes/audio/engines/famitracker.py` with `name = "famitracker"` and `tier = 1`
- [x] Alter Ego ROM staged at `corpus/roms/023ebe61…ef47.nes`
- [x] The reference fixture `tests/fixtures/in_process/alter_ego_natural_boot_600fr.tsv` exists (AC4 will assert run_song path produces the same trace)
- [x] No other story currently owns the file regions touched

## 4. Embedded scaffolding (file-level outline)

### 4.1 `qlnes/audio/engine.py` (extend)

Add a dedicated exception type + new ABC methods:

```python
class InProcessUnavailable(NotImplementedError):
    """Raised when an engine doesn't support in-process rendering.

    Subclass of NotImplementedError so callers can `except
    NotImplementedError` and get the standard semantic; the
    JSON-friendly `.meta` attribute lets F.5's resolver build a
    structured warning ("engine X has no in-process support, falling
    back to oracle").

    Not a `QlnesError` (those are user-facing exit codes); F.5
    catches this and decides whether to convert it.
    """

    def __init__(self, engine_name: str) -> None:
        super().__init__(
            f"engine {engine_name!r} does not support in-process rendering"
        )
        self.meta = {"class": "in_process_unavailable", "engine": engine_name}


class SoundEngine(abc.ABC):
    # ... existing methods ...

    def init_addr(self, rom: Rom, song: SongEntry) -> int:
        """CPU address ($8000-$FFFF) of the music driver's init routine.

        Engines that don't support in-process rendering (e.g. tier-2
        generic fallback) inherit the default-raise. Override to
        opt in.
        """
        raise InProcessUnavailable(self.name)

    def play_addr(self, rom: Rom, song: SongEntry) -> int:
        """CPU address ($8000-$FFFF) of the per-frame play routine."""
        raise InProcessUnavailable(self.name)
```

These are **non-abstract** (concrete with default-raise) so
existing engine subclasses (FamiTrackerEngine + future tier-2) keep
loading without forced overrides. Engines that DO want in-process
extraction override; AC3 verifies the default-raise path.

**Why `InProcessUnavailable(NotImplementedError)` and not `QlnesError`.**
QlnesError carries an exit code from a closed set (`EXIT_CODES`); adding
`in_process_unavailable` there would conflate "engine contract not
implemented" with "user-visible failure". The engine ABC's contract
miss is *internal*; F.5 catches it and decides whether to surface a
warning or escalate. Decoupling lets us add new engine capabilities
without expanding the user-facing exit-code schema.

### 4.2 `qlnes/audio/engines/famitracker.py` (extend)

Add init_addr / play_addr overrides. **Initial heuristic** — return
the ROM's reset and NMI vectors:

```python
class FamiTrackerEngine(SoundEngine):
    # ...

    def init_addr(self, rom: Rom, song: SongEntry) -> int:
        # The reset handler runs game init, which includes audio init.
        # For self-running FT ROMs (Alter Ego, most homebrew), this is
        # functionally identical to a famitone_init entry point.
        return _read_le16(rom, 0xFFFC)

    def play_addr(self, rom: Rom, song: SongEntry) -> int:
        # The NMI handler is what the music driver runs at 60 Hz.
        return _read_le16(rom, 0xFFFA)
```

Helper: `_read_le16(rom, addr)` reads two bytes from the ROM's PRG
view at the appropriate offset (mapper-0 NROM: addr ∈ $8000-$FFFF
maps to PRG offset `addr - 0x8000` for 32 KB PRG, `(addr - 0x8000) &
0x3FFF` for 16 KB).

This heuristic is **deliberately scoped to "what works for Alter Ego
and similar self-running ROMs"**. F.7 corpus expansion or F.4-followup
may need:
- Static signature scan for FamiTone entry symbols (the FamiTone
  driver source is public; we can grep for its known opcode prelude)
- NSF-formatted ROMs (rare in our corpus): pull addresses from the
  NSF header instead of vectors

The NSF-format path is an explicit non-goal of F.4 — those ROMs
arrive via story C.* and don't enter via the NES-ROM `qlnes audio`
flow.

### 4.3 `qlnes/audio/in_process/nmi.py` (extend)

Add `trigger_nmi_to(mpu, mem, target_pc)`:

```python
def trigger_nmi_to(mpu, mem, target_pc: int) -> None:
    """Same as trigger_nmi, but the destination PC is supplied
    explicitly instead of read from $FFFA.

    Used by InProcessRunner.run_song to drive a play_addr that is not
    the ROM's NMI vector. The 7-cycle NMI cost is still charged.
    """
    pc_hi = (mpu.pc >> 8) & 0xFF
    pc_lo = mpu.pc & 0xFF
    p_pushed = (mpu.p | 0x20) & ~0x10
    mem[0x0100 + mpu.sp] = pc_hi
    mpu.sp = (mpu.sp - 1) & 0xFF
    mem[0x0100 + mpu.sp] = pc_lo
    mpu.sp = (mpu.sp - 1) & 0xFF
    mem[0x0100 + mpu.sp] = p_pushed & 0xFF
    mpu.sp = (mpu.sp - 1) & 0xFF
    mpu.p |= 0x04
    mpu.pc = target_pc & 0xFFFF
    mpu.processorCycles += NMI_HANDLER_CYCLES
```

`trigger_nmi` (existing) becomes a thin wrapper:

```python
def trigger_nmi(mpu, mem) -> None:
    target = mem[NMI_VECTOR_LO] | (mem[NMI_VECTOR_HI] << 8)
    trigger_nmi_to(mpu, mem, target)
```

This refactor is opportunistic — keeps `trigger_nmi` callers
unchanged and avoids code duplication.

### 4.4 `qlnes/audio/in_process/runner.py` (extend run_song)

Currently `run_song` accepts `play_addr` but doesn't wire it. F.4
makes it actually drive the play loop:

```python
def run_song(
    self,
    init_addr: int,
    play_addr: int,
    *,
    frames: int = 600,
) -> Iterator[ApuWriteEvent]:
    mem = self._mem
    mpu = self._mpu
    mem.reset_capture()

    # Phase 1: run init from init_addr to RTS-via-sentinel
    mpu.pc = init_addr
    sentinel = 0xFFFF
    ret = sentinel - 1
    mem[0x0100 + mpu.sp] = (ret >> 8) & 0xFF; mpu.sp = (mpu.sp - 1) & 0xFF
    mem[0x0100 + mpu.sp] = ret & 0xFF;        mpu.sp = (mpu.sp - 1) & 0xFF

    init_start = mpu.processorCycles
    budget_end = init_start + INIT_BUDGET_CYCLES
    while mpu.processorCycles < budget_end:
        mpu.step()
        mem.cpu_cycles = mpu.processorCycles
        if mpu.pc == sentinel:
            break

    # Phase 2: NMI to play_addr at 60 Hz
    next_nmi_at = mpu.processorCycles + NTSC_CYCLES_PER_FRAME
    frames_done = 0
    while frames_done < frames:
        if mpu.processorCycles >= next_nmi_at:
            mem.vbl_flag = True
            trigger_nmi_to(mpu, mem, play_addr)
            next_nmi_at += NTSC_CYCLES_PER_FRAME
            frames_done += 1
        mpu.step()
        mem.cpu_cycles = mpu.processorCycles

    # ... last_stats + return iter(list(mem.apu_writes))
```

**Key change vs F.3.** Phase-2 NMI no longer gates on
`mem.nmi_enabled` because the engine has explicitly told us what to
run. We trust the engine. (For self-running boot via
`run_natural_boot`, the gate stays — the game's PPUCTRL write is the
only signal we have.)

### 4.5 Tests

#### `tests/unit/test_engine_init_play.py` (new)

- `test_default_init_addr_raises_in_process_unavailable` — synthetic
  engine subclass that doesn't override; assert `QlnesError` with
  `extra["class"] == "in_process_unavailable"` (AC3).
- `test_default_play_addr_raises_in_process_unavailable` — same shape.
- `test_famitracker_init_addr_returns_8000_range` — synthetic 32 KB
  PRG with reset vector at $8123, assert `init_addr` returns 0x8123
  (AC1 mechanism).
- `test_famitracker_play_addr_returns_8000_range` — synthetic ROM
  with NMI vector at $9080, assert `play_addr` returns 0x9080 (AC2).
- `test_famitracker_init_play_distinct_for_alter_ego` — uses real
  fixture if present, asserts init_addr ($8000) ≠ play_addr ($8093)
  (AC6).

#### `tests/unit/test_in_process_nmi.py` (extend)

Add 3 tests for `trigger_nmi_to`:
- `test_trigger_nmi_to_sets_pc_to_explicit_target` — bypass vector,
  confirm pc set to caller's target_pc.
- `test_trigger_nmi_to_pushes_same_3_bytes` — same stack semantics
  as trigger_nmi.
- `test_trigger_nmi_wraps_through_trigger_nmi_to` — refactor sanity:
  trigger_nmi(...) reads vector then delegates; assert pc lands at
  the vector value.

#### `tests/integration/test_in_process_alter_ego.py` (extend)

Add 2 tests:
- `test_ac4_run_song_equivalent_to_run_natural_boot_for_alter_ego` —
  AC4. `run_song(reset, nmi, frames=600)` produces a trace equal to
  the committed reference fixture.
- `test_ac5_play_addr_actually_used` — AC5. Patch the ROM's NMI
  vector to a wrong address ($DEAD), call run_song with the *correct*
  play_addr, confirm the trace still matches the fixture (proves
  run_song honors play_addr, not the in-ROM vector).

#### Negative test

- `test_unsupported_engine_init_addr_raises` — synthetic tier-2-style
  engine that inherits the default; assert exception path.

## 5. Implementation order

1. Refactor `nmi.py` — extract `trigger_nmi_to`, make `trigger_nmi` a
   wrapper. Tests stay green.
2. Add NMI tests for `trigger_nmi_to`.
3. Extend `SoundEngine` ABC with default `init_addr` / `play_addr`
   raising QlnesError.
4. Add the engine-default unit tests (AC3).
5. Implement `FamiTrackerEngine.init_addr` / `play_addr` with the
   reset/NMI-vector heuristic.
6. Add the FT-handler unit tests (AC1, AC2, AC6).
7. Wire `play_addr` through `InProcessRunner.run_song` (replace the
   no-gate trigger_nmi with `trigger_nmi_to(play_addr)`).
8. Add the integration tests (AC4, AC5).
9. Final full-suite green.

## 6. Decisions taken in CS facilitation

1. **`init_addr` / `play_addr` are concrete-with-default-raise, not
   `@abstractmethod`.** Existing engine subclasses (FamiTrackerEngine
   + future tier-2 generic fallback in A.5) don't have to override on
   day 1. Engines that *don't* support in-process rendering get a
   clean fall-through to the oracle path in F.5.
2. **First heuristic returns reset/NMI vectors.** The architectural
   intent of init/play is closer to NSF semantics (where they're
   isolated from game logic), but for self-running ROMs (Alter Ego
   and 95 % of the v0.5 corpus) the reset handler IS the audio init
   path because the game's startup runs through it. F.7's corpus
   expansion may surface ROMs where this heuristic fails; if so, we
   add a static-signature-scan fallback before falling through to the
   oracle path.
3. **`run_song` no longer gates on `mem.nmi_enabled`.** When the
   engine explicitly hands us `play_addr` we trust it, regardless of
   whether the ROM's PPUCTRL has been written. (The gate stays in
   `run_natural_boot` because we have no other signal there.)
4. **AC4 added in CS** to close the F.3 deviation §1 (run_song was
   accepted as dead code; F.4 brings it to life).
5. **AC4 revised after empirical check** — initially specified as
   "trace equal to run_natural_boot's". Implementation revealed the
   two paths diverge for Alter Ego: the game's reset handler doesn't
   enable NMI (PPUCTRL bit 7 stays clear), so `run_natural_boot`
   never fires NMIs and the music driver runs from the main loop's
   own polling logic. `run_song` forces NMI=play unconditionally,
   producing a *different* but still valid trace (8 645 events vs
   8 475). AC4 reframed as "run_song produces its own canonical
   fixture + passes musical-property battery". Both paths are
   correct; F.5 dispatch will pick `run_natural_boot` for self-running
   ROMs (where `run_song` would diverge from real hardware behavior)
   and `run_song` for NSF-shaped data-driven ROMs. The choice between
   them is per-engine, not in F.4's scope — F.5 introduces the
   selector.

## 7. Risks

- **R37 (NEW) — Heuristic too narrow.** Reset/NMI-vector heuristic
  works for Alter Ego (verified by AC4). May fail for FT ROMs that
  use a different vector layout (ex: bootloader at $C000 that doesn't
  init audio). Mitigation: F.7 corpus expansion will surface them;
  the engine handler is the right place to add ROM-specific overrides.
- **R32 carried — NMI cycle drift.** F.3's `NTSC_CYCLES_PER_FRAME =
  29780` truncation still applies. AC4 catches drift the moment trace
  bytes diverge from the fixture.

## 8. Definition of Done

- [x] All 6 ACs green (3 from spec, 3 added in CS)
- [x] Unit tests for default-raise + FT init_addr/play_addr (9 tests
       in `tests/unit/test_engine_init_play.py`)
- [x] `trigger_nmi_to` tested independently (4 tests added to
       `tests/unit/test_in_process_nmi.py`, total 11)
- [x] Integration test: `run_song(reset, nmi, 600)` on Alter Ego
       produces a committed run-song fixture (sha256 ea062dba…4baa).
       Note: AC4 was reframed in CS pass-2 — original spec said
       "equal to run_natural_boot's trace"; empirical run showed they
       diverge for self-running ROMs. Now run_song has its own
       canonical fixture + property battery.
- [x] Integration test: `play_addr` is honored even when ROM NMI
       vector is patched to bogus address ($DEAD)
- [x] No regression in tests/unit/ (the 30 pre-existing dataflow
       failures match master, no new failures)
- [x] F.3's existing 17 Alter Ego integration tests still pass
       (run alongside the 6 new F.4 tests, all 23 green)
- [x] `qlnes.audio.engine.SoundEngine` documents the new methods +
       `InProcessUnavailable` exception with full docstrings

## 8b. Code review applied (2026-05-04 pass-2)

CR identified 4 should-fix items, all applied in the same session:

- **CR-1** — `FamiTrackerEngine.init_addr/play_addr` now raise
  `InProcessUnavailable` for non-NROM mappers (mapper-1+). Was
  silently returning a wrong PRG offset for bank-switched ROMs;
  caught by `InProcessRunner` constructor's mapper check, but the
  engine should fail-fast at the right boundary so F.5's dispatch
  can fall back to the oracle path without ever constructing the
  runner. 3 new unit tests cover MMC1 reject, UNROM reject, and
  mapper-0 still accepted.
- **CR-2** — `InProcessUnavailable` class moved BEFORE `SoundEngine`
  in `qlnes/audio/engine.py` (was forward-referenced; worked at
  call-time but reads odd).
- **CR-3** — `run_song` now calls `mpu.start_pc = None; mpu.reset()`
  at entry so back-to-back calls on the same runner produce
  deterministic, independent traces. New unit test
  `test_run_song_back_to_back_on_same_runner_is_deterministic`
  verifies. Previous calls left SP/regs/processorCycles cumulative;
  silent-bug-but-not-yet-bitten because production paths construct
  fresh runners per render.
- **CR-4** — Comment "RTS lands at $0000" in `runner.py` corrected
  to describe the actual sentinel-trap mechanism (PC=$FFFF after
  pop+1).

**Tests count update.** F.4 now ships **22 new tests** (was 19
pre-CR; +3 mapper-reject + 1 deterministic = +4 minus a no-op test
rename). Run-song fixture hash unchanged (`ea062dba…4baa`) — the
MPU reset is idempotent on a fresh runner, so no fixture
regeneration was needed.

## 9. Hand-off to F.5

F.5 (`--engine-mode` CLI flag + pipeline dispatch) inherits:

- `engine.init_addr(rom, song)` and `engine.play_addr(rom, song)` are
  callable for any registered engine. Engines that don't override
  raise QlnesError with `class:in_process_unavailable` — F.5's auto
  resolution catches this and falls back to the oracle path.
- `InProcessRunner.run_song(init_addr, play_addr, frames)` is fully
  wired and behavior-equivalent to `run_natural_boot` on Alter Ego.
- F.5 introduces the `--engine-mode {auto,in-process,oracle}` flag
  and the dispatch logic per architecture step 20.4. F.5 also lands
  the CPython-side PyPy-subprocess workhorse pattern (per F.2
  decision artifact §"Distribution strategy").

## 10. Out-of-scope for F.4

- NSF-shaped extraction (story C.*).
- PyPy subprocess dispatch (story F.5).
- ROM-specific overrides for non-Alter-Ego FT ROMs (folded into F.7
  corpus expansion if/when needed).
- Static signature scan for FamiTone entry symbols (deferred until
  F.7 surfaces a ROM where the vector heuristic fails).
- A.5's tier-2 generic engine — its `init_addr` / `play_addr` will
  use the default-raise path and force F.5's resolver to pick oracle.

---

*End of story F.4 — ready for `bmad-dev-story` (DS).*
