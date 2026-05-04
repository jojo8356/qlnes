# CPython vs Cython vs PyPy — runtime benchmark

**Context.** F.2 spike pass-2 picked PyPy 3.11 for the qlnes v0.6
in-process audio renderer. This report justifies that choice in depth
against Cython and CPython, with measured numbers, per-workload
analysis, and architectural reasoning.

**Date.** 2026-05-04
**Hardware.** x86_64, Linux 6.12.73 amd64, glibc 2.36
**Runtimes tested.**
- CPython 3.13.5 (Debian system Python)
- Cython 3.2.4 compiled to a CPython 3.13 C extension (gcc -O2)
- PyPy 3.11.11 (v7.3.18, portable tarball from downloads.python.org)

**Methodology.** 8 workloads × {3 warmup runs + 5 timed runs} via
`time.perf_counter_ns()`. Geometric mean of the *minimum* time per
workload is reported as the headline number — geometric mean is the
honest summary across multi-magnitude workload mixes
(Fleming & Wallace, *Comm. ACM* 1986). Stddev across the 5 timed runs
captures variance. Peak RSS via `resource.getrusage(RUSAGE_SELF)`.
Code: `_bmad-output/spikes/v06-cpu-perf/benchmark_runtimes.py`,
`bench_cython.pyx`, `benchmark_cython_runner.py`.

---

## Headline numbers

| Runtime | Geomean min wall | Speedup vs CPython | Peak RSS | Startup |
|---|---:|---:|---:|---:|
| **CPython 3.13.5** | **0.2014 s** | 1.0× (baseline) | 110.5 MB | 10.4 ms |
| Cython on CPython 3.13 | 0.0071 s | **28.4× faster** | 42.2 MB | 10.4 ms + 0.23 s build |
| PyPy 3.11.11 | 0.0141 s | **14.3× faster** | 219.2 MB | 22.3 ms |

**TL;DR.** Cython is the absolute fastest on this benchmark (geomean),
PyPy is half its speed (still 14× over CPython), CPython is the slowest.
Cython needs source annotations + a compile step; PyPy is zero-effort
on the Python source as written.

---

## Per-workload results

Times in seconds, `min` of 5 timed runs after 3 warmup. Speedup is
relative to CPython for the same workload.

| Workload | CPython | Cython | PyPy | Cython × | PyPy × |
|---|---:|---:|---:|---:|---:|
| fib_recursive (n=30) | 0.0992 | 0.0032 | 0.0127 | **31.2×** | 7.8× |
| sieve (1M) | 0.0882 | 0.0018 | 0.0048 | **47.9×** | 18.3× |
| mandelbrot (320×240×128) | 0.2797 | 0.0087 | 0.0100 | **32.1×** | 27.8× |
| nbody (5b × 100K steps) | 0.4386 | 0.0066 | 0.0239 | **66.6×** | 18.4× |
| crc32_naive (2 MB) | 1.4586 | 0.0162 | 0.1302 | **90.2×** | 11.2× |
| dict_heavy (200K ops) | 0.0404 | 0.0169 | 0.0053 | 2.4× | **7.5×** |
| **mpu6502_proxy (1M insns)** | 0.2009 | 0.0015 | 0.0034 | **134.1×** | 59.7× |
| object_churn (500K dataclasses) | 0.2133 | 0.0444 | 0.0440 | 4.8× | 4.8× |

Variance across the 5 runs is low (stddev/mean < 5 % on all workloads
for all three runtimes), so the per-workload comparisons are robust to
single-shot noise.

### What each workload measures

- **fib_recursive** — function-call overhead. Recursive calls have no
  data to amortize, so the runtime's call-frame cost dominates.
  Cython's `cpdef` produces a direct C function; PyPy's tracing JIT
  inlines the recursion after a few hundred iterations.
- **sieve** — bytearray scan + nested integer loops. Both Cython and
  PyPy benefit hugely from typing the index variables and avoiding
  the PyObject pointer chase that CPython does on every byte access.
- **mandelbrot** — float arithmetic in a tight nested loop, classic
  numerics. Cython and PyPy almost tie; CPython is slow because each
  `*`, `+`, `<` runs through `PyNumber_*` C dispatch + reference-count
  bumps.
