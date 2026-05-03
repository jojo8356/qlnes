"""Sysexits-aligned error emitter with structured JSON stderr (FR33, FR34)."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import Any, NoReturn

from .._version import __version__ as _VERSION

EXIT_CODES: dict[str, int] = {
    "usage_error": 64,
    "bad_format_arg": 64,
    "bad_rom": 65,
    "missing_input": 66,
    "internal_error": 70,
    "cant_create": 73,
    "io_error": 74,
    "unsupported_mapper": 100,
    "equivalence_failed": 101,
    "missing_reference": 102,
    "interrupted": 130,
}

DEFAULT_HINTS: dict[str, str | None] = {
    "usage_error": "Run the command with --help to see valid usage.",
    "bad_format_arg": "Run the command with --help to see valid values.",
    "bad_rom": "Verify the file is a .nes ROM, not .nsf or .zip.",
    "missing_input": "Check the path; cwd is in the JSON `cwd` field.",
    "internal_error": "Re-run with --debug and open an issue.",
    "cant_create": "Add --force, or pick a different --output path.",
    "io_error": "Check disk space and permissions.",
    "unsupported_mapper": "Run `qlnes coverage` for the support matrix.",
    "equivalence_failed": "Re-run with --debug to dump the divergence frame.",
    "missing_reference": "Generate the reference: see corpus/README.md.",
    "interrupted": None,
}


@dataclass
class QlnesError(Exception):
    cls: str
    reason: str
    hint: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.cls not in EXIT_CODES:
            raise ValueError(f"unknown error class: {self.cls!r}")
        super().__init__(self.reason)

    @property
    def code(self) -> int:
        return EXIT_CODES[self.cls]


def _ansi(code: str, s: str, on: bool) -> str:
    return f"\033[{code}m{s}\033[0m" if on else s


def _payload(cls: str, code: int | None, extra: dict[str, Any]) -> str:
    base: dict[str, Any] = {"class": cls, "qlnes_version": _VERSION}
    if code is not None:
        base["code"] = code
    base.update(extra)
    return json.dumps(base, sort_keys=True, separators=(",", ":"))


def emit(err: QlnesError, *, no_hints: bool = False, color: bool = False) -> NoReturn:
    sys.stderr.write(_ansi("31;1", "qlnes: error: ", color) + err.reason + "\n")
    hint = err.hint if err.hint is not None else DEFAULT_HINTS.get(err.cls)
    if hint and not no_hints:
        sys.stderr.write("hint: " + hint + "\n")
    sys.stderr.write(_payload(err.cls, err.code, err.extra) + "\n")
    sys.exit(err.code)


def warn(
    cls: str,
    reason: str,
    *,
    hint: str | None = None,
    extra: dict[str, Any] | None = None,
    no_hints: bool = False,
    color: bool = False,
) -> None:
    sys.stderr.write(_ansi("33", "qlnes: warning: ", color) + reason + "\n")
    if hint and not no_hints:
        sys.stderr.write("hint: " + hint + "\n")
    sys.stderr.write(_payload(cls, None, extra or {}) + "\n")
