#!/usr/bin/env python3
"""Refuse direct PyQt5/PyQt6 imports: everything goes through qgis.PyQt, so
one source runs on QGIS 3 (Qt5) and QGIS 4 (Qt6)."""

import pathlib
import re
import sys

PATTERN = re.compile(r"^\s*(from|import)\s+PyQt[56]\b", re.MULTILINE)
bad = [
    str(p)
    for p in pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "airdress_qgis").rglob("*.py")
    if PATTERN.search(p.read_text(encoding="utf-8"))
]
if bad:
    print("import Qt through qgis.PyQt, not PyQt5/PyQt6 directly:", *bad, sep="\n  ")
    sys.exit(1)
