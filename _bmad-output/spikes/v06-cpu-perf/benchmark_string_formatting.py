"""benchmark_string_formatting.py — pick the fastest way to format strings.

Compares 5 idioms across 4 representative scenarios (1 small int arg,
3 mixed args, repeated wrapping, pre-conditional logger calls):

  1. f-string         — `f"foo {x}"` (compiled at parse time)
  2. printf %s        — `"foo %s" % x` (legacy, runtime parse)
  3. str.format()     — `"foo {}".format(x)` (parses templates at runtime)
  4. concatenation +  — `"foo " + str(x)` (builds intermediates)
  5. join             — `"".join(["foo ", str(x)])` (one alloc)
  6. logger deferred  — `logger.info("foo %s", x)` (formats only on emit)

The logger-deferred case is special: the message is NEVER formatted
when the logger's level is above the call's level. This is the
canonical Python-logging recommendation (PEP 282 + cpython docs).

Methodology — same as `benchmark_runtimes.py`:
  - WARMUP=3 untimed runs to stabilize caches
  - N_REPS=5 timed runs via `time.perf_counter_ns`
  - Report min, mean, stddev, geomean across scenarios
  - Geomean per Fleming & Wallace 1986

Run:
    .venv-spike/bin/python _bmad-output/spikes/v06-cpu-perf/benchmark_string_formatting.py
"""
from __future__ import annotations

import io
import logging
import math
import statistics
import time

WARMUP = 3
N_REPS = 5
ITERATIONS = 1_000_000  # per timed run


# -- Scenario 1: 1 simple int argument -----------------------------------


def s1_fstring() -> int:
    x = 42
    s = ""
    for _ in range(ITERATIONS):
        s = f"value={x}"
    return len(s)


def s1_percent() -> int:
    x = 42
    s = ""
    for _ in range(ITERATIONS):
        s = "value=%s" % x
    return len(s)


def s1_format() -> int:
    x = 42
    s = ""
    for _ in range(ITERATIONS):
        s = "value={}".format(x)
    return len(s)


def s1_plus() -> int:
    x = 42
    s = ""
    for _ in range(ITERATIONS):
        s = "value=" + str(x)
    return len(s)


def s1_join() -> int:
    x = 42
    s = ""
    for _ in range(ITERATIONS):
        s = "".join(["value=", str(x)])
    return len(s)


# -- Scenario 2: 3 mixed args (str + int + float) ------------------------


def s2_fstring() -> int:
    name = "famitracker"
    n = 600
    rate = 1.93
    s = ""
    for _ in range(ITERATIONS):
        s = f"engine={name} frames={n} ratio={rate}"
    return len(s)


def s2_percent() -> int:
    name = "famitracker"
    n = 600
    rate = 1.93
    s = ""
    for _ in range(ITERATIONS):
        s = "engine=%s frames=%d ratio=%.2f" % (name, n, rate)
    return len(s)


def s2_format() -> int:
    name = "famitracker"
    n = 600
    rate = 1.93
    s = ""
    for _ in range(ITERATIONS):
        s = "engine={} frames={} ratio={:.2f}".format(name, n, rate)
    return len(s)


def s2_plus() -> int:
    name = "famitracker"
    n = 600
    rate = 1.93
    s = ""
    for _ in range(ITERATIONS):
        s = "engine=" + name + " frames=" + str(n) + " ratio=" + f"{rate:.2f}"
    return len(s)


# -- Scenario 3: repeated short wrapping (logger-line shape) -------------


def s3_fstring() -> int:
    rom = "alter_ego.nes"
    cycles = 12345
    s = ""
    for _ in range(ITERATIONS):
        s = f"→ rendu in-process: {rom} ({cycles} cycles)"
    return len(s)


def s3_percent() -> int:
    rom = "alter_ego.nes"
    cycles = 12345
    s = ""
    for _ in range(ITERATIONS):
        s = "→ rendu in-process: %s (%d cycles)" % (rom, cycles)
    return len(s)


