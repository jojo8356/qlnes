---
project_name: 'qlnes'
user_name: 'Johan'
date: '2026-05-03'
sections_completed: ['technology_stack']
existing_patterns_found: 0
---

# Project Context for AI Agents

_This file contains critical rules and patterns that AI agents must follow when implementing code in this project. Focus on unobvious details that agents might otherwise miss._

---

## Technology Stack & Versions

**Language & runtime**
- Python 3.11+ (local dev: 3.11.2; CI: 3.13)
- 6502 assembler output (target ISA, not implementation language)
- C (vendored `vendor/QL6502-src/` — disassembler binary, compiled to `bin/ql6502` via `gcc -O2`)

**Python dependencies (`requirements.txt` — minimal, pinned by floor only)**
- `typer>=0.12` — CLI framework
- `py65>=1.2` — 6502 reassembler (round-trip)
- `cynes>=0.1.2` — headless NES emulator (dynamic discovery; **mapper 0 only** in current runner)
- `Pillow>=10` — PNG export of CHR tiles

**No** `pyproject.toml`, `setup.py`, or `setup.cfg`. The project is run as a module (`python -m qlnes`) — there is no `pip install .` flow.

**Tooling configs absent:** no `.ruff.toml`, `.flake8`, `.editorconfig`, `mypy.ini`. Style is informal but consistent (see "Critical Implementation Rules" below).

**CI:** `.github/workflows/deptry.yml` — weekly `deptry` audit of unused/missing deps only. No test or lint workflow runs in CI.

## Critical Implementation Rules

_To be filled in step 2 (collaborative discovery with the user)._
