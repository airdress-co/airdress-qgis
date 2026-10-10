"""The published MapLibre style, made into one QGIS can convert.

QGIS reads no PMTiles, so each vector source is pointed at the front's XYZ
route; relative sprite and glyph URLs are made absolute; sources QGIS will
not draw in this version (terrain, imagery) are dropped with the layers that
use them. The page's style stays the only style: this is a rewrite, never a
second copy.
"""

from __future__ import annotations

import copy

from .. import config

# The style's own vector source for the basemap archive.
BASEMAP_SOURCE = "protomaps"
BASEMAP_MAX_ZOOM = 15


def for_qgis(style: dict, basemap_template: str, origin: str = config.MAPS_ORIGIN) -> dict:
    out = copy.deepcopy(style)
    kept = {}
    for name, source in (style.get("sources") or {}).items():
        if source.get("type") != "vector":
            continue
        rewritten = {k: v for k, v in source.items() if k != "url"}
        rewritten["tiles"] = [basemap_template]
        rewritten.setdefault("minzoom", 0)
        rewritten.setdefault("maxzoom", BASEMAP_MAX_ZOOM)
        kept[name] = rewritten
    out["sources"] = kept
    out["layers"] = [
        layer for layer in style.get("layers", []) if layer.get("type") == "background" or layer.get("source") in kept
    ]
    for key in ("sprite", "glyphs"):
        value = out.get(key)
        if isinstance(value, str) and value.startswith("/"):
            out[key] = origin + value
    return out


def sprite_urls(style: dict) -> list[tuple[str, str]]:
    """(json, png) URL pairs, 2x first: QGIS scales down better than up."""
    base: str | None = style.get("sprite") if isinstance(style.get("sprite"), str) else None
    if not base:
        return []
    return [(base + "@2x.json", base + "@2x.png"), (base + ".json", base + ".png")]


def source_attributions(style: dict) -> list[str]:
    """Plain-text attributions from the style's sources (the HTML stripped)."""
    import re

    found = []
    for source in (style.get("sources") or {}).values():
        text = source.get("attribution")
        if isinstance(text, str):
            plain = re.sub(r"<[^>]+>", "", text).strip()
            if plain and plain not in found:
                found.append(plain)
    return found
