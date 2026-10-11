# Airdress for QGIS

The [Airdress map](https://maps.airdress.co) in QGIS: a styled vector
basemap, county and city boundaries, and place search. You sign in with your
Airdress account, and no API key goes into any project file.

Coverage is detailed in Europe and North America and an overview elsewhere.
You need an Airdress account that is past the waitlist.

- **Sign in** opens your browser. Where the browser cannot reach QGIS (a
  remote desktop, a locked-down machine), use the code shown instead.
- **Add basemap / Add boundaries** from the Airdress toolbar button or the
  *Airdress* entry in the Browser panel.
- **Search** in the locator bar (`Ctrl+K`) with the prefix `air`, e.g.
  `air munich`. One query at a time; there is deliberately no batch
  geocoding.
- **Attribution** is drawn on the map and added to print layouts with
  *Airdress → Add attribution to layout*. Credits and licences:
  <https://maps.airdress.co/licenses>.

Needs QGIS 3.40 or newer, including QGIS 4.

## Privacy

The plugin sends nothing but the requests the map needs. Your sign-in is
kept in QGIS's encrypted authentication database (QGIS asks you to set a
master password the first time); decline, and you stay signed in for the
session only. *Sign out* revokes the session on your account.

## Development

```sh
QT_QPA_PLATFORM=offscreen python3 -m pytest -q tests   # needs QGIS's Python bindings
python3 scripts/check-qt-imports.py
ln -s "$PWD/airdress_qgis" ~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/airdress_qgis
```

`AIRDRESS_QGIS_MAPS_ORIGIN` and `AIRDRESS_QGIS_HUB_ISSUER` point the
plugin at a test service; nothing else can redirect it.

Releases: `scripts/build-zip.sh vX.Y.Z` from a signed tag.

## Licence

GPL-2.0-or-later (see `LICENSE`), as plugins built on the QGIS Python API
are.
