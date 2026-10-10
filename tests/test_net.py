"""The QGIS network adapter, against a local HTTP server."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

pytest.importorskip("qgis.core")


@pytest.fixture(scope="module")
def server():
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status, body, ctype="application/json"):
            raw = body if isinstance(body, bytes) else body.encode()
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.path == "/json":
                self._send(200, json.dumps({"ok": True, "auth": self.headers.get("Authorization")}))
            elif self.path == "/text":
                self._send(200, "not json", "text/plain")
            elif self.path == "/bytes":
                self._send(200, b"\x89PNG\r\n", "image/png")
            else:
                self._send(503, json.dumps({"error": "maps_paused"}))

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
            self._send(
                200,
                json.dumps(
                    {"type": self.headers.get("Content-Type"), "body": body, "auth": self.headers.get("Authorization")}
                ),
            )

        def log_message(self, *a):
            pass

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


def test_get_json_and_its_failures(qgis_app, server):
    from airdress_qgis import net

    assert net.get_json(server + "/json") == (200, {"ok": True, "auth": None})
    assert net.get_json(server + "/text") == (200, None)
    assert net.get_json(server + "/nope") == (503, {"error": "maps_paused"})
    assert net.get_bytes(server + "/bytes") == (200, b"\x89PNG\r\n")


def test_posts_carry_the_right_body_and_headers(qgis_app, server):
    from airdress_qgis import net

    status, echo = net.post_form(server + "/t", {"a": "1", "b": "x y"}, {"Authorization": "Bearer T"})
    assert status == 200 and echo["body"] == "a=1&b=x+y" and echo["auth"] == "Bearer T"
    assert echo["type"].startswith("application/x-www-form-urlencoded")
    status, echo = net.post_json(server + "/t", {"text": "munich"})
    assert json.loads(echo["body"]) == {"text": "munich"} and echo["type"] == "application/json"


def test_the_attacher_never_sends_a_token_over_plain_http(qgis_app, server):
    from airdress_qgis import net
    from airdress_qgis.auth.credentials import Credentials

    creds = Credentials()
    creds.set("https://127.0.0.1", "SECRET")
    attacher = net.Attacher(creds)
    attacher.install()
    try:
        assert net.get_json(server + "/json")[1]["auth"] is None
    finally:
        attacher.remove()


def test_the_notifier_delivers_on_the_main_thread(qgis_app):
    from qgis.PyQt.QtCore import QCoreApplication

    from airdress_qgis import net

    notifier = net.Notifier()
    seen = []
    notifier.answer.connect(lambda s, b: seen.append((threading.current_thread(), s, b)))
    t = threading.Thread(target=notifier.answer.emit, args=(503, "{}"))
    t.start()
    t.join(5)
    for _ in range(20):
        QCoreApplication.processEvents()
    assert seen == [(threading.main_thread(), 503, "{}")]
