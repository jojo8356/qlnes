"""Super Mario Bros. custom NSF and MP3 exporter.

This is intentionally separate from the generic NSF writer. SMB's soundtrack is
driven by game-state queues, not a clean standalone INIT/PLAY API. The builder
adds a small NSF wrapper bank at $8000 that writes those queues and calls the
original sound engine at $F2D0 once per PLAY tick.

Typical use:

    >>> from pathlib import Path
    >>> from qlnes.smb_nsf import write_smb_nsf
    >>> write_smb_nsf(Path("roms/smb.nes"), Path("out/smb.nsf"))

The generated NSF is meant for private local validation from a user-supplied
ROM. Do not redistribute commercial ROM bytes or audio exports.
"""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .gme_play import render_nsf
from .ines import parse_header, strip_ines
from .nsf import NTSC_FRAME_US, NSFBuild, build_nsf_header

SMB_WRAPPER_LOAD_ADDR = 0x8000
SMB_WRAPPER_INIT_ADDR = 0x8000
SMB_WRAPPER_PLAY_ADDR = 0x8050
SMB_SOUND_ENGINE_ADDR = 0xF2D0
SMB_MUSIC_HEADER_OFFSET_DATA_ADDR = 0xF90C
SMB_MUSIC_HEADER_DATA_ADDR = 0xF90D
SMB_MUSIC_LENGTH_LOOKUP_ADDR = 0xFF66
SMB_NTSC_FPS = 1_000_000 / NTSC_FRAME_US

__all__ = [
    "SMB_TRACKS",
    "SMB_NTSC_FPS",
    "SmbTrack",
    "SmbTrackTiming",
    "build_smb_nsf_from_rom",
    "read_smb_track_timings",
    "write_smb_nsf",
    "write_smb_split_nsfs",
    "write_smb_trimmed_mp3s",
]


@dataclass(frozen=True)
class SmbTrack:
    """One playable SMB music queue exposed as an NSF track.

    SMB does not store a flat "track table" for external players. Music starts
    when game code writes a bitmask into one of two zero-page queues:
    ``$FB`` for area music and ``$FC`` for event music. The NSF wrapper maps a
    normal NSF song index to exactly one of those queue writes.

    Attributes:
        index: Zero-based NSF track index.
        label: Stable file-friendly track name.
        queue_addr: Zero-page address written by the wrapper, usually ``$FB``
            or ``$FC``.
        queue_value: SMB music/event bitmask written to ``queue_addr``.
        kind: Human category used by the timing reader: ``"area"`` or
            ``"event"``.
    """

    index: int
    label: str
    queue_addr: int
    queue_value: int
    kind: str


@dataclass(frozen=True)
class SmbTrackTiming:
    """No-repeat duration estimate for one SMB track.

    The duration is read from the original SMB music bytecode, not guessed from
    a fixed wall-clock length. Area/event streams terminate at the Square 2
    end marker. The ground theme is special because it is a chain of headers
    that loops back; qlnes sums headers before the loopback marker.

    Attributes:
        track: The logical SMB track being measured.
        frames: NTSC frame count before the first repeat or end marker.
        seconds: ``frames`` converted with the NSF NTSC frame period.
        reason: Short machine-readable explanation of the stop condition.
        header_ys: SMB music header indexes inspected to compute the timing.
    """

    track: SmbTrack
    frames: int
    seconds: float
    reason: str
    header_ys: tuple[int, ...]


SMB_TRACKS: tuple[SmbTrack, ...] = (
    SmbTrack(0, "ground", 0x00FB, 0x01, "area"),
    SmbTrack(1, "water", 0x00FB, 0x02, "area"),
    SmbTrack(2, "underground", 0x00FB, 0x04, "area"),
    SmbTrack(3, "castle", 0x00FB, 0x08, "area"),
    SmbTrack(4, "cloud", 0x00FB, 0x10, "area"),
    SmbTrack(5, "pipe-intro", 0x00FB, 0x20, "area"),
    SmbTrack(6, "star-power", 0x00FB, 0x40, "area"),
    SmbTrack(7, "death", 0x00FC, 0x01, "event"),
    SmbTrack(8, "game-over", 0x00FC, 0x02, "event"),
    SmbTrack(9, "victory", 0x00FC, 0x04, "event"),
    SmbTrack(10, "end-of-castle", 0x00FC, 0x08, "event"),
    SmbTrack(11, "end-of-level", 0x00FC, 0x20, "event"),
    SmbTrack(12, "time-running-out", 0x00FC, 0x40, "event"),
    SmbTrack(13, "silence", 0x00FC, 0x80, "event"),
)


