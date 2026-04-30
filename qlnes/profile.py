"""Profilage d'une ROM NES : détecte la stack tech utilisée.

Combine :
- Header iNES → mapper, mirroring, battery, tailles
- Vecteurs CPU (RESET/NMI/IRQ) extraits du dernier bank PRG
- Désassemblage statique (QL6502) + annotation (qlnes.annotate)
- Discovery dynamique (qlnes.emu) si cynes est disponible

Génère un STACK.md avec un panorama complet de la ROM.
"""

import datetime as _dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .annotate import AnnotationReport, annotate, rewrite_asm
from .assets import AssetsManifest, extract_chr
from .cross_ref import RoutineNameProposal, cross_reference, merge_proposals
from .dataflow import find_nmi_address, find_reset_address
from .engines import EngineHint, detect_copyright_year, detect_engines
from .ines import HEADER_SIZE, INesHeader, parse_header, strip_ines
from .lang_detect import LangHypothesis, detect_language
from .nes_hw import NES_REGS
from .parser import Disasm
from .ql6502 import QL6502
from .recompile import RomDiff, assemble_to_rom, verify_round_trip
from .rom import Rom


_MAPPER_NAMES = {
    0: "NROM",
    1: "MMC1",
    2: "UxROM",
    3: "CNROM",
    4: "MMC3",
    5: "MMC5",
    7: "AxROM",
    9: "MMC2",
    10: "MMC4",
    11: "Color Dreams",
    66: "GxROM",
}


def _mirroring(flags6: int) -> str:
    if flags6 & 0x08:
        return "four-screen"
    return "vertical" if (flags6 & 0x01) else "horizontal"


def _has_battery(flags6: int) -> bool:
    return bool(flags6 & 0x02)


def _has_trainer(flags6: int) -> bool:
    return bool(flags6 & 0x04)


@dataclass
class IRQVector:
    name: str
    addr: int
    prg_offset: int


@dataclass
class HardwareUsage:
    nmi_enabled: bool = False
    oam_dma_used: bool = False
    scrolling_used: bool = False
    palette_writes: bool = False
    nametable_writes: bool = False
    controller1_read: bool = False
    controller2_read: bool = False
    apu_used: bool = False
    apu_dmc_used: bool = False
    apu_pulse: bool = False
    apu_triangle: bool = False
    apu_noise: bool = False

    def to_rows(self) -> List[Tuple[str, bool, str]]:
        return [
            ("NMI activé (vblank)", self.nmi_enabled, "STA PPUCTRL avec bit 7"),
            ("OAM DMA (sprites)", self.oam_dma_used, "STA OAMDMA ($4014)"),
            ("Scrolling actif", self.scrolling_used, "STA PPUSCROLL ($2005)"),
            ("Écritures palette/nametable", self.palette_writes or self.nametable_writes, "STA PPUDATA ($2007)"),
            ("Contrôleur 1 lu", self.controller1_read, "LDA JOY1 ($4016)"),
            ("Contrôleur 2 lu", self.controller2_read, "LDA JOY2 ($4017)"),
            ("APU pulses", self.apu_pulse, "STA $4000-$4007"),
            ("APU triangle", self.apu_triangle, "STA $4008-$400B"),
            ("APU noise", self.apu_noise, "STA $400C-$400F"),
            ("APU DMC (samples)", self.apu_dmc_used, "STA $4010-$4013"),
        ]


