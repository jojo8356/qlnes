"""Wrapper haut-niveau autour de cynes pour scripter des scénarios.

Le runner encapsule un objet cynes.NES et expose des primitives stables :
- boot(frames)        : avance N frames sans aucune entrée (warmup PPU)
- hold(buttons, n)    : maintient un bitfield de boutons pendant n frames
- release()           : relâche tous les boutons
- snapshot_ram()      : copie 2KB de RAM CPU ($0000-$07FF)
- run_scenario(s)     : exécute un Scenario complet et collecte snapshots

Les Scenario sont des listes de (controller_bitmask, frames) qu'on enchaîne.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple, Union

try:
    import cynes
except ImportError as e:
    raise ImportError(
        "cynes non installé. Installer avec: pip install cynes "
        "(ou utiliser le venv .venv du projet)."
    ) from e


RAM_SIZE = 0x800
DEFAULT_BOOT_FRAMES = 60


@dataclass
class Snapshot:
    ram: bytes
    frame: int

    def __post_init__(self):
        if len(self.ram) != RAM_SIZE:
            raise ValueError(f"snapshot must be {RAM_SIZE} bytes, got {len(self.ram)}")

    def __getitem__(self, idx: int) -> int:
        return self.ram[idx]

    def diff(self, other: "Snapshot") -> dict:
        return {a: (self.ram[a], other.ram[a]) for a in range(RAM_SIZE)
                if self.ram[a] != other.ram[a]}


@dataclass
class Scenario:
    name: str
    steps: List[Tuple[int, int]] = field(default_factory=list)

    def hold(self, buttons: int, frames: int) -> "Scenario":
        if frames <= 0:
            raise ValueError("frames must be positive")
        self.steps.append((buttons, frames))
        return self

    def idle(self, frames: int) -> "Scenario":
        return self.hold(0, frames)

    def total_frames(self) -> int:
        return sum(f for _, f in self.steps)


class Runner:
    def __init__(self, rom_path: Union[str, Path]):
        self.rom_path = Path(rom_path)
        if not self.rom_path.exists():
            raise FileNotFoundError(self.rom_path)
        self.nes: Optional["cynes.NES"] = None
        self.frame = 0
        self._open()

    def _open(self):
        self.nes = cynes.NES(str(self.rom_path))
        self.frame = 0

    def reset(self) -> "Runner":
        self._open()
        return self

    def hold(self, buttons: int, frames: int) -> "Runner":
        self.nes.controller = buttons
        self.nes.step(frames)
        self.frame += frames
        return self

    def release(self) -> "Runner":
        self.nes.controller = 0
        return self

    def boot(self, frames: int = DEFAULT_BOOT_FRAMES) -> "Runner":
        return self.hold(0, frames)

    def snapshot_ram(self, lo: int = 0x0000, hi: int = RAM_SIZE) -> Snapshot:
        ram = bytes(self.nes[a] for a in range(lo, hi))
        if hi - lo != RAM_SIZE:
            padded = bytearray(RAM_SIZE)
            padded[lo:hi] = ram
            ram = bytes(padded)
        return Snapshot(ram=ram, frame=self.frame)

    def has_crashed(self) -> bool:
        return bool(self.nes.has_crashed)

    def run_scenario(
        self,
        scenario: Scenario,
        *,
        boot_frames: int = DEFAULT_BOOT_FRAMES,
        snapshot_each_step: bool = False,
    ) -> List[Snapshot]:
        self.reset()
        self.boot(boot_frames)
        snaps: List[Snapshot] = [self.snapshot_ram()]
        for buttons, frames in scenario.steps:
            self.hold(buttons, frames)
            if snapshot_each_step:
                snaps.append(self.snapshot_ram())
        if not snapshot_each_step:
            snaps.append(self.snapshot_ram())
        self.release()
        return snaps
