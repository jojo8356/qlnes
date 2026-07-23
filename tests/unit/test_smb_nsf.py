from __future__ import annotations

from qlnes.smb_nsf import (
    SMB_MUSIC_HEADER_DATA_ADDR,
    SMB_MUSIC_HEADER_OFFSET_DATA_ADDR,
    SMB_MUSIC_LENGTH_LOOKUP_ADDR,
    SMB_SFX_TRACKS,
    SMB_SOUND_ENGINE_ADDR,
    SMB_TRACKS,
    SMB_WRAPPER_INIT_ADDR,
    SMB_WRAPPER_PLAY_ADDR,
    _square2_duration_for_header_y,
    build_smb_nsf_from_rom,
    read_smb_track_timings,
    write_smb_sfx_split_nsfs,
    write_smb_split_nsfs,
)


def _nrom32() -> bytes:
    header = bytearray(b"NES\x1a")
    header.extend([2, 1, 0, 0])
    header.extend(b"\x00" * 8)
    prg = bytearray(0x8000)
    for i in range(8):
        prg[i * 0x1000 : (i + 1) * 0x1000] = bytes([i]) * 0x1000
    chr_rom = bytes(0x2000)
    return bytes(header) + bytes(prg) + chr_rom


def test_smb_nsf_header_and_bankswitch_layout():
    build = build_smb_nsf_from_rom(_nrom32())
    nsf = build.nsf_bytes

    assert nsf[:5] == b"NESM\x1a"
    assert nsf[5] == 1
    assert nsf[6] == len(SMB_TRACKS)
    assert int.from_bytes(nsf[0x08:0x0A], "little") == 0x8000
    assert int.from_bytes(nsf[0x0A:0x0C], "little") == SMB_WRAPPER_INIT_ADDR
    assert int.from_bytes(nsf[0x0C:0x0E], "little") == SMB_WRAPPER_PLAY_ADDR
    assert tuple(nsf[0x70:0x78]) == (0, 1, 2, 3, 4, 5, 6, 7)


def test_smb_nsf_wrapper_replaces_first_bank_and_preserves_audio_bank():
    build = build_smb_nsf_from_rom(_nrom32())
    data = build.nsf_bytes[0x80:]

    assert len(data) == 0x8000
    assert data[0] == 0xAA  # TAX at INIT, not original PRG bank 0 filler.
    assert data[0x1000] == 1
    assert data[0x7000] == 7

    play = SMB_WRAPPER_PLAY_ADDR - 0x8000
    assert data[play : play + 4] == bytes(
        [0x20, SMB_SOUND_ENGINE_ADDR & 0xFF, SMB_SOUND_ENGINE_ADDR >> 8, 0x60]
    )


def test_smb_nsf_track_table_maps_area_and_event_queues():
    build = build_smb_nsf_from_rom(_nrom32())
    wrapper = build.nsf_bytes[0x80 : 0x80 + 0x1000]

    lows = wrapper[0x60 : 0x60 + len(SMB_TRACKS)]
    highs = wrapper[0x80 : 0x80 + len(SMB_TRACKS)]
    values = wrapper[0xA0 : 0xA0 + len(SMB_TRACKS)]

    assert lows[0] == 0xFB
    assert highs[0] == 0x00
    assert values[0] == 0x01
    assert SMB_TRACKS[0].label == "ground"

    assert lows[7] == 0xFC
    assert highs[7] == 0x00
    assert values[7] == 0x01
    assert SMB_TRACKS[7].label == "death"


def test_smb_sfx_track_table_maps_sound_effect_queues():
    build = build_smb_nsf_from_rom(_nrom32(), tracks=SMB_SFX_TRACKS)
    wrapper = build.nsf_bytes[0x80 : 0x80 + 0x1000]

    lows = wrapper[0x60 : 0x60 + len(SMB_SFX_TRACKS)]
    highs = wrapper[0x80 : 0x80 + len(SMB_SFX_TRACKS)]
    values = wrapper[0xA0 : 0xA0 + len(SMB_SFX_TRACKS)]

    assert build.nsf_bytes[6] == len(SMB_SFX_TRACKS)
    assert lows[0] == 0xFF
    assert highs[0] == 0x00
    assert values[0] == 0x80
    assert SMB_SFX_TRACKS[0].label == "small-jump"

    assert lows[-1] == 0xFD
    assert highs[-1] == 0x00
    assert values[-1] == 0x02
    assert SMB_SFX_TRACKS[-1].label == "bowser-flame"


def test_smb_split_nsfs_write_one_track_per_file(tmp_path):
    rom = tmp_path / "smb.nes"
    rom.write_bytes(_nrom32())

    written = write_smb_split_nsfs(rom, tmp_path / "split")

    assert len(written) == len(SMB_TRACKS)
    assert written[0].name == "01-ground.nsf"
    assert written[-1].name == "14-silence.nsf"
    for path in written:
        data = path.read_bytes()
        assert data[:5] == b"NESM\x1a"
        assert data[6] == 1


def test_smb_sfx_split_nsfs_write_one_effect_per_file(tmp_path):
    rom = tmp_path / "smb.nes"
    rom.write_bytes(_nrom32())

    written = write_smb_sfx_split_nsfs(rom, tmp_path / "sfx")

    assert len(written) == len(SMB_SFX_TRACKS)
    assert written[0].name == "01-small-jump.nsf"
    assert written[-1].name == "18-bowser-flame.nsf"
    for path in written:
        data = path.read_bytes()
        assert data[:5] == b"NESM\x1a"
        assert data[6] == 1


def test_smb_square2_duration_stops_at_zero_marker():
    prg = bytearray(0x8000)
    data_addr = 0xA000
    header_offset = 0x20
    header_addr = SMB_MUSIC_HEADER_DATA_ADDR + header_offset
    prg[SMB_MUSIC_HEADER_OFFSET_DATA_ADDR + 1 - 0x8000] = header_offset
    prg[header_addr - 0x8000] = 0x00
    prg[header_addr + 1 - 0x8000] = data_addr & 0xFF
    prg[header_addr + 2 - 0x8000] = data_addr >> 8
    prg[SMB_MUSIC_LENGTH_LOOKUP_ADDR - 0x8000] = 5
    prg[SMB_MUSIC_LENGTH_LOOKUP_ADDR + 1 - 0x8000] = 9
    prg[data_addr - 0x8000 : data_addr + 5 - 0x8000] = bytes(
        [0x80, 0x2C, 0x81, 0x2E, 0x00]
    )

    assert _square2_duration_for_header_y(bytes(prg), 1) == 14


def test_smb_local_rom_timings_when_available():
    from pathlib import Path

    rom = Path("roms/Super Mario Bros. (World).nes")
    if not rom.exists():
        return

    timings = read_smb_track_timings(rom.read_bytes())
    by_label = {timing.track.label: timing.frames for timing in timings}

    assert by_label["ground"] == 5328
    assert by_label["water"] == 1536
    assert by_label["underground"] == 756
    assert by_label["castle"] == 480
    assert by_label["time-running-out"] == 168
    assert by_label["silence"] == 0
