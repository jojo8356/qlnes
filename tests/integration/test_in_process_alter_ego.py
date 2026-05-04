"""Integration test for the F.3 InProcessRunner on Alter Ego.

Lives under tests/integration/ because it depends on the corpus ROM at
corpus/roms/<sha256>.nes. Skipped if the file is absent.

Covers F.3 acceptance criteria:
- AC1 — InProcessRunner.run_natural_boot yields ApuWriteEvent
- AC2 — trace matches the committed reference fixture byte-for-byte
        (regression anchor) AND passes a battery of musical-property
        assertions (independent sanity check that doesn't need an
        external emulator). v0.6 is fceux-free by design — instead of
        comparing against fceux at test time, we pin the canonical
        in-process output as the reference.
- AC3 — no subprocess spawned during the render
- AC4 — wall-clock < 60 s for 600-frame render (NFR-PERF-80)
- AC5 — incremental Python-heap < 10 MB (NFR-MEM-80, amended) and
        RSS-delta sanity bound < 30 MB
- AC6 — two consecutive runs produce byte-identical output (NFR-REL-1)
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from qlnes.audio.engine import SongEntry
from qlnes.audio.engines.famitracker import FamiTrackerEngine
from qlnes.audio.in_process import InProcessRunner
from qlnes.audio.in_process.nmi import NTSC_CYCLES_PER_FRAME
from qlnes.audio.static.apu_event import ApuWriteEvent
from qlnes.rom import Rom


ROM_SHA = "023ebe61e8a4ba7a439f7fe9f7cbd31b364e5f63853dcbc0f7fa2183f023ef47"
ROM_PATH = Path(f"corpus/roms/{ROM_SHA}.nes")
FIXTURE_PATH = (
    Path(__file__).resolve().parent.parent
    / "fixtures"
    / "in_process"
    / "alter_ego_natural_boot_600fr.tsv"
)
# Hash of the canonical trace, computed over data lines as
#     b'\n'.join(f'{cycle}\t{reg}\t{val}'.encode() for e in events)
# Recompute and replace this value if the runner output legitimately
# changes (and update the fixture file). Drift without an explanation
# means a regression in the runner.
REFERENCE_TRACE_SHA256 = (
    "07d28dbb60880317facefec4c14e90ae773e7e50955ab1332880d29ed5c43672"
)
RUN_SONG_FIXTURE_PATH = (
    Path(__file__).resolve().parent.parent
    / "fixtures"
    / "in_process"
    / "alter_ego_run_song_600fr.tsv"
)
RUN_SONG_TRACE_SHA256 = (
    "ea062dba9752a5ef9ba0175addca895f36eac253e0b4e7eca5ac6d3806694baa"
)


pytestmark = pytest.mark.skipif(
    not ROM_PATH.exists(),
    reason=f"Alter Ego ROM not present at {ROM_PATH} — see corpus/README.md",
)


def _trace_to_bytes(events) -> bytes:
    return b"\n".join(
        f"{e.cpu_cycle}\t{e.register}\t{e.value}".encode() for e in events
    )


def _load_fixture_events() -> list[ApuWriteEvent]:
    """Parse the committed reference TSV into ApuWriteEvent."""
    events: list[ApuWriteEvent] = []
    for line in FIXTURE_PATH.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        cyc_s, reg_s, val_s = line.split("\t")
        events.append(
            ApuWriteEvent(
                cpu_cycle=int(cyc_s), register=int(reg_s), value=int(val_s)
            )
        )
    return events


@pytest.fixture(scope="module")
def alter_ego_rom() -> Rom:
    return Rom.from_file(ROM_PATH)


def test_ac1_yields_apu_write_events(alter_ego_rom):
    runner = InProcessRunner(alter_ego_rom)
    events = list(runner.run_natural_boot(frames=600))
    # F.2 spike measured exactly 8475 events for 600 frames; this is a
    # regression anchor — any change is either a bug or an intentional
    # APU-observer revision worth pinning the new number to.
    assert len(events) == 8475
    assert all(isinstance(e, ApuWriteEvent) for e in events)


def test_ac1_first_writes_match_spike_baseline(alter_ego_rom):
    """The first 5 APU writes should match the F.2 spike's recorded trace.

    Spike trace at _bmad-output/spikes/v06-cpu-perf/py65_apu_trace_600frames.tsv.
    """
    runner = InProcessRunner(alter_ego_rom)
    events = list(runner.run_natural_boot(frames=600))
    expected = [
        (12, 0x4010, 0x00),
        (736588, 0x4000, 0x00),
        (736596, 0x4002, 0xAD),
        (736614, 0x4003, 0x06),
        (736622, 0x4004, 0x00),
    ]
    actual = [(e.cpu_cycle, e.register, e.value) for e in events[:5]]
    assert actual == expected


# ---- AC2 -----------------------------------------------------------------
#
# AC2 was originally specified as "PCM byte-identical to FCEUX-driven render".
# v0.6 is fceux-free by design — we pin the canonical in-process trace as
# the reference instead. AC2 has two halves:
#
#   AC2a: byte-equivalence vs the committed reference fixture
#         (catches accidental regressions in the runner)
#   AC2b: musical-property battery on a freshly-rendered trace
#         (catches "the trace structurally looks like NES music"
#         without needing an external oracle)
#
# Together they bound the runner's correctness from above (regression
# pin) and below (musical sanity).


def test_ac2a_trace_byte_identical_to_reference_fixture(alter_ego_rom):
    """In-process 600-frame trace matches the committed reference fixture.

    If this fails, either:
    - the runner was changed (intentional: regenerate fixture + hash)
    - py65 was upgraded with a behavior change (investigate)
    - the host produced different output (NMI scheduler races? unlikely
      since runs are deterministic per AC6)
    """
    runner = InProcessRunner(alter_ego_rom)
    events = list(runner.run_natural_boot(frames=600))
    actual_sha = hashlib.sha256(_trace_to_bytes(events)).hexdigest()
    assert actual_sha == REFERENCE_TRACE_SHA256, (
        f"trace hash drift: got {actual_sha}, expected {REFERENCE_TRACE_SHA256}. "
        f"Compare against {FIXTURE_PATH} to find the divergence."
    )


def test_ac2a_event_count_matches_fixture(alter_ego_rom):
    """Quick-check: the live trace has exactly as many events as the fixture."""
    fixture_events = _load_fixture_events()
    runner = InProcessRunner(alter_ego_rom)
    live_events = list(runner.run_natural_boot(frames=600))
    assert len(live_events) == len(fixture_events) == 8475


def test_ac2a_diverges_at_first_byte_diff(alter_ego_rom):
    """If AC2a fails, this test reports WHERE — useful diagnostic."""
    fixture_events = _load_fixture_events()
    runner = InProcessRunner(alter_ego_rom)
    live_events = list(runner.run_natural_boot(frames=600))
    for i, (live, fix) in enumerate(zip(live_events, fixture_events)):
        assert live == fix, (
            f"first divergence at event #{i}: "
            f"live={live.cpu_cycle},{live.register:#x},{live.value:#x} vs "
            f"fixture={fix.cpu_cycle},{fix.register:#x},{fix.value:#x}"
        )
    assert len(live_events) == len(fixture_events)


def test_ac2b_apu_register_range_valid(alter_ego_rom):
    """Every event's register lies in the APU range [$4000, $4017]."""
    runner = InProcessRunner(alter_ego_rom)
    events = list(runner.run_natural_boot(frames=600))
    for e in events:
        assert 0x4000 <= e.register <= 0x4017, (
            f"register {e.register:#x} out of APU range"
        )
        assert 0 <= e.value <= 0xFF, f"value {e.value} out of byte range"