def _build_wrapper_bank(tracks: tuple[SmbTrack, ...] = SMB_TRACKS) -> bytes:
    """Return a 4 KiB wrapper bank mapped at $8000.

    6502 layout:
      $8000 INIT(A=song-1): clear RAM, set OperMode, write queue.
      $8050 PLAY(): JSR $F2D0; RTS.
      $8060 track queue address low/high/value tables.
    """
    if len(tracks) > 255:
        raise ValueError("SMB NSF wrapper supports at most 255 tracks")

    code = bytearray([0xEA] * 0x1000)
    init = [
        0xAA,  # TAX
        0x78,  # SEI
        0xD8,  # CLD
        0xA9, 0x00,  # LDA #$00
        0xA8,  # TAY
        # clear_loop:
        0x99, 0x00, 0x00,  # STA $0000,Y
        0x99, 0x00, 0x01,  # STA $0100,Y
        0x99, 0x00, 0x02,  # STA $0200,Y
        0x99, 0x00, 0x03,  # STA $0300,Y
        0x99, 0x00, 0x04,  # STA $0400,Y
        0x99, 0x00, 0x05,  # STA $0500,Y
        0x99, 0x00, 0x06,  # STA $0600,Y
        0x99, 0x00, 0x07,  # STA $0700,Y
        0xC8,  # INY
        0xD0, 0xE5,  # BNE clear_loop
        0xA9, 0x01,  # LDA #$01
        0x8D, 0x70, 0x07,  # STA $0770 ; OperMode != title
        0x8A,  # TXA
        0xC9, len(tracks),  # CMP #track_count
        0x90, 0x02,  # BCC valid
        0xA9, 0x00,  # LDA #$00
        # valid:
        0xAA,  # TAX
        0xBD, 0x60, 0x80,  # LDA queue_addr_lo,X
        0x85, 0x00,  # STA $00
        0xBD, 0x70, 0x80,  # LDA queue_addr_hi,X
        0x85, 0x01,  # STA $01
        0xBD, 0x80, 0x80,  # LDA queue_value,X
        0xA0, 0x00,  # LDY #$00
        0x91, 0x00,  # STA ($00),Y
        0x60,  # RTS
    ]
    code[0 : len(init)] = init
    play_offset = SMB_WRAPPER_PLAY_ADDR - SMB_WRAPPER_LOAD_ADDR
    code[play_offset : play_offset + 4] = bytes(
        [0x20, SMB_SOUND_ENGINE_ADDR & 0xFF, SMB_SOUND_ENGINE_ADDR >> 8, 0x60]
    )

    table_offset = 0x60
    lows = bytes(track.queue_addr & 0xFF for track in tracks)
    highs = bytes(track.queue_addr >> 8 for track in tracks)
    values = bytes(track.queue_value for track in tracks)
    code[table_offset : table_offset + len(lows)] = lows
    code[table_offset + 0x10 : table_offset + 0x10 + len(highs)] = highs
    code[table_offset + 0x20 : table_offset + 0x20 + len(values)] = values
    return bytes(code)


