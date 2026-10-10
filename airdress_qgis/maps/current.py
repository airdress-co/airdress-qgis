"""`/current.json`: the one place layer URLs come from.

The front serves only the archive this names, so a URL built from a guessed
or remembered snapshot would 404 the day the archive moves. Every layer is
(re)resolved through here.
"""

from __future__ import annotations

from dataclasses import dataclass

from .. import config

KINDS = ("basemap", "boundaries")


@dataclass
class Current:
    style: str  # absolute URL
    snapshot: str
    tiles: dict[str, str]  # kind -> absolute XYZ template

    def template(self, kind: str) -> str | None:
        return self.tiles.get(kind)


class NoTileRoute(Exception):
    """The front answered, but names no XYZ route: an older front."""


def parse(body: dict, origin: str = config.MAPS_ORIGIN) -> Current:
    tiles = body.get("tiles")
    if not isinstance(tiles, dict) or not tiles:
        raise NoTileRoute()
    absolute = {k: _absolute(v, origin) for k, v in tiles.items() if k in KINDS and isinstance(v, str)}
    if "basemap" not in absolute:
        raise NoTileRoute()
    return Current(style=_absolute(body["style"], origin), snapshot=str(body.get("snapshot", "")), tiles=absolute)


def _absolute(path: str, origin: str) -> str:
    if path.startswith("https://"):
        if not path.startswith(origin + "/"):
            raise ValueError("a /current.json URL points away from the map service")
        return path
    if not path.startswith("/"):
        raise ValueError("unexpected relative URL in /current.json")
    return origin + path
