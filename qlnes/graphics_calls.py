"""Static graphics-call analysis for NES ROM disassemblies.

NES games rarely call a clean `draw_sprite()` routine. Graphics code is usually
recognized by its hardware effects: writes to PPU registers, OAM RAM/OAMDMA and
mapper bank registers. This module collects those sites so qlnes can guide the
runtime sprite capture workflow from ASM evidence.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field

from .ines import INesHeader
from .nes_hw import NES_REGS
from .parser import Disasm, Line

_HEX = re.compile(r"(?:0x|\$|L_)([0-9A-Fa-f]{2,4})")
_WRITE_MNEMONICS = {"STA", "STX", "STY"}
_READ_MNEMONICS = {"LDA", "LDX", "LDY", "BIT"}
_PPU_NAMES = {
    "PPUCTRL": 0x2000,
    "PPUMASK": 0x2001,
    "PPUSTATUS": 0x2002,
    "OAMADDR": 0x2003,
    "OAMDATA": 0x2004,
    "PPUSCROLL": 0x2005,
    "PPUADDR": 0x2006,
    "PPUDATA": 0x2007,
    "OAMDMA": 0x4014,
}


@dataclass(frozen=True)
class GraphicsCall:
    """One ASM site that touches graphics hardware or mapper graphics state."""

    addr: int
    mnemonic: str
    operands: str
    target_addr: int | None
    target_name: str
    kind: str
    confidence: float
    why: str
    context: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "addr": f"0x{self.addr:04X}",
            "mnemonic": self.mnemonic,
            "operands": self.operands,
            "target_addr": f"0x{self.target_addr:04X}" if self.target_addr is not None else None,
            "target_name": self.target_name,
            "kind": self.kind,
            "confidence": self.confidence,
            "why": self.why,
            "context": list(self.context),
        }


@dataclass
class GraphicsCallReport:
    """Summary of graphics-relevant ASM calls."""

    calls: list[GraphicsCall] = field(default_factory=list)

    @property
    def counts_by_kind(self) -> dict[str, int]:
        return dict(Counter(call.kind for call in self.calls))

    def by_kind(self, kind: str) -> list[GraphicsCall]:
        return [call for call in self.calls if call.kind == kind]

    def to_dict(self) -> dict[str, object]:
        return {
            "summary": {
                "calls": len(self.calls),
                "kinds": self.counts_by_kind,
            },
            "calls": [call.to_dict() for call in self.calls],
        }

    def to_markdown(self, *, limit: int = 40) -> str:
        lines: list[str] = []
        lines.append("## Analyse ASM graphique")
        lines.append("")
        if not self.calls:
            lines.append("Aucun write PPU/OAM/mapper graphique direct detecte dans l'ASM statique.")
            lines.append("")
            return "\n".join(lines)

        lines.append("Résumé des points ASM qui pilotent les images/sprites :")
        lines.append("")
        for kind, count in sorted(self.counts_by_kind.items()):
            lines.append(f"- `{kind}` : {count}")
        lines.append("")
        lines.append("| Adresse | Type | Cible | Instruction | Pourquoi |")
        lines.append("|---|---|---|---|---|")
        for call in self.calls[:limit]:
            target = (
                f"{call.target_name} `${call.target_addr:04X}`"
                if call.target_addr is not None
                else call.target_name
            )
            instr = f"{call.mnemonic} {call.operands}".strip()
            lines.append(
                f"| `${call.addr:04X}` | `{call.kind}` | {target} | `{instr}` | {call.why} |"
            )
        if len(self.calls) > limit:
            lines.append(f"| ... | ... | ... | ... | {len(self.calls) - limit} appels masques |")
        lines.append("")
        lines.append(
            "Utilisation pratique : suivre ces adresses avec trace/debugger pour trouver les "
            "tables source des niveaux, palettes, OAM et banques CHR."
        )
        lines.append("")
        return "\n".join(lines)


def analyze_graphics_calls(disasm: Disasm, header: INesHeader | None = None) -> GraphicsCallReport:
    """Find ASM sites that drive NES graphics state.

    The detector is intentionally conservative: it records direct CPU accesses
    visible in the disassembly. Indirect data formats remain engine-specific,
    but these sites are the entry points to trace.
    """

    code = disasm.code_lines()
    calls: list[GraphicsCall] = []
    for index, line in enumerate(code):
        mnemonic = (line.mnemonic or "").upper()
        if mnemonic not in _WRITE_MNEMONICS and mnemonic not in _READ_MNEMONICS:
            continue
        target = _target_addr(line)
        named_target = _target_name(line, target)
        if target is None and named_target == "unknown":
            continue

        kind, confidence, why = _classify(line, target, named_target, header, index, code)
        if kind is None:
            continue
        calls.append(
            GraphicsCall(
                addr=line.addr,
                mnemonic=mnemonic,
                operands=line.operands or "",
                target_addr=target,
                target_name=named_target,
                kind=kind,
                confidence=confidence,
                why=why,
                context=_context_lines(code, index),
            )
        )
    return GraphicsCallReport(_dedupe(calls))


def _target_addr(line: Line) -> int | None:
    if line.refs:
        return line.refs[0]
    operands = line.operands or ""
    for match in _HEX.finditer(operands):
        value = int(match.group(1), 16)
        if value <= 0xFFFF:
            return value
    return None


def _target_name(line: Line, target: int | None) -> str:
    operands = line.operands or ""
    if "sprite_" in operands:
        return "OAM_BUFFER"
    for name, addr in _PPU_NAMES.items():
        if name in operands:
            return name
        if target == addr:
            return name
    if target is not None:
        return NES_REGS.get(target, f"${target:04X}")
    return "unknown"


def _classify(
    line: Line,
    target: int | None,
    target_name: str,
    header: INesHeader | None,
    index: int,
    code: list[Line],
) -> tuple[str | None, float, str]:
    mnemonic = (line.mnemonic or "").upper()
    if mnemonic in _READ_MNEMONICS:
        if target == 0x2002 or target_name == "PPUSTATUS":
            return ("ppu_status_latch", 0.55, "lecture PPUSTATUS avant sequence PPUADDR/PPUDATA")
        return (None, 0.0, "")

    if target == 0x4014 or target_name == "OAMDMA":
        return ("oam_dma", 0.98, "DMA copie une page CPU vers OAM sprites")
    if target_name == "OAM_BUFFER" or (target is not None and 0x0200 <= target <= 0x02FF):
        return ("oam_buffer_write", 0.9, "write dans le buffer OAM CPU $0200-$02FF")
    if target == 0x2003 or target_name == "OAMADDR":
        return ("oam_addr", 0.8, "selectionne l'adresse OAM avant OAMDATA/DMA")
    if target == 0x2004 or target_name == "OAMDATA":
        return ("oam_data_write", 0.85, "write direct dans OAMDATA")
    if target == 0x2000 or target_name == "PPUCTRL":
        return ("ppu_ctrl", 0.85, "controle NMI, pattern table sprite et taille 8x16")
    if target == 0x2001 or target_name == "PPUMASK":
        return ("ppu_mask", 0.75, "active/desactive rendu sprites/background et emphasis")
    if target == 0x2005 or target_name == "PPUSCROLL":
        return ("scroll_write", 0.75, "write scroll PPU")
    if target == 0x2006 or target_name == "PPUADDR":
        return ("ppu_addr", 0.8, "selectionne l'adresse VRAM pour PPUDATA")
    if target == 0x2007 or target_name == "PPUDATA":
        ppu_addr = _recent_ppuaddr_literal(index, code)
        if ppu_addr is not None and 0x3F00 <= ppu_addr <= 0x3FFF:
            return ("palette_upload", 0.9, "PPUDATA apres PPUADDR palette $3F00-$3FFF")
        if ppu_addr is not None and 0x0000 <= ppu_addr <= 0x1FFF:
            return ("chr_ram_upload", 0.85, "PPUDATA vers pattern table $0000-$1FFF")
        if ppu_addr is not None and 0x2000 <= ppu_addr <= 0x2FFF:
            return ("nametable_upload", 0.85, "PPUDATA vers nametable $2000-$2FFF")
        return ("ppu_data_write", 0.65, "write VRAM via PPUDATA; adresse PPU a tracer")
    if _is_mapper_write(target, header):
        return ("mapper_bank_switch", 0.7, "write registre mapper; peut changer PRG/CHR visible")
    return (None, 0.0, "")


def _recent_ppuaddr_literal(index: int, code: list[Line]) -> int | None:
    values: list[int] = []
    window_start = max(0, index - 12)
    for pos in range(window_start, index):
        line = code[pos]
        if (line.mnemonic or "").upper() not in _WRITE_MNEMONICS:
            continue
        target = _target_addr(line)
        target_name = _target_name(line, target)
        if target != 0x2006 and target_name != "PPUADDR":
            continue
        value = _previous_immediate_byte(pos, code)
        if value is not None:
            values.append(value)
    if len(values) < 2:
        return None
    return ((values[-2] << 8) | values[-1]) & 0x3FFF


def _previous_immediate_byte(index: int, code: list[Line]) -> int | None:
    for line in reversed(code[max(0, index - 3) : index]):
        if (line.mnemonic or "").upper() != "LDA":
            continue
        operands = (line.operands or "").strip()
        if not operands.startswith("#"):
            continue
        return _literal_byte(operands[1:].strip())
    return None


def _literal_byte(text: str) -> int | None:
    text = text.strip()
    if text.startswith("$"):
        text = text[1:]
    if text.lower().startswith("0x"):
        text = text[2:]
    try:
        value = int(text, 16)
    except ValueError:
        return None
    if 0 <= value <= 0xFF:
        return value
    return None


def _is_mapper_write(target: int | None, header: INesHeader | None) -> bool:
    if target is None or header is None or header.mapper == 0:
        return False
    if 0x8000 <= target <= 0xFFFF:
        return True
    if header.mapper in (16, 79, 87, 101) and 0x4100 <= target <= 0x7FFF:
        return True
    return header.mapper == 5 and 0x5100 <= target <= 0x5130


def _context_lines(code: list[Line], index: int) -> tuple[str, ...]:
    return tuple(line.raw for line in code[max(0, index - 3) : min(len(code), index + 2)])


def _dedupe(calls: Iterable[GraphicsCall]) -> list[GraphicsCall]:
    seen: set[tuple[int, str, int | None, str]] = set()
    out: list[GraphicsCall] = []
    for call in calls:
        key = (call.addr, call.kind, call.target_addr, call.operands)
        if key in seen:
            continue
        seen.add(key)
        out.append(call)
    return sorted(out, key=lambda call: (call.addr, call.kind))
