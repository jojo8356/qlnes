"""ROM NES → WAV/MP3 via fceux APU trace + pure-Python synth.

Pipeline:
  1) `record_apu_trace(rom)` → lance fceux headless avec un script Lua
     qui logue chaque écriture $4000-$4017 avec son cycle CPU absolu.
  2) `synthesize_wav(trace, out)` → simule l'APU 2A03 (pulse 1+2,
     triangle, noise) à 44.1 kHz et applique le mixeur non-linéaire.
  3) `wav_to_mp3(wav, mp3)` → ffmpeg shellout.

Mapper-agnostique : c'est fceux qui exécute la ROM, qlnes ne fait que
synthétiser à partir de la trace de registres.

Limites du MVP :
- DMC (samples) : ignoré, $4010-$4013/$4011 ne contribuent pas au mix
- Length counters : ignorés (les notes durent jusqu'au prochain write)
- Sweep : ignoré (peu de musique NES en dépend)
- Frame-counter IRQ : ignoré
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple


NTSC_CPU_HZ = 1_789_773.0
SAMPLE_RATE = 44_100

LUA_SCRIPT = Path(__file__).resolve().parent / "audio_trace.lua"


# ---------------------------------------------------------------------------
# Étape 1 : capture de la trace via fceux
# ---------------------------------------------------------------------------


@dataclass
class TraceEvent:
    cycle: int
    addr: int
    value: int


def record_apu_trace(
    rom_path: Path,
    *,
    frames: int = 600,
    out_trace: Optional[Path] = None,
    fceux_bin: str = "fceux",
    timeout: Optional[float] = None,
) -> Path:
    """Lance fceux en mode offscreen avec le script Lua de capture.
    Retourne le chemin de la trace TSV (créée par le script Lua).
    """
    rom_path = Path(rom_path).resolve()
    if not rom_path.exists():
        raise FileNotFoundError(rom_path)
    if not LUA_SCRIPT.exists():
        raise FileNotFoundError(f"audio_trace.lua introuvable : {LUA_SCRIPT}")
    if shutil.which(fceux_bin) is None:
        raise RuntimeError(
            f"`{fceux_bin}` introuvable. Lance scripts/install_audio_deps.sh."
        )

    if out_trace is None:
        out_trace = rom_path.with_suffix(".apu.tsv")
    out_trace = Path(out_trace).resolve()
    out_trace.parent.mkdir(parents=True, exist_ok=True)
    if out_trace.exists():
        out_trace.unlink()

    env = {
        **os.environ,
        "QLNES_TRACE_OUT": str(out_trace),
        "QLNES_FRAMES": str(frames),
        "QT_QPA_PLATFORM": "offscreen",
        "SDL_AUDIODRIVER": "dummy",
    }
    cmd = [
        fceux_bin,
        "--no-config", "1",
        "--sound", "0",
        "--loadlua", str(LUA_SCRIPT),
        str(rom_path),
    ]
    # Marge généreuse : fceux offscreen tourne en gros à la vitesse réelle.
    # On laisse 2× la durée NTSC + 30s pour le boot/teardown.
    if timeout is None:
        timeout = (frames / 60.0) * 2.0 + 30.0
    proc = subprocess.run(
        cmd, env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    # fceux Qt segfaule parfois au cleanup (race Qt offscreen) MAIS le
    # fichier est déjà flushé. On accepte l'exit 139 si le fichier a du
    # contenu.
    if not out_trace.exists() or out_trace.stat().st_size == 0:
        log_tail = proc.stdout.decode(errors="replace")[-2000:]
        raise RuntimeError(
            f"fceux n'a pas produit de trace (exit {proc.returncode}).\n"
            f"--- log ---\n{log_tail}"
        )
    return out_trace


def parse_trace(path: Path) -> List[TraceEvent]:
    events: List[TraceEvent] = []
    with open(path, "r") as fh:
        for line in fh:
            if line.startswith("#") or not line.strip():
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) != 4:
                continue
            try:
                _frame = int(parts[0])
                cycle = int(parts[1])
                addr = int(parts[2], 16)
                val = int(parts[3], 16)
            except ValueError:
                continue
            events.append(TraceEvent(cycle=cycle, addr=addr, value=val))
    events.sort(key=lambda e: e.cycle)
    return events


# ---------------------------------------------------------------------------
# Étape 2 : synth APU 2A03
# ---------------------------------------------------------------------------


# Duty cycle waveforms — 8 phases, 1 = haut, 0 = bas.
# 4 modes encodés dans bits 6-7 de $4000/$4004 :
#   0 → 12.5%  (0 1 0 0 0 0 0 0)
#   1 → 25%    (0 1 1 0 0 0 0 0)
#   2 → 50%    (0 1 1 1 1 0 0 0)
#   3 → 25%inv (1 0 0 1 1 1 1 1)
DUTY_TABLE = (
    (0, 1, 0, 0, 0, 0, 0, 0),
    (0, 1, 1, 0, 0, 0, 0, 0),
    (0, 1, 1, 1, 1, 0, 0, 0),
    (1, 0, 0, 1, 1, 1, 1, 1),
)

# Triangle : 32 phases, valeur 0..15 (formes en V).
TRIANGLE_TABLE = (
    15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0,
    0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15,
)

# Noise period table (NTSC), indexé par bits 0-3 de $400E.
NOISE_PERIODS = (
    4, 8, 16, 32, 64, 96, 128, 160,
    202, 254, 380, 508, 762, 1016, 2034, 4068,
)

# Length counter table : 5 bits hauts de $4003/$4007/$400B/$400F.
LENGTH_TABLE = (
    10, 254, 20,  2, 40,  4, 80,  6,
    160,  8, 60, 10, 14, 12, 26, 14,
    12, 16, 24, 18, 48, 20, 96, 22,
    192, 24, 72, 26, 16, 28, 32, 30,
)

# Frame counter : tick à 240 Hz (= 1789773 / 240 ≈ 7457 cycles CPU).
# Mode 0 (4-step) : seq = quarter, half, quarter, half  → length à steps 1,3
# Mode 1 (5-step) : seq = quarter, half, quarter, half, none → length à steps 1,3
FRAME_COUNTER_PERIOD = 7457


@dataclass
class PulseState:
    enabled: bool = False
    duty: int = 0
    halt: bool = False     # bit 5 de $4000 : halt length counter ET loop envelope
    constant: bool = True  # bit 4 de $4000 : volume constant vs envelope
    volume: int = 0        # bits 0-3 : volume si constant, sinon période envelope
    timer: int = 0
    counter: float = 0.0
    phase: int = 0

    length: int = 0
    env_start: bool = False
    env_decay: int = 0     # 0..15
    env_div: int = 0       # divider current

    def write(self, reg_idx: int, val: int) -> None:
        if reg_idx == 0:
            self.duty = (val >> 6) & 0x03
            self.halt = bool(val & 0x20)
            self.constant = bool(val & 0x10)
            self.volume = val & 0x0F
        elif reg_idx == 1:
            pass  # sweep ignoré
        elif reg_idx == 2:
            self.timer = (self.timer & 0x700) | val
        elif reg_idx == 3:
            self.timer = (self.timer & 0xFF) | ((val & 0x07) << 8)
            self.phase = 0
            self.counter = 0.0
            if self.enabled:
                self.length = LENGTH_TABLE[(val >> 3) & 0x1F]
            self.env_start = True

    def set_enabled(self, on: bool) -> None:
        self.enabled = on
        if not on:
            self.length = 0

    def clock_length(self) -> None:
        if not self.halt and self.length > 0:
            self.length -= 1

    def clock_envelope(self) -> None:
        if self.env_start:
            self.env_start = False
            self.env_decay = 15
            self.env_div = self.volume
        elif self.env_div == 0:
            self.env_div = self.volume
            if self.env_decay > 0:
                self.env_decay -= 1
            elif self.halt:
                self.env_decay = 15
        else:
            self.env_div -= 1

    def output(self) -> int:
        if not self.enabled or self.length == 0 or self.timer < 8:
            return 0
        if not DUTY_TABLE[self.duty][self.phase]:
            return 0
        return self.volume if self.constant else self.env_decay

    def step(self, cycles: float) -> int:
        if not self.enabled or self.length == 0 or self.timer < 8:
            return 0
        period = (self.timer + 1) * 2
        self.counter -= cycles
        while self.counter <= 0:
            self.counter += period
            self.phase = (self.phase + 1) & 7
        return self.output()


@dataclass
class TriangleState:
    enabled: bool = False
    timer: int = 0
    counter: float = 0.0
    phase: int = 0
    halt: bool = False           # $4008 bit 7 (control flag)
    linear_reload: int = 0
    linear: int = 0
    linear_reload_flag: bool = False

    length: int = 0

    def write(self, reg_idx: int, val: int) -> None:
        if reg_idx == 0:
            self.halt = bool(val & 0x80)
            self.linear_reload = val & 0x7F
        elif reg_idx == 2:
            self.timer = (self.timer & 0x700) | val
        elif reg_idx == 3:
            self.timer = (self.timer & 0xFF) | ((val & 0x07) << 8)
            self.counter = 0.0
            if self.enabled:
                self.length = LENGTH_TABLE[(val >> 3) & 0x1F]
            self.linear_reload_flag = True

    def set_enabled(self, on: bool) -> None:
        self.enabled = on
        if not on:
            self.length = 0

    def clock_length(self) -> None:
        if not self.halt and self.length > 0:
            self.length -= 1

    def clock_linear(self) -> None:
        if self.linear_reload_flag:
            self.linear = self.linear_reload
        elif self.linear > 0:
            self.linear -= 1
        if not self.halt:
            self.linear_reload_flag = False

    def step(self, cycles: float) -> int:
        if (not self.enabled or self.timer < 2
                or self.length == 0 or self.linear == 0):
            return TRIANGLE_TABLE[self.phase]  # gel sur la phase courante
        period = self.timer + 1
        self.counter -= cycles
        while self.counter <= 0:
            self.counter += period
            self.phase = (self.phase + 1) & 31
        return TRIANGLE_TABLE[self.phase]


@dataclass
class NoiseState:
    enabled: bool = False
    halt: bool = False
    constant: bool = True
    volume: int = 0
    period: int = NOISE_PERIODS[0]
    mode: bool = False
    counter: float = 0.0
    lfsr: int = 1

    length: int = 0
    env_start: bool = False
    env_decay: int = 0
    env_div: int = 0

    def write(self, reg_idx: int, val: int) -> None:
        if reg_idx == 0:
            self.halt = bool(val & 0x20)
            self.constant = bool(val & 0x10)
            self.volume = val & 0x0F
        elif reg_idx == 2:
            self.mode = bool(val & 0x80)
            self.period = NOISE_PERIODS[val & 0x0F]
        elif reg_idx == 3:
            if self.enabled:
                self.length = LENGTH_TABLE[(val >> 3) & 0x1F]
            self.env_start = True

    def set_enabled(self, on: bool) -> None:
        self.enabled = on
        if not on:
            self.length = 0

    def clock_length(self) -> None:
        if not self.halt and self.length > 0:
            self.length -= 1

    def clock_envelope(self) -> None:
        if self.env_start:
            self.env_start = False
            self.env_decay = 15
            self.env_div = self.volume
        elif self.env_div == 0:
            self.env_div = self.volume
            if self.env_decay > 0:
                self.env_decay -= 1
            elif self.halt:
                self.env_decay = 15
        else:
            self.env_div -= 1

    def step(self, cycles: float) -> int:
        if not self.enabled or self.length == 0:
            return 0
        self.counter -= cycles
        while self.counter <= 0:
            self.counter += self.period
            bit_a = self.lfsr & 1
            bit_b = ((self.lfsr >> (6 if self.mode else 1)) & 1)
            feedback = bit_a ^ bit_b
            self.lfsr = (self.lfsr >> 1) | (feedback << 14)
        if self.lfsr & 1:
            return 0
        return self.volume if self.constant else self.env_decay


def mix_sample(p1: int, p2: int, tri: int, noise: int, dmc: int) -> float:
    """Mixeur non-linéaire 2A03 (formule nesdev). Sortie brute ∈ [0, ~1]."""
    pulse_sum = p1 + p2
    pulse_out = 95.88 / (8128.0 / pulse_sum + 100.0) if pulse_sum else 0.0
    tnd_denom = (tri / 8227.0) + (noise / 12241.0) + (dmc / 22638.0)
    tnd_out = 159.79 / (1.0 / tnd_denom + 100.0) if tnd_denom > 0 else 0.0
    return pulse_out + tnd_out


def synthesize_wav(
    events: List[TraceEvent],
    out_wav: Path,
    *,
    sample_rate: int = SAMPLE_RATE,
) -> Path:
    """Simule l'APU à `sample_rate` à partir d'une trace cycle-précise
    et écrit un WAV mono 16 bits."""
    if not events:
        raise ValueError("trace vide")

    p1 = PulseState()
    p2 = PulseState()
    tri = TriangleState()
    noise = NoiseState()
    dmc_raw = 0

    cpu_per_sample = NTSC_CPU_HZ / sample_rate

    end_cycle = events[-1].cycle
    n_samples = int(end_cycle / cpu_per_sample)
    out = bytearray(n_samples * 2)

    ev_idx = 0
    n_ev = len(events)
    cur_cycle = 0.0

    # Frame counter (4-step) à 240 Hz. Phase 0..3, length aux phases 1 et 3.
    fc_counter = 0.0
    fc_phase = 0

    # DC blocker (high-pass ≈ 30 Hz à 44.1 kHz)
    hp_x_prev = 0.0
    hp_y_prev = 0.0
    hp_R = 0.999
    gain = 1.6

    for s in range(n_samples):
        target = (s + 1) * cpu_per_sample
        while ev_idx < n_ev and events[ev_idx].cycle <= target:
            e = events[ev_idx]
            ev_idx += 1
            a = e.addr
            v = e.value
            if 0x4000 <= a <= 0x4003:
                p1.write(a - 0x4000, v)
            elif 0x4004 <= a <= 0x4007:
                p2.write(a - 0x4004, v)
            elif 0x4008 <= a <= 0x400B:
                tri.write(a - 0x4008, v)
            elif 0x400C <= a <= 0x400F:
                noise.write(a - 0x400C, v)
            elif a == 0x4011:
                dmc_raw = v & 0x7F
            elif a == 0x4015:
                p1.set_enabled(bool(v & 0x01))
                p2.set_enabled(bool(v & 0x02))
                tri.set_enabled(bool(v & 0x04))
                noise.set_enabled(bool(v & 0x08))

        delta = target - cur_cycle
        cur_cycle = target

        # Frame counter ticks à 240 Hz. delta ≈ 40.6 cycles, FC period
        # = 7457 → ≤ 1 tick par échantillon.
        fc_counter += delta
        while fc_counter >= FRAME_COUNTER_PERIOD:
            fc_counter -= FRAME_COUNTER_PERIOD
            p1.clock_envelope()
            p2.clock_envelope()
            noise.clock_envelope()
            tri.clock_linear()
            if fc_phase == 1 or fc_phase == 3:
                p1.clock_length()
                p2.clock_length()
                tri.clock_length()
                noise.clock_length()
            fc_phase = (fc_phase + 1) & 3

        v1 = p1.step(delta)
        v2 = p2.step(delta)
        vt = tri.step(delta)
        vn = noise.step(delta)
        raw = mix_sample(v1, v2, vt, vn, dmc_raw)
        # DC blocker : y[n] = x[n] - x[n-1] + R * y[n-1]
        hp_y = raw - hp_x_prev + hp_R * hp_y_prev
        hp_x_prev = raw
        hp_y_prev = hp_y
        sample = hp_y * gain
        if sample > 1.0:
            sample = 1.0
        elif sample < -1.0:
            sample = -1.0
        struct.pack_into("<h", out, s * 2, int(sample * 32767))

    out_wav = Path(out_wav)
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(bytes(out))
    return out_wav


# ---------------------------------------------------------------------------
# Étape 3 : encode MP3 via ffmpeg
# ---------------------------------------------------------------------------


def wav_to_mp3(wav_path: Path, mp3_path: Path, *, bitrate: str = "192k") -> Path:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("`ffmpeg` introuvable. Lance scripts/install_audio_deps.sh.")
    mp3_path = Path(mp3_path)
    mp3_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-i", str(wav_path), "-b:a", bitrate, str(mp3_path)],
        check=True,
    )
    return mp3_path


# ---------------------------------------------------------------------------
# Pipeline complet
# ---------------------------------------------------------------------------


@dataclass
class AudioResult:
    trace: Path
    wav: Path
    mp3: Optional[Path] = None
    n_events: int = 0
    duration_s: float = 0.0


def render_rom_audio(
    rom_path: Path,
    out: Path,
    *,
    frames: int = 600,
    sample_rate: int = SAMPLE_RATE,
    keep_intermediate: bool = False,
) -> AudioResult:
    """Pipeline complet : ROM → trace → WAV → (MP3 si .mp3)."""
    out = Path(out)
    rom_path = Path(rom_path)

    trace_path = rom_path.with_suffix(".apu.tsv")
    record_apu_trace(rom_path, frames=frames, out_trace=trace_path)
    events = parse_trace(trace_path)

    wav_path = out.with_suffix(".wav") if out.suffix.lower() == ".mp3" else out
    synthesize_wav(events, wav_path, sample_rate=sample_rate)

    mp3_path: Optional[Path] = None
    if out.suffix.lower() == ".mp3":
        mp3_path = wav_to_mp3(wav_path, out)
        if not keep_intermediate:
            wav_path.unlink(missing_ok=True)

    if not keep_intermediate:
        trace_path.unlink(missing_ok=True)

    duration = events[-1].cycle / NTSC_CPU_HZ if events else 0.0
    return AudioResult(
        trace=trace_path, wav=wav_path, mp3=mp3_path,
        n_events=len(events), duration_s=duration,
    )
