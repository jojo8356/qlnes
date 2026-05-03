import re
from collections.abc import Iterator
from dataclasses import dataclass, field

_LABEL_RE = re.compile(r"L_([0-9A-Fa-f]{4})")
_ZP_OP_RE = re.compile(r"(?<![#A-Za-z_])0x([0-9A-Fa-f]{1,2})\b")
_LINE_RE = re.compile(
    r"""^
    (?P<lead>L_(?P<addr>[0-9A-Fa-f]{4}))
    (?P<is_label>:?)
    \s+
    (?P<rest>.*?)
    \s*$
    """,
    re.VERBOSE,
)


@dataclass
class Line:
    addr: int
    is_label: bool
    raw: str
    mnemonic: str | None = None
    operands: str | None = None
    comment: str | None = None
    is_data: bool = False
    refs: list[int] = field(default_factory=list)

    def addr_str(self) -> str:
        return f"${self.addr:04X}"


class Disasm:
    def __init__(self, asm_text: str) -> None:
        self.text = asm_text
        self.lines: list[Line] = []
        self._referenced: set[int] = set()
        self._parse()

    def _parse(self) -> None:
        for raw in self.text.splitlines():
            stripped = raw.rstrip()
            if not stripped:
                continue
            m = _LINE_RE.match(stripped)
            if not m:
                self.lines.append(Line(addr=-1, is_label=False, raw=stripped))
                continue
            addr = int(m.group("addr"), 16)
            is_label = m.group("is_label") == ":"
            rest = m.group("rest")
            line = Line(addr=addr, is_label=is_label, raw=stripped)
            self._fill_instr(line, rest)
            comment_pos = rest.find(";")
            instr_part = rest if comment_pos < 0 else rest[:comment_pos]
            for ref in _LABEL_RE.findall(instr_part):
                refi = int(ref, 16)
                line.refs.append(refi)
                self._referenced.add(refi)
            self.lines.append(line)

    def _fill_instr(self, line: Line, rest: str) -> None:
        comment_idx = rest.find(";")
        if comment_idx >= 0:
            line.comment = rest[comment_idx + 1 :].strip()
            rest = rest[:comment_idx].rstrip()
        if not rest:
            return
        parts = rest.split(None, 1)
        line.mnemonic = parts[0]
        if len(parts) > 1:
            line.operands = parts[1].strip()
        if line.mnemonic.upper() in {"DB", "DW"}:
            line.is_data = True
        if line.operands and not line.is_data:
            for m in _ZP_OP_RE.finditer(line.operands):
                a = int(m.group(1), 16)
                line.refs.append(a)
                self._referenced.add(a)

    def __iter__(self) -> Iterator[Line]:
        return iter(self.lines)

    def __len__(self) -> int:
        return len(self.lines)

    @property
    def referenced_addrs(self) -> set[int]:
        return set(self._referenced)

    def find(self, addr: int) -> Line | None:
        for line in self.lines:
            if line.addr == addr:
                return line
        return None

    def code_lines(self) -> list[Line]:
        return [ln for ln in self.lines if ln.mnemonic and not ln.is_data]

    def data_lines(self) -> list[Line]:
        return [ln for ln in self.lines if ln.is_data]
