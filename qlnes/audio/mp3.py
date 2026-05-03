"""LAME MP3 encoding via the `lameenc` Python wheel.

Architecture step 4 / ADR-04. Wraps `lameenc.Encoder` with the project's
locked encoding profile (mono, 44.1 kHz, VBR V2). Encoder version is read
once at module load via importlib.metadata; mismatch with EXPECTED_VERSION
emits a `mp3_encoder_version` warning (M-1 from readiness pass-2).

PCM input must be int16 LE mono at 44_100 Hz — exactly the shape the APU
emulator + Mixer produces. No resampling here.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

# Architecture step 4 originally pinned 1.7.0; PyPI's lowest available is 1.8.0.
# Benchmarked across 1.8.0 / 1.8.1 / 1.8.2 on silence + sine fixtures: all three
# produce byte-identical MP3 for the same PCM input. Pin relaxed to the 1.8.x
# range; cross-1.x-major drift would still trigger the warning.
EXPECTED_VERSION = "1.8.x"
EXPECTED_VERSION_PREFIX = "1.8."


def _read_installed_version() -> str | None:
    try:
        return version("lameenc")
    except PackageNotFoundError:
        return None


INSTALLED_VERSION: str | None = _read_installed_version()


class Mp3Encoder:
    """Encode int16 LE mono PCM to MP3 (LAME VBR V2)."""

    SAMPLE_RATE = 44_100
    CHANNELS = 1
    VBR_QUALITY = 2  # LAME -V 2 (preset "extreme" / ~190 kbps avg)

    def __init__(self) -> None:
        if INSTALLED_VERSION is None:
            from ..io.errors import QlnesError

            raise QlnesError(
                "internal_error",
                "lameenc is not installed",
                hint="Run scripts/install_audio_deps.sh, or pass --format wav.",
                extra={"detail": "missing_dependency", "dep": "lameenc"},
            )
        # Lazy import so the module is loadable for tests that mock around it.
        import lameenc

        self._enc = lameenc.Encoder()
        self._enc.set_channels(self.CHANNELS)
        self._enc.set_in_sample_rate(self.SAMPLE_RATE)
        self._enc.set_out_sample_rate(self.SAMPLE_RATE)
        # LAME VBR modes: 0=off (CBR), 2=vbr_rh, 3=vbr_abr, 4=vbr_mtrh.
        # mtrh is the modern recommended VBR; mode 1 is reserved/invalid.
        self._enc.set_vbr(4)
        self._enc.set_vbr_quality(self.VBR_QUALITY)

    def encode(self, pcm_le16: bytes) -> bytes:
        """Encode the full PCM buffer. Returns the complete MP3 byte stream."""
        if len(pcm_le16) % 2 != 0:
            raise ValueError(f"PCM length must be a multiple of 2 bytes, got {len(pcm_le16)}")
        encoded = self._enc.encode(pcm_le16)
        flushed = self._enc.flush()
        return bytes(encoded) + bytes(flushed)


def is_pinned_version() -> bool:
    """True iff the installed lameenc is in the byte-equivalence-verified range.

    The 1.8.x line is the validated band; cross-1.x-major drift triggers the
    `mp3_encoder_version` warning (M-1).
    """
    if INSTALLED_VERSION is None:
        return False
    return INSTALLED_VERSION.startswith(EXPECTED_VERSION_PREFIX)
