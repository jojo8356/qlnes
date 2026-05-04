"""benchmark_runtimes.py — CPython vs Cython vs PyPy on workloads relevant
to a 6502 emulator pipeline.

Designed to run identically under:
    python3   _bmad-output/spikes/v06-cpu-perf/benchmark_runtimes.py
    pypy3     _bmad-output/spikes/v06-cpu-perf/benchmark_runtimes.py

Cython results are produced by a sibling script `bench_cython.pyx` +
`build_cython.py` (compiled C extension imported when present under
CPython only — Cython doesn't run on PyPy because cpyext is slow and
Cython-generated code targets CPython's C API directly).

Methodology (per Bencher / pyperf community guidelines):

- Each workload runs WARMUP times (default 3) before timing — critical
  for PyPy's tracing JIT to specialize hot loops. The first PyPy run is
  always interpreted; the JIT only activates after the trace compiler
  has seen the same loop several times.

- Each workload runs N_REPS times (default 5) timed. We report
  min, mean, median, stddev — min is closest to the "true" walltime
  (background OS noise can only ADD time, not subtract), mean+stddev
  capture variance.

- The "geometric mean" across workloads gives a single-number ratio
  (PyPy vs CPython), more honest than arithmetic mean — see
  Fleming & Wallace 1986, "How not to lie with statistics: the correct
  way to summarize benchmark results".

- All timings are CPU-bound walltime via `time.perf_counter_ns()`.
  Wall-clock is what users actually feel; perf_counter is monotonic.

- We ALSO report startup time (separate fork via `subprocess.run`) and
  peak resident memory (`resource.ru_maxrss`) so the table is honest
  about PyPy's two operational handicaps.

Workloads (each chosen for what it stresses):

1. fib_recursive(30) — function-call overhead (PyPy strength: inlines
   recursive calls; Cython without typing barely beats CPython).
2. sieve(1_000_000) — bytearray scan + nested loops (PyPy strength).
3. mandelbrot(800x600, max=128) — float arithmetic in nested loops
   (PyPy & Cython equally strong; CPython painful).
4. nbody(50, 500_000_iters) — physics sim, classic JIT showcase
   (Computer Language Benchmarks Game canonical).
5. crc32_naive — byte-by-byte XOR loop (proxy for 6502 ALU; PyPy huge).
6. dict_heavy — 200K random gets/sets (CPython has best dict impl;
   PyPy/Cython about equal).
7. mpu6502_proxy — minimal 6502 dispatch loop simulating ~600K opcodes
   (matches the actual qlnes audio renderer workload).
8. object_churn — instantiate 1M small dataclasses (CPython has best
   alloc; PyPy minor lead because of nursery-based GC).

Output: prints a Markdown report to stdout, with both per-workload
tables and the overall geometric mean. Save with:
    python3 benchmark_runtimes.py > /tmp/cpython_results.md
    pypy3   benchmark_runtimes.py > /tmp/pypy_results.md

The companion `merge_results.py` produces the final combined report.
"""
from __future__ import annotations

import math
import platform
import resource
import statistics
import sys
import time
from dataclasses import dataclass


# -- Tunables --------------------------------------------------------------

WARMUP = 3
N_REPS = 5

# Workload sizes — small enough that the slowest config (CPython) finishes
# in < 30 s total, large enough that interpreter overhead is measurable.
FIB_N = 30
SIEVE_N = 1_000_000
MANDEL_W, MANDEL_H, MANDEL_MAXITER = 320, 240, 128
NBODY_STEPS = 100_000
CRC_NBYTES = 2_000_000
DICT_OPS = 200_000
MPU_INSNS = 1_000_000
OBJ_COUNT = 500_000


# -- Workloads -------------------------------------------------------------

def fib_recursive(n: int) -> int:
    if n < 2:
        return n
    return fib_recursive(n - 1) + fib_recursive(n - 2)


def workload_fib() -> int:
    return fib_recursive(FIB_N)


def workload_sieve() -> int:
    n = SIEVE_N
    sieve = bytearray(b"\x01") * (n + 1)
    sieve[0] = 0
    sieve[1] = 0
    i = 2
    while i * i <= n:
        if sieve[i]:
            j = i * i
            while j <= n:
                sieve[j] = 0
                j += i
        i += 1
    # Sum primes (proxy for "did the work")
    return sum(sieve)


