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

import ast
import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

try:
    from py65.assembler import Assembler
    from py65.devices.mpu6502 import MPU

    HAS_PY65 = True
except ImportError:
    HAS_PY65 = False

from .ines import HEADER_SIZE, parse_header
from .parser import Disasm, Line

_LABEL_TO_DOLLAR = re.compile(r"\bL_([0-9A-Fa-f]{4})\b")
_HEX_0X = re.compile(r"\b0x([0-9A-Fa-f]+)\b")
_DATA_LINE_RE = re.compile(
    r"^\s*L_[0-9A-Fa-f]+:?\s+(?:\.byte|DB|DW)\s+(?P<rest>.+)$",
    re.IGNORECASE,
)
_NAMED_LABEL_RE = re.compile(r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*):(?P<rest>\s+\S.*)$")


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
    first_diff_offset: int | None = None
    original_sha256: str = ""
    recompiled_sha256: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def hashes_match(self) -> bool:
        return bool(self.original_sha256) and self.original_sha256 == self.recompiled_sha256

    def summary(self) -> str:
        if self.equal:
            return f"identique ({self.original_size} octets, sha256 {self.original_sha256[:12]}…)"
        if not self.sizes_match:
            return f"taille différente : {self.original_size} vs {self.recompiled_size}"
        return f"{self.diff_bytes} octets diffèrent (premier diff @ 0x{self.first_diff_offset:04X})"


def _normalize_operand(operand: str) -> str:
    if not operand:
        return ""
    s = _LABEL_TO_DOLLAR.sub(r"$\1", operand)
    s = _HEX_0X.sub(r"$\1", s)
    return s


def _scan_quoted(body: str, start: int) -> tuple[str, int]:
    # Délimite une string Python "..." en respectant \\ et \" comme échappements.
    # Retourne (littéral_avec_guillemets, index_après_quote_fermante).
    i = start + 1
    while i < len(body):
        if body[i] == "\\" and i + 1 < len(body):
            i += 2
            continue
        if body[i] == '"':
            return body[start : i + 1], i + 1
        i += 1
    raise ValueError(f"unterminated string in: {body!r}")


def _parse_byte_tokens(body: str) -> list[int]:
    out: list[int] = []
    cursor = 0
    while cursor < len(body):
        ch = body[cursor]
        if ch.isspace() or ch == ",":
            cursor += 1
            continue
        if ch == '"':
            literal, cursor = _scan_quoted(body, cursor)
            decoded = ast.literal_eval(literal)
            if not isinstance(decoded, str):
                raise ValueError(f"unexpected literal type in: {body!r}")
            out.extend(decoded.encode("latin-1"))
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
        raise ValueError(f"can't parse token at {body[cursor : cursor + 20]!r}")
    return out


def _extract_data_bytes(line: str) -> list[int] | None:
    m = _DATA_LINE_RE.match(line)
    if not m:
        return None
    body = _strip_trailing_comment(m.group("rest"))
    return _parse_byte_tokens(body)


class Recompiler:
    def __init__(self, names_to_addr: dict[str, int] | None = None):
        if not HAS_PY65:
            raise ImportError(
                "py65 non installé : pip install py65 (ou utiliser le venv .venv du projet)."
            )
        self.mpu = MPU()
        self.assembler = Assembler(self.mpu)
        self.errors: list[str] = []
        self.names_to_addr = dict(names_to_addr or {})

    def _resolve_names(self, operand: str) -> str:
        if not self.names_to_addr or not operand:
            return operand

        def repl(match: re.Match[str]) -> str:
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

    def encode_line(self, line: Line) -> bytes | None:
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
            self.errors.append(f"erreur à 0x{line.addr:04X} ({line.raw!r}) : {e}")
            return None

    def assemble(self, asm_text: str, image_size: int = 0x10000) -> bytes:
        if self.names_to_addr:
            asm_text = self._restore_label_addresses(asm_text)
        disasm = Disasm(asm_text)
        image = bytearray(image_size)
        for line in disasm.lines:
            data = self.encode_line(line)
            if data is None:
                continue
            end = line.addr + len(data)
            if end > image_size:
                continue
            image[line.addr : end] = data
        return bytes(image)

    def _restore_label_addresses(self, asm_text: str) -> str:
        # Le rewriter remplace `L_8EDD:` par `update_scroll:` au début des
        # lignes de subroutines. Pour réassembler à la bonne adresse il faut
        # restaurer la forme `L_XXXX:`. On ne touche que les noms qui
        # résolvent à une adresse en zone PRG ($8000-$FFFF).
        out: list[str] = []
        for raw in asm_text.splitlines():
            m = _NAMED_LABEL_RE.match(raw)
            if m:
                name = m.group("name")
                addr = self.names_to_addr.get(name)
                if addr is not None and 0x8000 <= addr <= 0xFFFF:
                    raw = f"L_{addr:04X}:{m.group('rest')}"
            out.append(raw)
        result = "\n".join(out)
        if asm_text.endswith("\n"):
            result += "\n"
        return result