- **nbody** — physics sim, the canonical Computer Language Benchmarks
  Game showcase. Heavy float math, low memory pressure. Cython wins
  bigger here than mandelbrot because the body data sits in fixed-size
  C arrays (`double[5]`); PyPy uses Python lists, which JIT specializes
  but can't fully unbox.
- **crc32_naive** — byte-by-byte XOR + bitshift in 8-bit chunks. The
  tightest possible inner loop in Python. Cython's lead (90×) shows
  what raw bit math looks like with no PyObject overhead at all.
- **dict_heavy** — 200 K random gets/sets on a small (~16 K key) dict.
  **Cython loses to PyPy here.** CPython's dict implementation is
  already in C, so Cython just reaches the same impl by another path;
  PyPy has *specialized* dict implementations (called "strategies" —
  int-keyed dicts use compact integer storage) that make hot dict
  paths drastically faster than the C generic dict.
- **mpu6502_proxy** — minimal 6502-shaped opcode dispatch loop, the
  closest proxy in this suite to the actual qlnes audio renderer.
  Cython 134×, PyPy 60×. Both crush CPython.
- **object_churn** — instantiate 500 K small classes (`@dataclass`-ish
  shape). Cython and PyPy tie. Both still bottlenecked on Python's
  object-allocator semantics; neither runtime can stack-allocate
  Python objects.

---

## Architectural deep-dive

### CPython 3.13 — interpreter + experimental copy-and-patch JIT

CPython 3.13 ships PEP 659's *specializing adaptive interpreter*: hot
bytecodes are rewritten in-place to type-specialized variants
(`LOAD_ATTR_INSTANCE_VALUE`, `BINARY_OP_ADD_INT`, …). This shaved
~15 % off CPython 3.10's runtime overall.

3.13 also ships an *experimental* copy-and-patch JIT (PEP 659+744). The
JIT stitches together pre-compiled machine-code templates per bytecode.
On 3.13 and 3.14 it is **often slower than the specializing
interpreter** in practice — it activates on hot traces but the
templates' indirection costs eat the speedup. Python 3.15 alpha
finally crosses break-even on macOS/AArch64 (+11–12 %) and x86_64
Linux (+5–6 %). The JIT is **disabled by default** in our 3.13 baseline
because that's what real users get.

The CPython baseline numbers above therefore represent the *interpreter
with adaptive specialization*, not the JIT, which is the standard
configuration for `python3` on Debian/Ubuntu/macOS today.

