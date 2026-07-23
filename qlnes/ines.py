from dataclasses import dataclass
from pathlib import Path

INES_MAGIC = b"NES\x1a"
HEADER_SIZE = 16
PRG_BANK = 0x4000
CHR_BANK = 0x2000

SUPPORTED_MAPPERS = (0, 1, 2, 3, 4, 5, 7, 9, 10, 11, 13, 16, 18, 19, 21, 22, 23, 24, 25, 26, 32, 33, 34, 42, 66, 69, 70, 71, 72, 78, 79, 87, 101, 206)


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


def _layout_axrom(prg: bytes) -> list[tuple[int, bytes]]:
    # Mapper 7 (AxROM): switchable 32 KiB PRG bank at $8000-$FFFF.
    if len(prg) % 0x8000 != 0 or len(prg) == 0:
        raise ValueError(f"AxROM PRG size {len(prg):#x} not a multiple of 32K")
    out: list[tuple[int, bytes]] = []
    for idx in range(len(prg) // 0x8000):
        bank = prg[idx * 0x8000 : (idx + 1) * 0x8000]
        image = bytearray(0x10000)
        image[0x8000:0x10000] = bank
        out.append((idx, bytes(image)))
    return out


def _layout_colordreams(prg: bytes) -> list[tuple[int, bytes]]:
    # Mapper 11 (Color Dreams): switchable 32 KiB PRG bank at $8000-$FFFF.
    if len(prg) % 0x8000 != 0 or len(prg) == 0:
        raise ValueError(f"Color Dreams PRG size {len(prg):#x} not a multiple of 32K")
    out: list[tuple[int, bytes]] = []
    for idx in range(len(prg) // 0x8000):
        bank = prg[idx * 0x8000 : (idx + 1) * 0x8000]
        image = bytearray(0x10000)
        image[0x8000:0x10000] = bank
        out.append((idx, bytes(image)))
    return out


def _layout_bnrom(prg: bytes) -> list[tuple[int, bytes]]:
    # Mapper 34 BNROM/NINA: switchable 32 KiB PRG bank at $8000-$FFFF.
    if len(prg) % 0x8000 != 0 or len(prg) == 0:
        raise ValueError(f"Mapper 34 PRG size {len(prg):#x} not a multiple of 32K")
    out: list[tuple[int, bytes]] = []
    for idx in range(len(prg) // 0x8000):
        bank = prg[idx * 0x8000 : (idx + 1) * 0x8000]
        image = bytearray(0x10000)
        image[0x8000:0x10000] = bank
        out.append((idx, bytes(image)))
    return out


def _layout_mmc3_initial(prg: bytes) -> list[tuple[int, bytes]]:
    # Mapper 4 (MMC3): CPU PRG windows are 8 KiB. At reset, code is expected
    # to live in the fixed last 8 KiB window ($E000-$FFFF) and initialize the
    # mapper before leaving it. This static image is only a conservative view
    # for construction/disassembly; the in-process runner handles runtime
    # bank writes.
    if len(prg) % 0x2000 != 0 or len(prg) < 0x8000:
        raise ValueError(f"MMC3 PRG size {len(prg):#x} must be at least 32K")
    banks = [prg[i : i + 0x2000] for i in range(0, len(prg), 0x2000)]
    image = bytearray(0x10000)
    image[0x8000:0xA000] = banks[0]
    image[0xA000:0xC000] = banks[1]
    image[0xC000:0xE000] = banks[-2]
    image[0xE000:0x10000] = banks[-1]
    return [(0, bytes(image))]


def _layout_mmc2_initial(prg: bytes) -> list[tuple[int, bytes]]:
    # Mapper 9 (MMC2): one switchable 8 KiB PRG bank at $8000-$9FFF and
    # fixed last three 8 KiB banks at $A000-$FFFF.
    if len(prg) % 0x2000 != 0 or len(prg) < 0x8000:
        raise ValueError(f"MMC2 PRG size {len(prg):#x} must be at least 32K")
    banks = [prg[i : i + 0x2000] for i in range(0, len(prg), 0x2000)]
    image = bytearray(0x10000)
    image[0x8000:0xA000] = banks[0]
    image[0xA000:0xC000] = banks[-3]
    image[0xC000:0xE000] = banks[-2]
    image[0xE000:0x10000] = banks[-1]
    return [(0, bytes(image))]


def _layout_fme7_initial(prg: bytes) -> list[tuple[int, bytes]]:
    # Mapper 69 (Sunsoft FME-7/5B): CPU PRG windows are 8 KiB at
    # $8000/$A000/$C000 and the last 8 KiB bank is fixed at $E000-$FFFF.
    # This static image is the reset-safe view; runtime mapper writes are
    # modeled by the in-process runner for sprite capture.
    if len(prg) % 0x2000 != 0 or len(prg) < 0x8000:
        raise ValueError(f"FME-7 PRG size {len(prg):#x} must be at least 32K")
    banks = [prg[i : i + 0x2000] for i in range(0, len(prg), 0x2000)]
    image = bytearray(0x10000)
    image[0x8000:0xA000] = banks[0]
    image[0xA000:0xC000] = banks[1]
    image[0xC000:0xE000] = banks[2]
    image[0xE000:0x10000] = banks[-1]
    return [(0, bytes(image))]


def _layout_mapper42_initial(prg: bytes) -> list[tuple[int, bytes]]:
    # Mapper 42: fixed last 32 KiB at $8000-$FFFF and an 8 KiB switchable
    # PRG-ROM window at $6000-$7FFF. Runtime bank writes are modeled by the
    # in-process runner; this image exposes the reset-safe fixed region.
    if len(prg) % 0x2000 != 0 or len(prg) < 0x8000:
        raise ValueError(f"Mapper 42 PRG size {len(prg):#x} must be at least 32K")
    image = bytearray(0x10000)
    image[0x6000:0x8000] = prg[:0x2000]
    image[0x8000:0x10000] = prg[-0x8000:]
    return [(0, bytes(image))]


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
    if h.mapper in (0, 3, 13, 87, 101):
        return _layout_nrom(prg)
    if h.mapper in (2, 16, 70, 72, 78):
        return _layout_uxrom(prg)
    if h.mapper == 1:
        return _layout_mmc1_default(prg)
    if h.mapper in (4, 206):
        return _layout_mmc3_initial(prg)
    if h.mapper == 7:
        return _layout_axrom(prg)
    if h.mapper == 9:
        return _layout_mmc2_initial(prg)
    if h.mapper == 10:
        return _layout_uxrom(prg)
    if h.mapper in (11, 79):
        return _layout_colordreams(prg)
    if h.mapper == 34:
        return _layout_bnrom(prg)
    if h.mapper == 42:
        return _layout_mapper42_initial(prg)
    if h.mapper == 66:
        return _layout_gxrom(prg)
    if h.mapper in (5, 18, 19, 21, 22, 23, 24, 25, 26, 32, 33, 69):
        return _layout_fme7_initial(prg)
    if h.mapper == 71:
        return _layout_uxrom(prg)
    raise NotImplementedError(f"mapper {h.mapper} unhandled")


def load_rom_to_image(path: Path | str) -> bytes:
    raw = Path(path).read_bytes()
    images = rom_to_images(raw)
    if len(images) > 1:
        raise ValueError(f"ROM has {len(images)} switchable banks, use Rom.banks() instead")
    return images[0][1]