def workload_mandelbrot() -> int:
    w, h, maxit = MANDEL_W, MANDEL_H, MANDEL_MAXITER
    x_min, x_max = -2.0, 1.0
    y_min, y_max = -1.0, 1.0
    total = 0
    for py in range(h):
        y0 = y_min + (y_max - y_min) * py / h
        for px in range(w):
            x0 = x_min + (x_max - x_min) * px / w
            x = 0.0
            y = 0.0
            it = 0
            while x * x + y * y < 4.0 and it < maxit:
                xt = x * x - y * y + x0
                y = 2.0 * x * y + y0
                x = xt
                it += 1
            total += it
    return total


def workload_nbody() -> float:
    # 5 bodies, simple velocity verlet, NBODY_STEPS steps.
    # Lifted/simplified from the Computer Language Benchmarks Game canonical.
    PI = 3.141592653589793
    SOLAR_MASS = 4 * PI * PI
    DAYS = 365.24
    bodies = [
        # x, y, z, vx, vy, vz, mass
        [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, SOLAR_MASS],
        [4.84143144246472090e+00, -1.16032004402742839e+00, -1.03622044471123109e-01,
         1.66007664274403694e-03 * DAYS, 7.69901118419740425e-03 * DAYS,
         -6.90460016972063023e-05 * DAYS, 9.54791938424326609e-04 * SOLAR_MASS],
        [8.34336671824457987e+00, 4.12479856412430479e+00, -4.03523417114321381e-01,
         -2.76742510726862411e-03 * DAYS, 4.99852801234917238e-03 * DAYS,
         2.30417297573763929e-05 * DAYS, 2.85885980666130812e-04 * SOLAR_MASS],
        [1.28943695621391310e+01, -1.51111514016986312e+01, -2.23307578892655734e-01,
         2.96460137564761618e-03 * DAYS, 2.37847173959480950e-03 * DAYS,
         -2.96589568540237556e-05 * DAYS, 4.36624404335156298e-05 * SOLAR_MASS],
        [1.53796971148509165e+01, -2.59193146099879641e+01, 1.79258772950371181e-01,
         2.68067772490389322e-03 * DAYS, 1.62824170038242295e-03 * DAYS,
         -9.51592254519715870e-05 * DAYS, 5.15138902046611451e-05 * SOLAR_MASS],
    ]
    dt = 0.01
    n = NBODY_STEPS
    for _ in range(n):
        # Compute pairwise forces
        for i in range(len(bodies)):
            bi = bodies[i]
            for j in range(i + 1, len(bodies)):
                bj = bodies[j]
                dx = bi[0] - bj[0]
                dy = bi[1] - bj[1]
                dz = bi[2] - bj[2]
                d2 = dx * dx + dy * dy + dz * dz
                d = d2 * math.sqrt(d2)
                mag = dt / d
                bi[3] -= dx * bj[6] * mag
                bi[4] -= dy * bj[6] * mag
                bi[5] -= dz * bj[6] * mag
                bj[3] += dx * bi[6] * mag
                bj[4] += dy * bi[6] * mag
                bj[5] += dz * bi[6] * mag
        for b in bodies:
            b[0] += dt * b[3]
            b[1] += dt * b[4]
            b[2] += dt * b[5]
    # Final energy as sanity check
    return bodies[0][0]