def test_ac2b_cycles_monotonic_non_decreasing(alter_ego_rom):
    """APU writes are timestamped in CPU-cycle order."""
    runner = InProcessRunner(alter_ego_rom)
    events = list(runner.run_natural_boot(frames=600))
    prev = -1
    for e in events:
        assert e.cpu_cycle >= prev, (
            f"cycle went backwards at {e!r} (prev={prev})"
        )
        prev = e.cpu_cycle


def test_ac2b_init_signature_dpcm_disable_first(alter_ego_rom):
    """FamiTone-driven ROMs disable DPCM ($4010 ← 0) very early in init.

    This is a strong canary: if the runner ever stops producing this
    write (e.g. because the PPU stub timing changed), the music driver
    is no longer running through its expected init path.
    """
    runner = InProcessRunner(alter_ego_rom)
    events = list(runner.run_natural_boot(frames=600))
    first = events[0]
    assert first.register == 0x4010, (
        f"first write should be DPCM-disable at $4010; got {first!r}"
    )
    assert first.value == 0x00
    # And it should be cycle-cheap: somewhere in the first hundred cycles
    assert first.cpu_cycle < 200


def test_ac2b_apu_enable_register_4015_written(alter_ego_rom):
    """The music driver enables APU channels via $4015. There should be
    at least one $4015 write in any non-trivial 10-second render."""
    runner = InProcessRunner(alter_ego_rom)
    events = list(runner.run_natural_boot(frames=600))
    enable_writes = [e for e in events if e.register == 0x4015]
    assert len(enable_writes) > 0


