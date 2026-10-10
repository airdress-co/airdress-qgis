# Contributing

- Tests first: a behaviour change comes with a test that failed before it.
- Import Qt only through `qgis.PyQt` (`scripts/check-qt-imports.py`).
- No dependency outside the standard library and what QGIS ships.
- Commits are conventional (`feat:`, `fix:`, `docs:` …); pull requests are
  rebased, never merged.
