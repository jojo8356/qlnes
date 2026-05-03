"""DMC channel — STUB for MVP per architecture ADR-18.

The channel records register writes ($4010-$4013) for trace fidelity but never
produces output. Bit 4 of $4015 (DMC active) reads as 0. Full DMC implementation
is Growth-tier work, not part of A.1.
"""

from __future__ import annotations


class DmcChannelStub:
    def __init__(self) -> None:
        self.last_write: dict[int, int] = {}
        self.enabled = False

    def register_write(self, reg_index: int, value: int) -> None:
        self.last_write[reg_index] = value & 0xFF

    def set_enable(self, enabled: bool) -> None:
        self.enabled = enabled

    def output(self) -> int:
        return 0

    def is_active(self) -> bool:
        return False
