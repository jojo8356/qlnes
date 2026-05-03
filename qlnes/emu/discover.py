"""Auto-discovery des variables de jeu par diff comportemental.

Stratégie de base :
1. Calibration : on lance plusieurs runs idle (sans input) en repartant de
   reset, on identifie les adresses qui varient même sans input.
2. Pour chaque scénario {pressA, pressB, …}, on relance depuis reset, on
   exécute le scénario, et on diff la RAM (initial vs final) en filtrant
   le bruit. Les adresses qui ont changé UNIQUEMENT dans ce scénario sont
   les candidates pour la sémantique du bouton.
3. Classification : on regarde le delta (signe, magnitude vs durée) pour
   décider si c'est une jauge, un score, un état booléen, un level…

Stratégies avancées :
- discover_multi_duration : exécute le même bouton à 5/10/20f et compare
  les rates pour distinguer linéaire (counter/gauge) vs saturation (flag).
- discover_composed : 4 runs (A, B, A puis B, B puis A) pour identifier
  indépendance / ordre / interaction réelle entre deux boutons.
- find_transitions : surveille le frame_counter pendant un long scénario,
  détecte les resets (fc[t] < fc[t-1]) — game-over, level transition.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .runner import RAM_SIZE, Runner, Scenario, Snapshot


@dataclass
class DiscoveredVariable:
    addr: int
    name: str
    confidence: float
    why: str
    initial: int
    final: int
    delta: int


@dataclass
class DurationMeasurement:
    frames: int
    initial: int
    final: int

    @property
    def signed_delta(self) -> int:
        d = (self.final - self.initial) & 0xFF
        return d - 256 if d >= 128 else d

    @property
    def rate(self) -> float:
        return self.signed_delta / self.frames if self.frames else 0.0


@dataclass
class InteractionResult:
    addr: int
    a_alone: int
    b_alone: int
    a_then_b: int
    b_then_a: int

    @property
    def is_independent(self) -> bool:
        return self.a_then_b == self.b_then_a == self.a_alone + self.b_alone

    @property
    def order_matters(self) -> bool:
        return self.a_then_b != self.b_then_a

    @property
    def has_interaction(self) -> bool:
        return self.a_then_b != (self.a_alone + self.b_alone)

    def label(self) -> str:
        if self.is_independent:
            return "independent"
        if self.order_matters:
            return "order_dependent"
        if self.has_interaction:
            return "interactive"
        return "unrelated"

    def to_dict(self) -> dict[str, Any]:
        return {
            "addr": f"0x{self.addr:04X}",
            "a_alone": self.a_alone,
            "b_alone": self.b_alone,
            "a_then_b": self.a_then_b,
            "b_then_a": self.b_then_a,
            "label": self.label(),
        }


@dataclass
class Transition:
    frame: int
    fc_before: int
    fc_after: int
    ram_diff: dict[int, tuple[int, int]] = field(default_factory=dict)

    def changed_addrs(self) -> list[int]:
        return sorted(self.ram_diff.keys())

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame": self.frame,
            "fc_before": self.fc_before,
            "fc_after": self.fc_after,
            "n_changed": len(self.ram_diff),
            "changed": [
                {"addr": f"0x{a:04X}", "before": b, "after": x}
                for a, (b, x) in sorted(self.ram_diff.items())
            ],
        }


@dataclass
class DiscoveryResult:
    noise: set[int] = field(default_factory=set)
    baseline: Snapshot | None = None
    by_scenario: dict[str, list[DiscoveredVariable]] = field(default_factory=dict)

    def all_variables(self) -> list[DiscoveredVariable]:
        out: list[DiscoveredVariable] = []
        for vs in self.by_scenario.values():
            out.extend(vs)
        return out

    def names(self) -> dict[int, str]:
        merged: dict[int, tuple[str, float]] = {}
        for v in self.all_variables():
            cur = merged.get(v.addr)
            if cur is None or v.confidence > cur[1]:
                merged[v.addr] = (v.name, v.confidence)
        return {a: name for a, (name, _) in merged.items()}

    def to_dict(self) -> dict[str, Any]:
        return {
            "noise": sorted(f"0x{a:04X}" for a in self.noise),
            "scenarios": {
                name: [
                    {
                        "addr": f"0x{v.addr:04X}",
                        "name": v.name,
                        "confidence": round(v.confidence, 3),
                        "why": v.why,
                        "initial": v.initial,
                        "final": v.final,
                        "delta": v.delta,
                    }
                    for v in vs
                ]
                for name, vs in self.by_scenario.items()
            },
            "summary": {
                "noise_count": len(self.noise),
                "scenarios": {n: len(vs) for n, vs in self.by_scenario.items()},
            },
        }


def _signed(byte_delta: int) -> int:
    return byte_delta if byte_delta < 128 else byte_delta - 256


def classify_change(initial: int, final: int, frames_held: int) -> tuple[str, float, str]:
    delta = (final - initial) & 0xFF
    signed_delta = _signed(delta)

    if signed_delta == 0:
        return ("flag", 0.3, "valeur identique (peu informatif)")

    if frames_held > 0:
        per_frame = abs(signed_delta) / frames_held
        if 0.5 <= per_frame <= 1.5:
            if signed_delta < 0:
                return (
                    "gauge",
                    0.9,
                    f"décrément linéaire ~1/f (Δ={signed_delta} sur {frames_held}f)",
                )
            return (
                "counter",
                0.9,
                f"incrément linéaire ~1/f (Δ=+{signed_delta} sur {frames_held}f)",
            )
        if per_frame >= 4:
            return (
                "flag",
                0.6,
                f"saute brusquement (Δ={signed_delta} en {frames_held}f) — sans doute un état booléen",
            )

    if 0 < abs(signed_delta) <= frames_held / 2 + 1:
        return (
            "state",
            0.7,
            f"changement borné (Δ={signed_delta}) — probablement un état/level",
        )

    return ("changed", 0.5, f"Δ={signed_delta} sur {frames_held}f — comportement inclassé")


def classify_with_linearity(
    short_initial: int,
    short_final: int,
    short_frames: int,
    long_initial: int,
    long_final: int,
    long_frames: int,
) -> tuple[str, float, str]:
    return classify_durations(
        [
            DurationMeasurement(short_frames, short_initial, short_final),
            DurationMeasurement(long_frames, long_initial, long_final),
        ]
    )


def classify_durations(
    measurements: list[DurationMeasurement],
) -> tuple[str, float, str]:
    if not measurements:
        return ("flag", 0.0, "aucune mesure")
    rates = [m.rate for m in measurements]
    deltas = [m.signed_delta for m in measurements]
    nonzero = [d for d in deltas if d != 0]

    if not nonzero:
        return ("flag", 0.3, "aucun changement à toutes durées")

    rate_spread = max(rates) - min(rates)
    if rate_spread <= 0.3 and all(d != 0 for d in deltas):
        avg = sum(rates) / len(rates)
        rates_str = ", ".join(f"{r:+.2f}" for r in rates)
        if avg <= -0.5:
            return (
                "gauge",
                0.95,
                f"linéaire {avg:+.2f}/f (rates [{rates_str}])",
            )
        if avg >= 0.5:
            return (
                "counter",
                0.95,
                f"linéaire {avg:+.2f}/f (rates [{rates_str}])",
            )

    if len(set(deltas)) == 1 and deltas[0] != 0:
        return (
            "flag",
            0.9,
            f"saturé à Δ={deltas[0]} pour toutes durées",
        )

    if len(measurements) >= 2 and all(d != 0 for d in deltas) and abs(deltas[-1]) > abs(deltas[0]):
        return (
            "changed",
            0.65,
            f"évolution non-linéaire deltas={deltas}",
        )

    return (
        "changed",
        0.5,
        f"deltas={deltas} rates=[{', '.join(f'{r:+.2f}' for r in rates)}]",
    )


_NAME_TEMPLATES = {
    "press_a": {"gauge": "lives", "counter": "score", "state": "state_a"},
    "press_b": {"gauge": "ammo", "counter": "score", "state": "state_b"},
    "press_start": {"gauge": "menu", "counter": "level", "state": "level"},
    "press_select": {"gauge": "menu", "counter": "select_count", "state": "menu_state"},
    "press_up": {"counter": "y_up_count", "state": "player_y"},
    "press_down": {"counter": "y_down_count", "state": "player_y"},
    "press_left": {"counter": "x_left_count", "state": "player_x"},
    "press_right": {"counter": "x_right_count", "state": "player_x"},
}


def _name_for(scenario_name: str, kind: str) -> str:
    tmpl = _NAME_TEMPLATES.get(scenario_name.lower())
    if tmpl and kind in tmpl:
        return tmpl[kind]
    return f"{scenario_name}_{kind}"


class Discoverer:
    def __init__(
        self,
        rom_path: str | Path,
        static_names: dict[int, str] | None = None,
    ) -> None:
        self.rom_path = rom_path
        self.boot_frames = 60
        self.calibration_samples = 3
        self.static_names: dict[int, str] = dict(static_names or {})

    def _excluded(self, addr: int, noise: set[int]) -> bool:
        return addr in noise or addr in self.static_names

    def calibrate_noise(
        self,
        idle_frames: int = 30,
        samples: int | None = None,
    ) -> tuple[Snapshot, set[int]]:
        n = samples or self.calibration_samples
        snaps: list[Snapshot] = []
        for _ in range(n):
            r = Runner(self.rom_path)
            r.boot(self.boot_frames)
            r.hold(0, idle_frames)
            snaps.append(r.snapshot_ram())
        noise: set[int] = set()
        for a in range(RAM_SIZE):
            vals = {s.ram[a] for s in snaps}
            if len(vals) > 1:
                noise.add(a)
        return snaps[0], noise

    def discover(
        self,
        scenarios: list[Scenario],
        idle_frames: int | None = None,
    ) -> DiscoveryResult:
        result = DiscoveryResult()
        max_frames = max(s.total_frames() for s in scenarios) if scenarios else 30
        idle = idle_frames if idle_frames is not None else max_frames
        baseline, noise = self.calibrate_noise(idle_frames=idle)
        result.baseline = baseline
        result.noise = noise

        for sc in scenarios:
            r = Runner(self.rom_path)
            snaps = r.run_scenario(sc, boot_frames=self.boot_frames)
            initial = snaps[0]
            final = snaps[-1]
            held_frames = sc.total_frames()
            findings: list[DiscoveredVariable] = []
            for a in range(RAM_SIZE):
                if self._excluded(a, noise):
                    continue
                ini_v = initial.ram[a]
                fin_v = final.ram[a]
                if ini_v == fin_v:
                    continue
                kind, conf, why = classify_change(ini_v, fin_v, held_frames)
                findings.append(
                    DiscoveredVariable(
                        addr=a,
                        name=_name_for(sc.name, kind),
                        confidence=conf,
                        why=why,
                        initial=ini_v,
                        final=fin_v,
                        delta=(fin_v - ini_v) & 0xFF,
                    )
                )
            findings.sort(key=lambda v: -v.confidence)
            result.by_scenario[sc.name] = findings

        return result

    def discover_multi_duration(
        self,
        button_label: str,
        buttons: int,
        durations: tuple[int, ...] = (5, 10, 20),
    ) -> list[DiscoveredVariable]:
        if not durations:
            raise ValueError("durations must be non-empty")
        runs: dict[int, tuple[Snapshot, Snapshot]] = {}
        for d in durations:
            r = Runner(self.rom_path)
            sc = Scenario(f"{button_label}_{d}f").hold(buttons, d)
            snaps = r.run_scenario(sc, boot_frames=self.boot_frames)
            runs[d] = (snaps[0], snaps[-1])
        _, noise = self.calibrate_noise(idle_frames=max(durations))

        findings: list[DiscoveredVariable] = []
        for a in range(RAM_SIZE):
            if self._excluded(a, noise):
                continue
            measurements = [
                DurationMeasurement(
                    frames=d,
                    initial=runs[d][0].ram[a],
                    final=runs[d][1].ram[a],
                )
                for d in durations
            ]
            if all(m.signed_delta == 0 for m in measurements):
                continue
            kind, conf, why = classify_durations(measurements)
            canonical = measurements[-1]
            findings.append(
                DiscoveredVariable(
                    addr=a,
                    name=_name_for(button_label, kind),
                    confidence=conf,
                    why=why,
                    initial=canonical.initial,
                    final=canonical.final,
                    delta=(canonical.final - canonical.initial) & 0xFF,
                )
            )
        findings.sort(key=lambda v: -v.confidence)
        return findings

    def discover_composed(
        self,
        a_label: str,
        a_buttons: int,
        a_frames: int,
        b_label: str,
        b_buttons: int,
        b_frames: int,
    ) -> dict[int, InteractionResult]:
        def run(scenario: Scenario) -> tuple[Snapshot, Snapshot]:
            r = Runner(self.rom_path)
            snaps = r.run_scenario(scenario, boot_frames=self.boot_frames)
            return snaps[0], snaps[-1]

        a_alone = run(Scenario(f"{a_label}_alone").hold(a_buttons, a_frames))
        b_alone = run(Scenario(f"{b_label}_alone").hold(b_buttons, b_frames))
        a_then_b = run(
            Scenario(f"{a_label}_then_{b_label}")
            .hold(a_buttons, a_frames)
            .hold(b_buttons, b_frames)
        )
        b_then_a = run(
            Scenario(f"{b_label}_then_{a_label}")
            .hold(b_buttons, b_frames)
            .hold(a_buttons, a_frames)
        )
        _, noise = self.calibrate_noise(idle_frames=a_frames + b_frames)

        results: dict[int, InteractionResult] = {}
        for a in range(RAM_SIZE):
            if self._excluded(a, noise):
                continue
            d_aa = _signed((a_alone[1].ram[a] - a_alone[0].ram[a]) & 0xFF)
            d_bb = _signed((b_alone[1].ram[a] - b_alone[0].ram[a]) & 0xFF)
            d_ab = _signed((a_then_b[1].ram[a] - a_then_b[0].ram[a]) & 0xFF)
            d_ba = _signed((b_then_a[1].ram[a] - b_then_a[0].ram[a]) & 0xFF)
            if d_aa == 0 and d_bb == 0 and d_ab == 0 and d_ba == 0:
                continue
            results[a] = InteractionResult(
                addr=a,
                a_alone=d_aa,
                b_alone=d_bb,
                a_then_b=d_ab,
                b_then_a=d_ba,
            )
        return results

    def find_transitions(
        self,
        fc_addr: int,
        scenario: Scenario,
    ) -> list[Transition]:
        r = Runner(self.rom_path)
        r.boot(self.boot_frames)
        transitions: list[Transition] = []
        prev_snap = r.snapshot_ram()
        prev_fc = prev_snap.ram[fc_addr]
        for buttons, frames in scenario.steps:
            r.nes.controller = buttons
            for _ in range(frames):
                r.nes.step(1)
                r.frame += 1
                cur_snap = r.snapshot_ram()
                cur_fc = cur_snap.ram[fc_addr]
                if cur_fc < prev_fc:
                    diff: dict[int, tuple[int, int]] = {}
                    for a in range(RAM_SIZE):
                        if a == fc_addr:
                            continue
                        if prev_snap.ram[a] != cur_snap.ram[a]:
                            diff[a] = (prev_snap.ram[a], cur_snap.ram[a])
                    transitions.append(
                        Transition(
                            frame=r.frame,
                            fc_before=prev_fc,
                            fc_after=cur_fc,
                            ram_diff=diff,
                        )
                    )
                prev_snap = cur_snap
                prev_fc = cur_fc
        return transitions

    def transition_state_addrs(
        self,
        transitions: list[Transition],
        min_consistency: float = 0.8,
    ) -> dict[int, tuple[int, int]]:
        if not transitions:
            return {}
        per_addr_changes: dict[int, list[tuple[int, int]]] = {}
        for t in transitions:
            for a, (b, after) in t.ram_diff.items():
                per_addr_changes.setdefault(a, []).append((b, after))
        out: dict[int, tuple[int, int]] = {}
        threshold = max(1, int(len(transitions) * min_consistency))
        for a, changes in per_addr_changes.items():
            if len(changes) < threshold:
                continue
            after_vals = {x for _, x in changes}
            if len(after_vals) == 1:
                out[a] = changes[0]
        return out
