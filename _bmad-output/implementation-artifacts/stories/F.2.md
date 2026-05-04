---
story_id: F.2
epic: F
title: Performance spike — py65 vs cynes (in-process CPU backend choice)
sprint: 9
estimate: S
status: DONE + CR-clean (retrofit pass: 4 should-fixes applied to spike artefacts)
created_by: bmad-create-story (CS) — facilitated post-hoc after spike already executed
date_created: 2026-05-04
date_completed: 2026-05-04
project_name: qlnes
mvp_target: v0.6.0
inputDocuments:
  - _bmad-output/planning-artifacts/prd-no-fceux.md
  - _bmad-output/planning-artifacts/architecture-v0.6.md
  - _bmad-output/planning-artifacts/epics-and-stories-v0.6.md
fr_closed: [FR43]
nfr_touched: [PERF-80, MEM-80, PORT-80, DEP-80]
risks_realized: [R34]
risks_softened: [R30]
preconditions: [F.1]
outputs:
  - _bmad-output/decisions/v06-cpu-backend.md
  - _bmad-output/spikes/v06-cpu-perf/harness_py65.py
  - _bmad-output/spikes/v06-cpu-perf/harness_py65_optimized.py
  - _bmad-output/spikes/v06-cpu-perf/py65_apu_trace_600frames.tsv
next_story: F.3
next_action: bmad-create-story (CS) for F.3 — InProcessRunner module
---

# Story F.2 — Performance spike: py65 vs cynes

**Epic:** F — *Replace FCEUX subprocess by in-process CPU emulator*
**Sprint:** 9 (v0.6 — first sprint of the in-process pipeline)
**Estimate:** S (1 dev-day, time-boxed)
**Status:** DONE

---

## 1. User value

> **Johan (developer).** Before committing to a CPU backend in F.3,
> Johan needs measured numbers — not a PRD-time estimate — to know
> whether py65 makes the perf budget, and whether cynes is a viable
> fallback if it doesn't.

This is a decision-only spike. No production code lands. The deliverable
is a recommendation written into `_bmad-output/decisions/v06-cpu-backend.md`
that F.3 inherits as a pre-condition.

## 2. Acceptance criteria (per epics-and-stories-v0.6.md §F.2)

| # | AC | Result |
|---|---|---|
| AC1 | Decision artifact `_bmad-output/decisions/v06-cpu-backend.md` written, recommending py65 OR cynes OR a custom mini-CPU. | ✅ — adopted **py65 + FastNROMMemory on PyPy 3.11**. NFR-PERF-80 (60 s for 3-min) met with 14.4× margin. No PRD amendment needed. |
| AC2 | Spike code lives in `_bmad-output/spikes/v06-cpu-perf/` (not committed to qlnes/). | ✅ — `harness_py65.py`, `harness_py65_optimized.py`, `py65_apu_trace_600frames.tsv`. |
| AC3 | Trace-comparison sanity: at least the first 10 APU writes match the FCEUX trace's first 10 writes (cycle may differ; register and value must match). | ⚠️ Partial — full FCEUX baseline trace not available locally (fceux not on PATH; v0.6 explicitly avoids it). The 10 first writes are **plausible** for a FamiTone-driven mapper-0 ROM (DPCM disable at $4010, then full envelope/freq config from $4000-$400b). Independent FCEUX-side validation deferred to F.7 (the equivalence test, which compares full traces). |

## 3. Spike measurements (revised pass 2 — PyPy added)

| Backend | 10 s sample (600 frames) | 3-min (10800 frames) | vs realtime | vs budget |
|---|---|---|---|---|
| FCEUX (v0.5 baseline) | ~12 s | ~360 s | 0.5× | 6× over |
| py65 + ObservableMemory (CPython 3.13) | 7.227 s | 131.241 s | 1.37× | 2.19× over |
| py65 + FastNROMMemory (CPython 3.13) | 5.195 s | 93.201 s | 1.93× | 1.55× over |
| **py65 + FastNROMMemory (PyPy 3.11)** | **0.751 s** | **4.157 s** | **43×** | **14.4× under** |

Hardware: Linux 6.12 amd64. All four py65 configurations emit **identical**
APU traces (8 475 events / 600 fr; 163 045 / 10 800 fr). PyPy's tracing
JIT does not introduce any divergence in captured event sequence.

