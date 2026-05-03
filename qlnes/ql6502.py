import os
import subprocess
import tempfile
from pathlib import Path

DEFAULT_BIN = Path(__file__).resolve().parent.parent / "bin" / "ql6502"


class QL6502Error(RuntimeError):
    pass


class QL6502:
    def __init__(
        self,
        binary: Path | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.binary = Path(binary) if binary else DEFAULT_BIN
        if not self.binary.exists():
            raise QL6502Error(f"ql6502 binary not found at {self.binary}")
        self.timeout = timeout
        self._image: bytes | None = None
        self._image_name: str | None = None
        self._blanks: list[tuple[int, int]] = []
        self._jump_tables: list[tuple[int, int]] = []
        self._sub_entries: list[int] = []

    def load_image(self, image: bytes, name: str = "image.bin") -> "QL6502":
        if len(image) > 0x10000:
            raise QL6502Error(f"image must be ≤ 64 KB, got {len(image)}")
        self._image = bytes(image)
        self._image_name = name
        return self

    def load_file(self, path: os.PathLike[str]) -> "QL6502":
        data = Path(path).read_bytes()
        return self.load_image(data, Path(path).name)

    def mark_blank(self, start: int, end: int) -> "QL6502":
        self._blanks.append((start, end))
        return self

    def add_jump_table(self, start: int, end: int) -> "QL6502":
        self._jump_tables.append((start, end))
        return self

    def add_sub_entry(self, addr: int) -> "QL6502":
        self._sub_entries.append(addr)
        return self

    def generate_asm(self, start: int = 0, end: int = 0xFFFF) -> str:
        if self._image is None or self._image_name is None:
            raise QL6502Error("load an image first")
        with tempfile.TemporaryDirectory(prefix="qlnes_") as td:
            tdp = Path(td)
            bin_path = tdp / self._image_name
            bin_path.write_bytes(self._image)
            asm_path = tdp / "out.asm"
            script = self._build_script(self._image_name, asm_path, start, end)
            self._run(script, cwd=tdp)
            if not asm_path.exists():
                raise QL6502Error("ql6502 did not produce output asm")
            return asm_path.read_text(encoding="latin-1")

    def _build_script(self, image_name: str, asm_path: Path, start: int, end: int) -> str:
        lines = [f"l {image_name}"]
        for s, e in self._blanks:
            lines.append(f"b 0x{s:04X} 0x{e:04X}")
        for s, e in self._jump_tables:
            lines.append(f"j 0x{s:04X} 0x{e:04X}")
        for a in self._sub_entries:
            lines.append(f"c 0x{a:04X}")
        lines.append("x")
        lines.append(f"g {asm_path} 0x{start:04X} 0x{end:04X}")
        lines.append("q")
        return "\n".join(lines) + "\n"

    def _run(self, script: str, cwd: Path) -> str:
        proc = subprocess.run(
            [str(self.binary), "-X"],
            input=script,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=self.timeout,
        )
        if proc.returncode != 0:
            raise QL6502Error(f"ql6502 exited with {proc.returncode}\nSTDERR:\n{proc.stderr}")
        return proc.stdout

    @classmethod
    def disassemble(
        cls,
        image: bytes,
        blanks: list[tuple[int, int]] | None = None,
        jump_tables: list[tuple[int, int]] | None = None,
        sub_entries: list[int] | None = None,
        binary: Path | None = None,
    ) -> str:
        q = cls(binary=binary).load_image(image)
        for s, e in blanks or []:
            q.mark_blank(s, e)
        for s, e in jump_tables or []:
            q.add_jump_table(s, e)
        for a in sub_entries or []:
            q.add_sub_entry(a)
        return q.generate_asm()
