from dataclasses import dataclass
from pathlib import Path

INES_MAGIC = b"NES\x1a"
HEADER_SIZE = 16
PRG_BANK = 0x4000
CHR_BANK = 0x2000

SUPPORTED_MAPPERS = (0, 1, 2, 3, 66)


@dataclass
class INesHeader:
    prg_banks: int
    chr_banks: int
    mapper: int
    has_trainer: bool
    flags6: int
    flags7: int

    @property
    def prg_size(self) -> int:
        return self.prg_banks * PRG_BANK

    @property
    def chr_size(self) -> int:
        return self.chr_banks * CHR_BANK


def parse_header(data: bytes) -> INesHeader | None:
    if len(data) < HEADER_SIZE or data[:4] != INES_MAGIC:
        return None
    return INesHeader(
        prg_banks=data[4],
        chr_banks=data[5],
        mapper=((data[6] >> 4) & 0x0F) | (data[7] & 0xF0),
        has_trainer=bool(data[6] & 0x04),
        flags6=data[6],
        flags7=data[7],
    )


def strip_ines(data: bytes) -> bytes:
    h = parse_header(data)
    if h is None:
        return data
    offset = HEADER_SIZE + (512 if h.has_trainer else 0)
    return data[offset : offset + h.prg_size]


def _split_banks(prg: bytes) -> list[bytes]:
    n = len(prg) // PRG_BANK
    return [prg[i * PRG_BANK : (i + 1) * PRG_BANK] for i in range(n)]


def _layout_nrom(prg: bytes) -> list[tuple[int, bytes]]:
    image = bytearray(0x10000)
    if len(prg) == 0x8000:
        image[0x8000:0x10000] = prg
    elif len(prg) == 0x4000:
        image[0x8000:0xC000] = prg
        image[0xC000:0x10000] = prg
    else:
        raise ValueError(f"unexpected NROM PRG size {len(prg):#x}")
    return [(0, bytes(image))]


def _layout_uxrom(prg: bytes) -> list[tuple[int, bytes]]:
    banks = _split_banks(prg)
    if len(banks) < 2:
        raise ValueError(f"UxROM expects ≥2 banks, got {len(banks)}")
    last = banks[-1]
    out: list[tuple[int, bytes]] = []
    for idx, bank in enumerate(banks[:-1]):
        image = bytearray(0x10000)
        image[0x8000:0xC000] = bank
        image[0xC000:0x10000] = last
        out.append((idx, bytes(image)))
    out.append((len(banks) - 1, _fixed_only(last)))
    return out


def _layout_mmc1_default(prg: bytes) -> list[tuple[int, bytes]]:
    return _layout_uxrom(prg)


def _layout_gxrom(prg: bytes) -> list[tuple[int, bytes]]:
    # Mapper 66 (GxROM/GNROM) : PRG switchable par blocs de 32 KB en $8000-$FFFF.
    # Un seul registre en $8000-$FFFF : bits 5-4 = PRG bank, bits 1-0 = CHR bank.
    # Pas de half fixe : on émet une image 64 KB par bank PRG de 32 KB.
    if len(prg) % 0x8000 != 0 or len(prg) == 0:
        raise ValueError(f"GxROM PRG size {len(prg):#x} not a multiple of 32K")
    n = len(prg) // 0x8000
    out: list[tuple[int, bytes]] = []
    for idx in range(n):
        bank = prg[idx * 0x8000 : (idx + 1) * 0x8000]
        image = bytearray(0x10000)
        image[0x8000:0x10000] = bank
        out.append((idx, bytes(image)))
    return out


def _fixed_only(last: bytes) -> bytes:
    image = bytearray(0x10000)
    image[0x8000:0xC000] = last
    image[0xC000:0x10000] = last
    return bytes(image)


def rom_to_images(data: bytes) -> list[tuple[int, bytes]]:
    h = parse_header(data)
    if h is None:
        if len(data) > 0x10000:
            raise ValueError(f"raw image too big: {len(data)} bytes")
        image = bytearray(0x10000)
        image[: len(data)] = data
        return [(0, bytes(image))]
    if h.mapper not in SUPPORTED_MAPPERS:
        raise NotImplementedError(
            f"mapper {h.mapper} not supported. Supported: {SUPPORTED_MAPPERS}"
        )
    prg = strip_ines(data)
    if h.mapper in (0, 3):
        return _layout_nrom(prg)
    if h.mapper == 2:
        return _layout_uxrom(prg)
    if h.mapper == 1:
        return _layout_mmc1_default(prg)
    if h.mapper == 66:
        return _layout_gxrom(prg)
    raise NotImplementedError(f"mapper {h.mapper} unhandled")


def load_rom_to_image(path: Path | str) -> bytes:
    raw = Path(path).read_bytes()
    images = rom_to_images(raw)
    if len(images) > 1:
        raise ValueError(f"ROM has {len(images)} switchable banks, use Rom.banks() instead")
    return images[0][1]
