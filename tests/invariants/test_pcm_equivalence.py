"""PCM sample-equivalence to FCEUX — the qlnes correctness commitment (FR11 tier-1).

Each parametrization is one (ROM  x song-index) pair from `corpus/manifest.toml`.
For each, render via qlnes and compare PCM hash to the FCEUX reference.

A.1 ships an empty corpus — the manifest doesn't yet exist (B.3 lands it),
and even when it does, the per-ROM tests skip locally if the user doesn't
have the corresponding ROM file in `corpus/roms/<sha>.nes` (IP discipline:
hashes only in the repo, ROMs are user-supplied per architecture step 11).

Until the corpus exists this file collects 0 tests. That's intentional —
the harness IS the contract: when Johan adds the manifest + a ROM, sample-
equivalence checking activates with no test-code change.
"""

from __future__ import annotations

import shutil
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_MANIFEST = REPO_ROOT / "corpus" / "manifest.toml"
CORPUS_ROMS_DIR = REPO_ROOT / "corpus" / "roms"


def _load_corpus() -> list[dict]:
    """Read corpus/manifest.toml. Empty list if absent (A.1 reality)."""
    if not CORPUS_MANIFEST.exists():
        return []
    with CORPUS_MANIFEST.open("rb") as f:
        doc = tomllib.load(f)
    return list(doc.get("rom", []))


CORPUS_ENTRIES = _load_corpus()


pytestmark = pytest.mark.skipif(
    shutil.which("fceux") is None,
    reason="fceux not on PATH",
)


@pytest.mark.parametrize(
    "rom_entry",
    CORPUS_ENTRIES,
    ids=lambda e: f"{e.get('engine', '?')}-{e.get('sha256', '?')[:8]}",
)
def test_pcm_byte_equivalent_to_fceux(rom_entry):
    """For each manifest entry, render qlnes PCM + FCEUX reference, compare hash.

    Skips if the contributor doesn't have the actual ROM file locally.
    """
    from qlnes.audio.renderer import render_rom_audio_v2
    from qlnes.oracle import FceuxOracle

    sha = rom_entry["sha256"]
    rom_path = CORPUS_ROMS_DIR / f"{sha}.nes"
    if not rom_path.exists():
        pytest.skip(f"corpus ROM not present locally: {sha}")

    # Capture FCEUX reference PCM for this ROM.
    oracle = FceuxOracle()
    ref_pcm = oracle.reference_pcm(rom_path, frames=rom_entry.get("frames", 600))

    # Render via qlnes pipeline.
    out_dir = Path(f"/tmp/qlnes-eq-{sha[:8]}")
    out_dir.mkdir(exist_ok=True)
    result = render_rom_audio_v2(
        rom_path,
        out_dir,
        fmt="wav",
        frames=rom_entry.get("frames", 600),
        force=True,
    )

    # Strip RIFF header from qlnes WAV → raw PCM.
    import wave as _wave

    with _wave.open(str(result.output_paths[0]), "rb") as wf:
        qlnes_pcm = wf.readframes(wf.getnframes())

    # Sample-equivalence assertion. A.1 ships this as the canonical claim:
    # qlnes PCM == FCEUX PCM, byte-for-byte. Any divergence frame is reported.
    if qlnes_pcm != ref_pcm:
        # Find first mismatch frame (per UX §6.3 equivalence_failed payload).
        first_diff = next(
            (
                i // 2
                for i in range(0, min(len(qlnes_pcm), len(ref_pcm)), 2)
                if qlnes_pcm[i : i + 2] != ref_pcm[i : i + 2]
            ),
            None,
        )
        pytest.fail(
            f"PCM diverges at sample {first_diff} "
            f"(qlnes={len(qlnes_pcm)} bytes, fceux={len(ref_pcm)} bytes)"
        )


def test_corpus_manifest_is_documented_when_absent():
    """A.1 ships no corpus. This test pins that as a deliberate state until B.3."""
    if CORPUS_ENTRIES:
        pytest.skip("corpus manifest is populated; this guard test is moot")
    assert not CORPUS_MANIFEST.exists(), (
        "corpus/manifest.toml exists but parsing yielded 0 entries — investigate"
    )
