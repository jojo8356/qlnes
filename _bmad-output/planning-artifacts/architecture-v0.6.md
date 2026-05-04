---
docType: architecture-amendment
parent_architecture: _bmad-output/planning-artifacts/architecture.md
parent_prd: _bmad-output/planning-artifacts/prd-no-fceux.md
date: 2026-05-04
status: draft v2 (post-pivot)
project_name: qlnes-no-fceux
user_name: Johan
amendmentLog:
  - "2026-05-04: pivot from per-engine static walker to in-process Python CPU emulator (option C). See PRD §0."
---

# Architecture Amendment — qlnes v0.6 (In-Process CPU Emulator)

> **Pivot 2026-05-04.** This amendment originally proposed per-engine
> static walkers. After research (see PRD §0), it now proposes an
> in-process Python 6502 CPU emulator that replaces the FCEUX
> subprocess. The previous static-walker amendment (committed earlier
> on 2026-05-04) is superseded by this revision. The static walker
> approach is documented in PRD §0 as "explored, abandoned".

> **Relationship to v0.5 architecture.** This amendment is *additive*.
> v0.5 architecture (architecture.md) remains the contract for v0.5.x.
> This amendment specifies the *delta* that lands in v0.6.0.

---

## Step 20 — In-process CPU emulator pipeline

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
      | InProcessRunner   |      | OracleEngine        |
      | (this amendment)  |      | (existing v0.5)     |
      | py65 / cynes      |      | uses FCEUX subproc  |
      | runs init/play    |      | + Lua trace         |
      +---------+---------+      +----------+----------+
                |                           |
                v                           v
      +---------+---------+      +----------+----------+
      | List[ApuWriteEvent]      |  ApuTrace (FCEUX)   |
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

The key insight: both pipelines feed identical `ApuWriteEvent`
iterators to the unchanged APU emulator. Sample-equivalence is a
property of the EMITTED EVENTS, not of the runtime. v0.5 runs the
ROM under FCEUX subprocess and Lua-captures the events; v0.6 runs the
ROM under a Python CPU emulator in-process and observer-captures the
events.

### 20.2 InProcessRunner contract

```python
class InProcessRunner:
    """Executes a ROM's music driver in-process and yields APU writes.

    No subprocess, no SDL, no X11. Pure-Python (or Cython via cynes).
    """

    def __init__(self, rom: Rom, *, cpu_backend: str = "auto") -> None: ...

    def run_song(
        self,
        init_addr: int,
        play_addr: int,
        *,
        frames: int,
    ) -> Iterator[ApuWriteEvent]:
        """Initialize the music driver via JSR init_addr, then trigger
        NMI 60 times/sec for `frames` frames; play_addr runs in NMI.

        Yields every APU $4000-$4017 write captured by the memory
        observer, with absolute CPU cycle.
        """
```

`cpu_backend` resolution:
- `"auto"` — pick `py65` for pure-Python portability, switch to
  `cynes` if perf benchmark fails (NFR-PERF-80).
- `"py65"` / `"cynes"` — explicit override.

### 20.3 SoundEngine extension

`SoundEngine` ABC gets two new methods (NSF-format-style):

```python
class SoundEngine(abc.ABC):
    # ... existing v0.5 methods ...

    def init_addr(self, rom: Rom, song: SongEntry) -> int:
        """CPU address of the music-driver init routine for `song`."""
        raise NotImplementedError

    def play_addr(self, rom: Rom, song: SongEntry) -> int:
        """CPU address of the per-frame play routine."""
        raise NotImplementedError
```

Engines that don't implement these can't be extracted via in-process
mode. The renderer falls back to oracle (v0.5 path) automatically.

### 20.4 Engine-mode resolution

```
--engine-mode auto    (default)
   ↓
   if engine implements init_addr + play_addr:
       try InProcessRunner; if succeeds → use that
       on failure → fall back to oracle (with warning)
   else:
       → oracle (with warning)
   if oracle not available either:
       → exit 100, no_extraction_path

--engine-mode in-process
   ↓
   force InProcessRunner; fail fast (exit 100) on missing addrs.

--engine-mode oracle
   ↓
   force FCEUX path (v0.5 behavior).
```

### 20.5 Memory map for InProcessRunner (mapper-0 first)

```
$0000-$07FF  CPU RAM (2 KB)            — emulator-managed
$0800-$1FFF  RAM mirrors                — mapped to $0000-$07FF
$2000-$2007  PPU registers              — STUB (vblank=1 always)
$2008-$3FFF  PPU register mirrors       — STUB
$4000-$4017  APU + I/O                  — OBSERVER (capture writes)
$4018-$401F  APU test (rarely used)    — STUB
$4020-$5FFF  Cartridge expansion        — STUB
$6000-$7FFF  PRG-RAM (battery)          — STUB / RAM
$8000-$BFFF  PRG-ROM bank 0             — read-only from rom.prg
$C000-$FFFF  PRG-ROM bank 1 (mirror NROM-128, or bank 1 NROM-256)
```

Mapper-1+ (MMC1/MMC3) require bank-switch logic on writes to specific
PRG addresses. py65 doesn't support this natively — story F.8 lands
mapper support, likely by switching to cynes.

### 20.6 NMI emulation

NES music drivers run from NMI handler at 60.0988 Hz (NTSC). Our
wrapper triggers NMI manually every `CYCLES_PER_FRAME = 29780` CPU
cycles:

```python
def trigger_nmi(mpu, mem):
    nmi_vec = mem[0xFFFA] | (mem[0xFFFB] << 8)
    # Push PC high, low, status (interrupted state)
    mem[0x100 + mpu.sp] = (mpu.pc >> 8) & 0xFF; mpu.sp = (mpu.sp - 1) & 0xFF
    mem[0x100 + mpu.sp] = mpu.pc & 0xFF;        mpu.sp = (mpu.sp - 1) & 0xFF
    mem[0x100 + mpu.sp] = mpu.p | 0x20;         mpu.sp = (mpu.sp - 1) & 0xFF
    mpu.p |= 0x04   # set I flag (mask further interrupts)
    mpu.pc = nmi_vec
```

Then we step the CPU until it RTI's (return-from-interrupt). Loop
`frames` times.

### 20.7 PPU stub strategy

Music drivers occasionally read PPU registers ($2002 vblank flag is
the most common). Our PPU stub returns:
- `$2002 (PPUSTATUS)` → `0x80` (vblank flag set, always)
- All other PPU reads → `0x00`

This bypasses any "wait for vblank" loops cleanly. Risk: a music
driver that depends on more elaborate PPU state hangs (R31). Mitigation:
cycle budget per frame; abort with a clean error.

### 20.8 ApuWriteEvent capture

```python
mem.subscribe_to_write(range(0x4000, 0x4018), self._on_apu_write)

def _on_apu_write(self, addr: int, value: int) -> None:
    self._events.append(ApuWriteEvent(
        cpu_cycle=self.mpu.processorCycles,
        register=addr,
        value=value,
    ))
```

py65's `ObservableMemory.subscribe_to_write` (verified API surface)
provides the hook. cynes does NOT expose APU writes — if we switch to
cynes, we'll need a different capture strategy (likely a fork of
cynes with an exposed callback, or using cynes for CPU + custom APU
mirror in observable memory).

---

## Step 21 — ADRs

| ADR | Decision | Reverse cost |
|---|---|---|
| **ADR-21 (revised)** | In-process Python 6502 CPU emulator replaces FCEUX subprocess for audio extraction. Backend: `py65` first, `cynes` if perf insufficient. Both already in qlnes deps. | Medium — keeping FCEUX oracle fallback in tree allows per-engine rollback. |
| **ADR-22 (revised)** | The in-process emitted APU writes are byte-equivalent to FCEUX traces on the v0.5 corpus. v0.5 oracle remains the historical equivalence anchor. | Low — graceful degradation per ROM. |
| **ADR-23** | bilan v2 schema with `tier-1-in-process` / `tier-1-oracle` per-engine sub-keys. v1 readers fall through gracefully. | Low — versioned schema discipline (v0.5 ADR-10). |
| **ADR-24 (new)** | StaticWalker ABC (committed 2026-05-04) is **deprecated** but kept in tree. No concrete subclass ships. | Zero — unused code path. |

---

## Step 22 — NFR mapping (delta)

| NFR | Mechanism | Verification |
|---|---|---|
| NFR-PERF-80 | In-process CPU emulator + observable APU memory | F.2 spike + `tests/integration/test_audio_perf_in_process.py` |
| NFR-PERF-81 | No subprocess fork | Same test, separate timing assertion |
| NFR-MEM-80 (≤10 MB) | Pure-Python emu has small footprint | `tests/invariants/test_memory_ceiling.py` |
| NFR-PORT-80 | No SDL/X11/PulseAudio dep | CI matrix expansion (Linux + macOS + Windows) |
| NFR-DEP-80 | py65 + cynes are Python wheels only | `tests/integration/test_no_fceux_environment.py` (PATH stripped) |
| NFR-REL-80 | Byte-eq vs v0.5 oracle | `tests/invariants/test_in_process_oracle_equivalence.py` |

---

## Step 23 — Risk Register Delta

(Replaces v0.6 R20-R22 from the previous static-walker amendment.)

| ID | Risk | Mitigation |
|---|---|---|
| R30 (new) | py65 too slow (pure Python) | Spike F.2 measures; switch to cynes if needed (already a dep). |
| R31 (new) | Music driver init reads PPU state we don't simulate | Stub PPU registers; cycle budget per init phase; mark engine oracle-only for affected ROMs. |
| R32 (new) | NMI timing diverges from FCEUX by a few cycles | Tune trigger schedule; byte-eq test catches divergence. |
| R33 (new) | Mapper bank-switching unsupported in py65 | Switch to cynes for non-NROM (mapper 1+). cynes has native mapper support. |
| R34 (new) | cynes lacks public APU-write callback | If cynes path chosen, fork or subscribe via cynes's RAM mirror if exposed. Last resort: hand-roll a minimal CPU emu with the hooks we need. |

---

## Step 24 — Phasing & Story Seams

The v0.6 work fits into one epic (Epic F, revised) with 10 stories.
Sprint plan extends sprints 9-12 of the v0.5 plan.

See `epics-and-stories-v0.6.md` for the per-story breakdown.

---

## Sign-off

This amendment is **READY** for `bmad-create-epics-and-stories` (CE)
at the v0.6 tier. v0.5 architecture stays the production architecture
through v0.5.x.

**Author:** Claude (Opus 4.7), under `bmad-create-architecture`.
**Date:** 2026-05-04 (revised).
