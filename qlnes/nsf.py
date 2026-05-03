"""ROM NES → fichier NSF (NES Sound Format).

Le format NSF est un wrapper léger autour du code audio d'une ROM :
    - en-tête 128 octets (magic NESM\\x1a + métadonnées + adresses INIT/PLAY)
    - PRG data brute, chargée en mémoire à `load_addr`
    - le player NSF appelle INIT(A=song-1) une fois au démarrage,
      puis PLAY() à fréquence régulière (60 Hz NTSC).

Limites :
    - **Mapper 0 (NROM) seulement** en mode auto. C'est le seul cas
      simple : 16 ou 32 KB de PRG, pas de bankswitching, vecteurs
      directement utilisables.
    - **Mapper 1 (MMC1) et autres** : NSF a son propre système de
      bankswitching (writes à $5FF8-$5FFF) incompatible avec MMC1.
      Le mode `experimental=True` produit un NSF "best effort" qui
      ne joue PROBABLEMENT PAS correctement la musique sans RE manuel.

Spec NSF v1 : https://www.nesdev.org/wiki/NSF
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from .ines import HEADER_SIZE, parse_header, strip_ines


NSF_MAGIC = b"NESM\x1a"
NSF_HEADER_SIZE = 0x80
NTSC_FRAME_US = 16639  # 1 / 60.0988 fps en microsecondes
PAL_FRAME_US = 19997   # 1 / 50.007 fps


def build_nsf_header(
    *,
    songs: int = 1,
    start_song: int = 1,
    load_addr: int,
    init_addr: int,
    play_addr: int,
    title: str = "",
    artist: str = "",
    copyright_: str = "",
    ntsc_speed: int = NTSC_FRAME_US,
    pal_speed: int = PAL_FRAME_US,
    bankswitch: Tuple[int, int, int, int, int, int, int, int] = (0,) * 8,
    region: int = 0,         # bit 0 = PAL, bit 1 = both
    extra_chip: int = 0,     # bitfield : VRC6, VRC7, FDS, MMC5, Namco163, Sunsoft5B
) -> bytes:
    h = bytearray(NSF_HEADER_SIZE)
    h[0:5] = NSF_MAGIC
    h[5] = 1                 # version
    h[6] = songs & 0xFF
    h[7] = start_song & 0xFF
    h[8:10] = load_addr.to_bytes(2, "little")
    h[10:12] = init_addr.to_bytes(2, "little")
    h[12:14] = play_addr.to_bytes(2, "little")

    def _ascii32(s: str) -> bytes:
        b = s.encode("ascii", errors="replace")[:31]
        return b + b"\x00" * (32 - len(b))

    h[0x0E:0x2E] = _ascii32(title)
    h[0x2E:0x4E] = _ascii32(artist)
    h[0x4E:0x6E] = _ascii32(copyright_)
    h[0x6E:0x70] = ntsc_speed.to_bytes(2, "little")
    for i, b in enumerate(bankswitch[:8]):
        h[0x70 + i] = b & 0xFF
    h[0x78:0x7A] = pal_speed.to_bytes(2, "little")
    h[0x7A] = region & 0xFF
    h[0x7B] = extra_chip & 0xFF
    # 0x7C-0x7F : reserved (0)
    return bytes(h)


def _read_vector(prg_last_bank: bytes, vec_offset: int) -> int:
    """Lit un vecteur 16-bit LE depuis la dernière banque (mappée à $C000-$FFFF).
    `vec_offset` est l'offset CPU relatif à $C000 (ex: 0x3FFA pour NMI=$FFFA)."""
    lo = prg_last_bank[vec_offset]
    hi = prg_last_bank[vec_offset + 1]
    return lo | (hi << 8)


@dataclass
class NSFBuild:
    nsf_bytes: bytes
    load_addr: int
    init_addr: int
    play_addr: int
    note: str = ""


def build_nsf_from_rom(
    rom_bytes: bytes,
    *,
    title: str = "",
    artist: str = "qlnes",
    copyright_: str = "",
    init_addr: Optional[int] = None,
    play_addr: Optional[int] = None,
    songs: int = 1,
    start_song: int = 1,
    experimental: bool = False,
) -> NSFBuild:
    """Construit un NSF depuis une ROM iNES.

    Mode auto :
        - mapper 0 (NROM) : load=$8000 ou $C000 selon PRG size,
          INIT=RESET vector, PLAY=NMI vector.

    Mode expérimental :
        - tout autre mapper : prend la dernière banque PRG (16 KB),
          la charge à $C000, utilise NMI/RESET de cette banque.
          **N'inclut pas les autres banques** → la musique sera cassée
          si l'engine bankswitch en plein milieu, ce qui est le cas
          standard pour MMC1+.
    """
    h = parse_header(rom_bytes)
    if h is None:
        raise ValueError("ROM iNES invalide (header manquant)")

    prg = strip_ines(rom_bytes)
    note = ""

    if h.mapper == 0:
        # NROM : 16 KB → load $C000, miroirs $8000 ; 32 KB → load $8000
        if len(prg) == 0x4000:
            load_addr = 0xC000
            data = prg
        elif len(prg) == 0x8000:
            load_addr = 0x8000
            data = prg
        else:
            raise ValueError(
                f"NROM PRG attendu 16 ou 32 KB, trouvé {len(prg)}"
            )
        # Vecteurs lus depuis la fin du PRG (qui se mappe à $FFxx)
        last_bank = data[-0x4000:]
        nmi = _read_vector(last_bank, 0x3FFA)
        reset = _read_vector(last_bank, 0x3FFC)
        if init_addr is None:
            init_addr = reset
        if play_addr is None:
            play_addr = nmi
        nsf_data = data
    else:
        if not experimental:
            raise ValueError(
                f"Mapper {h.mapper} non supporté en auto (NSF n'a pas le "
                f"bankswitching MMC1+). Utilise --experimental pour un "
                f"best-effort, ou fournis --init/--play manuellement."
            )
        # Best-effort : on prend uniquement la dernière banque (souvent
        # la banque fixe pour MMC1 / contient le sound engine).
        last = prg[-0x4000:]
        load_addr = 0xC000
        nmi = _read_vector(last, 0x3FFA)
        reset = _read_vector(last, 0x3FFC)
        if init_addr is None:
            init_addr = reset
        if play_addr is None:
            play_addr = nmi
        nsf_data = last
        note = (
            f"⚠️  mode expérimental mapper {h.mapper} : "
            f"seule la dernière banque PRG (16 KB) est packagée. "
            f"Si l'engine audio bankswitche, la musique ne jouera pas."
        )

    header = build_nsf_header(
        songs=songs, start_song=start_song,
        load_addr=load_addr, init_addr=init_addr, play_addr=play_addr,
        title=title, artist=artist, copyright_=copyright_,
    )
    return NSFBuild(
        nsf_bytes=header + nsf_data,
        load_addr=load_addr, init_addr=init_addr, play_addr=play_addr,
        note=note,
    )


def write_nsf(rom_path: Path, out_path: Path, **kwargs) -> NSFBuild:
    rom_bytes = Path(rom_path).read_bytes()
    build = build_nsf_from_rom(rom_bytes, **kwargs)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(build.nsf_bytes)
    return build