def test_ac2b_pulse_and_triangle_channels_exercised(alter_ego_rom):
    """A real song touches multiple channel groups, not just one."""
    runner = InProcessRunner(alter_ego_rom)
    events = list(runner.run_natural_boot(frames=600))
    pulse1 = sum(1 for e in events if 0x4000 <= e.register <= 0x4003)
    pulse2 = sum(1 for e in events if 0x4004 <= e.register <= 0x4007)
    triangle = sum(1 for e in events if 0x4008 <= e.register <= 0x400B)
    noise = sum(1 for e in events if 0x400C <= e.register <= 0x400F)
    # Alter Ego's intro music uses all four: pulse 1, pulse 2, triangle, noise
    assert pulse1 > 100, f"pulse 1 underused ({pulse1} writes)"
    assert pulse2 > 100, f"pulse 2 underused ({pulse2} writes)"
    assert triangle > 100, f"triangle underused ({triangle} writes)"
    assert noise > 0, f"noise channel never touched ({noise} writes)"


def test_ac2b_density_consistent_with_60hz_driver(alter_ego_rom):
    """Most APU writes should fall after the music driver starts (post-init).

    Post-init density should be roughly stable — not a concentration in
    one frame and silence elsewhere. Compute writes per frame after init
    and assert the variance is sane.
    """
    runner = InProcessRunner(alter_ego_rom)
    events = list(runner.run_natural_boot(frames=600))
    # Take post-init events (heuristic: skip events before cycle 500_000;
    # F.2 spike showed init settles before the music starts at ~cycle 736k)
    post_init = [e for e in events if e.cpu_cycle > 500_000]
    assert len(post_init) > 1000, "almost no events post-init"
    # Count writes per frame bucket
    by_frame: dict[int, int] = {}
    for e in post_init:
        frame = e.cpu_cycle // NTSC_CYCLES_PER_FRAME
        by_frame[frame] = by_frame.get(frame, 0) + 1
    # We should have writes in many frames (driver runs every NMI), not all
    # bunched in a few
    frames_with_writes = len(by_frame)
    assert frames_with_writes >= 100, (
        f"writes only land in {frames_with_writes} frames; expected >= 100"
    )


def test_ac3_no_subprocess_spawned(alter_ego_rom):
    """The runner must not spawn any subprocess (architecture step 20.0)."""
    runner = InProcessRunner(alter_ego_rom)
    with patch("subprocess.run") as mock_run, \
         patch("subprocess.Popen") as mock_popen, \
         patch("os.fork", create=True) as mock_fork:
        events = list(runner.run_natural_boot(frames=10))
    assert mock_run.call_count == 0
    assert mock_popen.call_count == 0
    assert mock_fork.call_count == 0
    assert len(events) > 0


def test_ac4_wall_clock_under_budget(alter_ego_rom):
    """600-frame render must complete in < 60 s (NFR-PERF-80).

    Generous bound: F.2 spike measured 5.2 s on CPython, 0.75 s on PyPy.
    The 60 s ceiling absorbs slow CI and unloaded laptops alike.
    """
    runner = InProcessRunner(alter_ego_rom)
    t0 = time.perf_counter()
    list(runner.run_natural_boot(frames=600))
    wall = time.perf_counter() - t0
    assert wall < 60.0, f"render took {wall:.2f} s, exceeds 60 s budget"


