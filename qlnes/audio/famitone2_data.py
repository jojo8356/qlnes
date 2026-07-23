"""Conservative parser for FamiTone2 music-data headers.

FamiTone2 `text2data` emits a compact table:

- byte 0: sub-song count (1..17)
- word 1: instrument table pointer
- word 3: sample table pointer minus 3
- per sub-song: 5 channel-stream pointers + PAL tempo + NTSC tempo

This module only enumerates candidate tables. It does not know where a game
placed `FamiToneInit`, `FamiToneMusicPlay`, or `FamiToneUpdate`, so rendering a
real uninstrumented FamiTone2 dataset still needs a player-entrypoint resolver.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FamiTone2Song:
    index: int
    channel_pointers: tuple[int, int, int, int, int]
    pal_tempo: int
    ntsc_tempo: int


@dataclass(frozen=True)
class FamiTone2Table:
    prg_offset: int
    cpu_addr: int
    song_count: int
    instrument_pointer: int
    sample_pointer_minus_3: int
    songs: tuple[FamiTone2Song, ...]


@dataclass(frozen=True)
class FamiTone2Rows:
    notes: tuple[int, ...]
    speed: int
    loop_row: int | None = None


def first_note_code(prg: bytes, song: FamiTone2Song, *, channel: int = 0) -> int | None:
    """Return the first note/rest code reachable in a channel stream."""
    if not 0 <= channel < 5:
        raise ValueError(f"channel must be 0..4, got {channel}")
    return _first_note_from_pointer(
        prg,
        song.channel_pointers[channel],
        visited=set(),
        budget=1024,
    )


def read_channel_rows(
    prg: bytes,
    song: FamiTone2Song,
    *,
    channel: int = 0,
    max_rows: int = 256,
) -> FamiTone2Rows:
    """Decode one FamiTone2 channel stream into per-row note/rest codes.

    The decoder supports the stream-control primitives needed to avoid missing
    notes in common data: instrument changes, empty-row repeats, speed changes,
    end/loop pointers, and references. It deliberately returns note codes only;
    instrument/envelope exactness is a later tier-1 fidelity problem.
    """
    if max_rows <= 0:
        return FamiTone2Rows(notes=(), speed=6)
    if not 0 <= channel < 5:
        raise ValueError(f"channel must be 0..4, got {channel}")

    state = _StreamState(speed=6)
    notes: list[int] = []
    _read_rows_from_pointer(
        prg,
        song.channel_pointers[channel],
        notes=notes,
        state=state,
        max_rows=max_rows,
        visited_loops=set(),
        budget=4096,
    )
    return FamiTone2Rows(notes=tuple(notes[:max_rows]), speed=state.speed, loop_row=state.loop_row)


def note_code_to_frequency_hz(note_code: int) -> float:
    """Approximate FamiTone2 note code frequency using C1..D6 chromatic scale."""
    if not 1 <= note_code <= 60:
        raise ValueError(f"FamiTone2 note code must be 1..60, got {note_code}")
    # FamiTone2 docs: note code 1 is C-1. Treat that as scientific C1.
    midi = 24 + (note_code - 1)
    return 440.0 * (2.0 ** ((midi - 69) / 12.0))


def scan_famitone2_tables(prg: bytes) -> list[FamiTone2Table]:
    """Return plausible FamiTone2 music-data tables from mapper-0 PRG bytes."""
    tables: list[FamiTone2Table] = []
    for offset in range(0, max(0, len(prg) - 19)):
        count = prg[offset]
        if not 1 <= count <= 17:
            continue
        end = offset + 5 + 14 * count
        if end > len(prg):
            continue

        instrument_pointer = _u16(prg, offset + 1)
        sample_pointer_minus_3 = _u16(prg, offset + 3)
        instrument_offset = _cpu_to_prg_offset(instrument_pointer, len(prg))
        sample_offset = _cpu_to_prg_offset(sample_pointer_minus_3 + 3, len(prg))
        if instrument_offset is None or sample_offset is None:
            continue
        if prg[instrument_offset] & 0x0F:
            continue

        songs: list[FamiTone2Song] = []
        ok = True
        for index in range(count):
            base = offset + 5 + index * 14
            channel_pointers = tuple(_u16(prg, base + channel * 2) for channel in range(5))
            if len(channel_pointers) != 5:
                ok = False
                break
            for pointer in channel_pointers:
                stream_offset = _cpu_to_prg_offset(pointer, len(prg))
                if stream_offset is None or not _valid_stream_start(prg[stream_offset]):
                    ok = False
                    break
            if not ok:
                break
            pal_tempo = _u16(prg, base + 10)
            ntsc_tempo = _u16(prg, base + 12)
            if not (1 <= pal_tempo <= 2000 and 1 <= ntsc_tempo <= 2000):
                ok = False
                break
            songs.append(
                FamiTone2Song(
                    index=index,
                    channel_pointers=channel_pointers,  # type: ignore[arg-type]
                    pal_tempo=pal_tempo,
                    ntsc_tempo=ntsc_tempo,
                )
            )
        if ok and songs:
            tables.append(
                FamiTone2Table(
                    prg_offset=offset,
                    cpu_addr=0x8000 + (offset & 0x7FFF),
                    song_count=count,
                    instrument_pointer=instrument_pointer,
                    sample_pointer_minus_3=sample_pointer_minus_3,
                    songs=tuple(songs),
                )
            )
    return tables


def _u16(buf: bytes, offset: int) -> int:
    return buf[offset] | (buf[offset + 1] << 8)


def _cpu_to_prg_offset(addr: int, prg_len: int) -> int | None:
    if not 0x8000 <= addr <= 0xFFFF:
        return None
    if prg_len == 0x4000:
        return (addr - 0x8000) & 0x3FFF
    if prg_len == 0x8000:
        return addr - 0x8000
    return None


def _valid_stream_start(byte: int) -> bool:
    if byte in (0xFB, 0xFD, 0xFF):
        return True
    if byte <= 0x78:
        return True
    if 0x80 <= byte <= 0xFA:
        return True
    return False


@dataclass
class _StreamState:
    speed: int
    current_note: int = 0
    loop_row: int | None = None


def _first_note_from_pointer(
    prg: bytes,
    pointer: int,
    *,
    visited: set[int],
    budget: int,
) -> int | None:
    offset = _cpu_to_prg_offset(pointer, len(prg))
    if offset is None or pointer in visited:
        return None
    visited.add(pointer)
    while budget > 0 and 0 <= offset < len(prg):
        budget -= 1
        value = prg[offset]
        offset += 1
        if value < 0x80:
            return value >> 1
        tag = value & 0x7F
        if (tag & 1) == 0:
            # Instrument select.
            continue
        code = tag >> 1
        if code < 0x3D:
            # Empty rows.
            continue
        if code == 0x3D:
            # Speed tag, skip next byte.
            offset += 1
            continue
        if code == 0x3E:
            if offset + 1 >= len(prg):
                return None
            pointer = _u16(prg, offset)
            next_offset = _cpu_to_prg_offset(pointer, len(prg))
            offset = next_offset if next_offset is not None else -1
            continue
        if offset + 2 >= len(prg):
            return None
        # Reference: len byte + absolute pointer. Inspect referenced stream.
        ref_pointer = _u16(prg, offset + 1)
        note = _first_note_from_pointer(
            prg,
            ref_pointer,
            visited=visited,
            budget=budget,
        )
        if note is not None:
            return note
        offset += 3
    return None


def _read_rows_from_pointer(
    prg: bytes,
    pointer: int,
    *,
    notes: list[int],
    state: _StreamState,
    max_rows: int,
    visited_loops: set[int],
    budget: int,
) -> None:
    offset = _cpu_to_prg_offset(pointer, len(prg))
    if offset is None:
        return
    while budget > 0 and len(notes) < max_rows and 0 <= offset < len(prg):
        budget -= 1
        value = prg[offset]
        offset += 1
        if value < 0x80:
            state.current_note = value >> 1
            notes.append(state.current_note)
            if value & 1 and len(notes) < max_rows:
                notes.append(state.current_note)
            continue

        tag = value & 0x7F
        if (tag & 1) == 0:
            # Instrument select. Rendering remains conservative and ignores
            # envelopes; the following note event still drives frequency.
            continue

        code = tag >> 1
        if code < 0x3D:
            notes.extend([state.current_note] * min(code + 1, max_rows - len(notes)))
            continue

        if code == 0x3D:
            if offset >= len(prg):
                return
            state.speed = max(1, prg[offset])
            offset += 1
            continue

        if code == 0x3E:
            if offset + 1 >= len(prg):
                return
            loop_pointer = _u16(prg, offset)
            if state.loop_row is None:
                state.loop_row = len(notes)
            visited_loops.add(loop_pointer)
            next_offset = _cpu_to_prg_offset(loop_pointer, len(prg))
            if next_offset is None:
                return
            offset = next_offset
            continue

        if offset + 2 >= len(prg):
            return
        ref_rows = prg[offset]
        ref_pointer = _u16(prg, offset + 1)
        before = len(notes)
        _read_rows_from_pointer(
            prg,
            ref_pointer,
            notes=notes,
            state=state,
            max_rows=min(max_rows, before + ref_rows),
            visited_loops=visited_loops,
            budget=budget,
        )
        offset += 3