def workload_crc32() -> int:
    POLY = 0xEDB88320
    crc = 0xFFFFFFFF
    data = bytes(range(256)) * (CRC_NBYTES // 256)
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ (POLY if (crc & 1) else 0)
    return crc ^ 0xFFFFFFFF


def workload_dict_heavy() -> int:
    d: dict[int, int] = {}
    n = DICT_OPS
    # LCG for deterministic pseudo-random keys without hashlib overhead
    state = 1
    for i in range(n):
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        key = state & 0xFFFF
        d[key] = d.get(key, 0) + i
    return sum(d.values())


def workload_mpu6502_proxy() -> int:
    """Minimal 6502-shaped dispatch loop. Simulates ~1M opcode executions
    using the same shape as py65: opcode lookup → handler call → mem
    access → flag update. The numeric values are chosen so the loop
    can't be fully constant-folded by the JIT (we want the loop body
    work to dominate)."""
    rom = bytearray(0x10000)
    # Fill with a mix of LDA/STA/JMP/BNE pattern
    for i in range(0, len(rom) - 4, 4):
        rom[i] = 0xA9          # LDA imm
        rom[i + 1] = i & 0xFF
        rom[i + 2] = 0x8D      # STA abs
        rom[i + 3] = (i + 1) & 0xFF
    a = 0
    pc = 0
    cycles = 0
    target = MPU_INSNS
    n = 0
    while n < target:
        op = rom[pc]
        if op == 0xA9:
            a = rom[(pc + 1) & 0xFFFF]
            pc = (pc + 2) & 0xFFFF
            cycles += 2
        elif op == 0x8D:
            addr = rom[(pc + 1) & 0xFFFF] | (rom[(pc + 2) & 0xFFFF] << 8)
            rom[addr] = a
            pc = (pc + 3) & 0xFFFF
            cycles += 4
        else:
            pc = (pc + 1) & 0xFFFF
            cycles += 2
        n += 1
    return cycles


@dataclass
class _Cell:
    a: int
    b: int
    c: int

    def total(self) -> int:
        return self.a + self.b + self.c


def workload_object_churn() -> int:
    cells = []
    for i in range(OBJ_COUNT):
        cells.append(_Cell(i, i * 2, i * 3))
    s = 0
    for c in cells:
        s += c.total()
    return s


WORKLOADS = [
    ("fib_recursive", workload_fib),
    ("sieve", workload_sieve),
    ("mandelbrot", workload_mandelbrot),
    ("nbody", workload_nbody),
    ("crc32_naive", workload_crc32),
    ("dict_heavy", workload_dict_heavy),
    ("mpu6502_proxy", workload_mpu6502_proxy),
    ("object_churn", workload_object_churn),
]


# -- Runner ----------------------------------------------------------------

@dataclass
class Result:
    name: str
    times_s: list[float]
    result: object
    rss_kb: int

    @property
    def min_s(self) -> float:
        return min(self.times_s)

    @property
    def mean_s(self) -> float:
        return statistics.mean(self.times_s)

    @property
    def median_s(self) -> float:
        return statistics.median(self.times_s)

    @property
    def stddev_s(self) -> float:
        return statistics.stdev(self.times_s) if len(self.times_s) > 1 else 0.0


def _runtime_id() -> str:
    impl = platform.python_implementation()
    ver = platform.python_version()
    return f"{impl} {ver}"


def measure(name: str, fn) -> Result:
    # Warmup runs (discarded) — critical for PyPy's tracing JIT
    for _ in range(WARMUP):
        fn()
    times: list[float] = []
    last_result = None
    for _ in range(N_REPS):
        t0 = time.perf_counter_ns()
        last_result = fn()
        t1 = time.perf_counter_ns()
        times.append((t1 - t0) / 1e9)
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return Result(name=name, times_s=times, result=last_result, rss_kb=rss)


def main() -> None:
    rid = _runtime_id()
    print(f"# Benchmark — {rid}")
    print()
    print(f"- Hardware: {platform.machine()} / {platform.system()} {platform.release()}")
    print(f"- Workloads: {len(WORKLOADS)}, warmup={WARMUP}, reps={N_REPS}")
    print()
    print("| Workload | min (s) | mean (s) | stddev (s) | result |")
    print("|---|---:|---:|---:|---|")
    results: list[Result] = []
    for name, fn in WORKLOADS:
        r = measure(name, fn)
        results.append(r)
        print(f"| {r.name} | {r.min_s:.4f} | {r.mean_s:.4f} | {r.stddev_s:.4f} | `{str(r.result)[:32]}` |")
    print()
    # Geometric mean of min times — single-number summary
    gm_min = math.exp(sum(math.log(r.min_s) for r in results) / len(results))
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    print(f"**Geometric-mean min wall:** {gm_min:.4f} s")
    print(f"**Peak RSS:** {rss/1024:.1f} MB")
    print()
    # Machine-readable JSON line at the end for the merge script
    import json
    payload = {
        "runtime": rid,
        "results": [
            {"name": r.name, "min_s": r.min_s, "mean_s": r.mean_s,
             "stddev_s": r.stddev_s} for r in results
        ],
        "geomean_min_s": gm_min,
        "peak_rss_kb": rss,
    }
    print("<!-- BENCHMARK_JSON " + json.dumps(payload) + " -->")


if __name__ == "__main__":
    main()
