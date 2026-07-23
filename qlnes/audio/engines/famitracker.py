"""FamiTracker / 0CC-FamiTracker engine handler — tier-1 sample-equivalent target.

A.1 scope. This handler ships:
  - `detect()` — real implementation, scans for canonical FT ASCII signatures
    plus mapper match. Same heuristics as `qlnes/engines.py::detect_famitone`,
    promoted to a tier-1 plugin.
  - `walk_song_table()` — A.1 simplification: returns a single SongEntry that
    represents "the whole capture window". Real per-song pointer-table walking
    lands in A.4 (FR10 — exhaustive song-table walk including unreferenced
    entries). Until then, one ROM = one WAV.
  - `render_song()` — captures the FCEUX trace via the oracle, replays the
    APU register writes through `ApuEmulator`, returns int16 LE PCM. Sample
    equivalence to FCEUX is NOT yet verified (no fixture corpus until 7.6+);
    architectural correctness IS verified by unit tests.
  - `detect_loop()` — returns None per story spec (A.3 implements the FT `Bxx`
    loop-opcode parser).

Spec: NESdev wiki — FamiTracker driver / 0CC-FamiTracker docs.
Story: A.1 §8.9.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, ClassVar

from ...apu import ApuEmulator
from ...rom import Rom
from ..engine import (
    DetectionResult,
    InProcessUnavailable,
    LoopBoundary,
    PcmStream,
    SongEntry,
    SoundEngine,
    SoundEngineRegistry,
)
from ..famitone2_data import (
    first_note_code,
    note_code_to_frequency_hz,
    read_channel_rows,
    scan_famitone2_tables,
)

if TYPE_CHECKING:
    from ...oracle import FceuxOracle

# Default capture window matches `[audio] frames = 600` from the config schema
# (UX §4.4) — 600 NTSC frames ≈ 10 s.
DEFAULT_FRAMES = 600
NTSC_CPU_HZ = 1_789_773
NTSC_FRAME_RATE = 60.0988  # actual NTSC; close enough to 60 for our cycle math
CYCLES_PER_FRAME = NTSC_CPU_HZ / NTSC_FRAME_RATE  # ≈ 29780

# Ordered most-specific-first: 0CC-FamiTracker contains "FamiTracker" as a
# substring, so we must check the longer signature first to attribute the
# right tool name in detection evidence.
_FT_SIGNATURES: tuple[bytes, ...] = (
    b"0CC-FamiTracker",
    b"FamiTracker",
    b"FamiTone",
)
_METADATA_MARKER = b"QLNESFTMETA1\x00"
_NSF_MAGIC = b"NESM\x1a"


@SoundEngineRegistry.register
class FamiTrackerEngine(SoundEngine):
    name: ClassVar[str] = "famitracker"
    tier: ClassVar = 1
    # A.1 scope = mapper 0 (NROM) per the story; A.4 broadens to 1, 4, 66.
    target_mappers: ClassVar[frozenset[int]] = frozenset({0, 1, 4, 66})

    def detect(self, rom: Rom) -> DetectionResult:
        evidence: list[str] = []
        confidence = 0.0
        prg = rom.prg if hasattr(rom, "prg") else b""
        if not prg:
            prg = rom.raw

        # 1. ASCII signature scan. Most FT-authored homebrew compiled with
        # FamiTone does NOT embed the literal "FamiTracker" string, so this
        # only catches a subset (notably the FT export tool's debug builds).
        for sig in _FT_SIGNATURES:
            if sig in prg:
                evidence.append(f"signature:{sig.decode('ascii')}")
                confidence += 0.5
                break

        if _read_embedded_metadata(rom) is not None:
            evidence.append("metadata:QLNESFTMETA1")
            confidence += 0.5
        if _read_embedded_nsf_header(rom) is not None:
            evidence.append("metadata:embedded_nsf_header")
            confidence += 0.5
        tables = _scan_famitone2_tables(rom)
        if tables:
            evidence.append(f"famitone2_tables:{len(tables)}")
            confidence += 0.5

        # 2. Mapper match (target_mappers already pre-filters at registry level
        # but we still record the evidence for debugging).
        if rom.mapper in self.target_mappers:
            evidence.append(f"mapper:{rom.mapper}")
            confidence += 0.2

        # 3. Heuristic: count static APU register writes in PRG. Pattern is
        # 6502 STA absolute = `0x8D <lo> <hi>` where <hi>=0x40 and <lo> ∈
        # 0x00..0x17. A real sound engine emits dozens of these; a non-audio
        # ROM has zero or a handful (e.g., $4014 OAMDMA, $4016/$4017 joypad
        # reads — those are STA too but to specific addrs).
        # We exclude the joypad/OAMDMA addresses to avoid false positives
        # from games that don't have a sound engine but poll the controllers.
        non_audio_apu_lo = {0x14, 0x16, 0x17}  # OAMDMA, JOY1, FRAME_CNT/JOY2
        n_apu_writes = 0
        i = 0
        while i < len(prg) - 2:
            if prg[i] == 0x8D and prg[i + 2] == 0x40:
                lo = prg[i + 1]
                if 0x00 <= lo <= 0x17 and lo not in non_audio_apu_lo:
                    n_apu_writes += 1
                i += 3
            else:
                i += 1
        if n_apu_writes >= 30:
            evidence.append(f"apu_writes_static:{n_apu_writes}")
            confidence += 0.3
        elif n_apu_writes >= 15:
            evidence.append(f"apu_writes_static:{n_apu_writes}")
            confidence += 0.2
        elif n_apu_writes >= 5:
            evidence.append(f"apu_writes_static:{n_apu_writes}")
            confidence += 0.1

        return DetectionResult(
            confidence=min(confidence, 1.0),
            evidence=evidence,
            metadata={"apu_writes_static": n_apu_writes},
        )

    def walk_song_table(self, rom: Rom) -> list[SongEntry]:
        """Return one SongEntry per declared song when metadata is present.

        Plain FamiTracker exports do not expose one universal song-table shape
        across every driver/exporter. For deterministic fixtures and ROMs that
        opt in, qlnes recognizes a compact `QLNESFTMETA1` metadata block and
        treats it as the authoritative song list, including unreferenced songs.
        ROMs without that block keep the conservative one-capture fallback.
        """
        metadata = _read_embedded_metadata(rom)
        if metadata is not None:
            songs = _songs_from_metadata(metadata)
            if songs:
                return songs
        nsf_songs = _songs_from_embedded_nsf_header(rom)
        if nsf_songs:
            return nsf_songs
        famitone2_songs = _songs_from_famitone2_tables(rom)
        if famitone2_songs:
            return famitone2_songs
        return [SongEntry(index=0, label=None, referenced=True, metadata={})]

    def render_song(
        self,
        rom: Rom,
        song: SongEntry,
        oracle: FceuxOracle,
        *,
        frames: int = DEFAULT_FRAMES,
    ) -> PcmStream:
        """Render one song by replaying the FCEUX trace through ApuEmulator."""
        if rom.path is None:
            raise ValueError(
                "rom must be constructed via Rom.from_file (oracle.trace needs the source path)"
            )
        trace = oracle.trace(rom.path, frames=frames)
        emu = ApuEmulator()
        for ev in trace.events:
            emu.write(ev.addr, ev.value, ev.cycle)
        end_cycle = max(trace.end_cycle, int(frames * CYCLES_PER_FRAME))
        pcm = emu.render_until(cycle=end_cycle)
        return PcmStream(samples=pcm, sample_rate=44_100, loop=None)

    def render_song_in_process(
        self, rom: Rom, song: SongEntry, *, frames: int = DEFAULT_FRAMES
    ) -> PcmStream:
        """Render with optional NSF-style song selector in A."""
        if song.metadata.get("source") == "famitone2_data":
            return _render_famitone2_static(rom, song, frames=frames)

        from ..in_process import InProcessRunner

        init = self.init_addr(rom, song)
        play = self.play_addr(rom, song)
        runner = InProcessRunner(rom)
        events = runner.run_song(
            init,
            play,
            frames=frames,
            init_a=_song_init_a(song),
        )
        emu = ApuEmulator()
        last_cycle = 0
        for ev in events:
            emu.write(ev.register, ev.value, ev.cpu_cycle)
            last_cycle = ev.cpu_cycle
        end_cycle = max(last_cycle, int(frames * CYCLES_PER_FRAME))
        return PcmStream(samples=emu.render_until(cycle=end_cycle), sample_rate=44_100)

    def init_addr(self, rom: Rom, song: SongEntry) -> int:
        """In-process init = the ROM's reset vector ($FFFC-$FFFD).

        For self-running FT homebrew (Alter Ego, Shiru's stack, most of
        the v0.5 FT corpus), the reset handler runs the entire game
        init including audio init. F.7 corpus expansion may surface
        ROMs where this heuristic doesn't hold; the right place to
        widen the heuristic is here, behind a per-ROM-fingerprint
        table or a static signature scan for FamiTone entry symbols.

        Mapper-1+ ROMs raise `InProcessUnavailable` — bank-switching
        breaks the mapper-0 vector-read trick, and F.5 falls back to
        the oracle path. F.8 will land MMC1/MMC3 support.
        """
        metadata_addr = _song_cpu_addr(song, "init_addr")
        if metadata_addr is not None:
            return metadata_addr
        if rom.mapper not in (0, None):
            raise InProcessUnavailable(self.name)
        return _read_le16_at_cpu(rom, 0xFFFC)

    def play_addr(self, rom: Rom, song: SongEntry) -> int:
        """In-process play = the ROM's NMI vector ($FFFA-$FFFB).

        The NMI handler is what runs at 60 Hz on real hardware, and for
        FT-driven ROMs it is what calls FamiTone's play routine.

        Mapper-1+ ROMs raise `InProcessUnavailable` (see init_addr).
        """
        metadata_addr = _song_cpu_addr(song, "play_addr")
        if metadata_addr is not None:
            return metadata_addr
        if rom.mapper not in (0, None):
            raise InProcessUnavailable(self.name)
        return _read_le16_at_cpu(rom, 0xFFFA)

    def detect_loop(self, song: SongEntry, pcm: PcmStream) -> LoopBoundary | None:
        loop = song.metadata.get("loop")
        if not isinstance(loop, dict):
            return None
        start = loop.get("start_sample")
        end = loop.get("end_sample")
        if not isinstance(start, int) or not isinstance(end, int):
            return None
        if 0 <= start < end <= pcm.n_samples:
            return LoopBoundary(start_sample=start, end_sample=end)
        return None


def _read_embedded_metadata(rom: Rom) -> dict[str, Any] | None:
    """Read optional qlnes FamiTracker metadata from PRG bytes.

    Layout:
      `QLNESFTMETA1\0` + little-endian uint16 JSON length + UTF-8 JSON payload.
    The schema is intentionally small and testable:
      {"songs":[{"index":0,"label":"main","referenced":true,
                 "init_addr":32768,"play_addr":33024,
                 "loop":{"start_sample":100,"end_sample":1000}}]}
    """
    prg = rom.prg if hasattr(rom, "prg") else b""
    if not prg:
        prg = rom.raw
    pos = prg.find(_METADATA_MARKER)
    if pos < 0:
        return None
    size_pos = pos + len(_METADATA_MARKER)
    if size_pos + 2 > len(prg):
        return None
    size = prg[size_pos] | (prg[size_pos + 1] << 8)
    start = size_pos + 2
    end = start + size
    if size <= 0 or end > len(prg):
        return None
    try:
        data = json.loads(prg[start:end].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _read_embedded_nsf_header(rom: Rom) -> dict[str, object] | None:
    prg = rom.prg if hasattr(rom, "prg") else b""
    if not prg:
        prg = rom.raw
    pos = prg.find(_NSF_MAGIC)
    if pos < 0 or pos + 0x80 > len(prg):
        return None
    header = prg[pos : pos + 0x80]
    songs = header[0x06]
    if not 1 <= songs <= 64:
        return None
    init_addr = header[0x0A] | (header[0x0B] << 8)
    play_addr = header[0x0C] | (header[0x0D] << 8)
    if not (0x8000 <= init_addr <= 0xFFFF and 0x8000 <= play_addr <= 0xFFFF):
        return None
    name = header[0x0E:0x2E].split(b"\x00", 1)[0].decode("ascii", "replace")
    return {
        "songs": songs,
        "initial_song": header[0x07],
        "init_addr": init_addr,
        "play_addr": play_addr,
        "name": name,
    }


def _scan_famitone2_tables(rom: Rom):
    prg = rom.prg if hasattr(rom, "prg") else b""
    if not prg:
        prg = rom.raw
    return scan_famitone2_tables(prg)


def _songs_from_embedded_nsf_header(rom: Rom) -> list[SongEntry]:
    metadata = _read_embedded_nsf_header(rom)
    if metadata is None:
        return []
    count = metadata["songs"]
    init_addr = metadata["init_addr"]
    play_addr = metadata["play_addr"]
    name = metadata.get("name")
    if not isinstance(count, int) or not isinstance(init_addr, int) or not isinstance(play_addr, int):
        return []
    label_prefix = name if isinstance(name, str) and name else "nsf"
    return [
        SongEntry(
            index=i,
            label=f"{label_prefix} {i + 1}",
            referenced=True,
            metadata={
                "source": "embedded_nsf_header",
                "nsf_song_number": i + 1,
                "init_a": i,
                "init_addr": init_addr,
                "play_addr": play_addr,
            },
        )
        for i in range(count)
    ]


def _songs_from_famitone2_tables(rom: Rom) -> list[SongEntry]:
    prg = rom.prg if hasattr(rom, "prg") else b""
    if not prg:
        prg = rom.raw
    songs: list[SongEntry] = []
    out_index = 0
    for table_index, table in enumerate(scan_famitone2_tables(prg)):
        for song in table.songs:
            tonal_channel, note_code = _first_famitone2_tonal_note(prg, song)
            metadata: dict[str, object] = {
                "source": "famitone2_data",
                "status": "unverified",
                "table_index": table_index,
                "table_cpu_addr": table.cpu_addr,
                "table_prg_offset": table.prg_offset,
                "subsong_index": song.index,
                "channel_pointers": list(song.channel_pointers),
                "pal_tempo": song.pal_tempo,
                "ntsc_tempo": song.ntsc_tempo,
            }
            if note_code is not None:
                metadata["first_note_code"] = note_code
                metadata["first_note_channel"] = tonal_channel
                if note_code > 0:
                    metadata["expected_frequency_hz"] = note_code_to_frequency_hz(note_code)
            rows = read_channel_rows(prg, song, channel=0, max_rows=64)
            if rows.notes:
                metadata["decoded_rows_preview"] = list(rows.notes[:16])
                metadata["decoded_speed"] = rows.speed
                if rows.loop_row is not None:
                    metadata["decoded_loop_row"] = rows.loop_row
            songs.append(
                SongEntry(
                    index=out_index,
                    label=f"famitone2-{table_index}-{song.index}",
                    referenced=True,
                    metadata=metadata,
                )
            )
            out_index += 1
    return songs


def _first_famitone2_tonal_note(prg: bytes, song) -> tuple[int, int | None]:
    for channel in range(3):
        note_code = first_note_code(prg, song, channel=channel)
        if note_code is not None and note_code > 0:
            return channel, note_code
    return 0, first_note_code(prg, song, channel=0)


def _render_famitone2_static(rom: Rom, song: SongEntry, *, frames: int) -> PcmStream:
    prg = rom.prg if hasattr(rom, "prg") else b""
    if not prg:
        prg = rom.raw
    channel_pointers = song.metadata.get("channel_pointers")
    if not (
        isinstance(channel_pointers, list)
        and len(channel_pointers) == 5
        and all(isinstance(v, int) for v in channel_pointers)
    ):
        samples = ApuEmulator().render_until(int(frames * CYCLES_PER_FRAME))
        return PcmStream(samples=samples, sample_rate=44_100)

    from ..famitone2_data import FamiTone2Song

    ft_song = FamiTone2Song(
        index=int(song.metadata.get("subsong_index", 0)),
        channel_pointers=tuple(channel_pointers),  # type: ignore[arg-type]
        pal_tempo=int(song.metadata.get("pal_tempo", 307)),
        ntsc_tempo=int(song.metadata.get("ntsc_tempo", 256)),
    )
    max_rows = max(1, (frames // 2) + 8)
    channel_rows = [
        read_channel_rows(prg, ft_song, channel=channel, max_rows=max_rows)
        for channel in range(4)
    ]
    emu = ApuEmulator()
    row_frames = max(1, channel_rows[0].speed if channel_rows else 6)
    last_notes: list[int | None] = [None, None, None, None]
    enable_mask = 0
    max_decoded_rows = max((len(rows.notes) for rows in channel_rows), default=0)
    for row_index in range(max_decoded_rows):
        cycle = int(row_index * row_frames * CYCLES_PER_FRAME)
        if cycle >= int(frames * CYCLES_PER_FRAME):
            break
        write_cycle = cycle
        for channel, rows in enumerate(channel_rows):
            if row_index >= len(rows.notes):
                continue
            note_code = rows.notes[row_index]
            if note_code == last_notes[channel]:
                continue
            last_notes[channel] = note_code
            bit = 1 << channel
            if note_code <= 0:
                if not (enable_mask & bit):
                    continue
                enable_mask &= ~bit
                emu.write(0x4015, enable_mask, write_cycle)
                write_cycle += 1
                continue
            enable_mask |= bit
            emu.write(0x4015, enable_mask, write_cycle)
            write_cycle = _write_channel_note(emu, channel, note_code, write_cycle + 1)
    return PcmStream(
        samples=emu.render_until(int(frames * CYCLES_PER_FRAME)),
        sample_rate=44_100,
    )


def _write_channel_note(
    emu: ApuEmulator, channel: int, note_code: int, cycle: int
) -> int:
    if channel in (0, 1):
        return _write_pulse_note(emu, channel, note_code, cycle)
    elif channel == 2:
        return _write_triangle_note(emu, note_code, cycle)
    elif channel == 3:
        return _write_noise_note(emu, note_code, cycle)
    return cycle


def _write_pulse_note(emu: ApuEmulator, channel: int, note_code: int, cycle: int) -> int:
    freq = note_code_to_frequency_hz(note_code)
    timer = max(0, min(0x7FF, round(NTSC_CPU_HZ / (16 * freq)) - 1))
    base = 0x4000 if channel == 0 else 0x4004
    emu.write(base, 0xBF, cycle)
    emu.write(base + 1, 0x00, cycle + 1)
    emu.write(base + 2, timer & 0xFF, cycle + 2)
    emu.write(base + 3, 0x08 | ((timer >> 8) & 0x07), cycle + 3)
    return cycle + 4


def _write_triangle_note(emu: ApuEmulator, note_code: int, cycle: int) -> int:
    freq = note_code_to_frequency_hz(note_code)
    timer = max(2, min(0x7FF, round(NTSC_CPU_HZ / (32 * freq)) - 1))
    emu.write(0x4008, 0xFF, cycle)
    emu.write(0x400A, timer & 0xFF, cycle + 1)
    emu.write(0x400B, 0x08 | ((timer >> 8) & 0x07), cycle + 2)
    return cycle + 3


def _write_noise_note(emu: ApuEmulator, note_code: int, cycle: int) -> int:
    # Noise is not pitched chromatically. Map higher notes to shorter periods
    # so row timing and audible activity are preserved without false pitch claims.
    period_index = max(0, min(0x0F, 15 - (note_code // 4)))
    emu.write(0x400C, 0x3F, cycle)
    emu.write(0x400E, period_index, cycle + 1)
    emu.write(0x400F, 0x08, cycle + 2)
    return cycle + 3


def _song_cpu_addr(song: SongEntry, key: str) -> int | None:
    addr = song.metadata.get(key)
    if isinstance(addr, int) and 0x8000 <= addr <= 0xFFFF:
        return addr
    return None


def _song_init_a(song: SongEntry) -> int | None:
    init_a = song.metadata.get("init_a")
    if isinstance(init_a, int) and 0 <= init_a <= 0xFF:
        return init_a
    nsf_song_number = song.metadata.get("nsf_song_number")
    if isinstance(nsf_song_number, int) and 1 <= nsf_song_number <= 0x100:
        return (nsf_song_number - 1) & 0xFF
    return None


def _songs_from_metadata(metadata: dict[str, Any]) -> list[SongEntry]:
    raw_songs = metadata.get("songs")
    if not isinstance(raw_songs, list):
        return []
    songs: list[SongEntry] = []
    seen: set[int] = set()
    for raw_song in raw_songs:
        if not isinstance(raw_song, dict):
            continue
        index = raw_song.get("index")
        if not isinstance(index, int) or index < 0 or index in seen:
            continue
        seen.add(index)
        label = raw_song.get("label")
        if not isinstance(label, str):
            label = None
        referenced = raw_song.get("referenced", True)
        if not isinstance(referenced, bool):
            referenced = True
        song_metadata: dict[str, object] = {"source": "QLNESFTMETA1"}
        for key in ("init_addr", "play_addr"):
            addr = raw_song.get(key)
            if isinstance(addr, int) and 0x8000 <= addr <= 0xFFFF:
                song_metadata[key] = addr
        init_a = raw_song.get("init_a")
        if isinstance(init_a, int) and 0 <= init_a <= 0xFF:
            song_metadata["init_a"] = init_a
        loop = raw_song.get("loop")
        if isinstance(loop, dict):
            start = loop.get("start_sample")
            end = loop.get("end_sample")
            if isinstance(start, int) and isinstance(end, int):
                song_metadata["loop"] = {
                    "start_sample": start,
                    "end_sample": end,
                }
        songs.append(
            SongEntry(
                index=index,
                label=label,
                referenced=referenced,
                metadata=song_metadata,
            )
        )
    return sorted(songs, key=lambda s: s.index)


def _read_le16_at_cpu(rom: Rom, cpu_addr: int) -> int:
    """Read a little-endian uint16 from CPU address `cpu_addr` (mapper 0).

    NROM PRG maps to $8000-$FFFF. 32 KB PRG occupies the full 32 KB;
    16 KB PRG mirrors at $8000 and $C000. cpu_addr must lie in
    [0x8000, 0xFFFF].
    """
    if not 0x8000 <= cpu_addr <= 0xFFFE:
        raise ValueError(
            f"cpu_addr {cpu_addr:#x} out of NROM PRG range "
            f"$8000-$FFFE (need 2 bytes)"
        )
    prg = rom.prg if rom.header is not None else rom.raw
    if len(prg) == 0x4000:
        # NROM-128: 16 KB PRG mirrored. Both $8xxx and $Cxxx map to same offset.
        offset = (cpu_addr - 0x8000) & 0x3FFF
    elif len(prg) == 0x8000:
        offset = cpu_addr - 0x8000
    else:
        raise ValueError(f"NROM PRG must be 16 or 32 KB; got {len(prg)} bytes")
    lo = prg[offset]
    hi = prg[offset + 1]
    return lo | (hi << 8)
