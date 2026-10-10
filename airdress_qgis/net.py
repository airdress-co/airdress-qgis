"""QGIS's network stack, from the plugin's side.

* `http_post` / `http_get` — blocking JSON calls through
  QgsBlockingNetworkRequest, so QGIS's proxy and certificate settings apply.
* `Attacher` — the one request preprocessor: it adds the bearer for the
  exact hosts `Credentials` holds, and never overwrites a header someone else
  set. It covers QGIS's own credential-less style and sprite fetches too.
* `Watcher` — a reply preprocessor that reports refusals from our hosts to
  the main thread. It reads the status only, never a body.
"""

from __future__ import annotations

import json
from typing import Optional
from urllib.parse import urlencode, urlsplit

from qgis.core import QgsBlockingNetworkRequest, QgsNetworkAccessManager
from qgis.PyQt.QtCore import QByteArray, QBuffer, QIODevice, QObject, QUrl, pyqtSignal
from qgis.PyQt.QtNetwork import QNetworkReply, QNetworkRequest

from .auth.credentials import Credentials

_STATUS = QNetworkRequest.Attribute.HttpStatusCodeAttribute
_CONTENT_TYPE = QNetworkRequest.KnownHeaders.ContentTypeHeader


def _request(url: str, headers: dict) -> QNetworkRequest:
    request = QNetworkRequest(QUrl(url))
    for name, value in headers.items():
        request.setRawHeader(name.encode("ascii"), value.encode("ascii"))
    return request


def _answer(blocking: QgsBlockingNetworkRequest) -> "tuple[int, Optional[dict]]":
    reply = blocking.reply()
    status = reply.attribute(_STATUS)
    status = int(status) if status is not None else 0
    raw = bytes(reply.content())
    try:
        body = json.loads(raw.decode("utf-8")) if raw else None
    except (UnicodeDecodeError, ValueError):
        body = None
    return status, body


def _post(url: str, payload: bytes, content_type: str, headers: dict, feedback=None) -> "tuple[int, Optional[dict]]":
    request = _request(url, headers)
    request.setHeader(_CONTENT_TYPE, content_type)
    request.setRawHeader(b"Accept", b"application/json")
    buffer = QBuffer()
    buffer.setData(QByteArray(payload))
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    blocking = QgsBlockingNetworkRequest()
    blocking.post(request, buffer, True, feedback)
    return _answer(blocking)


def post_form(url: str, form: Optional[dict], headers: dict) -> "tuple[int, Optional[dict]]":
    """application/x-www-form-urlencoded, for the authorization server; and
    an empty POST with a bearer, for the maps-token mint."""
    return _post(url, urlencode(form or {}).encode("ascii"), "application/x-www-form-urlencoded", headers)


def post_json(url: str, body: dict, headers: Optional[dict] = None, feedback=None) -> "tuple[int, Optional[dict]]":
    return _post(url, json.dumps(body).encode("utf-8"), "application/json", headers or {}, feedback)


def get_json(url: str, headers: Optional[dict] = None) -> "tuple[int, Optional[dict]]":
    blocking = QgsBlockingNetworkRequest()
    request = _request(url, headers or {})
    request.setRawHeader(b"Accept", b"application/json")
    blocking.get(request, True)
    return _answer(blocking)


def get_bytes(url: str) -> "tuple[int, bytes]":
    blocking = QgsBlockingNetworkRequest()
    blocking.get(_request(url, {}), True)
    reply = blocking.reply()
    status = reply.attribute(_STATUS)
    return (int(status) if status is not None else 0), bytes(reply.content())


class Attacher:
    def __init__(self, credentials: Credentials):
        self._credentials = credentials
        self._id: Optional[str] = None

    def __call__(self, request: QNetworkRequest) -> None:
        if request.hasRawHeader(b"Authorization"):
            return
        token = self._credentials.for_url(request.url().toString())
        if token:
            request.setRawHeader(b"Authorization", b"Bearer " + token.encode("ascii"))

    def install(self) -> None:
        if self._id is None:
            self._id = QgsNetworkAccessManager.setRequestPreprocessor(self)

    def remove(self) -> None:
        if self._id is not None:
            QgsNetworkAccessManager.removeRequestPreprocessor(self._id)
            self._id = None


class Watcher(QObject):
    """Emits `refused(status, host)` on the main thread for 403/429/503 from
    the hosts it watches."""

    refused = pyqtSignal(int, str)

    def __init__(self, hosts: "set[str]"):
        super().__init__()
        self.hosts = {h.lower() for h in hosts}
        self._id: Optional[str] = None

    def __call__(self, request: QNetworkRequest, reply: QNetworkReply) -> None:
        host = (urlsplit(request.url().toString()).hostname or "").lower()
        if host not in self.hosts:
            return

        def finished() -> None:
            status = reply.attribute(_STATUS)
            if status is not None and int(status) in (403, 429, 503):
                self.refused.emit(int(status), host)

        reply.finished.connect(finished)

    def install(self) -> None:
        if self._id is None:
            self._id = QgsNetworkAccessManager.setReplyPreprocessor(self)

    def remove(self) -> None:
        if self._id is not None:
            QgsNetworkAccessManager.removeReplyPreprocessor(self._id)
            self._id = None
