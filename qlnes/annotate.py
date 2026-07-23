import re
from dataclasses import dataclass, field
from typing import Any

from .asm_text import rewrite_db_strings
from .dataflow import (
    Detection,
    Subroutine,
    detect_all,
    detect_subroutine_kinds,
    merge_detections,
)
from .nes_hw import NES_REGS, oam_name
from .parser import Disasm

_LABEL_REF = re.compile(r"L_([0-9A-Fa-f]{4})")
_ZP_REF = re.compile(r"(?<![#A-Za-z_])0x([0-9A-Fa-f]{1,2})\b")


@dataclass
class AnnotationReport:
    hardware: dict[int, str] = field(default_factory=dict)
    oam: dict[int, str] = field(default_factory=dict)
    dataflow: dict[int, str] = field(default_factory=dict)
    subroutines: dict[int, str] = field(default_factory=dict)
    subroutine_details: dict[int, Subroutine] = field(default_factory=dict)
    fallback: dict[int, str] = field(default_factory=dict)
    code_labels: set[int] = field(default_factory=set)
    unmapped: set[int] = field(default_factory=set)
    detections: list[Detection] = field(default_factory=list)

    @property
    def names(self) -> dict[int, str]:
        merged: dict[int, str] = {}
        merged.update(self.fallback)
        merged.update(self.oam)
        merged.update(self.dataflow)
        merged.update(self.subroutines)
        merged.update(self.hardware)
        return merged

    def to_dict(self) -> dict[str, Any]:
        def hexkeys(d: dict[int, str]) -> dict[str, str]:
            return {f"0x{k:04X}": v for k, v in sorted(d.items())}

        return {
            "hardware": hexkeys(self.hardware),
            "oam": hexkeys(self.oam),
            "dataflow": hexkeys(self.dataflow),
            "subroutines": hexkeys(self.subroutines),
            "fallback": hexkeys(self.fallback),
            "code_labels": sorted(f"0x{a:04X}" for a in self.code_labels),
            "unmapped": sorted(f"0x{a:04X}" for a in self.unmapped),
            "detections": [
                {
                    "addr": f"0x{d.addr:04X}",
                    "name": d.name,
                    "confidence": round(d.confidence, 3),
                    "why": d.why,
                    "pattern": d.pattern,
                }
                for d in self.detections
            ],
            "summary": {
                "hardware": len(self.hardware),
                "oam": len(self.oam),
                "dataflow": len(self.dataflow),
                "subroutines": len(self.subroutines),
                "fallback": len(self.fallback),
                "code_labels": len(self.code_labels),
                "unmapped": len(self.unmapped),
            },
        }


def _symbol_kind(addr: int, report: AnnotationReport) -> str:
    if addr in report.hardware:
        if 0x2000 <= addr <= 0x2007:
            return "hw_ppu_reg"
        if 0x4000 <= addr <= 0x4017:
            return "hw_apu_io_reg"
        if 0xFFFA <= addr <= 0xFFFF:
            return "vector_const"
        return "hw_reg"
    if addr in report.oam:
        return "ram_oam_sprite"
    if addr in report.dataflow:
        if 0x0000 <= addr <= 0x00FF:
            return "ram_zp_var"
        if 0x0100 <= addr <= 0x01FF:
            return "ram_stack"
        if 0x0200 <= addr <= 0x07FF:
            return "ram_var"
        return "dataflow_symbol"
    if addr in report.subroutines:
        return "prg_subroutine"
    if addr in report.fallback:
        if 0x0000 <= addr <= 0x00FF:
            return "ram_zp_var"
        if 0x0100 <= addr <= 0x01FF:
            return "ram_stack"
        return "ram_var"
    if addr in report.code_labels:
        return "prg_code_label"
    if 0x0000 <= addr <= 0x00FF:
        return "ram_zp_var"
    if 0x0100 <= addr <= 0x01FF:
        return "ram_stack"
    if 0x0200 <= addr <= 0x02FF:
        return "ram_oam_sprite"
    if 0x0300 <= addr <= 0x07FF:
        return "ram_var"
    if 0x8000 <= addr <= 0xFFFF:
        return "prg_rom_const_or_code"
    return "unknown_ref"


def format_symbol_notation(names: dict[int, str], report: AnnotationReport) -> str:
    lines = [
        "; ============================================================",
        "; Symbol notation",
        "; @const: immediate value (#$xx) or immutable ROM/table data; not writable RAM.",
        "; @ram_zp_var: CPU RAM zero-page variable ($0000-$00FF).",
        "; @ram_var: CPU RAM variable ($0200-$07FF); @ram_oam_sprite is sprite DMA/OAM shadow.",
        "; @hw_ppu_reg / @hw_apu_io_reg: memory-mapped NES hardware register, not normal RAM.",
        "; @prg_subroutine / @prg_code_label: executable PRG-ROM target.",
        "; Format below: ; <name> = $addr ; @kind",
        "; ============================================================",
    ]
    for addr, name in sorted(names.items()):
        lines.append(f"; {name} = ${addr:04X} ; @{_symbol_kind(addr, report)}")
    lines.append("")
    return "\n".join(lines) + "\n"


def _pass_hardware(addrs: set[int]) -> dict[int, str]:
    return {a: NES_REGS[a] for a in addrs if a in NES_REGS}


