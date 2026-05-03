"""Devine le langage / toolchain qui a produit la ROM.

Sans symboles, c'est probabiliste. On combine plusieurs métriques :

- distribution de la taille des sous-routines (cc65 produit beaucoup de
  petites trampolines, l'asm écrit à la main a moins de routines mais plus
  longues)
- usage de la pseudo-pile ZP en mode (zp,X)/(zp),Y avec X petit (signature
  cc65/cc65-like)
- présence de prologues TSX/TXS répétés (frames de stack C)
- mapper et taille CHR (CHR-RAM ⇒ probable homebrew)
- présence de famitone/famitracker (8-9 octets de table caractéristiques)

Renvoie une liste d'hypothèses ordonnées, chacune avec sa confiance et
les indices qui la motivent.
"""

from collections import Counter
from dataclasses import dataclass

from .dataflow import find_subroutines
from .ines import INesHeader
from .parser import Disasm


@dataclass
class LangHypothesis:
    label: str
    confidence: float
    evidence: str

    def to_row(self) -> str:
        return f"| **{self.label}** | {self.confidence:.2f} | {self.evidence} |"


def _short_sub_count(disasm: Disasm, max_size: int = 8) -> int:
    return sum(1 for s in find_subroutines(disasm) if s.size <= max_size)


def _zp_indexed_uses(disasm: Disasm) -> int:
    n = 0
    for line in disasm.code_lines():
        ops = line.operands or ""
        if not ops:
            continue
        if not (
            ops.endswith(",X") or ops.endswith(",Y") or ops.endswith(",x") or ops.endswith(",y")
        ):
            continue
        for ref in line.refs:
            if 0 <= ref <= 0x1F:
                n += 1
                break
    return n


def _stack_frame_count(disasm: Disasm) -> int:
    code = disasm.code_lines()
    n = 0
    for i, line in enumerate(code):
        if (line.mnemonic or "").upper() != "TSX":
            continue
        for j in range(i + 1, min(len(code), i + 6)):
            ln = code[j]
            up = (ln.mnemonic or "").upper()
            if up in ("LDA", "STA") and (ln.operands or "").startswith("0x01"):
                n += 1
                break
    return n


def _instruction_histogram(disasm: Disasm) -> Counter[str]:
    return Counter((ln.mnemonic or "").upper() for ln in disasm.code_lines() if ln.mnemonic)


def _has_oamdma_idiom(disasm: Disasm) -> bool:
    code = disasm.code_lines()
    for i, line in enumerate(code):
        if (line.mnemonic or "").upper() != "STA":
            continue
        if 0x4014 not in line.refs:
            continue
        for j in range(max(0, i - 3), i):
            prev = code[j]
            if (prev.mnemonic or "").upper() == "LDA" and (prev.operands or "").startswith("#"):
                return True
    return False


def _branch_density(hist: Counter[str]) -> float:
    branches = sum(hist.get(m, 0) for m in ("BCC", "BCS", "BEQ", "BNE", "BMI", "BPL", "BVC", "BVS"))
    total = sum(hist.values()) or 1
    return branches / total


def detect_language(
    disasm: Disasm,
    header: INesHeader | None = None,
) -> list[LangHypothesis]:
    if not disasm.code_lines():
        return [LangHypothesis("indéterminé", 0.0, "pas de code identifié")]

    short = _short_sub_count(disasm)
    zp_idx = _zp_indexed_uses(disasm)
    frames = _stack_frame_count(disasm)
    hist = _instruction_histogram(disasm)
    oamdma = _has_oamdma_idiom(disasm)
    branch_pct = _branch_density(hist)
    n_subs = len(find_subroutines(disasm))
    n_lda = hist.get("LDA", 0)
    hist.get("JSR", 0)
    chr_ram = header is not None and header.chr_banks == 0

    hypotheses: list[LangHypothesis] = []

    if short >= 20 and zp_idx >= 30 and frames >= 1:
        hypotheses.append(
            LangHypothesis(
                "cc65 (compilateur C)",
                0.75,
                f"{short} routines courtes ≤8 lignes, {zp_idx} accès `0n,X` ZP, {frames} frames TSX/$0100",
            )
        )

    if zp_idx <= 5 and n_subs >= 5 and frames == 0:
        hypotheses.append(
            LangHypothesis(
                "ASM écrit à la main",
                0.7,
                f"peu d'accès indexés ZP ({zp_idx}), pas de frame stack, {n_subs} routines",
            )
        )

    if oamdma and n_subs >= 3 and short < 10 and not chr_ram:
        hypotheses.append(
            LangHypothesis(
                "ASM cartouche commerciale (NESASM/ca65 hand-written)",
                0.65,
                "OAM DMA classique + structure routines moyennes + CHR-ROM",
            )
        )

    if chr_ram and n_subs >= 3:
        hypotheses.append(
            LangHypothesis(
                "Homebrew moderne (cc65 ou ca65 + CHR-RAM)",
                0.6,
                "CHR-RAM (typique homebrew post-2005)",
            )
        )

    if branch_pct < 0.05 and n_lda > 100:
        hypotheses.append(
            LangHypothesis(
                "ROM de test / synthétique",
                0.55,
                f"{branch_pct:.1%} de branchements seulement (linéaire), {n_lda} LDA",
            )
        )

    if not hypotheses:
        hypotheses.append(
            LangHypothesis(
                "indéterminé",
                0.4,
                f"signatures mixtes (subs={n_subs}, zp_idx={zp_idx}, branches={branch_pct:.1%})",
            )
        )

    hypotheses.sort(key=lambda h: -h.confidence)
    return hypotheses
