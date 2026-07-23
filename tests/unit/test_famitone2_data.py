from __future__ import annotations

from pathlib import Path

from qlnes.audio.famitone2_data import read_channel_rows, scan_famitone2_tables
from qlnes.rom import Rom


def test_scan_famitone2_table_from_synthetic_prg():
    prg = bytearray(0x4000)
    table = 0x0100
    prg[table] = 2
    prg[table + 1 : table + 3] = (0x8300).to_bytes(2, "little")
    prg[table + 3 : table + 5] = (0x83FD).to_bytes(2, "little")
    prg[0x0300] = 0x30
    prg[0x0400] = 0x00
    for song in range(2):
        base = table + 5 + song * 14
        for channel in range(5):
            pointer = 0x8500 + song * 0x100 + channel * 0x10
            prg[base + channel * 2 : base + channel * 2 + 2] = pointer.to_bytes(
                2, "little"
            )
            prg[pointer - 0x8000] = 0x84
        prg[base + 10 : base + 12] = (307).to_bytes(2, "little")
        prg[base + 12 : base + 14] = (256).to_bytes(2, "little")

    tables = scan_famitone2_tables(bytes(prg))
    assert len(tables) == 1
    assert tables[0].cpu_addr == 0x8100
    assert tables[0].song_count == 2
    assert tables[0].songs[1].channel_pointers[0] == 0x8600


def test_scan_famitone2_official_demo_tables():
    demo = Path("_bmad-output/external-fixtures/famitone2-v1.15/demo.nes")
    if not demo.exists():
        return
    rom = Rom.from_file(demo)
    addrs = {table.cpu_addr for table in scan_famitone2_tables(rom.prg)}
    assert 0x8983 in addrs
    assert 0x9A85 in addrs


def test_read_channel_rows_decodes_notes_repeats_speed_loop_and_reference():
    prg = bytearray(0x4000)
    table = 0x0100
    prg[table] = 1
    prg[table + 1 : table + 3] = (0x8300).to_bytes(2, "little")
    prg[table + 3 : table + 5] = (0x83FD).to_bytes(2, "little")
    prg[0x0300] = 0x30
    prg[0x0400] = 0x00
    base = table + 5
    prg[base : base + 2] = (0x8500).to_bytes(2, "little")
    for channel in range(1, 5):
        prg[base + channel * 2 : base + channel * 2 + 2] = (0x8600).to_bytes(
            2, "little"
        )
        prg[0x0600] = 0
    prg[base + 10 : base + 12] = (307).to_bytes(2, "little")
    prg[base + 12 : base + 14] = (256).to_bytes(2, "little")

    stream = 0x0500
    ref = 0x0520
    prg[stream : stream + 12] = bytes(
        [
            46 << 1,  # row 0: A4
            (49 << 1) | 1,  # rows 1-2: C5 + one empty row
            0xFB,
            3,  # speed = 3
            0x84,  # instrument select, ignored
            0xFF,
            2,
            0x20,
            0x85,  # reference 2 rows at $8520
            0xFD,
            0x00,
            0x85,  # loop to $8500
        ]
    )
    prg[ref : ref + 2] = bytes([51 << 1, 52 << 1])

    table_obj = scan_famitone2_tables(bytes(prg))[0]
    rows = read_channel_rows(bytes(prg), table_obj.songs[0], max_rows=7)
    assert rows.notes == (46, 49, 49, 51, 52, 46, 49)
    assert rows.speed == 3
    assert rows.loop_row == 5