# -- Scenario 4: logger calls (the F.5 migration's actual pattern) -------
#
# This is the scenario that matters for qlnes specifically. Two
# patterns:
#   A) `logger.info(f"... {x} ...")` — the f-string is built BEFORE
#      logger.info gets a chance to check the level. If level filters
#      out the message, the work was wasted.
#   B) `logger.info("... %s ...", x)` — logger checks level FIRST;
#      formatting happens only if the message is actually emitted.
#
# Pattern (B) is canonical Python (PEP 282, logging cookbook). The
# benchmark runs both at WARNING level (so INFO calls are filtered)
# to expose pattern (A)'s waste.


def _make_logger_at_warning() -> logging.Logger:
    """Logger with level=WARNING; INFO calls are filtered out."""
    logger = logging.getLogger("bench_string_formatting")
    for h in list(logger.handlers):
        logger.removeHandler(h)
    logger.addHandler(logging.StreamHandler(io.StringIO()))  # discard stream
    logger.setLevel(logging.WARNING)
    logger.propagate = False
    return logger


def s4_logger_fstring_filtered() -> int:
    """f-string built every iteration even though INFO is filtered."""
    logger = _make_logger_at_warning()
    rom = "alter_ego.nes"
    cycles = 12345
    for _ in range(ITERATIONS):
        logger.info(f"→ rendu in-process: {rom} ({cycles} cycles)")
    return 0


def s4_logger_deferred_filtered() -> int:
    """%s deferred; format work skipped because INFO is filtered out."""
    logger = _make_logger_at_warning()
    rom = "alter_ego.nes"
    cycles = 12345
    for _ in range(ITERATIONS):
        logger.info("→ rendu in-process: %s (%d cycles)", rom, cycles)
    return 0


# -- Runner --------------------------------------------------------------


SCENARIOS = [
    ("s1 / 1 int / f-string",   s1_fstring),
    ("s1 / 1 int / %s",         s1_percent),
    ("s1 / 1 int / .format()",  s1_format),
    ("s1 / 1 int / +",          s1_plus),
    ("s1 / 1 int / join",       s1_join),
    ("s2 / 3 args / f-string",  s2_fstring),
    ("s2 / 3 args / %s",        s2_percent),
    ("s2 / 3 args / .format()", s2_format),
    ("s2 / 3 args / +",         s2_plus),
    ("s3 / wrap / f-string",    s3_fstring),
    ("s3 / wrap / %s",          s3_percent),
    ("s4 / logger filtered f-string", s4_logger_fstring_filtered),
    ("s4 / logger filtered deferred", s4_logger_deferred_filtered),
]


def measure(name: str, fn) -> dict:
    for _ in range(WARMUP):
        fn()
    times = []
    for _ in range(N_REPS):
        t0 = time.perf_counter_ns()
        fn()
        t1 = time.perf_counter_ns()
        times.append((t1 - t0) / 1e9)
    return {
        "name": name,
        "min_s": min(times),
        "mean_s": statistics.mean(times),
        "stddev_s": statistics.stdev(times),
        "ns_per_iter": min(times) / ITERATIONS * 1e9,
    }


def main() -> None:
    print(f"# String-formatting benchmark — {ITERATIONS:,} iterations × {N_REPS} reps")
    print()
    results = [measure(name, fn) for name, fn in SCENARIOS]
    print("| Scenario | min wall (s) | ns/iter | stddev | rel |")
    print("|---|---:|---:|---:|---:|")
    # Group by scenario prefix to compute relative speed within each
    by_group: dict[str, list[dict]] = {}
    for r in results:
        prefix = r["name"].split(" /")[0]
        by_group.setdefault(prefix, []).append(r)
    for prefix, group in by_group.items():
        baseline = min(r["ns_per_iter"] for r in group)
        for r in group:
            rel = r["ns_per_iter"] / baseline
            print(
                f"| {r['name']} | {r['min_s']:.4f} | "
                f"{r['ns_per_iter']:.1f} | {r['stddev_s']:.4f} | "
                f"{'**1.00×**' if rel == 1.0 else f'{rel:.2f}×'} |"
            )
    print()

    # Geomean across all timed scenarios
    gm = math.exp(sum(math.log(r["min_s"]) for r in results) / len(results))
    print(f"**Geomean min wall:** {gm:.4f} s")


if __name__ == "__main__":
    main()
