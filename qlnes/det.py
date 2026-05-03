"""Determinism utilities. Every output writer routes through these."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")

CANONICAL_JSON_KW: dict[str, Any] = {
    "sort_keys": True,
    "ensure_ascii": False,
    "separators": (",", ":"),
}


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, **CANONICAL_JSON_KW)


def canonical_json_bytes(obj: Any) -> bytes:
    return canonical_json(obj).encode("utf-8")


def sha256_file(path: Path, *, chunk: int = 1 << 16) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for buf in iter(lambda: f.read(chunk), b""):
            h.update(buf)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stable_iter(items: Iterable[T], *, key: Callable[[T], Any] | None = None) -> list[T]:
    return sorted(items, key=key) if key is not None else sorted(items)  # type: ignore[type-var]


def deterministic_track_filename(
    rom_stem: str,
    song_index: int,
    engine: str,
    ext: str,
) -> str:
    return f"{rom_stem}.{song_index:02d}.{engine}.{ext}"
