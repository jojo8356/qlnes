#!/usr/bin/env bash
# Installe fceux + ffmpeg, requis par la commande `qlnes audio`.
# fceux : émulateur NES headless capable de produire du son (toutes les ROMs / mappers).
# ffmpeg : encode WAV → MP3.

set -euo pipefail

need=()
for bin in fceux ffmpeg; do
    if ! command -v "$bin" >/dev/null 2>&1; then
        need+=("$bin")
    else
        echo "✓ $bin déjà installé : $(command -v "$bin")"
    fi
done

if [ "${#need[@]}" -eq 0 ]; then
    echo "Tout est déjà là."
    exit 0
fi

if ! command -v apt-get >/dev/null 2>&1; then
    echo "Erreur : ce script suppose Debian/Ubuntu (apt-get introuvable)." >&2
    echo "Installe manuellement : ${need[*]}" >&2
    exit 1
fi

echo "→ apt update + install ${need[*]} (sudo demandera ton mot de passe)"
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends "${need[@]}" xvfb

echo
for bin in "${need[@]}"; do
    if command -v "$bin" >/dev/null 2>&1; then
        echo "✓ $bin → $(command -v "$bin")"
    else
        echo "✗ $bin non installé après apt — vérifie le log ci-dessus" >&2
        exit 1
    fi
done