@dataclass
class RomProfile:
    rom: Rom
    header: Optional[INesHeader]
    vectors: List[IRQVector] = field(default_factory=list)
    static_report: Optional[AnnotationReport] = None
    annotated_asm: str = ""
    hardware: HardwareUsage = field(default_factory=HardwareUsage)
    indirect_jumps: int = 0
    asm_line_count: int = 0
    dynamic_summary: Optional[Dict] = None
    routine_proposals: List[RoutineNameProposal] = field(default_factory=list)
    language_hypotheses: List[LangHypothesis] = field(default_factory=list)
    engine_hints: List[EngineHint] = field(default_factory=list)
    copyright_string: Optional[str] = None
    assets: Optional[AssetsManifest] = None

    @classmethod
    def from_path(cls, path) -> "RomProfile":
        return cls.from_rom(Rom.from_file(path))

    @classmethod
    def from_rom(cls, rom: Rom) -> "RomProfile":
        return cls(rom=rom, header=rom.header)

    def analyze_static(self) -> "RomProfile":
        try:
            image = self.rom.single_image()
        except ValueError:
            image = next(self.rom.banks()).image
        asm = (
            QL6502()
            .load_image(image)
            .mark_blank(0x0000, 0x7FFF)
            .generate_asm()
        )
        self.asm_line_count = len(asm.splitlines())
        self.annotated_asm, self.static_report = annotate(asm, image=image)
        self.vectors = self._extract_vectors(image)
        base_disasm = Disasm(asm)
        self.hardware = self._detect_hardware(self.annotated_asm, base_disasm)
        self.language_hypotheses = detect_language(base_disasm, self.header)
        self.engine_hints = detect_engines(self.rom.raw, self.header, base_disasm)
        cr = detect_copyright_year(self.rom.raw)
        if cr:
            self.copyright_string = cr[1]
        return self

    def extract_assets(self, out_dir) -> AssetsManifest:
        from pathlib import Path as _Path
        out = _Path(out_dir)
        self.assets = extract_chr(self.rom, out)
        return self.assets

    def names_to_addr(self) -> Dict[str, int]:
        if not self.static_report:
            return {}
        out: Dict[str, int] = {}
        for d in (
            self.static_report.hardware,
            self.static_report.oam,
            self.static_report.dataflow,
            self.static_report.fallback,
            self.static_report.subroutines,
        ):
            for addr, name in d.items():
                out.setdefault(name, addr)
        return out

    def recompile(self, output_path) -> Path:
        if not self.annotated_asm:
            raise RuntimeError("appeler analyze_static() d'abord")
        recompiled, errors = assemble_to_rom(
            self.annotated_asm,
            self.rom.raw,
            names_to_addr=self.names_to_addr(),
        )
        from pathlib import Path as _Path
        out = _Path(output_path)
        out.write_bytes(recompiled)
        return out

    def verify_round_trip(self) -> RomDiff:
        if not self.annotated_asm:
            raise RuntimeError("appeler analyze_static() d'abord")
        recompiled, errors = assemble_to_rom(
            self.annotated_asm,
            self.rom.raw,
            names_to_addr=self.names_to_addr(),
        )
        from .recompile import compare_roms
        diff = compare_roms(self.rom.raw, recompiled)
        if errors:
            diff.notes.append(f"{len(errors)} lignes non assemblées")
        return diff

    def analyze_dynamic(
        self,
        rom_path,
        scenarios: Optional[List] = None,
    ) -> "RomProfile":
        from .emu import Discoverer, Scenario  # type: ignore
        import cynes

        static_names = {}
        if self.static_report:
            static_names.update(self.static_report.hardware)
            static_names.update(self.static_report.dataflow)
        ram_static = {a: n for a, n in static_names.items() if a < 0x0800}
        d = Discoverer(rom_path, static_names=ram_static)
        if scenarios is None:
            scenarios = [
                Scenario("press_a").hold(cynes.NES_INPUT_A, 10),
                Scenario("press_b").hold(cynes.NES_INPUT_B, 10),
                Scenario("press_start").hold(cynes.NES_INPUT_START, 10),
            ]
        result = d.discover(scenarios, idle_frames=10)
        self.dynamic_summary = result.to_dict()

        if self.static_report and result.names():
            disasm = Disasm(self.annotated_asm if self.annotated_asm else "")
            try:
                image = self.rom.single_image()
            except ValueError:
                image = next(self.rom.banks()).image
            asm = (
                QL6502()
                .load_image(image)
                .mark_blank(0x0000, 0x7FFF)
                .generate_asm()
            )
            base_disasm = Disasm(asm)
            self.routine_proposals = cross_reference(
                base_disasm,
                result.names(),
                existing=self.static_report.subroutines,
            )
            extra = merge_proposals(self.routine_proposals)
            if extra:
                merged = dict(self.static_report.names)
                merged.update(extra)
                merged.update(result.names())
                self.annotated_asm = rewrite_asm(asm, merged)
                self.static_report.subroutines = {
                    **self.static_report.subroutines,
                    **extra,
                }
        return self

    def _extract_vectors(self, image: bytes) -> List[IRQVector]:
        if len(image) < 0x10000 or self.header is None:
            return []
        prg_offset_base = HEADER_SIZE + (512 if self.header.has_trainer else 0)
        prg = strip_ines(self.rom.raw)
        prg_size = len(prg)
        cpu_to_prg_offset = lambda cpu_addr: (cpu_addr - 0x8000) % max(prg_size, 1)
        out: List[IRQVector] = []
        for name, vec_addr in [("NMI", 0xFFFA), ("RESET", 0xFFFC), ("IRQ", 0xFFFE)]:
            target = image[vec_addr] | (image[vec_addr + 1] << 8)
            out.append(
                IRQVector(
                    name=name,
                    addr=target,
                    prg_offset=prg_offset_base + cpu_to_prg_offset(target),
                )
            )
        return out

    def _detect_hardware(self, annotated_asm: str, disasm: Disasm) -> HardwareUsage:
        h = HardwareUsage()
        text = annotated_asm
        for line in disasm.code_lines():
            mn = (line.mnemonic or "").upper()
            ops = (line.operands or "")
            if mn == "STA":
                if "OAMDMA" in ops or "$4014" in ops or "L_4014" in ops:
                    h.oam_dma_used = True
                if "PPUSCROLL" in ops or "L_2005" in ops:
                    h.scrolling_used = True
                if "PPUDATA" in ops or "L_2007" in ops:
                    h.palette_writes = True
                if "PPUADDR" in ops or "L_2006" in ops:
                    h.nametable_writes = True
                if "PPUCTRL" in ops or "L_2000" in ops:
                    if line.refs and any(0x2000 == r for r in line.refs):
                        pass
            if mn == "LDA":
                if "JOY1" in ops or "L_4016" in ops:
                    h.controller1_read = True
                if "JOY2_FRAMECTR" in ops or "L_4017" in ops:
                    h.controller2_read = True
        for line in disasm.code_lines():
            mn = (line.mnemonic or "").upper()
            if mn != "STA":
                continue
            for ref in line.refs:
                if 0x4000 <= ref <= 0x4013:
                    h.apu_used = True
                if 0x4000 <= ref <= 0x4007:
                    h.apu_pulse = True
                if 0x4008 <= ref <= 0x400B:
                    h.apu_triangle = True
                if 0x400C <= ref <= 0x400F:
                    h.apu_noise = True
                if 0x4010 <= ref <= 0x4013:
                    h.apu_dmc_used = True
        if "PPUCTRL" in annotated_asm:
            for line in disasm.code_lines():
                if (line.mnemonic or "").upper() != "STA":
                    continue
                if 0x2000 not in line.refs:
                    continue
                idx = disasm.code_lines().index(line)
                code = disasm.code_lines()
                for back in range(max(0, idx - 4), idx):
                    prev = code[back]
                    if (prev.mnemonic or "").upper() == "LDA" and prev.operands and prev.operands.startswith("#"):
                        try:
                            val = int(prev.operands[1:].strip().replace("0x", ""), 16)
                        except ValueError:
                            continue
                        if val & 0x80:
                            h.nmi_enabled = True
                            break
        for line in disasm.code_lines():
            if (line.mnemonic or "").upper() == "JMP" and line.operands and line.operands.startswith("("):
                self.indirect_jumps += 1
        return h

    def characterize(self) -> List[str]:
        traits = []
        if self.hardware.scrolling_used:
            traits.append("jeu avec scrolling")
        elif self.hardware.oam_dma_used:
            traits.append("jeu avec sprites mais sans scrolling (single-screen)")
        else:
            traits.append("ROM sans gameplay évident (test/démo/menu statique)")
        if self.hardware.apu_dmc_used:
            traits.append("utilise des samples DMC (musique/voix digitale)")
        if self.hardware.apu_pulse and self.hardware.apu_triangle:
            traits.append("musique multi-canaux APU")
        if self.header and _has_battery(self.header.flags6):
            traits.append("save battery (RPG/aventure probable)")
        if self.indirect_jumps > 0:
            traits.append(f"{self.indirect_jumps} JMP indirect détectés (tables de pointeurs)")
        if self.dynamic_summary:
            n_scen = sum(self.dynamic_summary.get("summary", {}).get("scenarios", {}).values())
            if n_scen > 0:
                traits.append(f"{n_scen} variables réactives découvertes par discovery dynamique")
        return traits

    def to_markdown(self) -> str:
        lines: List[str] = []
        name = self.rom.name
        now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        lines.append(f"# STACK — {name}")
        lines.append("")
        lines.append(f"_Généré automatiquement par **qlnes** le {now}._")
        lines.append("")
        lines.append("## En-tête iNES")
        lines.append("")
        if self.header is None:
            lines.append("⚠️  Pas d'en-tête iNES valide (image brute ou format inconnu).")
        else:
            mapper_name = _MAPPER_NAMES.get(self.header.mapper, "?")
            lines.append("| Champ | Valeur |")
            lines.append("|---|---|")
            lines.append(f"| Magic | `NES\\x1A` ✓ |")
            lines.append(f"| Mapper | {self.header.mapper} ({mapper_name}) |")
            lines.append(f"| PRG-ROM | {self.header.prg_size // 1024} KB ({self.header.prg_banks} bank{'s' if self.header.prg_banks != 1 else ''}) |")
            lines.append(f"| CHR-ROM | {self.header.chr_size // 1024} KB ({self.header.chr_banks} bank{'s' if self.header.chr_banks != 1 else ''}) |")
            lines.append(f"| Mirroring | {_mirroring(self.header.flags6)} |")
            lines.append(f"| Battery (SRAM) | {'oui' if _has_battery(self.header.flags6) else 'non'} |")
            lines.append(f"| Trainer | {'oui' if _has_trainer(self.header.flags6) else 'non'} |")
        lines.append("")

        if self.vectors:
            lines.append("## Vecteurs CPU")
            lines.append("")
            lines.append("| Vecteur | Adresse CPU | Offset PRG |")
            lines.append("|---|---|---|")
            for v in self.vectors:
                lines.append(f"| {v.name} | `${v.addr:04X}` | `0x{v.prg_offset:04X}` |")
            lines.append("")

        if self.static_report:
            r = self.static_report
            summary = r.to_dict()["summary"]
            lines.append("## Désassemblage statique")
            lines.append("")
            lines.append(f"- **{self.asm_line_count}** lignes assembleur")
            lines.append(f"- **{summary['hardware']}** registres hardware identifiés")
            lines.append(f"- **{summary['oam']}** zones OAM")
            lines.append(f"- **{summary['dataflow']}** patterns dataflow détectés")
            lines.append(f"- **{summary['code_labels']}** labels de code internes")
            lines.append(f"- **{summary['fallback']}** vars zero-page non classifiées")
            lines.append(f"- **{summary['unmapped']}** adresses non classifiées")
            if self.indirect_jumps:
                lines.append(f"- **{self.indirect_jumps}** JMP indirects (tables de pointeurs)")
            lines.append("")

            if r.hardware:
                lines.append("### Registres hardware utilisés")
                lines.append("")
                for addr in sorted(r.hardware):
                    lines.append(f"- `${addr:04X}` — **{r.hardware[addr]}**")
                lines.append("")

            if r.dataflow:
                lines.append("### Patterns dataflow détectés")
                lines.append("")
                detections_by_addr: Dict[int, object] = {}
                for d in r.detections:
                    cur = detections_by_addr.get(d.addr)
                    if cur is None or d.confidence > cur.confidence:
                        detections_by_addr[d.addr] = d
                for addr in sorted(r.dataflow):
                    name = r.dataflow[addr]
                    det = detections_by_addr.get(addr)
                    why = f" — _{det.why}_" if det else ""
                    lines.append(f"- `${addr:04X}` → **{name}**{why}")
                lines.append("")

            if r.subroutines:
                lines.append("### Sous-routines nommées")
                lines.append("")
                lines.append("| Adresse | Nom | Type | Pourquoi |")
                lines.append("|---|---|---|---|")
                for entry in sorted(r.subroutines):
                    name = r.subroutines[entry]
                    sub = r.subroutine_details.get(entry)
                    kind = sub.kind if sub else "—"
                    why = sub.why if sub and sub.why else "_cross-ref dynamique_"
                    lines.append(f"| `${entry:04X}` | **{name}** | `{kind or '—'}` | {why} |")
                lines.append("")

            if r.oam:
                lines.append("### Sprites (OAM)")
                lines.append("")
                lines.append(f"{len(r.oam)} adresses dans la zone OAM ($0200-$02FF) référencées.")
                lines.append("")

        lines.append("## Stack technique détectée")
        lines.append("")
        lines.append("| Capacité | Présent | Indice |")
        lines.append("|---|:---:|---|")
        for label, present, hint in self.hardware.to_rows():
            mark = "✅" if present else "❌"
            lines.append(f"| {label} | {mark} | `{hint}` |")
        lines.append("")

        if self.engine_hints or self.copyright_string:
            lines.append("## Éditeur / moteur")
            lines.append("")
            if self.copyright_string:
                lines.append(f"Chaîne copyright trouvée : `{self.copyright_string}`")
                lines.append("")
            if self.engine_hints:
                lines.append("| Hypothèse | Type | Confiance | Indice |")
                lines.append("|---|---|---:|---|")
                for h in self.engine_hints:
                    lines.append(h.to_row())
                lines.append("")

        if self.language_hypotheses:
            lines.append("## Langage / toolchain probable")
            lines.append("")
            lines.append("| Hypothèse | Confiance | Indices |")
            lines.append("|---|---:|---|")
            for h in self.language_hypotheses:
                lines.append(h.to_row())
            lines.append("")

        traits = self.characterize()
        if traits:
            lines.append("## Caractérisation")
            lines.append("")
            for t in traits:
                lines.append(f"- {t}")
            lines.append("")

        if self.routine_proposals:
            lines.append("## Cross-référence dynamique → routines")
            lines.append("")
            lines.append("Adresses nommées par diff comportemental, propagées aux routines qui les modifient :")
            lines.append("")
            lines.append("| Routine | Nom proposé | Confiance | Raison |")
            lines.append("|---|---|---:|---|")
            for p in self.routine_proposals:
                lines.append(
                    f"| `${p.entry:04X}` | **{p.name}** | {p.confidence:.2f} | {p.why} |"
                )
            lines.append("")

        if self.dynamic_summary:
            lines.append("## Discovery dynamique (cynes)")
            lines.append("")
            scen = self.dynamic_summary.get("scenarios", {})
            for name, vars_ in scen.items():
                if not vars_:
                    continue
                lines.append(f"### Scénario `{name}`")
                lines.append("")
                lines.append("| Adresse | Nom | Δ | Confiance | Raison |")
                lines.append("|---|---|---:|---:|---|")
                for v in vars_[:10]:
                    lines.append(
                        f"| `{v['addr']}` | **{v['name']}** | {v['delta']} | {v['confidence']:.2f} | {v['why']} |"
                    )
                lines.append("")

        if self.assets:
            lines.append("## Assets extraits")
            lines.append("")
            for row in self.assets.to_rows():
                lines.append(row)
            lines.append("")

        lines.append("---")
        lines.append("")
        lines.append("_Pour modder cette ROM, voir le désassemblage annoté généré séparément._")
        lines.append("")
        return "\n".join(lines)

    def write_markdown(self, path) -> Path:
        out = Path(path)
        out.write_text(self.to_markdown(), encoding="utf-8")
        return out
