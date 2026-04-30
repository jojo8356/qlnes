"""Recompilation et vérification round-trip d'une ROM via py65.

py65.assembler.Assembler fournit l'encodeur 6502, on lui fournit chaque
ligne du désassemblage QL6502 :

- les `DB`/`.byte` sont parsés directement en bytes
- les instructions sont normalisées (L_xxxx → $xxxx, 0x → $) puis
  passées à py65 qui retourne les opcodes
- les bytes sont placés à `line.addr` dans une image 64KB

Pour la vérification, on extrait la PRG-ROM de l'image (intervalles
$8000-$FFFF), on remet le header iNES + CHR, et on diff au binaire original.

Comparaison rapide : on utilise d'abord `bytes == bytes` (memcmp C-niveau,
~5 GB/s sur ROM normale) et on calcule un sha256 pour le fingerprint. La
boucle Python octet-par-octet n'est utilisée que quand on doit pinpointer
le premier byte qui diffère.
"""

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from py65.assembler import Assembler
    from py65.devices.mpu6502 import MPU
    HAS_PY65 = True
except ImportError:
    HAS_PY65 = False

from .asm_text import find_ascii_runs, parse_db_line
from .ines import HEADER_SIZE, parse_header, strip_ines
from .parser import Disasm, Line


_LABEL_TO_DOLLAR = re.compile(r"\bL_([0-9A-Fa-f]{4})\b")
_HEX_0X = re.compile(r"\b0x([0-9A-Fa-f]+)\b")
_DATA_LINE_RE = re.compile(
    r"^\s*L_[0-9A-Fa-f]+:?\s+(?:\.byte|DB|DW)\s+(?P<rest>.+)$",
    re.IGNORECASE,
)


def _strip_trailing_comment(s: str) -> str:
    in_string = False
    escape = False
    for i, ch in enumerate(s):
        if escape:
            escape = False
            continue
        if in_string and ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if ch == ";" and not in_string:
            return s[:i].rstrip()
    return s.rstrip()


@dataclass
class RomDiff:
    equal: bool
    sizes_match: bool
    original_size: int
    recompiled_size: int
    diff_bytes: int
    first_diff_offset: Optional[int] = None
    original_sha256: str = ""
    recompiled_sha256: str = ""
    notes: List[str] = field(default_factory=list)

    @property
    def hashes_match(self) -> bool:
        return bool(self.original_sha256) and self.original_sha256 == self.recompiled_sha256

    def summary(self) -> str:
        if self.equal:
            return f"identique ({self.original_size} octets, sha256 {self.original_sha256[:12]}…)"
        if not self.sizes_match:
            return (
                f"taille différente : {self.original_size} vs "
                f"{self.recompiled_size}"
            )
        return (
            f"{self.diff_bytes} octets diffèrent "
            f"(premier diff @ 0x{self.first_diff_offset:04X})"
        )


def _normalize_operand(operand: str) -> str:
    if not operand:
        return ""
    s = _LABEL_TO_DOLLAR.sub(r"$\1", operand)
    s = _HEX_0X.sub(r"$\1", s)
    return s


def _parse_byte_tokens(body: str) -> List[int]:
    out: List[int] = []
    cursor = 0
    while cursor < len(body):
        ch = body[cursor]
        if ch.isspace() or ch == ",":
            cursor += 1
            continue
        if ch == '"':
            end = body.find('"', cursor + 1)
            if end < 0:
                raise ValueError(f"unterminated string in: {body!r}")
            out.extend(b for b in body[cursor + 1 : end].encode("latin-1"))
            cursor = end + 1
            continue
        m = re.match(r"(?:0x|\$)([0-9A-Fa-f]+)", body[cursor:])
        if m:
            out.append(int(m.group(1), 16))
            cursor += m.end()
            continue
        m = re.match(r"(\d+)", body[cursor:])
        if m:
            out.append(int(m.group(1)))
            cursor += m.end()
            continue
        raise ValueError(f"can't parse token at {body[cursor:cursor + 20]!r}")
    return out


def _extract_data_bytes(line: str) -> Optional[List[int]]:
    m = _DATA_LINE_RE.match(line)
    if not m:
        return None
    body = _strip_trailing_comment(m.group("rest"))
    return _parse_byte_tokens(body)


