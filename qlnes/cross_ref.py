"""Cross-référence des découvertes dynamiques dans le désassemblage statique.

Quand la discovery dynamique a nommé $11=lives, on cherche les routines
qui écrivent à $11 et on les baptise update_lives. Idem pour score, level…
On peut aussi nommer la routine d'init si elle écrit la valeur initiale
de plusieurs vars de game state.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Set

from .dataflow import Subroutine, find_subroutines
from .parser import Disasm


_PRIORITY_NAMES = ("lives", "score", "level", "ammo", "menu_state")


@dataclass
class RoutineNameProposal:
    entry: int
    name: str
    why: str
    confidence: float


def _addrs_written_by(body) -> Set[int]:
    out: Set[int] = set()
    for line in body:
        up = (line.mnemonic or "").upper()
        if up not in ("STA", "STX", "STY", "INC", "DEC"):
            continue
        for ref in line.refs:
            if 0x0000 <= ref <= 0x07FF:
                out.add(ref)
    return out


def _addrs_read_by(body) -> Set[int]:
    out: Set[int] = set()
    for line in body:
        up = (line.mnemonic or "").upper()
        if up not in ("LDA", "LDX", "LDY", "CMP", "CPX", "CPY", "BIT", "ADC", "SBC", "AND", "ORA", "EOR"):
            continue
        for ref in line.refs:
            if 0x0000 <= ref <= 0x07FF:
                out.add(ref)
    return out


def cross_reference(
    disasm: Disasm,
    dynamic_names: Dict[int, str],
    existing: Optional[Dict[int, str]] = None,
) -> List[RoutineNameProposal]:
    if not dynamic_names:
        return []
    existing = existing or {}
    proposals: List[RoutineNameProposal] = []
    subs = find_subroutines(disasm)
    for sub in subs:
        if sub.entry in existing:
            continue
        writes = _addrs_written_by(sub.body)
        named_writes = {a: dynamic_names[a] for a in writes if a in dynamic_names}
        if not named_writes:
            continue
        priority_hits = [
            (a, n)
            for a, n in named_writes.items()
            if any(n.startswith(p) for p in _PRIORITY_NAMES)
        ]
        candidates = priority_hits or list(named_writes.items())
        if len(candidates) == 1:
            addr, var = candidates[0]
            confidence = 0.85 if addr in {a for a, _ in priority_hits} else 0.7
            proposals.append(
                RoutineNameProposal(
                    entry=sub.entry,
                    name=f"update_{var}",
                    why=f"écrit uniquement à ${addr:04X} ({var}) parmi les vars nommées",
                    confidence=confidence,
                )
            )
        else:
            joined = "_".join(n for _, n in sorted(candidates))[:40]
            proposals.append(
                RoutineNameProposal(
                    entry=sub.entry,
                    name=f"update_{joined}",
                    why=f"écrit à {len(candidates)} vars nommées : {[n for _,n in candidates]}",
                    confidence=0.5,
                )
            )
    return proposals


def merge_proposals(
    proposals: List[RoutineNameProposal],
) -> Dict[int, str]:
    by_entry: Dict[int, RoutineNameProposal] = {}
    for p in proposals:
        cur = by_entry.get(p.entry)
        if cur is None or p.confidence > cur.confidence:
            by_entry[p.entry] = p
    return {e: p.name for e, p in by_entry.items()}
