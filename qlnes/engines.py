"""Détection d'éditeur, moteur et signatures connues dans une ROM NES.

Trois sources d'information sont combinées :

1. **Mapper number** : beaucoup d'éditeurs ont des mappers custom signés
   (Konami → VRC, Sunsoft → FME-7, Namco → 163, …). Le mapper donne donc
   un fort indice sur l'éditeur d'origine.

2. **Chaînes ASCII dans la PRG/CHR** : copyright et noms d'éditeur sont
   souvent stockés en clair pour l'écran-titre. Scanner les bytes pour
   trouver KONAMI, CAPCOM, NINTENDO, etc.

3. **Heuristiques sur idiomes de moteurs sonores** (FamiTone, Sunsoft 5B,
   Capcom audio…) — détection partielle, encore probabiliste.

Les hits sont retournés avec confiance et indices motivants.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .ines import INesHeader, strip_ines

if TYPE_CHECKING:
    from .parser import Disasm


@dataclass
class EngineHint:
    name: str
    kind: str
    confidence: float
    evidence: str

    def to_row(self) -> str:
        return f"| **{self.name}** | `{self.kind}` | {self.confidence:.2f} | {self.evidence} |"


MAPPER_PUBLISHER_HINTS = {
    1: ("Nintendo (MMC1)", "publisher", 0.55, "MMC1 → souvent Nintendo, Capcom, Square"),
    4: ("Nintendo (MMC3)", "publisher", 0.55, "MMC3 → Nintendo, Konami, Capcom"),
    5: ("Nintendo (MMC5)", "publisher", 0.85, "MMC5 → Nintendo (Castlevania III JP)"),
    9: ("Nintendo (MMC2)", "publisher", 0.9, "MMC2 → exclu de Punch-Out!! Nintendo"),
    10: ("Nintendo (MMC4)", "publisher", 0.9, "MMC4 → Fire Emblem Gaiden Nintendo"),
    16: (
        "Bandai (FCG)",
        "publisher",
        0.9,
        "mapper 16 = Bandai FCG-1/-2 (Dragon Ball, Famicom Jump)",
    ),
    18: ("Jaleco (SS 88006)", "publisher", 0.9, "mapper 18 = Jaleco custom (Bases Loaded II/III)"),
    19: ("Namco (N163)", "publisher", 0.9, "mapper 19 = Namco 163 (Battle Fleet, Megami Tensei)"),
    20: ("Famicom Disk System", "platform", 0.95, "mapper 20 = FDS"),
    21: ("Konami (VRC4)", "publisher", 0.95, "mapper 21 = VRC4a/c"),
    23: ("Konami (VRC2)", "publisher", 0.95, "mapper 23 = VRC2b (Wai Wai World)"),
    24: (
        "Konami (VRC6)",
        "publisher",
        0.95,
        "mapper 24 = VRC6a (Akumajou Densetsu / Castlevania III JP)",
    ),
    25: ("Konami (VRC4)", "publisher", 0.95, "mapper 25 = VRC4b/d"),
    26: ("Konami (VRC6 alt)", "publisher", 0.95, "mapper 26 = VRC6b (Madara, Esper Dream 2)"),
    32: ("Irem (G-101)", "publisher", 0.9, "mapper 32 = Image Fight, Major League"),
    33: ("Taito (TC0190)", "publisher", 0.9, "mapper 33 = Akira, Power Blade 2"),
    48: ("Taito (TC0690)", "publisher", 0.9, "mapper 48 = Don Doko Don 2, Flintstones"),
    65: ("Irem (H3001)", "publisher", 0.9, "mapper 65 = Daiku no Gen-san 2"),
    66: ("Generic (GxROM)", "platform", 0.5, "mapper 66 = GNROM (Sunsoft, Bandai...)"),
    67: ("Sunsoft (3)", "publisher", 0.9, "mapper 67 = Sunsoft 3"),
    68: ("Sunsoft (4)", "publisher", 0.9, "mapper 68 = After Burner"),
    69: ("Sunsoft (FME-7/5B)", "publisher", 0.95, "mapper 69 = FME-7 (Batman ROTJ, Gimmick!)"),
    73: ("Konami (VRC3)", "publisher", 0.9, "mapper 73 = VRC3 (Salamander)"),
    75: ("Konami (VRC1)", "publisher", 0.9, "mapper 75 = VRC1"),
    80: ("Taito (X1-005)", "publisher", 0.9, "mapper 80 = Taito Bingo, Minelvaton Saga"),
    85: ("Konami (VRC7)", "publisher", 0.95, "mapper 85 = VRC7 (Lagrange Point — synthé FM)"),
    87: ("Jaleco/Konami (J87)", "publisher", 0.7, "mapper 87 = J87 small"),
    95: ("Namco (108)", "publisher", 0.9, "mapper 95 = Namco 108 (Dragon Buster)"),
    105: (
        "Nintendo World Cup",
        "publisher",
        0.95,
        "mapper 105 = Nintendo World Championships 1990",
    ),
}


PUBLISHER_KEYWORDS = {
    "KONAMI": "Konami",
    "CAPCOM": "Capcom",
    "NINTENDO": "Nintendo",
    "TAITO": "Taito",
    "NAMCO": "Namco",
    "NAMCOT": "Namco",
    "IREM": "Irem",
    "JALECO": "Jaleco",
    "SUNSOFT": "Sunsoft",
    "TECMO": "Tecmo",
    "SQUARE": "Squaresoft",
    "HUDSON": "Hudson Soft",
    "BANDAI": "Bandai",
    "ENIX": "Enix",
    "ACCLAIM": "Acclaim",
    "ULTRA": "Ultra Games",
    "NATSUME": "Natsume",
    "ATLUS": "Atlus",
    "DATA EAST": "Data East",
    "TENGEN": "Tengen",
    "ASCII": "ASCII Corp.",
    "TOSE": "TOSE",
    "PONY CANYON": "Pony Canyon",
    "VICTOR": "Victor / JVC",
    "KEMCO": "Kemco",
    "CULTURE BRAIN": "Culture Brain",
    "VAP": "VAP",
    "SETA": "Seta",
    "SAMMY": "Sammy",
    "INTV": "Intelligent Systems",
    "RARE": "Rare Ltd.",
    "BEAM": "Beam Software",
}


def find_ascii_strings(data: bytes, min_len: int = 4) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    cur: list[str] = []
    start = 0
    for i, b in enumerate(data):
        if 0x20 <= b <= 0x7E:
            if not cur:
                start = i
            cur.append(chr(b))
        else:
            if len(cur) >= min_len:
                out.append((start, "".join(cur)))
            cur = []
    if len(cur) >= min_len:
        out.append((start, "".join(cur)))
    return out


def detect_publisher_by_strings(data: bytes) -> list[EngineHint]:
    strings = find_ascii_strings(data, min_len=4)
    seen_publishers: set[str] = set()
    hints: list[EngineHint] = []
    for start, s in strings:
        s_upper = s.upper()
        for keyword, publisher in PUBLISHER_KEYWORDS.items():
            if keyword in s_upper and publisher not in seen_publishers:
                seen_publishers.add(publisher)
                hints.append(
                    EngineHint(
                        name=publisher,
                        kind="publisher",
                        confidence=0.9,
                        evidence=f'chaîne "{s}" trouvée à offset 0x{start:04X}',
                    )
                )
                break
    return hints


def detect_copyright_year(data: bytes) -> tuple[int, str] | None:
    strings = find_ascii_strings(data, min_len=4)
    for start, s in strings:
        for prefix in ("(C)", "©", "(c)", "COPYRIGHT"):
            if prefix in s.upper():
                return (start, s)
    for start, s in strings:
        if any(yr in s for yr in ("198", "199")):
            return (start, s)
    return None


def detect_publisher_by_mapper(header: INesHeader | None) -> list[EngineHint]:
    if header is None:
        return []
    hint = MAPPER_PUBLISHER_HINTS.get(header.mapper)
    if not hint:
        return []
    name, kind, conf, why = hint
    return [EngineHint(name=name, kind=kind, confidence=conf, evidence=why)]


def detect_famitone(disasm: "Disasm | None") -> EngineHint | None:
    code = disasm.code_lines() if disasm else []
    if not code:
        return None
    apu_writes = 0
    pointer_loads_zp = 0
    for line in code:
        mn = (line.mnemonic or "").upper()
        if mn == "STA":
            for ref in line.refs:
                if 0x4000 <= ref <= 0x4013:
                    apu_writes += 1
        if mn == "LDA" and line.operands and "(" in line.operands and ")" in line.operands:
            pointer_loads_zp += 1
    if apu_writes >= 30 and pointer_loads_zp >= 5:
        return EngineHint(
            name="moteur audio à pointeurs (FamiTone-like / NSF custom)",
            kind="sound_engine",
            confidence=0.6,
            evidence=f"{apu_writes} writes APU $4000-$4013 + {pointer_loads_zp} dérefs (zp),Y",
        )
    return None


def detect_engines(
    rom_raw: bytes,
    header: INesHeader | None,
    disasm: "Disasm | None" = None,
) -> list[EngineHint]:
    hints: list[EngineHint] = []
    hints.extend(detect_publisher_by_mapper(header))
    if header is not None:
        prg = strip_ines(rom_raw)
        chr_offset = 16 + (512 if header.has_trainer else 0) + header.prg_size
        chr_data = rom_raw[chr_offset : chr_offset + header.chr_size] if header.chr_size else b""
        hints.extend(detect_publisher_by_strings(prg))
        if chr_data:
            hints.extend(detect_publisher_by_strings(chr_data))
    else:
        hints.extend(detect_publisher_by_strings(rom_raw))
    famitone = detect_famitone(disasm) if disasm else None
    if famitone:
        hints.append(famitone)
    seen: set[tuple[str, str]] = set()
    out: list[EngineHint] = []
    for h in sorted(hints, key=lambda x: -x.confidence):
        key = (h.name.lower(), h.kind)
        if key in seen:
            continue
        seen.add(key)
        out.append(h)
    return out