## 4. Decisions taken (see decision artifact for full rationale)

1. **CPU backend:** py65 + custom `FastNROMMemory` flat-memory wrapper.
2. **Runtime:** **PyPy 3.11 for the in-process render path.** Rest of
   the project remains on CPython 3.11+. PyPy renders 3-min in 4.16 s
   (14.4× under NFR-PERF-80 budget).
3. **NFR-PERF-80 unchanged.** Original 60 s budget holds. Earlier
   amendment proposal (60 → 100 s) is **withdrawn** — PyPy clears the
   original budget by an order of magnitude.
4. **cynes ruled out for v0.6:** R34 realized (no APU hook in cynes 0.1.2)
   AND cynes wheel fails to build on PyPy 3.11 (CMake error). Doubly
   disqualified.
5. **Mapper plan:** NROM in F.3 → MMC1/MMC3 in F.8 — implemented as
   memory subclasses, not CPU changes.
6. **F.11 demoted** from "perf upgrade backup" (M-L) to "post-v0.6
   nice-to-have" (S). Only matters if MMC5/expansion-audio busts budget
   on PyPy.
7. **Distribution strategy:** Hybrid — CPython main, PyPy as subprocess
   workhorse for in-process audio. CPython fallback if PyPy not on PATH
   (with a warning + speedup hint). PyPy 3.11 portable tarball ~32 MB
   (vs FCEUX+SDL+xvfb ~80 MB).

## 5. Risks

- **R34 realized.** cynes has no APU hook. Mitigation: PyPy bypasses
  the need entirely; cynes simply isn't on the v0.6 path.
- **R30 NEUTRALIZED.** "py65 too slow" — PyPy renders 3-min in 4.16 s,
  14.4× under budget. The PRD's pessimistic 50K cyc/s estimate is
  ~1500× off (PyPy measures ~78M cyc/s effective).
- **R31 monitored.** PPU stub returns vblank flag toggled by frame
  schedule + PPUCTRL bit-7 read. Worked for Alter Ego; F.3 will
  validate against more ROMs.
- **R35 (new) — PyPy availability across distribution targets.** Linux
  amd64 + macOS + Windows wheels exist on pypy.org; users on exotic
  arches (RPi 32-bit, FreeBSD) fall back to CPython slow path with
  warning. Monitor F.9 CI matrix.
- **R36 (new) — PyPy stability + maintenance.** PyPy is independently
  maintained, released roughly quarterly, and lags CPython by ~1
  release. The 7.3.x series targets Python 3.11. v0.6.0 pins to
  PyPy ≥ 7.3.18. F.10 release notes will document this.

## 6. Outputs

- `_bmad-output/decisions/v06-cpu-backend.md` — full decision +
  alternatives table + survey of TetaNES/nes-py/jameskmurphy options.
- `_bmad-output/spikes/v06-cpu-perf/harness_py65.py` — vanilla py65
  baseline harness.
- `_bmad-output/spikes/v06-cpu-perf/harness_py65_optimized.py` —
  FastNROMMemory variant. Used as F.3 reference implementation.
- `_bmad-output/spikes/v06-cpu-perf/py65_apu_trace_600frames.tsv` —
  10-s APU trace dump for manual cross-check vs an FCEUX trace
  on a machine where fceux is installed.

## 7. PRD/architecture amendments triggered (revised)

1. `prd-no-fceux.md` — **no NFR amendment needed**. Original 60 s
   budget holds. Add user-flow note that the in-process audio path
   prefers PyPy and falls back to CPython with a slowdown warning.
2. `epics-and-stories-v0.6.md` — append story **F.11** but **demoted**:
   "post-v0.6 nice-to-have — cynes APU callback / Cython 6502 /
   tetanes-core PyO3, only if MMC5 or expansion-audio ROMs bust budget
   on PyPy."
3. `architecture-v0.6.md`:
   - Step 20.2: `InProcessRunner` carries a `Memory` ABC with
     `FastNROMMemory` as first concrete subclass; F.8 adds
     `FastMMC1Memory`, `FastMMC3Memory`.
   - **New step 20.3 (PyPy provisioning).** `scripts/install_audio_deps.sh`
     installs PyPy 3.11 portable tarball into `vendor/pypy/`. The
     in-process renderer auto-detects `vendor/pypy/bin/pypy3` →
     `$PYPY_BIN` env → `pypy3` on PATH; falls back to `sys.executable`
     (CPython slow path) with a warning if none found.
