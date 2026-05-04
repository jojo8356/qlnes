"""qlnes logging infrastructure (stdlib `logging` based).

The canonical user-facing output format is preserved byte-for-byte
from the pre-logging implementation (`qlnes: error: ...`,
`qlnes: warning: ...`, plain info lines without prefix). Errors and
warnings get ANSI colors when `use_color=True`. The exit-code error
path and structured JSON payloads (FR33/FR34) live in
`qlnes/io/errors.py::emit` — this module just provides the levelled
streaming layer underneath.

Usage from CLI commands:

    from qlnes.io.log import setup_logging
    setup_logging(level="INFO", use_color=True)

    import logging
    logger = logging.getLogger(__name__)
    logger.info("rendering 600 frames…")
    logger.warning("lameenc 1.9.0 outside verified range")
    logger.error("ROM not found")

`setup_logging` is idempotent (safe to call multiple times in tests).
The qlnes logger hierarchy is rooted at `"qlnes"`; everything under
that name (e.g. `"qlnes.audio.renderer"`) inherits the configured
handler.
"""
from __future__ import annotations

import logging
import sys
from typing import Literal

from ucolor import UColor
from ucolor.color_mode import ColorMode

LOG_LEVELS: tuple[str, ...] = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

# Per-level styling via ucolor. Plain INFO is uncolored (it's the dominant
# output and noise reduction wins). The mapping below produces the
# canonical CLI palette: bold red for errors, yellow for warnings,
# dim grey for debug.
_LEVEL_STYLES: dict[int, "object"] = {
    logging.WARNING: UColor.css("yellow"),
    logging.ERROR: UColor.css("red").bold(),
    logging.CRITICAL: UColor.css("red").bold(),
    logging.DEBUG: UColor.css("grey").dim(),
}


class _QlnesFormatter(logging.Formatter):
    """Renders messages as `qlnes: <level>: <message>` for non-INFO,
    bare `<message>` for INFO. Color decoration applied via ucolor when
    `use_color=True`; ucolor's auto-detection is bypassed and we force
    the mode explicitly so the formatter is deterministic regardless of
    isatty()."""

    def __init__(self, *, use_color: bool) -> None:
        super().__init__()
        self._use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        msg = record.getMessage()
        if record.levelno == logging.INFO:
            # User-visible info lines (success ticks, progress) print
            # without the "qlnes: info:" decoration — matches the
            # pre-logging typer.echo output.
            return msg
        level_name = record.levelname.lower()
        prefix = f"qlnes: {level_name}: "
        if self._use_color:
            style = _LEVEL_STYLES.get(record.levelno)
            if style is not None:
                prefix = style.wrap(prefix)
        return prefix + msg


def setup_logging(
    *,
    level: LogLevel = "INFO",
    use_color: bool = False,
    stream=None,
) -> None:
    """Configure the `qlnes` logger hierarchy.

    Idempotent: removes any handlers we previously installed before
    re-installing. Tests that override the level can call this
    repeatedly without leaking handlers.

    Args:
      level: minimum level to emit. CLI flag `--log-level` maps here.
        `--quiet` clamps to `WARNING`; `--debug` (D.3) sets `DEBUG`.
      use_color: ANSI escapes on the level prefix. CLI's `--color
        {auto,always,never}` resolves this.
      stream: defaults to `sys.stderr` (where qlnes always writes).
        Test fixtures inject a StringIO when they need to capture.
    """
    if level not in LOG_LEVELS:
        raise ValueError(
            f"unknown log level {level!r}; valid: {', '.join(LOG_LEVELS)}"
        )

    # Lock ucolor's mode to match our `use_color` decision so the
    # formatter is deterministic regardless of TTY detection state.
    UColor.force_mode(ColorMode.TRUE_COLOR if use_color else ColorMode.NONE)

    logger = logging.getLogger("qlnes")
    # Drop any previous qlnes-installed handler — keeps idempotency.
    for h in list(logger.handlers):
        if getattr(h, "_qlnes_managed", False):
            logger.removeHandler(h)

    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(_QlnesFormatter(use_color=use_color))
    handler._qlnes_managed = True  # type: ignore[attr-defined]
    logger.addHandler(handler)
    logger.setLevel(level)
    # Don't bubble up to the root logger; qlnes runs as a CLI app and
    # we don't want consumers' configurations to double-print.
    logger.propagate = False


def get_logger(name: str = "qlnes") -> logging.Logger:
    """Convenience for modules that want `logger = get_logger(__name__)`."""
    return logging.getLogger(name)