def recompile_asm(
    asm_text: str,
    image_size: int = 0x10000,
    names_to_addr: dict[str, int] | None = None,
) -> tuple[bytes, list[str]]:
    rec = Recompiler(names_to_addr=names_to_addr)
    image = rec.assemble(asm_text, image_size=image_size)
    return image, rec.errors


def assemble_to_rom(
    asm_text: str,
    original_rom: bytes,
    names_to_addr: dict[str, int] | None = None,
) -> tuple[bytes, list[str]]:
    h = parse_header(original_rom)
    if h is None:
        image, errors = recompile_asm(asm_text, names_to_addr=names_to_addr)
        return image, errors

    image, errors = recompile_asm(asm_text, image_size=0x10000, names_to_addr=names_to_addr)
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


def _bank_prg_chunk(image: bytes, mapper: int, bank_idx: int, total_banks: int) -> bytes:
    # Extrait le morceau de PRG correspondant au bank `bank_idx` depuis l'image 64KB
    # désassemblée, en suivant la convention de mapping de chaque mapper.
    if mapper == 66:
        return image[0x8000:0x10000]
    if mapper in (1, 2):
        if bank_idx == total_banks - 1:
            return image[0xC000:0x10000]
        return image[0x8000:0xC000]
    if mapper in (0, 3):
        return image[0x8000:0x10000]
    raise NotImplementedError(f"chunk extraction not implemented for mapper {mapper}")


def assemble_to_rom_multibank(
    bank_asms: list[str],
    original_rom: bytes,
    bank_names: Sequence[dict[str, int] | None] | None = None,
) -> tuple[bytes, list[str]]:
    """Recompile une ROM multi-bank depuis N ASMs (un par bank PRG).

    Chaque ASM est assemblé en image 64KB avec sa **propre** name-map
    (les détecteurs dataflow peuvent attribuer le même nom à des adresses
    différentes selon le bank). On découpe ensuite le morceau pertinent
    selon le mapper, on concatène dans l'ordre des banks, puis on ré-attache
    l'header iNES + CHR-ROM originale.
    """
    h = parse_header(original_rom)
    if h is None:
        raise ValueError("multibank requires iNES header")
    if not bank_asms:
        raise ValueError("bank_asms is empty")
    if bank_names is not None and len(bank_names) != len(bank_asms):
        raise ValueError("bank_names length must match bank_asms")

    n = len(bank_asms)
    chunks: list[bytes] = []
    all_errors: list[str] = []
    for idx, asm in enumerate(bank_asms):
        names = bank_names[idx] if bank_names else None
        image, errors = recompile_asm(asm, image_size=0x10000, names_to_addr=names)
        chunks.append(_bank_prg_chunk(image, h.mapper, idx, n))
        all_errors.extend(errors)
    new_prg = b"".join(chunks)
    if len(new_prg) != h.prg_size:
        raise ValueError(f"multibank PRG size mismatch: expected {h.prg_size}, got {len(new_prg)}")

    chr_offset = HEADER_SIZE + (512 if h.has_trainer else 0) + h.prg_size
    chr_data = original_rom[chr_offset : chr_offset + h.chr_size] if h.chr_size else b""
    out = bytearray(original_rom[:HEADER_SIZE])
    if h.has_trainer:
        out += original_rom[HEADER_SIZE : HEADER_SIZE + 512]
    out += new_prg
    out += chr_data
    return bytes(out), all_errors


def _first_diff_offset(a: bytes, b: bytes) -> tuple[int | None, int]:
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
    original_rom_path: Path | str,
    output_recompiled: Path | None = None,
    names_to_addr: dict[str, int] | None = None,
) -> tuple[RomDiff, list[str]]:
    original_rom = Path(original_rom_path).read_bytes()
    recompiled, errors = assemble_to_rom(asm_text, original_rom, names_to_addr=names_to_addr)
    if output_recompiled is not None:
        Path(output_recompiled).write_bytes(recompiled)
    diff = compare_roms(original_rom, recompiled)
    if errors:
        diff.notes.append(f"{len(errors)} erreurs d'assemblage non-bloquantes")
    return diff, errors
