"""qlnes logging — thin wrapper around `ulog`.

Historically `qlnes/io/log.py` shipped its own custom formatter. Since
the formatter was generally useful, it was extracted into the
[ulog](https://github.com/jojo8356/ulog-python) library (vendored under
`vendor/ulog-python/`). This module is now a 30-line wrapper that
preserves the v0.5/v0.6 `setup_logging(level, use_color, ...)` API
the rest of qlnes calls into, and threads in the v0.6-default SQL
handler so every render persists logs to a SQLite file inspectable by
`ulog-web` (see `qlnes/io/log.py::DEFAULT_LOG_DB`).
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import IO, Literal

import ulog

# Re-export ulog's level enumeration so callers don't depend on ulog
# directly — keeps the qlnes API surface stable if we ever swap
# logging libs again.
LOG_LEVELS = ulog.LOG_LEVELS
LogLevel = ulog.LogLevel


def _default_log_db_path() -> Path:
    """Where qlnes persists logs by default. v0.6 ships SQLite under
    `~/.cache/qlnes/last-run.sqlite` (matches the PRD §3.1.3 "Erwan
    persona" workflow: user reports a bug, we open ulog-web on this
    file to triage).
    """
    cache_dir = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return cache_dir / "qlnes" / "last-run.sqlite"


def setup_logging(
    *,
    level: str = "INFO",
    use_color: bool = False,
    stream: IO[str] | None = None,
    log_db: str | Path | None = None,
    enable_db: bool = True,
) -> None:
    """Configure the qlnes logger via ulog.

    Args:
      level: minimum log level. Standard `LOG_LEVELS`.
      use_color: ANSI escapes on the level prefix. CLI's `--color
        {auto,always,never}` resolves this.
      stream: defaults to `sys.stderr`.
      log_db: path to the SQLite file persisting log records. None
        falls back to `~/.cache/qlnes/last-run.sqlite`. Inspect with
        `ulog-web <path>` (see `qlnes/io/log.py` docstring).
      enable_db: when False, only the stream handler is installed —
        pipeline-mode users on read-only filesystems can opt out.
    """
    color = "always" if use_color else "never"
    handlers: list[str] = ["stream"]
    if enable_db:
        handlers.append("sql")

    db_path = Path(log_db) if log_db is not None else _default_log_db_path()
    if enable_db:
        # Make sure the parent dir exists before SQLAlchemy tries to
        # open the DB; `Path.mkdir(exist_ok=True)` is idempotent.
        db_path.parent.mkdir(parents=True, exist_ok=True)

    ulog.setup(
        level=level,
        format="qlnes",
        color=color,
        stream=stream if stream is not None else sys.stderr,
        handlers=handlers,
        sql_url=f"sqlite:///{db_path}",
        sql_batch_size=50,  # smaller batch than default to flush errors faster
        prefix="qlnes",
    )


def get_logger(name: str = "qlnes") -> logging.Logger:
    """Convenience for modules that want `logger = get_logger(__name__)`."""
    return ulog.get_logger(name)


def default_log_db_path() -> Path:
    """Public access to the default log DB path — used by `qlnes audio`
    to print the inspection hint at the end of a run."""
    return _default_log_db_path()
