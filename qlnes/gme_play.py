"""Joue un fichier NSF (ou autre format Game Music Emu) → WAV via libgme.

Wrapper ctypes minimal autour de libgme.so.0 (paquet Debian `libgme0`).
On contourne ainsi mpv/VLC qui sur certaines distros (Debian 12 par défaut)
sont compilés sans support GME.

API utilisée (déclarations C de gme.h) :
    Music_Emu* gme_open_file(const char*, Music_Emu**, int sample_rate)
    gme_err_t  gme_start_track(Music_Emu*, int track)
    gme_err_t  gme_play(Music_Emu*, int sample_count, short* buf)
    void       gme_set_fade(Music_Emu*, int start_msec)
    int        gme_track_count(Music_Emu*)
    void       gme_delete(Music_Emu*)
"""

from __future__ import annotations

import ctypes
import wave
from ctypes.util import find_library
from pathlib import Path

_lib_handle = None


def _load() -> ctypes.CDLL:
    global _lib_handle
    if _lib_handle is not None:
        return _lib_handle
    candidates = [
        find_library("gme"),
        "libgme.so.0",
        "libgme.so",
        "/usr/lib/x86_64-linux-gnu/libgme.so.0",
    ]
    last_err: OSError | None = None
    for name in candidates:
        if not name:
            continue
        try:
            lib = ctypes.CDLL(name)
        except OSError as e:
            last_err = e
            continue
        # Signatures
        lib.gme_open_file.argtypes = [
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_int,
        ]
        lib.gme_open_file.restype = ctypes.c_char_p  # NULL si OK, sinon msg
        lib.gme_start_track.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.gme_start_track.restype = ctypes.c_char_p
        lib.gme_play.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_short)]
        lib.gme_play.restype = ctypes.c_char_p
        lib.gme_set_fade.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.gme_set_fade.restype = None
        lib.gme_track_count.argtypes = [ctypes.c_void_p]
        lib.gme_track_count.restype = ctypes.c_int
        lib.gme_track_ended.argtypes = [ctypes.c_void_p]
        lib.gme_track_ended.restype = ctypes.c_int
        lib.gme_delete.argtypes = [ctypes.c_void_p]
        lib.gme_delete.restype = None
        _lib_handle = lib
        return lib
    raise RuntimeError(
        f"libgme0 introuvable. Installe-la avec : sudo apt install libgme0\n"
        f"(dernière erreur : {last_err})"
    )


def _check(err: bytes | None, context: str) -> None:
    if err:
        raise RuntimeError(f"libgme {context}: {err.decode(errors='replace')}")


def render_nsf(
    nsf_path: Path,
    wav_path: Path,
    *,
    track: int = 0,
    duration_s: float = 60.0,
    fade_s: float = 2.0,
    sample_rate: int = 44100,
) -> Path:
    """Décode un NSF/VGM/SPC/etc. via libgme et écrit un WAV stéréo 16 bits.
    `track` est 0-based (track 0 = premier morceau du fichier).
    """
    lib = _load()
    nsf_path = Path(nsf_path)
    if not nsf_path.exists():
        raise FileNotFoundError(nsf_path)

    emu = ctypes.c_void_p()
    err = lib.gme_open_file(str(nsf_path).encode(), ctypes.byref(emu), sample_rate)
    _check(err, "open_file")
    try:
        n_tracks = lib.gme_track_count(emu)
        if track < 0 or track >= n_tracks:
            raise ValueError(f"track {track} hors range (NSF contient {n_tracks} morceaux)")
        # gme_set_fade attend un timestamp en millisecondes où le fade out
        # commence. La piste s'éteint sur ~8 s après ce point.
        fade_start_ms = int((duration_s - fade_s) * 1000)
        lib.gme_set_fade(emu, fade_start_ms)
        err = lib.gme_start_track(emu, track)
        _check(err, "start_track")

        chunk_frames = 4096  # frames stéréo par appel
        chunk_samples = chunk_frames * 2
        buf = (ctypes.c_short * chunk_samples)()

        total_frames = int(duration_s * sample_rate)
        written = 0

        wav_path = Path(wav_path)
        wav_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(wav_path), "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(sample_rate)
            while written < total_frames:
                want = min(chunk_frames, total_frames - written)
                err = lib.gme_play(emu, want * 2, buf)
                _check(err, "play")
                w.writeframes(bytes(buf[: want * 2]))
                written += want
        return wav_path
    finally:
        lib.gme_delete(emu)
