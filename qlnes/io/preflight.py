"""Pre-flight validation runner (FR36)."""

from __future__ import annotations

from collections.abc import Callable

from .errors import QlnesError


class Preflight:
    def __init__(self) -> None:
        self._checks: list[tuple[str, Callable[[], None]]] = []

    def add(self, name: str, check: Callable[[], None]) -> None:
        self._checks.append((name, check))

    def run(self) -> None:
        for name, check in self._checks:
            try:
                check()
            except QlnesError:
                raise
            except Exception as e:
                raise QlnesError(
                    "internal_error",
                    f"preflight {name!r} crashed: {e}",
                    extra={"check": name},
                ) from e
