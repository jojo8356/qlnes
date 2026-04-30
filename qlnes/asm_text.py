"""Conversion automatique des chaînes ASCII dans les lignes DB.

QL6502 produit ses tables de données en hex pur :
    L_C700: DB  0x52,0x75,0x6E,0x20,0x61,0x6C,0x6C    ; Run all

On scanne chaque ligne DB, on détecte les sous-séquences imprimables (≥ 4
caractères ASCII consécutifs) et on les réécrit en `.byte "..."`. Les
octets non-imprimables sont préservés en hex. Le résultat reste totalement
réversible byte-pour-byte.

Exemple :
    L_C700: DB  0x52,0x75,0x6E,0x20,0x61,0x6C,0x6C,0x00,0x21
    →
    L_C700: .byte "Run all", 0x00, 0x21

Le seuil min de 4 caractères évite les faux positifs sur des paires d'opcodes
qui happen to be in printable range (e.g., 'AB' = 0x41,0x42).
"""

import re
from typing import List, Optional, Tuple


_DB_LINE = re.compile(
    r"^(?P<lead>\s*L_[0-9A-Fa-f]+:?\s+)(?P<mn>DB|DW)\s+(?P<body>[^;]+?)\s*(?P<trail>;.*)?$",
    re.IGNORECASE,
)
_HEX_TOKEN = re.compile(r"^(?:0x([0-9A-Fa-f]+)|\$([0-9A-Fa-f]+))$")
PRINTABLE_MIN = 0x20
PRINTABLE_MAX = 0x7E
DEFAULT_MIN_RUN = 4


def parse_db_line(line: str) -> Optional[Tuple[str, str, List[int], str]]:
    m = _DB_LINE.match(line)
    if not m:
        return None
    body = m.group("body")
    bytes_list: List[int] = []
    for tok in body.split(","):
        tok = tok.strip()
        hm = _HEX_TOKEN.match(tok)
        if not hm:
            return None
        v = int(hm.group(1) or hm.group(2), 16)
        if not (0 <= v <= 0xFF):
            return None
        bytes_list.append(v)
    return m.group("lead"), m.group("mn"), bytes_list, m.group("trail") or ""


def find_ascii_runs(
    bytes_list: List[int], min_len: int = DEFAULT_MIN_RUN
) -> List[Tuple[int, int]]:
    runs: List[Tuple[int, int]] = []
    start: Optional[int] = None
    for i, b in enumerate(bytes_list):
        if PRINTABLE_MIN <= b <= PRINTABLE_MAX:
            if start is None:
                start = i
        else:
            if start is not None and i - start >= min_len:
                runs.append((start, i))
            start = None
    if start is not None and len(bytes_list) - start >= min_len:
        runs.append((start, len(bytes_list)))
    return runs


def _escape_string(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _format_hex_run(bytes_list: List[int], start: int, end: int) -> str:
    return ",".join(f"0x{bytes_list[i]:02X}" for i in range(start, end))


def db_line_to_text(line: str, min_run: int = DEFAULT_MIN_RUN) -> str:
    parsed = parse_db_line(line)
    if not parsed:
        return line
    lead, _, bytes_list, trail = parsed
    runs = find_ascii_runs(bytes_list, min_len=min_run)
    if not runs:
        return line

    parts: List[str] = []
    cursor = 0
    for r_start, r_end in runs:
        if r_start > cursor:
            parts.append(_format_hex_run(bytes_list, cursor, r_start))
        s = "".join(chr(b) for b in bytes_list[r_start:r_end])
        parts.append(f'"{_escape_string(s)}"')
        cursor = r_end
    if cursor < len(bytes_list):
        parts.append(_format_hex_run(bytes_list, cursor, len(bytes_list)))

    body = ",".join(parts)
    out = f"{lead}.byte  {body}"
    if trail:
        out = f"{out}    {trail}"
    return out


def rewrite_db_strings(asm_text: str, min_run: int = DEFAULT_MIN_RUN) -> str:
    new_lines: List[str] = []
    converted = 0
    for line in asm_text.splitlines():
        new_line = db_line_to_text(line, min_run=min_run)
        if new_line != line:
            converted += 1
        new_lines.append(new_line)
    out = "\n".join(new_lines)
    if asm_text.endswith("\n"):
        out += "\n"
    return out


def count_string_lines(asm_text: str, min_run: int = DEFAULT_MIN_RUN) -> int:
    count = 0
    for line in asm_text.splitlines():
        parsed = parse_db_line(line)
        if not parsed:
            continue
        if find_ascii_runs(parsed[2], min_len=min_run):
            count += 1
    return count
