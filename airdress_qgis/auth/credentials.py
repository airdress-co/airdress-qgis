"""Which token goes to which host. Exactly one place answers that.

The request preprocessor runs on whatever thread QGIS makes a request
from, so the map is guarded by a lock and holds only finished strings:
nothing here ever does network I/O.
"""

from __future__ import annotations

import threading
from urllib.parse import urlsplit


class Credentials:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_host: dict[str, str] = {}

    def set(self, origin: str, token: str) -> None:
        host = _host(origin)
        with self._lock:
            self._by_host[host] = token

    def remove(self, origin: str) -> None:
        with self._lock:
            self._by_host.pop(_host(origin), None)

    def clear(self) -> None:
        with self._lock:
            self._by_host.clear()

    def for_url(self, url: str) -> str | None:
        """The token for this URL's host — https only, exact host match, no
        suffix rule, no port other than 443."""
        parts = urlsplit(url)
        if parts.scheme != "https":
            return None
        if parts.port not in (None, 443):
            return None
        host = (parts.hostname or "").lower()
        with self._lock:
            return self._by_host.get(host)

    def hosts(self) -> list[str]:
        with self._lock:
            return sorted(self._by_host)


def _host(origin: str) -> str:
    parts = urlsplit(origin)
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError("credentials are only ever held for an https origin")
    return parts.hostname.lower()