class Recompiler:
    def __init__(self, names_to_addr: Optional[Dict[str, int]] = None):
        if not HAS_PY65:
            raise ImportError(
                "py65 non installé : pip install py65 "
                "(ou utiliser le venv .venv du projet)."
            )
        self.mpu = MPU()
        self.assembler = Assembler(self.mpu)
        self.errors: List[str] = []
        self.names_to_addr = dict(names_to_addr or {})

    def _resolve_names(self, operand: str) -> str:
        if not self.names_to_addr or not operand:
            return operand

        def repl(match: re.Match) -> str:
            name = match.group(0)
            addr = self.names_to_addr.get(name)
            if addr is None:
                return name
            return f"${addr:X}"

        return re.sub(r"\b[A-Za-z_][A-Za-z0-9_]*\b", repl, operand)

    def encode_instruction(self, line: Line) -> bytes:
        mn = (line.mnemonic or "").upper()
        operand = self._resolve_names(line.operands or "")
        operand = _normalize_operand(operand)
        statement = mn if not operand else f"{mn} {operand}"
        result = self.assembler.assemble(statement, pc=line.addr)
        return bytes(result)

    def encode_line(self, line: Line) -> Optional[bytes]:
        if line.addr < 0:
            return None
        data_bytes = _extract_data_bytes(line.raw)
        if data_bytes is not None:
            return bytes(data_bytes)
        if not line.mnemonic:
            return None
        try:
            return self.encode_instruction(line)
        except Exception as e:
            self.errors.append(
                f"erreur à 0x{line.addr:04X} ({line.raw!r}) : {e}"
            )
            return None

    def assemble(self, asm_text: str, image_size: int = 0x10000) -> bytes:
        disasm = Disasm(asm_text)
        image = bytearray(image_size)
        for line in disasm.lines:
            data = self.encode_line(line)
            if data is None:
                continue
            end = line.addr + len(data)
            if end > image_size:
                continue
            image[line.addr:end] = data
        return bytes(image)


def recompile_asm(
    asm_text: str,
    image_size: int = 0x10000,
    names_to_addr: Optional[Dict[str, int]] = None,
) -> Tuple[bytes, List[str]]:
    rec = Recompiler(names_to_addr=names_to_addr)
    image = rec.assemble(asm_text, image_size=image_size)
    return image, rec.errors


def assemble_to_rom(
    asm_text: str,
    original_rom: bytes,
    names_to_addr: Optional[Dict[str, int]] = None,
) -> Tuple[bytes, List[str]]:
    h = parse_header(original_rom)
    if h is None:
        image, errors = recompile_asm(asm_text, names_to_addr=names_to_addr)
        return image, errors

    image, errors = recompile_asm(
        asm_text, image_size=0x10000, names_to_addr=names_to_addr
    )
    prg_size = h.prg_size
    chr_offset = HEADER_SIZE + (512 if h.has_trainer else 0) + prg_size
    chr_data = original_rom[chr_offset : chr_offset + h.chr_size] if h.chr_size else b""

    if prg_size == 0x8000:
        new_prg = image[0x8000:0x10000]
    elif prg_size == 0x4000:
        new_prg = image[0x8000:0xC000]
    else:
        new_prg = image[0x10000 - prg_size : 0x10000]

    out = bytearray(original_rom[:HEADER_SIZE])
    if h.has_trainer:
        out += original_rom[HEADER_SIZE : HEADER_SIZE + 512]
    out += new_prg
    out += chr_data
    return bytes(out), errors


def _first_diff_offset(a: bytes, b: bytes) -> Tuple[Optional[int], int]:
    n = min(len(a), len(b))
    chunk = 4096
    for base in range(0, n, chunk):
        end = min(base + chunk, n)
        if a[base:end] == b[base:end]:
            continue
        for i in range(base, end):
            if a[i] != b[i]:
                first = i
                count = sum(1 for j in range(first, n) if a[j] != b[j])
                count += abs(len(a) - len(b))
                return first, count
    if len(a) != len(b):
        return n, abs(len(a) - len(b))
    return None, 0


def compare_roms(rom1: bytes, rom2: bytes) -> RomDiff:
    sizes_match = len(rom1) == len(rom2)
    h1 = hashlib.sha256(rom1).hexdigest()
    h2 = hashlib.sha256(rom2).hexdigest()

    if sizes_match and h1 == h2:
        return RomDiff(
            equal=True,
            sizes_match=True,
            original_size=len(rom1),
            recompiled_size=len(rom2),
            diff_bytes=0,
            original_sha256=h1,
            recompiled_sha256=h2,
        )

    first_diff, diff_count = _first_diff_offset(rom1, rom2)
    return RomDiff(
        equal=False,
        sizes_match=sizes_match,
        original_size=len(rom1),
        recompiled_size=len(rom2),
        diff_bytes=diff_count,
        first_diff_offset=first_diff,
        original_sha256=h1,
        recompiled_sha256=h2,
    )


def hash_rom(data: bytes, algorithm: str = "sha256") -> str:
    return hashlib.new(algorithm, data).hexdigest()


def fast_equal(rom1: bytes, rom2: bytes) -> bool:
    if len(rom1) != len(rom2):
        return False
    return rom1 == rom2


def verify_round_trip(
    asm_text: str,
    original_rom_path,
    output_recompiled: Optional[Path] = None,
    names_to_addr: Optional[Dict[str, int]] = None,
) -> Tuple[RomDiff, List[str]]:
    original_rom = Path(original_rom_path).read_bytes()
    recompiled, errors = assemble_to_rom(
        asm_text, original_rom, names_to_addr=names_to_addr
    )
    if output_recompiled is not None:
        Path(output_recompiled).write_bytes(recompiled)
    diff = compare_roms(original_rom, recompiled)
    if errors:
        diff.notes.append(f"{len(errors)} erreurs d'assemblage non-bloquantes")
    return diff, errors
