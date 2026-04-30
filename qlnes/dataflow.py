"""Pattern detection on parsed disassembly.

These are static heuristics, not true dataflow analysis. They scan windows
of consecutive instructions looking for canonical 6502/NES idioms.
Each detector reports candidates with a confidence and an explanation.
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from .parser import Disasm, Line


_HEX = re.compile(r"\$?0x([0-9A-Fa-f]+)|\$([0-9A-Fa-f]+)")
_ZP_OPERAND = re.compile(r"^0x([0-9A-Fa-f]{1,2})$")


@dataclass
class Detection:
    addr: int
    name: str
    confidence: float
    why: str
    pattern: str


def _operand_addr(line: Line) -> Optional[int]:
    if not line.operands:
        return None
    op = line.operands.strip()
    if op.startswith("#"):
        return None
    m = _ZP_OPERAND.match(op)
    if m:
        return int(m.group(1), 16)
    if line.refs:
        return line.refs[0]
    m = _HEX.search(op)
    if m:
        return int(m.group(1) or m.group(2), 16)
    return None


def _is_zp_or_ram(addr: Optional[int]) -> bool:
    if addr is None:
        return False
    if 0x0000 <= addr <= 0x00FF:
        return True
    if 0x0300 <= addr <= 0x07FF:
        return True
    return False


def detect_frame_counter(
    disasm: Disasm, nmi_addr: Optional[int] = None
) -> List[Detection]:
    out: List[Detection] = []
    code = disasm.code_lines()
    if not code:
        return out

    handlers: List[int] = []
    if nmi_addr is not None:
        handlers.append(nmi_addr)
    by_addr = {l.addr: i for i, l in enumerate(code)}

    candidates: Set[int] = set()
    if not handlers:
        for i, line in enumerate(code[:50]):
            if line.mnemonic and line.mnemonic.upper() == "INC":
                a = _operand_addr(line)
                if _is_zp_or_ram(a):
                    candidates.add(a)
    else:
        for h in handlers:
            if h not in by_addr:
                continue
            start = by_addr[h]
            for line in code[start : start + 30]:
                up = (line.mnemonic or "").upper()
                if up in ("BCC", "BCS", "BEQ", "BNE", "BMI", "BPL", "BVC", "BVS"):
                    break
                if up == "INC":
                    a = _operand_addr(line)
                    if _is_zp_or_ram(a):
                        candidates.add(a)
                        break

    for a in candidates:
        out.append(
            Detection(
                addr=a,
                name="frame_counter",
                confidence=0.85 if nmi_addr else 0.55,
                why="INC unconditionnel près du NMI handler" if nmi_addr else "INC précoce",
                pattern="INC <addr>",
            )
        )
    return out


_JOY_TOKENS = ("JOY1", "JOY2_FRAMECTR", "L_4016", "L_4017", "0x4016", "0x4017", "$4016", "$4017")


def detect_controller_reads(disasm: Disasm) -> List[Detection]:
    out: List[Detection] = []
    code = disasm.code_lines()
    by_addr: Dict[int, Dict[str, int]] = {}
    for i, line in enumerate(code):
        up = (line.mnemonic or "").upper()
        operands = (line.operands or "")
        if up != "LDA":
            continue
        joy = None
        for tok in _JOY_TOKENS:
            if tok in operands:
                joy = "1" if "4016" in tok or "JOY1" == tok else "2"
                break
        if joy is None:
            continue
        for j in range(max(0, i - 2), min(len(code), i + 6)):
            lj = code[j]
            if (lj.mnemonic or "").upper() != "ROL":
                continue
            a = _operand_addr(lj)
            if _is_zp_or_ram(a):
                slot = by_addr.setdefault(a, {"1": 0, "2": 0})
                slot[joy] += 1
    for a, slot in sorted(by_addr.items()):
        if slot["1"] >= 2:
            out.append(
                Detection(
                    addr=a,
                    name="controller1_state",
                    confidence=0.9,
                    why=f"LDA $4016 / ROL ${a:04X} répété {slot['1']}×",
                    pattern="LDA JOY1 ; LSR A ; ROL <addr>",
                )
            )
        elif slot["2"] >= 2:
            out.append(
                Detection(
                    addr=a,
                    name="controller2_state",
                    confidence=0.9,
                    why=f"LDA $4017 / ROL ${a:04X} répété {slot['2']}×",
                    pattern="LDA JOY2 ; LSR A ; ROL <addr>",
                )
            )
    return out


_OAM_TOKENS = ("sprite_", "0x0200", "$0200", "L_0200", "L_0201", "L_0202", "L_0203")


def detect_oam_indices(disasm: Disasm) -> List[Detection]:
    out: List[Detection] = []
    code = disasm.code_lines()
    found: Dict[int, str] = {}
    for i, line in enumerate(code):
        up = (line.mnemonic or "").upper()
        if up not in ("LDX", "LDY"):
            continue
        idx_addr = _operand_addr(line)
        if not _is_zp_or_ram(idx_addr):
            continue
        for j in range(i + 1, min(len(code), i + 10)):
            nl = code[j]
            up2 = (nl.mnemonic or "").upper()
            ops = (nl.operands or "")
            if up2 in ("STA", "LDA") and any(t in ops for t in _OAM_TOKENS):
                found[idx_addr] = up
                break
            if up2 in ("RTS", "RTI", "JMP"):
                break
    for a, reg in found.items():
        out.append(
            Detection(
                addr=a,
                name="oam_index",
                confidence=0.7,
                why=f"{reg} ${a:04X} suivi d'accès OAM ($0200,{reg[1]})",
                pattern=f"{reg} <addr> ; ... STA $0200,{reg[1]}",
            )
        )
    return out


def detect_pointer_pairs(disasm: Disasm) -> List[Detection]:
    out: List[Detection] = []
    code = disasm.code_lines()
    indirect_targets: Set[int] = set()
    for line in code:
        up = (line.mnemonic or "").upper()
        ops = (line.operands or "").strip()
        if up in ("JMP", "LDA", "STA", "ADC", "SBC", "CMP", "AND", "ORA", "EOR"):
            m = re.match(r"\(\s*(?:0x([0-9A-Fa-f]+)|\$([0-9A-Fa-f]+))", ops)
            if m:
                a = int(m.group(1) or m.group(2), 16)
                if 0 <= a <= 0xFF:
                    indirect_targets.add(a)
    counter = 0
    for a in sorted(indirect_targets):
        out.append(
            Detection(
                addr=a,
                name=f"ptr{counter}_lo",
                confidence=0.8,
                why="utilisé en addressing indirect (zp),Y ou (zp,X)",
                pattern="LDA (zp),Y / JMP (zp)",
            )
        )
        out.append(
            Detection(
                addr=a + 1,
                name=f"ptr{counter}_hi",
                confidence=0.75,
                why=f"high byte du pointeur ${a:02X}/${a+1:02X}",
                pattern="zp+1 par convention",
            )
        )
        counter += 1
    return out


_OAMDMA_TOKENS = ("OAMDMA", "L_4014", "0x4014", "$4014")


def detect_oamdma_buffer(disasm: Disasm) -> List[Detection]:
    out: List[Detection] = []
    code = disasm.code_lines()
    for i, line in enumerate(code):
        up = (line.mnemonic or "").upper()
        ops = (line.operands or "")
        if up != "STA" or not any(t in ops for t in _OAMDMA_TOKENS):
            continue
        for j in range(max(0, i - 4), i):
            prev = code[j]
            up2 = (prev.mnemonic or "").upper()
            if up2 == "LDA" and prev.operands and prev.operands.startswith("#"):
                val = prev.operands[1:].strip()
                try:
                    page = int(val.replace("0x", ""), 16)
                except ValueError:
                    continue
                if 0x02 <= page <= 0x07:
                    out.append(
                        Detection(
                            addr=page << 8,
                            name="oam_dma_page",
                            confidence=0.95,
                            why=f"OAMDMA write avec page #${page:02X}",
                            pattern="LDA #$xx ; STA OAMDMA",
                        )
                    )
                    break
    seen: Set[int] = set()
    out_dedup: List[Detection] = []
    for d in out:
        if d.addr in seen:
            continue
        seen.add(d.addr)
        out_dedup.append(d)
    return out_dedup


_PPU_SHADOW_TARGETS = {
    "PPUCTRL": ("ppu_ctrl_shadow", 0x2000),
    "L_2000": ("ppu_ctrl_shadow", 0x2000),
    "PPUMASK": ("ppu_mask_shadow", 0x2001),
    "L_2001": ("ppu_mask_shadow", 0x2001),
}


def detect_ppu_shadows(disasm: Disasm) -> List[Detection]:
    out: List[Detection] = []
    seen: Set[int] = set()
    code = disasm.code_lines()
    for i, line in enumerate(code):
        if (line.mnemonic or "").upper() != "STA":
            continue
        ops = line.operands or ""
        target = None
        for tok, info in _PPU_SHADOW_TARGETS.items():
            if tok in ops:
                target = info
                break
        if target is None:
            continue
        for j in range(max(0, i - 4), i):
            prev = code[j]
            up = (prev.mnemonic or "").upper()
            if up != "LDA":
                continue
            a = _operand_addr(prev)
            if not _is_zp_or_ram(a) or a in seen:
                continue
            seen.add(a)
            out.append(
                Detection(
                    addr=a,
                    name=target[0],
                    confidence=0.85,
                    why=f"LDA ${a:04X} ; STA ${target[1]:04X} (shadow register)",
                    pattern="LDA <zp> ; STA PPU_REG",
                )
            )
            break
    return out


def detect_loop_counters(disasm: Disasm) -> List[Detection]:
    out: List[Detection] = []
    code = disasm.code_lines()
    for i, line in enumerate(code):
        up = (line.mnemonic or "").upper()
        if up not in ("LDX", "LDY"):
            continue
        a = _operand_addr(line)
        if not _is_zp_or_ram(a):
            continue
        decmn = "DEX" if up == "LDX" else "DEY"
        for j in range(i + 1, min(len(code), i + 12)):
            nxt = code[j]
            if (nxt.mnemonic or "").upper() == decmn:
                for k in range(j + 1, min(len(code), j + 4)):
                    bnext = code[k]
                    if (bnext.mnemonic or "").upper() == "BNE":
                        out.append(
                            Detection(
                                addr=a,
                                name="loop_counter",
                                confidence=0.75,
                                why=f"LD{up[2]} ${a:04X} ... {decmn} ; BNE",
                                pattern="LDX/Y <zp> ; ... DEX/Y ; BNE",
                            )
                        )
                        break
                break
            if (nxt.mnemonic or "").upper() in ("RTS", "RTI", "JMP", "JSR"):
                break
    seen: Set[int] = set()
    return [d for d in out if d.addr not in seen and not seen.add(d.addr)]


def detect_subroutine_args(disasm: Disasm) -> List[Detection]:
    out: List[Detection] = []
    code = disasm.code_lines()
    seen: Set[int] = set()
    for i, line in enumerate(code):
        if (line.mnemonic or "").upper() != "JSR":
            continue
        for j in range(max(0, i - 4), i):
            prev = code[j]
            up = (prev.mnemonic or "").upper()
            if up != "STA":
                continue
            a = _operand_addr(prev)
            if not _is_zp_or_ram(a) or a in seen:
                continue
            seen.add(a)
            out.append(
                Detection(
                    addr=a,
                    name="arg_pre_jsr",
                    confidence=0.55,
                    why=f"STA ${a:04X} juste avant JSR (probable argument)",
                    pattern="STA <zp> ; ... ; JSR <routine>",
                )
            )
    return out


@dataclass
class Subroutine:
    entry: int
    body: List[Line]
    name: Optional[str] = None
    kind: Optional[str] = None
    why: Optional[str] = None

    @property
    def size(self) -> int:
        return len(self.body)


def find_subroutines(disasm: Disasm, max_body: int = 200) -> List[Subroutine]:
    code = disasm.code_lines()
    line_idx = {l.addr: i for i, l in enumerate(code)}
    targets: Set[int] = set()
    for line in code:
        if (line.mnemonic or "").upper() != "JSR":
            continue
        if line.refs:
            targets.add(line.refs[0])
    subs: List[Subroutine] = []
    for entry in sorted(targets):
        if entry not in line_idx:
            continue
        start = line_idx[entry]
        body: List[Line] = []
        for j in range(start, min(len(code), start + max_body)):
            ln = code[j]
            body.append(ln)
            up = (ln.mnemonic or "").upper()
            if up in ("RTS", "RTI"):
                break
            if up == "JMP" and ln.refs and ln.refs[0] in targets:
                break
        subs.append(Subroutine(entry=entry, body=body))
    return subs


def _classify_subroutine(body: List[Line]) -> Tuple[Optional[str], Optional[str]]:
    apu_targets: Set[int] = set()
    ppu_targets: Set[int] = set()
    has_oam_dma = False
    has_joy1_strobe = False
    has_joy_read_loop = 0
    has_pulse = has_triangle = has_noise = has_dmc = False
    for line in body:
        for ref in line.refs:
            if 0x2000 <= ref <= 0x3FFF:
                ppu_targets.add(ref & 0x2007)
            elif 0x4000 <= ref <= 0x4017:
                apu_targets.add(ref)
            if ref == 0x4014:
                has_oam_dma = True
            if 0x4000 <= ref <= 0x4007:
                has_pulse = True
            if 0x4008 <= ref <= 0x400B:
                has_triangle = True
            if 0x400C <= ref <= 0x400F:
                has_noise = True
            if 0x4010 <= ref <= 0x4013:
                has_dmc = True
            if ref == 0x4016 and (line.mnemonic or "").upper() == "STA":
                has_joy1_strobe = True
            if ref == 0x4016 and (line.mnemonic or "").upper() == "LDA":
                has_joy_read_loop += 1
    if has_joy1_strobe and has_joy_read_loop >= 4:
        return ("read_controllers", "strobe + 8x LDA $4016 / LSR / ROL")
    if has_oam_dma and len(apu_targets) <= 2:
        return ("oam_dma_transfer", "STA OAMDMA + setup OAMADDR")
    if has_dmc and not (has_pulse or has_triangle or has_noise):
        return ("play_dmc", "écrit uniquement les registres DMC")
    if (has_pulse or has_triangle or has_noise) and has_dmc:
        return ("play_sound", "mix APU multi-canaux")
    if has_pulse and not has_triangle and not has_noise and not has_dmc:
        return ("play_pulse", "écrit registres pulse APU")
    if has_triangle and not has_pulse and not has_noise:
        return ("play_triangle", "écrit registres triangle APU")
    if has_noise and not has_pulse and not has_triangle:
        return ("play_noise", "écrit registres noise APU")
    if ppu_targets and not apu_targets:
        if 0x2007 in ppu_targets and 0x2006 in ppu_targets:
            if any(line.operands and "PPUDATA" in (line.operands or "") and ",X" in (line.operands or "")
                   for line in body):
                return ("ppu_blit", "PPUADDR setup + STA PPUDATA en boucle")
            return ("ppu_load", "PPUADDR setup + STA PPUDATA")
        if ppu_targets <= {0x2000, 0x2001}:
            return ("ppu_setup", "écrit PPUCTRL/PPUMASK")
        if 0x2005 in ppu_targets:
            return ("update_scroll", "écrit PPUSCROLL")
    return (None, None)


def detect_subroutine_kinds(disasm: Disasm) -> Dict[int, Subroutine]:
    out: Dict[int, Subroutine] = {}
    for sub in find_subroutines(disasm):
        kind, why = _classify_subroutine(sub.body)
        if kind:
            sub.kind = kind
            sub.why = why
            sub.name = kind
            out[sub.entry] = sub
    return out


def find_nmi_address(image: bytes) -> Optional[int]:
    if len(image) < 0x10000:
        return None
    return image[0xFFFA] | (image[0xFFFB] << 8)


def find_reset_address(image: bytes) -> Optional[int]:
    if len(image) < 0x10000:
        return None
    return image[0xFFFC] | (image[0xFFFD] << 8)


def detect_all(
    disasm: Disasm, image: Optional[bytes] = None
) -> List[Detection]:
    nmi = find_nmi_address(image) if image else None
    detections: List[Detection] = []
    detections.extend(detect_frame_counter(disasm, nmi))
    detections.extend(detect_controller_reads(disasm))
    detections.extend(detect_oam_indices(disasm))
    detections.extend(detect_pointer_pairs(disasm))
    detections.extend(detect_oamdma_buffer(disasm))
    detections.extend(detect_ppu_shadows(disasm))
    detections.extend(detect_loop_counters(disasm))
    detections.extend(detect_subroutine_args(disasm))
    return detections


def merge_detections(
    detections: List[Detection],
) -> Tuple[Dict[int, str], Dict[int, List[Detection]]]:
    by_addr: Dict[int, List[Detection]] = {}
    for d in detections:
        by_addr.setdefault(d.addr, []).append(d)
    names: Dict[int, str] = {}
    for a, lst in by_addr.items():
        best = max(lst, key=lambda x: x.confidence)
        names[a] = best.name
    return names, by_addr
