"""A one-shot loopback listener for the authorization code redirect.

Binds 127.0.0.1 on a free port, accepts exactly one request for
/callback, answers with a short page, and closes. Anything else on the
port gets a 404 and does not end the wait.
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlsplit

PAGE = """<!doctype html><meta charset="utf-8"><title>Airdress</title>
<style>body{font:16px system-ui,sans-serif;background:#0b0d10;color:#e8eaed;display:grid;place-items:center;height:100vh;margin:0}
@media (prefers-color-scheme: light){body{background:#fff;color:#111}}</style>
<p>{message}</p>"""


class LoopbackReceiver:
    def __init__(self) -> None:
        self.result: dict | None = None
        self._done = threading.Event()
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                parts = urlsplit(self.path)
                if parts.path != "/callback":
                    self.send_error(404)
                    return
                query = {k: v[0] for k, v in parse_qs(parts.query).items()}
                ok = "code" in query
                message = (
                    "You can close this tab and return to QGIS."
                    if ok
                    else "Sign-in did not complete. You can close this tab and try again in QGIS."
                )
                body = PAGE.replace("{message}", message).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.end_headers()
                self.wfile.write(body)
                receiver.result = query
                receiver._done.set()

            def log_message(self, *args) -> None:  # the query holds the code: never log it
                pass

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._serve, daemon=True)

    @property
    def redirect_uri(self) -> str:
        return f"http://127.0.0.1:{self._server.server_port}/callback"

    def start(self) -> None:
        self._thread.start()

    def _serve(self) -> None:
        while not self._done.is_set():
            self._server.timeout = 0.5
            self._server.handle_request()
        self._server.server_close()

    def wait(self, timeout: float) -> dict | None:
        self._done.wait(timeout)
        return self.result

    def done(self) -> bool:
        return self._done.is_set()

    def cancel(self) -> None:
        self._done.set()
