"""What every Airdress layer must credit, in plain text.

Mirrors the page (`services/maps-front/app/app.js`, the attribution
control and the boundaries source) so a QGIS map credits exactly what the
page does. The register check compares these constants with the page.
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

BY_KIND = {"basemap": BASEMAP, "boundaries": BOUNDARIES}


def line(kinds: "list[str]") -> str:
    """One attribution line for the layers in `kinds`, de-duplicated, in a
    stable order, ending with where the licences are."""
    parts: "list[str]" = []
    for kind in ("basemap", "boundaries"):
        if kind in kinds:
            for item in BY_KIND[kind]:
                if item not in parts:
                    parts.append(item)
    if not parts:
        return ""
    host = config.LICENSES_URL.split("://", 1)[1]
    return " · ".join(parts) + " — " + host