def _pass_oam(addrs: set[int]) -> dict[int, str]:
    return {a: oam_name(a) for a in addrs if 0x0200 <= a <= 0x02FF}


def _pass_fallback(addrs: set[int], already: set[int]) -> dict[int, str]:
    out: dict[int, str] = {}
    for a in addrs:
        if a in already:
            continue
        if 0x0000 <= a <= 0x00FF:
            out[a] = f"zp_{a:02X}"
        elif 0x0100 <= a <= 0x01FF:
            out[a] = f"stack_{a:04X}"
        elif 0x0300 <= a <= 0x07FF:
            out[a] = f"ram_{a:04X}"
    return out


def _disambiguate(name: str, taken: set[str]) -> str:
    if name not in taken:
        return name
    i = 2
    while f"{name}_{i}" in taken:
        i += 1
    return f"{name}_{i}"


def build_report(disasm: Disasm, image: bytes | None = None) -> AnnotationReport:
    addrs = set(disasm.referenced_addrs)
    report = AnnotationReport()
    report.hardware = _pass_hardware(addrs)
    report.oam = _pass_oam(addrs)

    detections = detect_all(disasm, image=image)
    report.detections = detections

    # Détecte d'abord les subroutines : leur kind sert à renommer les args
    # (`arg_pre_jsr` → `play_pulse_arg`, etc.) avant la dédup nom-unique.
    sub_kinds = detect_subroutine_kinds(disasm)
    used_names: set[str] = set()
    for entry, sub in sorted(sub_kinds.items()):
        if entry not in addrs:
            continue
        unique = _disambiguate(sub.kind or f"sub_{entry:04X}", used_names)
        used_names.add(unique)
        sub.name = unique
        report.subroutines[entry] = unique
        report.subroutine_details[entry] = sub

    df_names, _ = merge_detections(detections)
    raw_dataflow = {a: n for a, n in df_names.items() if a not in report.hardware}

    # Si tous les JSR qui suivent un STA <addr> visent la même *famille* de
    # sub (même `kind`), renomme l'arg en `<kind>_arg`. Sinon laisse
    # `arg_pre_jsr` (la dédup ci-dessous suffixe l'adresse).
    arg_targets: dict[int, set[int]] = {}
    for d in detections:
        if d.name == "arg_pre_jsr" and d.target_addr is not None:
            arg_targets.setdefault(d.addr, set()).add(d.target_addr)
    renamed: dict[int, str] = {}
    for addr, name in raw_dataflow.items():
        if name == "arg_pre_jsr":
            kinds = {
                report.subroutine_details[t].kind
                for t in arg_targets.get(addr, ())
                if t in report.subroutine_details
            }
            kinds.discard(None)
            if len(kinds) == 1:
                renamed[addr] = f"{next(iter(kinds))}_arg"
                continue
        renamed[addr] = name

    # Dédup : un même nom ne peut pas pointer vers plusieurs adresses
    # (sinon le round-trip ne sait plus quelle adresse rétablir).
    counts: dict[str, int] = {}
    for n in renamed.values():
        counts[n] = counts.get(n, 0) + 1
    report.dataflow = {a: (f"{n}_{a:04X}" if counts[n] > 1 else n) for a, n in renamed.items()}

    mapped = set(report.hardware) | set(report.oam) | set(report.dataflow) | set(report.subroutines)
    report.fallback = _pass_fallback(addrs, mapped)

    code_label_addrs = {ln.addr for ln in disasm.lines if ln.is_label and ln.addr >= 0}
    report.code_labels = {
        a for a in addrs if a in code_label_addrs and a >= 0x4020 and a not in report.subroutines
    }

    all_classified = mapped | set(report.fallback) | report.code_labels
    report.unmapped = {a for a in addrs if a not in all_classified}
    return report


_DATA_DIRECTIVE = re.compile(r"(?:\b(?:DB|DW)\b|\.byte\b|\.word\b)", re.IGNORECASE)


def rewrite_asm(asm_text: str, names: dict[int, str]) -> str:
    asm_text = rewrite_db_strings(asm_text)

    def sub_lbl(m: re.Match[str]) -> str:
        addr = int(m.group(1), 16)
        return names.get(addr, m.group(0))

    def rewrite_line(line: str) -> str:
        comment_pos = line.find(";")
        if comment_pos >= 0:
            instr, comment = line[:comment_pos], line[comment_pos:]
        else:
            instr, comment = line, ""
        instr = _LABEL_REF.sub(sub_lbl, instr)
        if not _DATA_DIRECTIVE.search(instr):
            instr = _ZP_REF.sub(sub_lbl, instr)
        return instr + comment

    return "\n".join(rewrite_line(ln) for ln in asm_text.splitlines()) + (
        "\n" if asm_text.endswith("\n") else ""
    )


def annotate(
    asm_text: str,
    *,
    image: bytes | None = None,
    extra_names: dict[int, str] | None = None,
) -> tuple[str, AnnotationReport]:
    disasm = Disasm(asm_text)
    report = build_report(disasm, image=image)
    names = report.names
    if extra_names:
        names.update(extra_names)
    rewritten = rewrite_asm(asm_text, names)
    return format_symbol_notation(names, report) + rewritten, report
