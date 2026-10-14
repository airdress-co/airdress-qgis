"""`/current.json`: the one place layer URLs come from.

The front serves only the archive this names, so a URL built from a guessed
or remembered snapshot would 404 the day the archive moves. Every layer is
(re)resolved through here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .. import config

KINDS = ("basemap", "boundaries", "imagery")

# `/tiles/aerial/<id>/{z}/{x}/{y}`: the archive id is the path's fourth part.
_AERIAL_ID = re.compile(r"/tiles/aerial/([a-z0-9-]{1,64})/")
# An archive's vintage at the end of its id (`-2024`, `-2026-09`): two
# archives that differ only there are the same place, flown again.
_VINTAGE = re.compile(r"(-[0-9]{4})(-[0-9]{2})?$")


@dataclass
class Aerial:
    """One aerial archive, as /current.json lists it."""

    id: str
    tiles: str  # absolute XYZ template
    bounds: tuple[float, float, float, float]  # west, south, east, north
    minzoom: int
    maxzoom: int
    years: str
    line: str  # the provider's own words
    line_url: str | None
    licence: str
    licence_url: str
    changed: bool

    @property
    def place(self) -> str:
        """`aerial-de-by-munich-2024` → `Munich`: the words between the
        country and region codes and the vintage."""
        words = _VINTAGE.sub("", self.id.removeprefix("aerial-")).split("-")
        while len(words) > 1 and len(words[0]) == 2:
            words = words[1:]
        return " ".join(w.capitalize() for w in words) or self.id

    @property
    def family(self) -> str:
        return family_of(self.id)


def family_of(archive_id: str) -> str:
    return _VINTAGE.sub("", archive_id)


@dataclass
class Current:
    style: str  # absolute URL
    snapshot: str
    tiles: dict[str, str]  # kind -> absolute XYZ template
    aerial: list[Aerial] = field(default_factory=list)

    def template(self, kind: str) -> str | None:
        return self.tiles.get(kind)

    def aerial_for(self, archive_id: str) -> Aerial | None:
        """The archive itself, else today's archive of the same place."""
        for a in self.aerial:
            if a.id == archive_id:
                return a
        family = family_of(archive_id)
        same = [a for a in self.aerial if a.family == family]
        return same[0] if same else None


class NoTileRoute(Exception):
    """The front answered, but names no XYZ route: an older front."""


def parse(body: dict, origin: str = config.MAPS_ORIGIN) -> Current:
    tiles = body.get("tiles")
    if not isinstance(tiles, dict) or not tiles:
        raise NoTileRoute()
    absolute = {k: _absolute(v, origin) for k, v in tiles.items() if k in KINDS and isinstance(v, str)}
    if "basemap" not in absolute:
        raise NoTileRoute()
    return Current(
        style=_absolute(body["style"], origin),
        snapshot=str(body.get("snapshot", "")),
        tiles=absolute,
        aerial=_aerial(body.get("aerial"), origin),
    )


def _aerial(entries, origin: str) -> list[Aerial]:
    """The aerial archives a client may draw: each with its template and its
    credit in words. An entry without either is left out, so an archive is
    never drawn uncredited."""
    out: list[Aerial] = []
    if not isinstance(entries, list):
        return out
    for e in entries:
        if not isinstance(e, dict):
            continue
        tiles, credit, bounds = e.get("tiles"), e.get("attribution"), e.get("bounds")
        if not isinstance(tiles, str) or not isinstance(credit, dict) or not isinstance(credit.get("line"), str):
            continue
        found = _AERIAL_ID.search(tiles)
        if found is None or not isinstance(bounds, list) or len(bounds) != 4:
            continue
        try:
            out.append(
                Aerial(
                    id=found.group(1),
                    tiles=_absolute(tiles, origin),
                    bounds=tuple(float(b) for b in bounds),
                    minzoom=int(e.get("minzoom", 0)),
                    maxzoom=int(e.get("maxzoom", 19)),
                    years=str(e.get("years") or e.get("year") or ""),
                    line=credit["line"],
                    line_url=credit.get("lineUrl") if isinstance(credit.get("lineUrl"), str) else None,
                    licence=str(credit.get("licence") or ""),
                    licence_url=str(credit.get("licenceUrl") or ""),
                    changed=bool(credit.get("changed")),
                )
            )
        except (TypeError, ValueError):
            continue
    return out


def _absolute(path: str, origin: str) -> str:
    if path.startswith("https://"):
        if not path.startswith(origin + "/"):
            raise ValueError("a /current.json URL points away from the map service")
        return path
    if not path.startswith("/"):
        raise ValueError("unexpected relative URL in /current.json")
    return origin + path
