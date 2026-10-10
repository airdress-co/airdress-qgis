"""One person, one query: the request and result shapes for /geocode and
/reverse. No batch path exists anywhere in the plugin, by design — the
geocoding licence covers name, address and point for one query at a time.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

MIN_CHARS = 3
DEBOUNCE_MS = 300
LIMIT = 8

_ADDRESS_ORDER = ("street", "housenumber", "postcode", "city", "district", "state", "country")


@dataclass
class Hit:
    name: str
    address: str
    lon: float
    lat: float
    layer: str
    credit: str


def zoom_for_width(width_degrees: float) -> int:
    """A web-map zoom level for a view this many degrees wide, clamped to
    what /geocode accepts."""
    if width_degrees <= 0:
        return 12
    return max(3, min(18, round(math.log2(360.0 / width_degrees) + 1)))


def forward_body(text: str, focus: tuple[float, float] | None, zoom: int | None, lang: str) -> dict | None:
    text = text.strip()
    if len(text) < MIN_CHARS:
        return None
    body = {"text": text, "autocomplete": True, "limit": LIMIT}
    if focus is not None:
        body["focus"] = [round(focus[0], 2), round(focus[1], 2)]
    if zoom is not None:
        body["zoom"] = zoom
    if lang in ("en", "de", "fr"):
        body["lang"] = lang
    return body


def reverse_body(lon: float, lat: float) -> dict:
    return {"point": [lon, lat], "limit": 1}


def format_address(address) -> str:
    if not isinstance(address, dict):
        return ""
    street = " ".join(str(address[k]) for k in ("street", "housenumber") if address.get(k))
    rest = [str(address[k]) for k in _ADDRESS_ORDER[2:] if address.get(k)]
    parts = ([street] if street else []) + rest
    seen: list[str] = []
    for part in parts:
        if part not in seen:
            seen.append(part)
    return ", ".join(seen)


def hits(body: dict | None) -> list[Hit]:
    out = []
    for r in (body or {}).get("results", []) or []:
        point = r.get("point")
        if not (isinstance(point, list) and len(point) == 2):
            continue
        out.append(
            Hit(
                name=str(r.get("name") or ""),
                address=format_address(r.get("address")),
                lon=float(point[0]),
                lat=float(point[1]),
                layer=str(r.get("layer") or ""),
                credit=str(r.get("credit") or ""),
            )
        )
    return out


def scale_for(layer: str) -> float:
    return {"country": 10_000_000, "region": 2_000_000, "county": 500_000, "locality": 100_000}.get(layer, 5_000)
