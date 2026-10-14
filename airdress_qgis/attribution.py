"""What every Airdress layer must credit, in plain text.

Mirrors the page (`services/maps-front/app/app.js`, the attribution
control and the boundaries source) so a QGIS map credits exactly what the
page does. The register check compares these constants with the page. The
aerial credits are not constants: each archive's comes from /current.json,
in its provider's words, and is put together here the way the page does.
"""

from __future__ import annotations

from . import config

# The basemap style's own source credit, then the page's customAttribution.
BASEMAP = [
    "© OpenStreetMap",
    "Overture Maps Foundation",
    "GeoNames",
    "Wikidata",
    "© ESA WorldCover",
    "Protomaps",
]

BOUNDARIES = ["Boundaries: Overture Maps Foundation, © OpenStreetMap"]

# The Satellite view's source, as the page's raster source credits it.
SATELLITE = ["Contains modified Copernicus Sentinel data"]

BY_KIND = {"basemap": BASEMAP, "boundaries": BOUNDARIES, "imagery": SATELLITE}

# The page's two words around an aerial credit (app_en.arb, app_de.arb).
_AERIAL_WORDS = {"en": ("Imagery", "changed"), "de": ("Luftbild", "verändert")}


def aerial(entry, locale: str = "en") -> str:
    """`Imagery: <provider's words> (<licence>), <years>, changed`, as the
    page's map line has it: the licence only where it must be named, the
    years once (a provider's words may already end with them), and the
    change note only where the licence asks for one."""
    lang = "de" if (locale or "").lower().startswith("de") else "en"
    label, changed = _AERIAL_WORDS[lang]
    text = f"{label}: {entry.line}"
    if entry.licence:
        text += f" ({entry.licence})"
    if entry.years and not entry.line.endswith(entry.years):
        text += f", {entry.years}"
    if entry.changed:
        text += f", {changed}"
    return text


def line(kinds: list[str], extra: list[str] | None = None) -> str:
    """One attribution line for the layers in `kinds`, plus each of `extra`
    (the aerial layers' own credits), de-duplicated, in a stable order,
    ending with where the licences are."""
    parts: list[str] = []
    for kind in ("basemap", "boundaries", "imagery"):
        if kind in kinds:
            for item in BY_KIND[kind]:
                if item not in parts:
                    parts.append(item)
    for item in extra or []:
        if item and item not in parts:
            parts.append(item)
    if not parts:
        return ""
    host = config.LICENSES_URL.split("://", 1)[1]
    return " · ".join(parts) + " — " + host
