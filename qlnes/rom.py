from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

from .ines import INesHeader, parse_header, rom_to_images, strip_ines


@dataclass
class Bank:
    bank_id: int
    image: bytes
    is_fixed_only: bool = False


class Rom:
    def __init__(self, raw: bytes, name: str = "rom") -> None:
        self.raw = raw
        self.name = name
        self.header: Optional[INesHeader] = parse_header(raw)
        self._images: List[Tuple[int, bytes]] = rom_to_images(raw)
        if self.header is not None:
            self.prg = strip_ines(raw)
        else:
            self.prg = raw

    @classmethod
    def from_file(cls, path) -> "Rom":
        p = Path(path)
        return cls(p.read_bytes(), name=p.stem)

    @property
    def mapper(self) -> Optional[int]:
        return self.header.mapper if self.header else None

    @property
    def num_prg_banks(self) -> int:
        return self.header.prg_banks if self.header else 0

    def banks(self) -> Iterator[Bank]:
        last_idx = len(self._images) - 1
        for i, (bank_id, image) in enumerate(self._images):
            yield Bank(
                bank_id=bank_id,
                image=image,
                is_fixed_only=(self.mapper in (1, 2) and i == last_idx),
            )

    def single_image(self) -> bytes:
        if len(self._images) != 1:
            raise ValueError(
                f"ROM has {len(self._images)} banks; use banks() instead"
            )
        return self._images[0][1]

    def __repr__(self) -> str:
        return (
            f"Rom(name={self.name!r}, mapper={self.mapper}, "
            f"prg_banks={self.num_prg_banks}, switchable_layouts={len(self._images)})"
        )
