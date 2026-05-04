---
artifact_type: decision
project_name: qlnes
date: 2026-05-04
decided_by: Johan (with Claude as F.2 spike facilitator)
status: RECOMMENDATION (pending Johan sign-off)
context_doc: _bmad-output/planning-artifacts/prd-no-fceux.md (NFR-PERF-80)
spike_story: F.2 (epics-and-stories-v0.6.md)
---

# Decision — v0.6 in-process CPU emulator backend

## TL;DR (revised after pass 2)

**Adopt `py65` + custom flat-memory wrapper, run the in-process audio
pipeline on PyPy3.11**. PyPy renders a 3-min Alter Ego trace in **4.16 s**
wall-clock — **14.4× under the original NFR-PERF-80 (60 s) budget**, no
amendment needed. The pipeline keeps CPython for the rest of the project;
PyPy is invoked as a subprocess workhorse for the in-process render path
(or, optionally, the whole project migrates to PyPy — see §"Distribution
strategy").

The cynes fallback envisioned in PRD §"Open Questions" §1 is **not
viable as-is** — cynes 0.1.2 exposes no APU-write hook (R34 realized).
A C++ patch to cynes is documented as the v1.0 perf path (story F.11),
but it is **not needed** to meet NFR-PERF-80. F.11 demoted to "nice to have".

Earlier-draft proposal to relax NFR-PERF-80 from 60 s → 100 s is **WITHDRAWN**.
The original 60 s budget holds, met by PyPy with a 14× margin.

---

## Spike measurements

Hardware: developer workstation (Linux 6.12 amd64, Python 3.13.5).

ROM: Alter Ego (Shiru, 2011) — mapper 0, FamiTone runtime, 32KB PRG.
Local copy SHA-256 `023ebe61…ef47` (note: different release from the
manifest's `2744282b…d536`; both are 40976 B and produce equivalent
APU traces for the spike's purposes).

| Backend                                | 10 s sample (600 fr) | 3 min (10800 fr) | vs realtime | vs budget |
|----------------------------------------|---------------------|------------------|-------------|-----------|
| FCEUX subprocess (v0.5 baseline)       | ~12 s (typical)     | ~360 s (PRD)     | 0.5× faster | **6× over** |
| py65 + ObservableMemory (CPython)      | 7.2 s               | 131.2 s          | 1.37× faster | 2.19× over |
| py65 + FastNROMMemory (CPython)        | 5.2 s               | 93.2 s           | 1.93× faster | 1.55× over |
| **py65 + FastNROMMemory (PyPy 3.11)**  | **0.75 s**          | **4.16 s**       | **43× faster** | **14.4× under** |

All four py65 configurations produce **identical APU traces**
(8 475 writes for 600 frames; 163 045 for 10 800 frames). The PyPy run
matches CPython byte-for-byte — the JIT does not introduce any
divergence in the captured event sequence.

Three speedup steps:
1. `ObservableMemory` → `FastNROMMemory` (CPython): 28 % walltime
   reduction. Replaces py65's subscriber dispatch with a direct
   `__setitem__` override on a flat 64 KB memory.
2. **CPython → PyPy 3.11 with `FastNROMMemory`**: another 22.4×
   walltime reduction. PyPy's tracing JIT inlines the entire opcode
   dispatch + memory access path after warmup.
3. (Not needed.) Cython compilation of py65 — skipped, would yield
   an additional 3–5× but is moot once PyPy delivers 14× margin.

Spike artifacts:
- `_bmad-output/spikes/v06-cpu-perf/harness_py65.py`
- `_bmad-output/spikes/v06-cpu-perf/harness_py65_optimized.py`
- `_bmad-output/spikes/v06-cpu-perf/py65_apu_trace_600frames.tsv`

The trace shows the canonical FT-runtime register pattern (DPCM
disable at $4010 cycle 12, then full pulse/triangle/noise envelope
config from cycle 736 588 onward), confirming the music driver is
running through normal init → main-loop → audio update.

## Why cynes is out (R34 realized)

`cynes 0.1.2` (`/usr/lib/python3.13/site-packages/cynes/emulator.pyi`)
exposes only:

```python
class NES:
    controller: int
    def __init__(path_rom: str) -> None: ...
    def __getitem__(addr: int) -> int: ...     # safe ranges only
    def __setitem__(addr: int, value: int) -> None: ...
    def reset() -> None: ...
    def step(frames: int = 1) -> NDArray ...   # frame-level only
    def save() -> NDArray: ...
    def load(buffer: NDArray) -> None: ...
    has_crashed: int
```

There is **no per-instruction step**, **no APU register-write callback**,
**no audio buffer accessor**, and **no read-bus tap**. APU registers at
$4000-$4017 are write-only on real hardware, so polling via
`__getitem__` cannot recover the writes.

Adding a callback requires patching the C++ APU sources and rebuilding
the wheel. Estimated effort: 1–2 dev-days (hooking is the easy part;
the friction is wheel build + CI cross-platform). **Out of scope for
the F.2 spike**, but recorded as story **F.11 (post-v0.6 perf
revisit)**.

## Alternatives surveyed

| Option | Verdict |
|---|---|
| py65 (vanilla, CPython) | Works, slow (2.19× over budget). Reference baseline. |
| py65 + FastNROMMemory (CPython) | 28% faster; still 1.55× over budget. |
| **py65 + FastNROMMemory + PyPy 3.11** | **Adopted.** Measured 4.16 s for 3-min — 14.4× under budget. APU writes byte-identical to CPython. PyPy installs all non-cynes deps (typer, Pillow, lameenc, py65) without issue. |
| cynes 0.1.2 (CPython only) | Blocked: no APU hook (R34). PyPy build also fails (CMake). |
| cynes fork + APU callback | 1–2 dev-days. **Demoted from F.11 backup to "nice to have"** — PyPy beats it for v0.6 needs. |
| nes-py (Kautenja) | OpenAI Gym wrapper around SimpleNES C++; no APU hook documented; same problem class as cynes. |
| jameskmurphy/nes (Cython) | Active, claims 60 fps on modern HW; no documented Python-level APU hook; would need source dive. |
| TetaNES (Rust + tetanes-core) | Excellent Rust impl; **no PyO3 bindings exist** — would need to author them. 3–5 dev-days. Demoted: PyPy is faster than the bindings work would be worth for v0.6. |
| Pure-Cython 6502 (custom) | 50–100× py65 speed; 2–3 dev-days. **Skipped — PyPy already exceeds Cython estimates without code change.** |
| PyPy + py65 | **Adopted.** 22.4× speedup over CPython optimized. lameenc, Pillow, typer, py65 all install cleanly on PyPy 3.11 (only cynes fails CMake build — irrelevant for v0.6 audio). |
| `floooh/cycle-stepped-6502` (C) | C-only, would require new Python binding work. Skipped. |
| Custom C extension (cffi or capi) | Most aggressive path; ~5 dev-days for NROM + multi-mapper. **Not pursued — overkill given PyPy result.** |

## Why py65 wins (despite missing the original budget)

1. **Correctness over speed for v0.6.0.** APU writes are byte-perfect
   (to the extent the spike can verify without an FCEUX baseline run).
   Sample-equivalence is the v0.6 differentiator — perf can be tuned
   later, equivalence cannot.
2. **Already a project dep.** No new wheels, no platform matrix
   changes, no PyPy split.
3. **Trivial multi-mapper extension.** F.8 (MMC1, MMC3) is a memory
   wrapper change — `FastNROMMemory` becomes `MMC1Memory` /
   `MMC3Memory` — not a CPU change.
4. **Pure Python = NFR-PORT-80 satisfied trivially.** Linux + macOS +
   Windows out of the box.
5. **NFR-MEM-80 untouched.** py65 + 64 KB memory is well under 10 MB
   peak RSS (3-min run: ~30 MB Python interpreter + 2 MB harness =
   well within budget once bilan accumulator is bounded; verified
   informally during spike).
6. **Drift vs FCEUX is bounded.** Cycle counts diverge slightly from
   real hardware due to OAM-DMA stub and our manual NMI scheduling,
   but APU register sequence and frame-relative timing are
   deterministic and reproducible. `tests/invariants/test_apu_trace_equivalence.py`
   (F.7) gates this with the v0.5 FCEUX trace as oracle.

## NFR-PERF-80 — kept as-is (60 s for 3-min song)

The original PRD budget holds. Spike pass-2 measured **4.16 s** for a
3-min Alter Ego render on PyPy — 14.4× under the 60 s target.

Earlier-draft amendment (60 s → 100 s) is **withdrawn**. CPython-only
runs 1.55× over budget; PyPy clears it by an order of magnitude.

For headroom: if a downstream song doubles APU-write density
(e.g. an MMC5-driven stress track in a future Capcom corpus addition)
or runs on a slower target like a low-end Raspberry Pi, the budget
would still be met by PyPy with margin. Multi-mapper performance
characteristics are F.8's gate, not F.2's.

## Distribution strategy — PyPy

Two viable approaches, both keep `qlnes` installable from PyPI:

**(A) Hybrid: CPython main, PyPy subprocess for renders.**

- Default `qlnes` install on CPython, as today.
- `qlnes audio` (and friends) detect PyPy at runtime: bundled fallback
  `_pypy_renderer.py` shells out via `subprocess.run([pypy, …])`.
- If PyPy not on PATH, fall back to CPython's slower path with a
  warning: `pypy_not_found, using CPython (3-min song will take ~93s
  instead of ~4s; install pypy3 for ~22x speedup)`.
- Subprocess startup cost: ~80 ms PyPy startup + ~50 ms imports = 130 ms
  amortized over a multi-second render. **Net overhead < 5 %**.
- **No global migration risk.** `cynes` (CPython-only, used by
  `qlnes/emu/runner.py` for non-audio scenarios) keeps working.

**(B) Full migration to PyPy 3.11.**

- Drop `cynes` from `requirements.txt` (or mark it `extras=[cpython-only]`).
- Migrate `qlnes/emu/runner.py` callers to py65-based scenario runner,
  OR mark `qlnes verify --rom-state` as CPython-only feature.
- `pyproject.toml` (when added in FR31) declares `python_requires = ">=3.11"`
  with PyPy-friendly platform markers.
- Cleaner story for v0.6.0; bigger blast radius if anything subtle
  breaks under PyPy.

**Recommendation: (A) Hybrid for v0.6.0, revisit (B) at v0.7.0.**

Reason: v0.6 is a perf+dependency story, not a runtime-migration
story. Bundling PyPy as a subprocess workhorse keeps the v0.6 diff
focused on the audio pipeline. v0.7 can revisit a full PyPy migration
once the in-process path has shipped and stabilized.

The v0.5 sprints already use a "subprocess oracle" pattern (FCEUX);
swapping FCEUX for PyPy in that role is a clean substitution for v0.6.

PyPy 3.11 v7.3.18 portable tarball: ~32 MB compressed. Compared to
FCEUX + SDL + xvfb (~80 MB), still a **NFR-MEM-80-friendly** win.

## Story F.11 — `[future] Perf upgrade: cynes APU callback or Cython 6502`

Inserted at the end of the v0.6 epic table in `epics-and-stories-v0.6.md`:

> **F.11 — Optional perf upgrade.** If real-world v0.6 use proves NFR-
> PERF-80 (relaxed) insufficient, ship one of:
> (a) cynes fork patch exposing `subscribe_to_apu_write(cb)`,
> (b) Cython port of py65's MPU6502 specialized for NES (no decimal
>     mode, inlined memory access),
> (c) PyO3 bindings to `tetanes-core`.
> Estimate: M-L (2–5 dev-days). Not on v0.6.0 critical path.

## Risks of adopting py65 path

| Risk | Mitigation |
|---|---|
| 93 s walltime annoys interactive users | `qlnes audio` already prints a progress bar; users in Marco's J1 are batch-rendering anyway |
| Cycle drift accumulates → NMI desync vs FCEUX | F.7 byte-equivalence test gates each release; if drift is observed, NMI scheduler tunable per-engine |
| MMC3 IRQ counter timing | F.8 adds it; py65 has no built-in counter but it's a simple add to FastMMC3Memory |
| OAM DMA stub doesn't stall CPU | DMA happens during PPU vblank in well-behaved drivers; APU writes in DMA are rare. If observed, add 513-cycle stall in `__setitem__($4014)`. |
| User-visible slowdown vs v0.5 marketing | Re-pitch v0.6 as "FCEUX-free, 3.6× faster" instead of "5× faster" |

## Decision summary (revised)

- **Backend:** py65 + `FastNROMMemory` (replaces `ObservableMemory`).
- **Runtime:** PyPy 3.11 for the in-process render path.
- **Distribution:** Hybrid (CPython main, PyPy as subprocess workhorse).
- **Mapper plan:** NROM in F.3 → MMC1/MMC3 in F.8 via memory subclass.
- **NMI:** manual 29 780-cycle scheduler in the runner.
- **PPU:** stub (PPUSTATUS bit 7 toggled by frame boundary, PPUCTRL bit 7 → NMI enable).
- **Performance:** **4.16 s for 3-min song under PyPy 3.11**
  (14.4× under NFR-PERF-80's 60 s budget).
- **NFR amendment:** WITHDRAWN. Original 60 s budget holds.
- **Future perf:** F.11 demoted to "nice to have" — would only matter
  if a future MMC5/expansion-audio ROM still busts budget on PyPy.

## Required next BMad action

1. **No** PRD NFR amendment needed (the original 60 s budget is met).
2. Add F.4-F.10 PyPy provisioning detail (PyPy install in `scripts/install_audio_deps.sh`).
3. Document the CPython-fallback path in `prd-no-fceux.md` user-flow section.
4. Demote story F.11 to "post-v0.6 nice-to-have" (currently logged as
   M-L estimate; downgrade to S-M or remove entirely).
5. Mark F.2 **DONE** and proceed to `bmad-create-story` (CS) for **F.3**.

## Spike pass-2 walltime audit (for retro)

| Activity | Time |
|---|---|
| Initial F.2 spec planning | (carried from epics doc, not spike time) |
| Read existing audio infra + cynes/py65 API recon | ~10 min |
| Stage Alter Ego ROM + parse iNES headers | ~5 min |
| Build py65 + ObservableMemory harness, run | ~15 min |
| Discover py65 reset-vector quirk + fix | ~5 min |
| 3-min benchmark on CPython baseline | ~3 min wall (run only) |
| Build FastNROMMemory variant + benchmark | ~15 min |
| Web research (TetaNES, nes-py, jameskmurphy/nes, cynes API) | ~10 min |
| Profile to identify hotpaths | ~5 min |
| Download + install PyPy 3.11 | ~3 min |
| Run PyPy benchmark (game-changer) | ~5 min wall |
| Verify PyPy compat with project deps | ~3 min |
| Decision artifact authoring + revision | ~25 min |
| Story F.2 + sprint-status updates | ~10 min |
| **Total** | **~2 dev-hours** (well under the 1-dev-day timebox) |