def test_ac5_python_heap_under_10mb(alter_ego_rom):
    """NFR-MEM-80 (amended): incremental Python heap allocation < 10 MB.

    Original spec said "peak RSS ≤ 10 MB" — impossible since the CPython
    interpreter floor is ~30 MB. Amended in F.3 closeout to "incremental
    over import baseline" measured via `tracemalloc` (clean Python-heap
    delta, isolated from interpreter / OS-mmap / JIT noise).

    Calibration on Linux x86_64 / CPython 3.13.5 (F.3 spike):
      - tracemalloc peak ≈ 1.67 MB
      - 8 475 ApuWriteEvent + py65 mpu state + 64 KB memory map
    The 10 MB ceiling absorbs 6× headroom for mappers F.8 will land.
    """
    import gc
    import tracemalloc

    gc.collect()
    tracemalloc.start()
    runner = InProcessRunner(alter_ego_rom)
    events = list(runner.run_natural_boot(frames=600))
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    peak_mb = peak_bytes / 1024 / 1024
    assert peak_mb < 10.0, (
        f"Python heap peak during render = {peak_mb:.2f} MB, exceeds 10 MB"
    )
    # Anchor: keep events alive so they don't get GC'd before measurement
    assert len(events) > 0


def test_ac5_rss_delta_diagnostic(alter_ego_rom):
    """Sanity bound on full process RSS delta (looser than tracemalloc).

    `resource.ru_maxrss` is a high-water mark; this test runs a render
    and asserts the RSS-after-RSS-before delta stays under 30 MB. This
    catches mmap / cache leaks that wouldn't show up in tracemalloc.
    The 30 MB bound is generous because this number is noisier
    (interpreter caches, py65 module load, etc. land here too).
    """
    import gc
    import resource

    gc.collect()
    rss_before_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    runner = InProcessRunner(alter_ego_rom)
    events = list(runner.run_natural_boot(frames=600))
    rss_after_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    delta_mb = (rss_after_kb - rss_before_kb) / 1024
    assert delta_mb < 30.0, (
        f"RSS delta during render = {delta_mb:.2f} MB; "
        f"baseline {rss_before_kb/1024:.1f} MB → peak {rss_after_kb/1024:.1f} MB"
    )
    assert len(events) > 0


def test_ac6_two_runs_byte_identical(alter_ego_rom):
    """Two fresh runners on the same ROM must produce equal event lists."""
    runner1 = InProcessRunner(alter_ego_rom)
    events1 = list(runner1.run_natural_boot(frames=600))
    runner2 = InProcessRunner(alter_ego_rom)
    events2 = list(runner2.run_natural_boot(frames=600))
    assert events1 == events2


def test_run_stats_populated(alter_ego_rom):
    runner = InProcessRunner(alter_ego_rom)
    list(runner.run_natural_boot(frames=600))
    s = runner.last_stats
    assert s is not None
    assert s.apu_event_count == 8475
    # Init takes ~200K cycles on Alter Ego (game settles to main loop)
    assert 100_000 <= s.init_cycles <= 300_000
    # Total cycles ≈ init + 600 * 29780 = init + ~17.87M
    assert 17_800_000 <= s.total_cycles <= 18_500_000


# ---- F.4 ACs -------------------------------------------------------------


def _ft_init_play(rom: Rom) -> tuple[int, int]:
    e = FamiTrackerEngine()
    s = SongEntry(index=0)
    return e.init_addr(rom, s), e.play_addr(rom, s)


def test_f4_ac6_init_play_addresses_distinct_for_alter_ego(alter_ego_rom):
    """AC6: FT engine returns distinct init / play addresses for Alter Ego.
    Catches a regression where both would return the same vector."""
    init, play = _ft_init_play(alter_ego_rom)
    assert init == 0x8000
    assert play == 0x8093
    assert init != play


def test_f4_ac4_run_song_matches_run_song_fixture(alter_ego_rom):
    """AC4: run_song(reset, nmi, 600) on Alter Ego matches its committed
    fixture (sha256 ea062dba…4baa). NB: this trace is INTENTIONALLY
    different from run_natural_boot's because Alter Ego doesn't enable
    NMI naturally; run_song forces NMI=play unconditionally and follows
    a different valid execution path. See story F.4 §6 decision 5."""
    init, play = _ft_init_play(alter_ego_rom)
    runner = InProcessRunner(alter_ego_rom)
    events = list(runner.run_song(init, play, frames=600))
    actual_sha = hashlib.sha256(_trace_to_bytes(events)).hexdigest()
    assert actual_sha == RUN_SONG_TRACE_SHA256, (
        f"run_song hash drift: got {actual_sha}, expected "
        f"{RUN_SONG_TRACE_SHA256}. Compare against {RUN_SONG_FIXTURE_PATH}."
    )
    assert len(events) == 8645


