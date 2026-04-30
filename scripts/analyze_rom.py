#!/usr/bin/env python3
"""Wrapper CLI standalone — équivalent à `python -m qlnes`.

Usage : python scripts/analyze_rom.py <rom.nes> [--output STACK.md]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qlnes.cli import main

if __name__ == "__main__":
    sys.exit(main())
