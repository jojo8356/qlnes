"""benchmark_cython_runner.py — run the Cython-compiled workloads under
CPython, with the same warmup/N_REPS methodology as benchmark_runtimes.py.

Cython doesn't run on PyPy — its generated code targets CPython's C API
directly. The cpyext compatibility layer technically lets PyPy import
CPython C extensions, but it's slow enough that running Cython on PyPy
would consistently lose to running pure Python on PyPy. So we measure
Cython on CPython only, which is the standard Cython use case.
"""
from __future__ import annotations

import json
import math
import platform
import resource
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import bench_cython as bc  # noqa: E402  — imports the .so

# Mirror the constants in benchmark_runtimes.py exactly
WARMUP = 3
N_REPS = 5
FIB_N = 30
SIEVE_N = 1_000_000
MANDEL_W, MANDEL_H, MANDEL_MAXITER = 320, 240, 128
NBODY_STEPS = 100_000
CRC_NBYTES = 2_000_000
DICT_OPS = 200_000
MPU_INSNS = 1_000_000
OBJ_COUNT = 500_000


WORKLOADS = [
    ("fib_recursive", lambda: bc.fib_recursive(FIB_N)),
    ("sieve", lambda: bc.workload_sieve(SIEVE_N)),
    ("mandelbrot", lambda: bc.workload_mandelbrot(MANDEL_W, MANDEL_H, MANDEL_MAXITER)),
    ("nbody", lambda: bc.workload_nbody(NBODY_STEPS)),
    ("crc32_naive", lambda: bc.workload_crc32(CRC_NBYTES)),
    ("dict_heavy", lambda: bc.workload_dict_heavy(DICT_OPS)),
    ("mpu6502_proxy", lambda: bc.workload_mpu6502_proxy(MPU_INSNS)),
    ("object_churn", lambda: bc.workload_object_churn(OBJ_COUNT)),
]


@dataclass
class Result:
    name: str
    times_s: list[float]
    result: object

    @property
    def min_s(self) -> float: return min(self.times_s)
    @property
    def mean_s(self) -> float: return statistics.mean(self.times_s)
    @property
    def stddev_s(self) -> float:
        return statistics.stdev(self.times_s) if len(self.times_s) > 1 else 0.0


def measure(name, fn) -> Result:
    for _ in range(WARMUP):
        fn()
    times = []
    last = None
    for _ in range(N_REPS):
        t0 = time.perf_counter_ns()
        last = fn()
        t1 = time.perf_counter_ns()
        times.append((t1 - t0) / 1e9)
    return Result(name=name, times_s=times, result=last)


def main():
    rid = f"Cython 3.x on {platform.python_implementation()} {platform.python_version()}"
    print(f"# Benchmark — {rid}")
    print()
    print(f"- Hardware: {platform.machine()} / {platform.system()} {platform.release()}")
    print(f"- Workloads: {len(WORKLOADS)}, warmup={WARMUP}, reps={N_REPS}")
    print()
    print("| Workload | min (s) | mean (s) | stddev (s) | result |")
    print("|---|---:|---:|---:|---|")
    results = []
    for name, fn in WORKLOADS:
        r = measure(name, fn)
        results.append(r)
        print(f"| {r.name} | {r.min_s:.4f} | {r.mean_s:.4f} | {r.stddev_s:.4f} | `{str(r.result)[:32]}` |")
    print()
    gm = math.exp(sum(math.log(r.min_s) for r in results) / len(results))
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    print(f"**Geometric-mean min wall:** {gm:.4f} s")
    print(f"**Peak RSS:** {rss/1024:.1f} MB")
    print()
    payload = {
        "runtime": rid,
        "results": [
            {"name": r.name, "min_s": r.min_s, "mean_s": r.mean_s,
             "stddev_s": r.stddev_s} for r in results
        ],
        "geomean_min_s": gm,
        "peak_rss_kb": rss,
    }
    print("<!-- BENCHMARK_JSON " + json.dumps(payload) + " -->")


if __name__ == "__main__":
    main()