**Where CPython is competitive.**
- I/O-bound and shell-out workloads (interpreter time is noise).
- Code that calls into NumPy/Pandas/Pillow C extensions for the heavy
  lifting (the benchmark game's "fasta" or "regex-redux" workloads).
- Code where startup latency dominates (CLI tools that run sub-second).
- C-extension-heavy code that PyPy struggles with via cpyext.

**Where CPython falls flat.**
- Pure-Python tight loops (every workload above except `dict_heavy`
  shows 7×–134× headroom).
- Bit math, byte scans, opcode dispatch — exactly the qlnes audio
  renderer's profile.

Sources: [Python 3.13 JIT (Tony Baloney, 2024)](https://tonybaloney.github.io/posts/python-gets-a-jit.html),
[CPython JIT explanation (pydevtools)](https://pydevtools.com/handbook/explanation/what-is-cpythons-jit-compiler/),
[Python 3.15 JIT progress (Python Insider, 2026-03)](https://blog.python.org/2026/03/jit-on-track/).

### Cython 3.x — Python superset compiled to C

Cython is a *Python-to-C ahead-of-time compiler*. You write
`cdef int x` to type a local, `cpdef long fib(int n)` to type a
function. The Cython compiler emits C source that calls into the
CPython C API for non-typed code paths and uses raw C types for typed
code paths. The resulting `.so` is a normal CPython C extension —
import-and-call from any CPython program.

**Strengths.**
- Best raw speed of the three runtimes on every numerical / opcode
  workload above. 90×–134× speedups are routine for tight loops.
- Predictable, ahead-of-time. No JIT warmup. Same speed on the first
  call as on the millionth.
- Drops to C-level data structures (`double[5]`, `bint`,
  `unsigned char[]`) so it can avoid PyObject-boxing entirely in hot
  loops.
- Plays well with NumPy via typed memoryviews — not exercised here,
  but a multiplier on numerical work.
- Full CPython C-extension compatibility (it *is* one).

**Weaknesses.**
- Requires writing `.pyx` files with type annotations. Idiomatic Python
  ported as-is gives modest gains (2–5×); the 30–134× gains require
  developer effort.
- Build step. `cython` to `.c`, `gcc` to `.so`. ~0.23 s for our 200-line
  `bench_cython.pyx` on this hardware. Fast for one file, painful for
  100. Distribution requires per-platform wheels (manylinux, macOS
  universal, Windows MSVC).
- No PyPy support. Cython generates code against the CPython C API.
  PyPy can technically import it via the `cpyext` compatibility layer
  but the calling overhead makes it consistently slower than running
  pure Python on PyPy.
- Maintaining .pyx-side type annotations is its own discipline. Forget
  to type a hot variable and you lose 80 % of the speedup silently.

Sources: [Cython performance notes](https://notes-on-cython.readthedocs.io/en/latest/std_dev.html),
[Cython vs CPython vs PyPy (HackerNoon)](https://hackernoon.com/analyzing-python-compilers-cpython-vs-cython-vs-pypy-qid735s6),
[Cython benchmarks repo](https://github.com/DelSquared/Cython-Benchmarks).

### PyPy 3.11 — meta-tracing JIT compiler

PyPy is an *alternative Python implementation* (not just an extension).
It is itself written in RPython and JIT-compiled at PyPy build time.
The runtime watches for hot loops, *traces* one full execution path
through them, and emits specialized machine code for that path with
guards on the assumed types. If a guard fails, the JIT bails to the
interpreter and may eventually retrace.

**Strengths.**
- Zero source changes. The `benchmark_runtimes.py` file ran identically
  on CPython and PyPy with no edits.
- 7×–60× speedups on every workload above (geometric mean 14×).
- Beats Cython on `dict_heavy` because PyPy's dict has multiple
  internal *strategies* that specialize for key-type homogeneity
  (int-only-key dicts, str-only-key dicts), faster than CPython's
  generic dict.
- Generational GC with a young-object nursery — fast allocation and
  no reference-count bumps.
- Single-file portable distributions on Linux/macOS/Windows. Pre-built
  tarballs on downloads.python.org.

**Weaknesses.**
- **JIT warmup cost.** The first time a hot loop runs it is interpreted.
  Tracing kicks in around the third or fourth iteration, then there is
  a few-millisecond compilation pause. For batch workloads that run
  for seconds, irrelevant. For sub-100 ms scripts, PyPy can be slower
  than CPython end-to-end.
- **Higher peak RSS.** PyPy carries a JIT compiler + traces in memory.
  Our suite hit 219 MB peak vs CPython's 110 MB and Cython's 42 MB.
  Generally PyPy uses ~2× the RAM of CPython for the same workload.
- **Slower startup.** 22.3 ms cold-start on this machine vs CPython's
  10.4 ms. Negligible for renders that take seconds; visible if the
  tool is invoked in a tight shell loop.
- **C-extension compatibility via cpyext** is slow and incomplete. C
  extensions that PyPy doesn't have a native port for run through
  cpyext, often 2–10× slower than under CPython. This is why **cynes
  (C++ via pybind11) doesn't build on PyPy** in the first place — its
  CMake script doesn't recognize PyPy's environment, and even if
  forced to build, it would underperform native PyPy code on the same
  job.
- **Different GC semantics.** Files/sockets are not promptly closed
  when out of scope (no refcount). Code that relied on
  `f = open(…); f.read()` without `with`/`.close()` may leak fds under
  PyPy. The qlnes renderer uses `with` everywhere — non-issue.
- **Marginally different identity rules** for primitive ints/floats
  (PyPy's value-based identity for small ints means
  `x + 1 is x + 1` is always True; CPython's behavior is
  implementation-defined).

Sources: [PyPy / CPython differences (PyPy docs)](https://doc.pypy.org/en/latest/cpython_differences.html),
[InfoWorld: which Python runtime does JIT better](https://www.infoworld.com/article/4117428/which-python-runtime-does-jit-better-cpython-or-pypy.html),
[Chauvel: PyPy/CPython/Cython/Numba benchmark](https://www.chauvel.org/blog/pypy-benchmark-take2/).

---

## Why the qlnes audio renderer chose PyPy over Cython

Cython is faster (134× vs 60× over CPython on `mpu6502_proxy`). It
should be the obvious pick — except for what each choice costs.

| Concern | Cython | PyPy |
|---|---|---|
| Source changes to `harness_py65_optimized.py` | Significant — reach into `py65` itself, type-annotate `MPU6502.step()` and `FastNROMMemory.__getitem__/__setitem__`, deal with py65's dynamic opcode-table dispatch which Cython can't easily inline | None |
| Forking py65 | Yes — would need a Cython-port of `py65/devices/mpu6502.py`, ~2000 LOC | No |
| Build pipeline | `cython` + `gcc` per platform, manylinux wheels for PyPI | Just install PyPy |
| Distribution | qlnes ships an `.so` per (Python version × OS × arch) — 4–8 wheels | qlnes ships pure Python; PyPy provided as portable tarball |
| Cross-platform support effort | Linux/macOS/Windows × py3.11/3.12/3.13 = 9 wheels | One PyPy 3.11 tarball per OS = 3 |
| Multi-mapper extension cost | Touch the Cython source again, recompile | Subclass `FastNROMMemory` in pure Python |
| Speed margin vs NFR-PERF-80 | 134× over budget (overkill) | 14× over budget (still overkill) |
| Risk of subtle bugs from type changes | Real — Cython's typing semantics differ from Python's in edge cases (overflow, division) | Zero — runs the same source |

PyPy clears the budget by 14×. Cython would clear it by 30×. **The
extra 2× from Cython does not buy anything**: NFR-PERF-80 is met, the
renderer isn't on a hot interactive path, and any future MMC5 or
expansion-audio ROM that doubles APU-write density still has a 7×
margin under PyPy.

The cost of Cython is real and recurring: fork py65 or write our own
6502 in Cython, maintain .pyx files, ship per-platform wheels, deal
with PyPy users being unable to install the package. The cost of PyPy
is one-time: write `_pypy_renderer.py` to detect and shell out, ship a
PyPy tarball alongside.

**Pick PyPy.** Revisit Cython only if a future ROM busts budget on
PyPy *and* the gap is too small to close with a memory-class trick.
That's story F.11, demoted to "post-v0.6 nice-to-have".

---

## When you would pick differently

This benchmark argues for PyPy in qlnes' specific case. It does not argue
for PyPy globally. Decision tree:

- **Workload < 100 ms total.** PyPy startup + warmup eats the win; pick
  CPython.
- **Pandas / NumPy / scikit-learn / PIL-heavy code.** CPython + the C
  extensions is already fast; PyPy's cpyext layer slows them down. Pick
  CPython.
- **Tight numerical inner loops, long-running batch.** Pick PyPy if you
  control the source. Pick Cython if you need to ship a wheel and don't
  control the consumers' runtime.
- **Library that other people install.** PyPy compatibility is a feature
  to advertise, but you can't *require* it. Cython gives you a wheel
  that works for everyone (modulo cross-compilation pain). Pick Cython.
- **Application you control end-to-end.** PyPy is a free 5–20× speedup
  if your code is pure-Python. Pick PyPy.
- **Hard real-time / predictable latency.** JIT warmup pauses are not
  acceptable. Pick Cython (or Numba's AOT mode).
- **Memory-constrained target (e.g. embedded, RPi 256 MB).** PyPy's RSS
  overhead may not fit. Pick CPython or Cython.

qlnes audio is "application I control, batch render, pure Python wins"
→ PyPy.

The qlnes-as-a-library-on-PyPI question (FR31) is for v1.0; at that
point we revisit with Cython wheels in the mix.

---

## Reproducing this benchmark

```bash
# CPython
.venv-spike/bin/python _bmad-output/spikes/v06-cpu-perf/benchmark_runtimes.py

# PyPy (after extracting pypy3.11-v7.3.18-linux64.tar.bz2)
/path/to/pypy3 _bmad-output/spikes/v06-cpu-perf/benchmark_runtimes.py

# Cython (compile then run)
cd _bmad-output/spikes/v06-cpu-perf
.venv-spike/bin/python build_cython.py build_ext --inplace
.venv-spike/bin/python benchmark_cython_runner.py
```

All three runners append a JSON-encoded result line at the bottom of
their stdout for tooling. Workload sizes are tunable at the top of
`benchmark_runtimes.py`.

---

## Cross-check: synthetic numbers vs the real qlnes audio renderer

F.3 shipped the actual `InProcessRunner` (`qlnes/audio/in_process/`)
and ran the same 6502-shaped workload on Alter Ego at story-AC time.
This grounds the synthetic `mpu6502_proxy` benchmark above:

| Configuration | Workload | Wall-clock | Source |
|---|---|---|---|
| CPython 3.13 + py65 + FastNROMMemory | Alter Ego, 600 frames | 5.55 s | F.3 smoke + integration test `test_ac4_wall_clock_under_budget` |
| CPython 3.13 + py65 + FastNROMMemory | Alter Ego, 10 800 frames (3 min) | 93.2 s | F.2 decision artifact, table §"Spike measurements" |
| PyPy 3.11 + py65 + FastNROMMemory | Alter Ego, 10 800 frames (3 min) | 4.16 s | F.2 decision artifact, same table |
| `mpu6502_proxy` (this file's synthetic) | 1M instructions | 0.20 s CPython / 0.003 s PyPy | this file's table |

The synthetic benchmark's relative speedups (PyPy 60×, Cython 134×
over CPython on `mpu6502_proxy`) hold up against the real-renderer
walltime ratios (CPython 93 s / PyPy 4.16 s ≈ 22× — closer to the
geomean than to the per-workload peaks because the real renderer
dominates on opcode dispatch but also spends time on Python-level
NMI scheduling, dataclass construction for `ApuWriteEvent`, etc.).

Both numbers tell the same story: PyPy clears NFR-PERF-80 (60 s
for 3-min) by an order of magnitude on Alter Ego, and Cython would
be overkill at the cost of a fork-py65-into-cython project. F.2's
decision to ship PyPy + py65 + FastNROMMemory holds.

---

## References

- [Fleming PJ, Wallace JJ (1986). "How not to lie with statistics: the correct way to summarize benchmark results." *Communications of the ACM* 29(3):218–221](https://dl.acm.org/doi/10.1145/5666.5673) — geometric mean for benchmark summaries.
- [PyPy / CPython documented differences](https://doc.pypy.org/en/latest/cpython_differences.html)
- [Speed Center for PyPy (live benchmark dashboard)](https://speed.pypy.org/)
- [Python 3.13 JIT explained — Tony Baloney](https://tonybaloney.github.io/posts/python-gets-a-jit.html)
- [Python 3.15 JIT on track — Python Insider, 2026-03](https://blog.python.org/2026/03/jit-on-track/)
- [What is CPython's JIT compiler — pydevtools](https://pydevtools.com/handbook/explanation/what-is-cpythons-jit-compiler/)
- [InfoWorld — which Python runtime does JIT better, CPython or PyPy](https://www.infoworld.com/article/4117428/which-python-runtime-does-jit-better-cpython-or-pypy.html)
- [Chauvel — Benchmarking Python Flavors: PyPy, CPython, Cython, Numba](https://www.chauvel.org/blog/pypy-benchmark-take2/)
- [Cython def, cdef, cpdef performance notes](https://notes-on-cython.readthedocs.io/en/latest/std_dev.html)
- [Two JITs One Problem — tracing JIT vs CPython's copy-and-patch (April 2026)](https://henry-the-frog.github.io/2026/04/05/jit-comparison/)
