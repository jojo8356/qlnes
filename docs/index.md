# Documentation qlnes

qlnes est un outil Python pour analyser, annoter, recompiler et valider des
ROMs NES. La documentation longue est volontairement separee du README pour
laisser la page d'accueil concentrée sur l'installation et les commandes.

## Documents

- [Audio NES, NSF et MP3](audio-nes-nsf-mp3.md) : fonctionnement de l'audio
  NES, limites de l'extraction directe, flux generique ROM vers NSF, et flux
  specifique Super Mario Bros.

## Documentation API locale

La documentation HTML peut etre generee sans installer d'outil externe :

```bash
mkdir -p docs/api
cd docs/api
../../.venv/bin/python -m pydoc -w qlnes.smb_nsf
```

Le fichier HTML genere est volontairement ignore si un jour on decide de ne
pas versionner la doc construite. Aujourd'hui, il sert surtout a verifier que
les docstrings Python sont exploitables par un generateur.
