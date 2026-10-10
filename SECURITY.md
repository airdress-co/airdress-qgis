# Security

Report vulnerabilities to **security@airdress.co**, not in public issues.
We acknowledge within three working days.

What the plugin promises, and what a report against it looks like:

- No token is written into a project, a layer source, QGIS settings or the
  message log.
- A token is sent only over https, and only to the exact hosts it is for.
- The refresh token is stored only encrypted, in QGIS's auth database.
