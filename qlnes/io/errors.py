"""Sysexits-aligned error emitter with structured JSON stderr (FR33, FR34).

The human-readable line ("qlnes: error: ...", "qlnes: warning: ...")
goes through the `qlnes` stdlib `logging` hierarchy (configured by
`qlnes.io.log.setup_logging`); the structured JSON payload is written
directly to stderr to keep the contract byte-stable for downstream
consumers (Lin's pipeline-mode parsing, B.1's bilan generator). The
hint line uses logging too so `--no-hints` and color follow the same
rules as the message.

When `setup_logging` hasn't been called (tests that use the in-process
renderer directly without going through the CLI), the default logger
config still emits at WARNING level via a basicConfig handler — but
without the qlnes prefix. Callers that depend on the formatted prefix
must install `setup_logging` first.
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass, field
from typing import Any, NoReturn

from .._version import __version__ as _VERSION

_LOG = logging.getLogger("qlnes")


def _emit_line(level: int, prefix: str, msg: str, *, color: bool = False) -> None:
    """Send a message to the qlnes logger if it's configured; otherwise
    write directly to stderr in the canonical "qlnes: <level>: <msg>"
    format. This keeps the human-readable output stable for tests and
    library users that don't go through `qlnes.io.log.setup_logging`,
    while letting CLI invocations pick up `--log-level` filtering and
    color formatting from the configured logger.
    """
    if any(getattr(h, "_qlnes_managed", False) for h in _LOG.handlers):
        _LOG.log(level, msg)
        return
    # Fallback: direct stderr write with the canonical prefix.
    line = prefix + msg
    if color:
        ansi = "\033[31;1m" if level >= logging.ERROR else "\033[33m"
        line = ansi + prefix + "\033[0m" + msg
    sys.stderr.write(line + "\n")

EXIT_CODES: dict[str, int] = {
    "usage_error": 64,
    "bad_format_arg": 64,
    "bad_rom": 65,
    "missing_input": 66,
    "internal_error": 70,
    "cant_create": 73,
    "io_error": 74,
    "unsupported_mapper": 100,
    "in_process_unavailable": 100,  # F.5 — engine has no in-process support
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
    "in_process_unavailable":
        "Try `--engine-mode auto` to fall back to oracle, or `qlnes coverage` for the support matrix.",
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


def _payload(cls: str, code: int | None, extra: dict[str, Any]) -> str:
    base: dict[str, Any] = {"class": cls, "qlnes_version": _VERSION}
    if code is not None:
        base["code"] = code
    base.update(extra)
    return json.dumps(base, sort_keys=True, separators=(",", ":"))


def emit(err: QlnesError, *, no_hints: bool = False, color: bool = False) -> NoReturn:
    """Emit an error and exit. `color` controls the fallback-path output
    when no qlnes logger handler is installed; CLI invocations go
    through the logger's own formatter (`qlnes.io.log.setup_logging`)
    and this flag is ignored.
    """
    _emit_line(logging.ERROR, "qlnes: error: ", err.reason, color=color)
    hint = err.hint if err.hint is not None else DEFAULT_HINTS.get(err.cls)
    if hint and not no_hints:
        # Hint is a continuation of the error line — bypass the logger
        # so it doesn't get the "qlnes: error: " prefix.
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
    _emit_line(logging.WARNING, "qlnes: warning: ", reason, color=color)
    if hint and not no_hints:
        sys.stderr.write("hint: " + hint + "\n")
    sys.stderr.write(_payload(cls, None, extra or {}) + "\n")