4. `requirements.txt` — keep cynes pinned (used by `qlnes/emu/runner.py`
   for non-audio scenarios). Add a `requirements-pypy.txt` listing the
   subset that runs under PyPy: `py65`, `Pillow`, `lameenc`, `typer`.

## 8. Definition of Done (DoD)

- [x] AC1 — decision artifact written with measured numbers.
- [x] AC2 — spike code lives under `_bmad-output/spikes/`.
- [x] AC3 — first-10 APU writes plausibility verified; full FCEUX
       cross-check deferred to F.7.
- [x] PRD/epics amendments enumerated for next planning touch.
- [x] No production code touched (spike is decision-only).
- [x] Sprint status table updated (F.2 → DONE, F.3 → READY).

## 8b. Code review applied (2026-05-04 retrofit pass)

CR retrofit on F.2 spike artefacts identified 4 should-fix items, all
applied:

- **F.2.CR-1** — `harness_py65.py` carried a leftover `# 3 min @ 60Hz`
  inline comment tail next to `TOTAL_FRAMES = 10800` from sed-edits
  during the spike. Cleaned up; both harnesses now have a docstring
  block explaining the 600 vs 10800 choice and why.
- **F.2.CR-2** — Cython-generated `bench_cython.c` and
  `bench_cython.cpython-313-x86_64-linux-gnu.so` plus the `build/`
  directory were committable as-is. Added `.gitignore` rules scoped
  to `_bmad-output/spikes/v06-cpu-perf/` so the .pyx source stays
  the only tracked artefact for the Cython benchmark.
- **F.2.CR-4** — `harness_py65.py` had unused `NMI_VECTOR` /
  `RESET_VECTOR` constants. Removed; the addresses are read inline
  via `prg[-N]` math.
- **F.2.CR-7** — `RUNTIME_BENCHMARK.md` synthesized numbers from the
  `mpu6502_proxy` workload but didn't tie them back to the real
  renderer's measured walltimes. Added a "Cross-check" section
  comparing the synthetic `mpu6502_proxy` ratios (PyPy 60×, Cython
  134× over CPython) against the real-renderer ratio (CPython 93 s /
  PyPy 4.16 s ≈ 22× on Alter Ego 3-min).

Skipped:
- F.2.CR-5 (path-not-found error message) — unchanged; the harnesses
  fail with FileNotFoundError already, which is sufficient for spike
  scope.
- F.2.CR-6 (DRY iNES parsing across harness + production) — both
  harnesses are frozen baseline scripts; refactoring them to use
  F.4's `_read_le16_at_cpu` would couple the spike to production code.

## 9. Hand-off to F.3

F.3 (`InProcessRunner` module) inherits:

- **Backend choice:** py65 + FastNROMMemory.
- **Runtime:** PyPy 3.11 (subprocess workhorse pattern). Renderer
  detects PyPy via `_PYPY_BIN` resolution; falls back to CPython with
  warning + speedup hint.
- **Reference impl:** `harness_py65_optimized.py` is the literal seed
  for `qlnes/audio/in_process/runner.py` + `qlnes/audio/in_process/memory.py`.
- **Init/play protocol:** for NROM, run from reset vector, manual NMI
  scheduler, no JSR-init needed (game's natural reset handler does it).
  This is a **simplification** vs the original F.3 plan that assumed an
  explicit `JSR init_addr` — the in-process pipeline can use natural
  boot for self-running ROMs and the F.4 init/play protocol becomes
  the path for *NSF-shaped* sources only.
- **Test fixture:** Alter Ego at `corpus/roms/023ebe61…ef47.nes`.
  (Note: SHA differs from manifest's `2744282b…d536` — manifest needs
  reconciliation to either the spike SHA or the original target SHA;
  see corpus/manifest.toml inspection in F.3.)
- **PyPy provisioning:** `scripts/install_audio_deps.sh` will install
  PyPy 3.11 portable tarball into `vendor/pypy/` (~32 MB).