def build_smb_nsf_from_rom(
    rom_bytes: bytes,
    *,
    title: str = "Super Mario Bros. SMB custom soundtrack",
    artist: str = "Koji Kondo",
    copyright_: str = "Local private rip; do not distribute commercial ROM audio",
    tracks: tuple[SmbTrack, ...] = SMB_TRACKS,
) -> NSFBuild:
    """Build a banked NSF image from a Super Mario Bros. iNES ROM.

    The source ROM must be the standard mapper-0/NROM shape used by SMB:
    32 KiB PRG. qlnes replaces the first 4 KiB NSF bank with a tiny wrapper at
    ``$8000`` and keeps the original PRG banks mapped from ``$9000`` through
    ``$FFFF``. That preserves the original sound engine at ``$F2D0``.

    Args:
        rom_bytes: Complete iNES file bytes, including the 16-byte iNES header.
        title: NSF title metadata.
        artist: NSF artist metadata.
        copyright_: NSF copyright field. Keep this private for commercial ROMs.
        tracks: Track queue definitions to expose. Passing a single track is
            how ``write_smb_split_nsfs`` creates one-file-per-track exports.

    Returns:
        NSFBuild containing the bytes and the load/init/play addresses.

    Raises:
        ValueError: If the input is not iNES, not mapper 0, or not 32 KiB PRG.
    """

    header = parse_header(rom_bytes)
    if header is None:
        raise ValueError("ROM iNES invalide (header manquant)")
    if header.mapper != 0:
        raise ValueError(f"Super Mario Bros. NSF builder expects mapper 0, got {header.mapper}")
    prg = strip_ines(rom_bytes)
    if len(prg) != 0x8000:
        raise ValueError(f"Super Mario Bros. NSF builder expects 32 KiB PRG, got {len(prg)}")

    wrapper = _build_wrapper_bank(tracks)
    original_banks = [prg[i : i + 0x1000] for i in range(0, len(prg), 0x1000)]
    # Map wrapper at $8000 and original PRG banks 1..7 at $9000..$FFFF.
    nsf_data = wrapper + b"".join(original_banks[1:])
    nsf_header = build_nsf_header(
        songs=len(tracks),
        start_song=1,
        load_addr=SMB_WRAPPER_LOAD_ADDR,
        init_addr=SMB_WRAPPER_INIT_ADDR,
        play_addr=SMB_WRAPPER_PLAY_ADDR,
        title=title,
        artist=artist,
        copyright_=copyright_,
        ntsc_speed=NTSC_FRAME_US,
        bankswitch=(0, 1, 2, 3, 4, 5, 6, 7),
        region=0,
        extra_chip=0,
    )
    return NSFBuild(
        nsf_bytes=nsf_header + nsf_data,
        load_addr=SMB_WRAPPER_LOAD_ADDR,
        init_addr=SMB_WRAPPER_INIT_ADDR,
        play_addr=SMB_WRAPPER_PLAY_ADDR,
        note=(
            "SMB custom banked NSF: wrapper bank at $8000, original sound "
            "engine at $F2D0, tracks selected through $FB/$FC queues."
        ),
    )


def write_smb_nsf(
    rom_path: Path,
    out_path: Path,
    *,
    title: str = "Super Mario Bros. SMB custom soundtrack",
    artist: str = "Koji Kondo",
    copyright_: str = "Local private rip; do not distribute commercial ROM audio",
) -> NSFBuild:
    """Write the multi-track SMB NSF to disk and return its build metadata."""

    build = build_smb_nsf_from_rom(
        Path(rom_path).read_bytes(),
        title=title,
        artist=artist,
        copyright_=copyright_,
    )
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(build.nsf_bytes)
    return build


def write_smb_split_nsfs(
    rom_path: Path,
    out_dir: Path,
    *,
    artist: str = "Koji Kondo",
    copyright_: str = "Local private rip; do not distribute commercial ROM audio",
) -> list[Path]:
    """Write one single-track NSF per SMB queue.

    Single-track files are convenient for players and for deterministic MP3
    rendering because every file starts at track ``0``.
    """

    rom_bytes = Path(rom_path).read_bytes()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for track in SMB_TRACKS:
        title = f"Super Mario Bros. - {track.index + 1:02d} {track.label}"
        build = build_smb_nsf_from_rom(
            rom_bytes,
            title=title,
            artist=artist,
            copyright_=copyright_,
            tracks=(track,),
        )
        path = out_dir / f"{track.index + 1:02d}-{track.label}.nsf"
        path.write_bytes(build.nsf_bytes)
        written.append(path)
    return written


def _cpu_read(prg: bytes, addr: int) -> int:
    if not 0x8000 <= addr <= 0xFFFF:
        raise ValueError(f"CPU address outside NROM PRG: ${addr:04X}")
    return prg[addr - 0x8000]


def _cpu_read_word(prg: bytes, addr: int) -> int:
    return _cpu_read(prg, addr) | (_cpu_read(prg, addr + 1) << 8)


def _header_y_for_track(track: SmbTrack) -> int | None:
    if track.kind == "area" and track.queue_value == 0x01:
        return None
    y = 0 if track.kind == "event" else 8
    value = track.queue_value
    while True:
        y += 1
        carry = value & 0x01
        value >>= 1
        if carry:
            return y


