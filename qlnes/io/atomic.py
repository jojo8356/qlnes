"""Atomic file writes (FR35). Crash-safe across the whole product."""

from __future__ import annotations

import contextlib
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO


@contextmanager
def atomic_writer(target: Path | str, mode: str = "wb") -> Iterator[IO[bytes]]:
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=str(target.parent),
    )
    tmp_path = Path(tmp)
    try:
        with os.fdopen(fd, mode) as f:
            yield f
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, target)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            tmp_path.unlink()
        raise


def atomic_write_bytes(target: Path | str, data: bytes) -> None:
    with atomic_writer(target, "wb") as f:
        f.write(data)


def atomic_write_text(target: Path | str, text: str, encoding: str = "utf-8") -> None:
    with atomic_writer(target, "wb") as f:
        f.write(text.encode(encoding))