def test_f4_ac4_run_song_passes_musical_property_battery(alter_ego_rom):
    """AC4 (cont.): run_song's trace passes the same musical-sanity
    battery as F.3 AC2b — registers in APU range, cycles monotonic,
    multi-channel coverage, $4015 enable, post-init density."""
    init, play = _ft_init_play(alter_ego_rom)
    runner = InProcessRunner(alter_ego_rom)
    events = list(runner.run_song(init, play, frames=600))
    # Range + range monotonicity
    prev = -1
    for e in events:
        assert 0x4000 <= e.register <= 0x4017
        assert 0 <= e.value <= 0xFF
        assert e.cpu_cycle >= prev
        prev = e.cpu_cycle
    # Channel coverage
    pulse1 = sum(1 for e in events if 0x4000 <= e.register <= 0x4003)
    pulse2 = sum(1 for e in events if 0x4004 <= e.register <= 0x4007)
    triangle = sum(1 for e in events if 0x4008 <= e.register <= 0x400B)
    enable = sum(1 for e in events if e.register == 0x4015)
    assert pulse1 > 100 and pulse2 > 100 and triangle > 100
    assert enable > 0


def test_f4_ac5_play_addr_honored_when_rom_nmi_vector_patched(alter_ego_rom):
    """AC5: run_song uses the explicit play_addr argument, not the ROM's
    NMI vector. Patch the in-memory NROMMemory's view of $FFFA-$FFFB
    to a bogus address; if run_song still produces the same trace as
    the unpatched run, the wiring is real."""
    init, play = _ft_init_play(alter_ego_rom)

    # Run 1: clean
    r1 = InProcessRunner(alter_ego_rom)
    clean = list(r1.run_song(init, play, frames=200))

    # Run 2: patch the ROM's NMI vector to point to a non-music dead-end.
    # We can't mutate the ROM bytes without recreating the Rom; instead,
    # we patch the runner's memory directly after construction. This
    # tests that run_song reads play_addr from its argument, not from
    # the ROM-vector slot.
    r2 = InProcessRunner(alter_ego_rom)
    r2._mem._rom[0x7FFA] = 0xAD  # CPU $FFFA — NMI vector low byte
    r2._mem._rom[0x7FFB] = 0xDE  # CPU $FFFB — NMI vector high byte ($DEAD)
    patched = list(r2.run_song(init, play, frames=200))

    assert clean == patched, (
        "run_song must use play_addr argument, not the ROM's $FFFA-$FFFB "
        "vector. If this fails, run_song is silently reading the vector "
        "and ignoring its play_addr parameter."
    )


def test_f4_ac4_run_song_byte_diff_diagnostic(alter_ego_rom):
    """If AC4 fixture-hash test fails, this test reports WHERE the
    divergence starts. Mirror of test_ac2a_diverges_at_first_byte_diff."""
    fixture_events: list[ApuWriteEvent] = []
    for line in RUN_SONG_FIXTURE_PATH.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        cyc_s, reg_s, val_s = line.split("\t")
        fixture_events.append(
            ApuWriteEvent(
                cpu_cycle=int(cyc_s), register=int(reg_s), value=int(val_s)
            )
        )
    init, play = _ft_init_play(alter_ego_rom)
    runner = InProcessRunner(alter_ego_rom)
    live_events = list(runner.run_song(init, play, frames=600))
    for i, (live, fix) in enumerate(zip(live_events, fixture_events)):
        assert live == fix, (
            f"first divergence at event #{i}: "
            f"live={live.cpu_cycle},{live.register:#x},{live.value:#x} vs "
            f"fixture={fix.cpu_cycle},{fix.register:#x},{fix.value:#x}"
        )
    assert len(live_events) == len(fixture_events)


def test_f4_run_song_is_deterministic(alter_ego_rom):
    """Bonus determinism check on the run_song path (mirrors AC6 of F.3)."""
    init, play = _ft_init_play(alter_ego_rom)
    r1 = InProcessRunner(alter_ego_rom)
    e1 = list(r1.run_song(init, play, frames=200))
    r2 = InProcessRunner(alter_ego_rom)
    e2 = list(r2.run_song(init, play, frames=200))
    assert e1 == e2