def _square2_duration_for_header_y(
    prg: bytes,
    header_y: int,
    *,
    note_length_adder: int = 0,
) -> int:
    header_offset = _cpu_read(prg, SMB_MUSIC_HEADER_OFFSET_DATA_ADDR + header_y)
    header_addr = SMB_MUSIC_HEADER_DATA_ADDR + header_offset
    note_len_lookup_offset = _cpu_read(prg, header_addr)
    music_data_addr = _cpu_read_word(prg, header_addr + 1)
    lengths = [
        _cpu_read(prg, SMB_MUSIC_LENGTH_LOOKUP_ADDR + i)
        for i in range(48)
    ]

    frames = 0
    current_note_len = 0
    data_offset = 0
    guard = 0
    while True:
        guard += 1
        if guard > 4096:
            raise ValueError(f"unterminated SMB music stream for header Y=${header_y:02X}")
        byte = _cpu_read(prg, music_data_addr + data_offset)
        data_offset += 1
        if byte == 0:
            return frames
        if byte >= 0x80:
            lookup_index = (byte & 0x07) + note_len_lookup_offset + note_length_adder
            if lookup_index >= len(lengths):
                raise ValueError(
                    f"SMB note length lookup out of range: {lookup_index}"
                )
            current_note_len = lengths[lookup_index]
            # The engine immediately fetches the following note/rest byte after
            # a length byte; it does not treat a zero here as EndOfMusicData.
            _cpu_read(prg, music_data_addr + data_offset)
            data_offset += 1
            frames += current_note_len
        else:
            if current_note_len == 0:
                current_note_len = 1
            frames += current_note_len


def read_smb_track_timings(rom_bytes: bytes) -> list[SmbTrackTiming]:
    """Read SMB music bytecode and return no-repeat durations for every track.

    This function intentionally inspects the PRG music tables instead of
    rendering a long fixed duration. It prevents the common "180 seconds per
    track" export mistake where looped themes are captured multiple times.
    """

    header = parse_header(rom_bytes)
    if header is None:
        raise ValueError("ROM iNES invalide (header manquant)")
    if header.mapper != 0:
        raise ValueError(f"Super Mario Bros. timing reader expects mapper 0, got {header.mapper}")
    prg = strip_ines(rom_bytes)
    if len(prg) != 0x8000:
        raise ValueError(f"Super Mario Bros. timing reader expects 32 KiB PRG, got {len(prg)}")

    timings: list[SmbTrackTiming] = []
    for track in SMB_TRACKS:
        if track.label == "ground":
            header_ys = tuple(range(0x11, 0x32))
            frames = sum(_square2_duration_for_header_y(prg, y) for y in header_ys)
            reason = "ground_headers_before_0x32_loopback"
        else:
            header_y = _header_y_for_track(track)
            if header_y is None:
                raise ValueError(f"no header Y for SMB track {track.label}")
            adder = 8 if track.label == "time-running-out" else 0
            frames = _square2_duration_for_header_y(
                prg,
                header_y,
                note_length_adder=adder,
            )
            header_ys = (header_y,)
            reason = "square2_0x00_end_marker"
        timings.append(
            SmbTrackTiming(
                track=track,
                frames=frames,
                seconds=frames / SMB_NTSC_FPS,
                reason=reason,
                header_ys=header_ys,
            )
        )
    return timings


def write_smb_trimmed_mp3s(
    rom_path: Path,
    nsf_dir: Path,
    out_dir: Path,
    *,
    fade_s: float = 2.0,
    bitrate: str = "192k",
) -> list[Path]:
    """Render split SMB NSFs to MP3 files trimmed before the first loop.

    Args:
        rom_path: User-supplied SMB ROM used only to compute exact timings.
        nsf_dir: Directory containing files created by ``write_smb_split_nsfs``.
        out_dir: Destination directory for MP3 files.
        fade_s: Fade-out duration at the end of each computed track window.
        bitrate: ffmpeg/libmp3lame bitrate, for example ``"192k"``.

    Returns:
        Paths of the MP3 files written.

    Raises:
        FileNotFoundError: If a required split NSF is missing.
        RuntimeError: If libgme/ffmpeg decoding fails through lower layers.
    """

    timings = read_smb_track_timings(Path(rom_path).read_bytes())
    nsf_dir = Path(nsf_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    with tempfile.TemporaryDirectory(prefix="qlnes-smb-mp3-") as tmp:
        tmp_dir = Path(tmp)
        for timing in timings:
            nsf = nsf_dir / f"{timing.track.index + 1:02d}-{timing.track.label}.nsf"
            if not nsf.exists():
                raise FileNotFoundError(nsf)
            wav = tmp_dir / f"{nsf.stem}.wav"
            mp3 = out_dir / f"{nsf.stem}.mp3"
            duration = max(0.05, timing.seconds)
            fade = min(max(0.0, fade_s), max(0.0, duration - 0.05))
            render_nsf(nsf, wav, track=0, duration_s=duration, fade_s=fade)
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-loglevel",
                    "error",
                    "-i",
                    str(wav),
                    "-codec:a",
                    "libmp3lame",
                    "-b:a",
                    bitrate,
                    str(mp3),
                ],
                check=True,
            )
            written.append(mp3)
    return written
