import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

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
    hardware: Dict[int, str] = field(default_factory=dict)
    oam: Dict[int, str] = field(default_factory=dict)
    dataflow: Dict[int, str] = field(default_factory=dict)
    subroutines: Dict[int, str] = field(default_factory=dict)
    subroutine_details: Dict[int, Subroutine] = field(default_factory=dict)
    fallback: Dict[int, str] = field(default_factory=dict)
    code_labels: Set[int] = field(default_factory=set)
    unmapped: Set[int] = field(default_factory=set)
    detections: List[Detection] = field(default_factory=list)

    @property
    def names(self) -> Dict[int, str]:
        merged: Dict[int, str] = {}
        merged.update(self.fallback)
        merged.update(self.oam)
        merged.update(self.dataflow)
        merged.update(self.subroutines)
        merged.update(self.hardware)
        return merged

    def to_dict(self) -> dict:
        def hexkeys(d: Dict[int, str]) -> Dict[str, str]:
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


def _pass_hardware(addrs: Set[int]) -> Dict[int, str]:
    return {a: NES_REGS[a] for a in addrs if a in NES_REGS}


def _pass_oam(addrs: Set[int]) -> Dict[int, str]:
    return {a: oam_name(a) for a in addrs if 0x0200 <= a <= 0x02FF}


def _pass_fallback(addrs: Set[int], already: Set[int]) -> Dict[int, str]:
    out: Dict[int, str] = {}
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


def _disambiguate(name: str, taken: Set[str]) -> str:
    if name not in taken:
        return name
    i = 2
    while f"{name}_{i}" in taken:
        i += 1
    return f"{name}_{i}"


def build_report(
    disasm: Disasm, image: Optional[bytes] = None
) -> AnnotationReport:
    addrs = set(disasm.referenced_addrs)
    report = AnnotationReport()
    report.hardware = _pass_hardware(addrs)
    report.oam = _pass_oam(addrs)

    detections = detect_all(disasm, image=image)
    report.detections = detections

    # Détecte d'abord les subroutines : leur kind sert à renommer les args
    # (`arg_pre_jsr` → `play_pulse_arg`, etc.) avant la dédup nom-unique.
    sub_kinds = detect_subroutine_kinds(disasm)
    used_names: Set[str] = set()
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
    arg_targets: Dict[int, Set[int]] = {}
    for d in detections:
        if d.name == "arg_pre_jsr" and d.target_addr is not None:
            arg_targets.setdefault(d.addr, set()).add(d.target_addr)
    renamed: Dict[int, str] = {}
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
    counts: Dict[str, int] = {}
    for n in renamed.values():
        counts[n] = counts.get(n, 0) + 1
    report.dataflow = {
        a: (f"{n}_{a:04X}" if counts[n] > 1 else n)
        for a, n in renamed.items()
    }

    mapped = set(report.hardware) | set(report.oam) | set(report.dataflow) | set(report.subroutines)
    report.fallback = _pass_fallback(addrs, mapped)

    code_label_addrs = {l.addr for l in disasm.lines if l.is_label and l.addr >= 0}
    report.code_labels = {a for a in addrs if a in code_label_addrs and a >= 0x4020 and a not in report.subroutines}

    all_classified = mapped | set(report.fallback) | report.code_labels
    report.unmapped = {a for a in addrs if a not in all_classified}
    return report


_DATA_DIRECTIVE = re.compile(r"(?:\b(?:DB|DW)\b|\.byte\b|\.word\b)", re.IGNORECASE)


def rewrite_asm(asm_text: str, names: Dict[int, str]) -> str:
    asm_text = rewrite_db_strings(asm_text)

    def sub_lbl(m: re.Match) -> str:
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

    return "\n".join(rewrite_line(l) for l in asm_text.splitlines()) + (
        "\n" if asm_text.endswith("\n") else ""
    )


def annotate(
    asm_text: str,
    *,
    image: Optional[bytes] = None,
    extra_names: Optional[Dict[int, str]] = None,
) -> Tuple[str, AnnotationReport]:
    disasm = Disasm(asm_text)
    report = build_report(disasm, image=image)
    names = report.names
    if extra_names:
        names.update(extra_names)
    rewritten = rewrite_asm(asm_text, names)
    return rewritten, report
