"""A fake authorization server and hub, in process, for the flow tests."""

from __future__ import annotations

import itertools


class Clock:
    def __init__(self, now: float = 1_000_000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


class FakeHub:
    """Enough of /oauth/* and /api/maps/token to drive the session.

    Refresh tokens rotate; presenting a rotated one revokes the grant, as
    the real server does.
    """

    def __init__(self, clock: Clock):
        self.clock = clock
        self._n = itertools.count(1)
        self.live_refresh: "set[str]" = set()
        self.rotated: "set[str]" = set()
        self.revoked = False
        self.calls: "list[tuple[str, dict]]" = []
        self.device_pending = 2
        self.mint_status = 200

    def _new(self, prefix: str) -> str:
        return f"{prefix}-{next(self._n)}"

    def post(self, url: str, form: dict, headers: dict):
        path = url.split("://", 1)[1].split("/", 1)[1]
        self.calls.append(("/" + path, dict(form, **headers)))
        if path == "oauth/token":
            return self._token(form)
        if path == "oauth/device_authorization":
            return 200, {
                "device_code": "dev-1",
                "user_code": "ABCD-EFGH",
                "verification_uri": "https://hub.example/oauth/device",
                "verification_uri_complete": "https://hub.example/oauth/device?user_code=ABCD-EFGH",
                "expires_in": 600,
                "interval": 5,
            }
        if path == "oauth/revoke":
            self.revoked = True
            self.live_refresh.clear()
            return 200, None
        if path == "api/maps/token":
            if not headers.get("Authorization", "").startswith("Bearer at-"):
                return 401, {"error": "invalid_token"}
            if self.mint_status != 200:
                return self.mint_status, {"error": "forbidden"}
            return 200, {"token": self._new("maps"), "expiresAt": None}
        return 404, None

    def _grant(self):
        rt = self._new("rt")
        self.live_refresh.add(rt)
        return 200, {"access_token": self._new("at"), "token_type": "Bearer", "expires_in": 900, "refresh_token": rt}

    def _token(self, form: dict):
        grant = form["grant_type"]
        if grant == "authorization_code":
            if form.get("code") != "good-code" or not form.get("code_verifier"):
                return 400, {"error": "invalid_grant"}
            return self._grant()
        if grant.endswith("device_code"):
            if self.device_pending:
                self.device_pending -= 1
                return 400, {"error": "authorization_pending"}
            return self._grant()
        if grant == "refresh_token":
            rt = form["refresh_token"]
            if rt in self.rotated:
                self.live_refresh.clear()
                return 400, {"error": "invalid_grant"}
            if rt not in self.live_refresh:
                return 400, {"error": "invalid_grant"}
            self.live_refresh.discard(rt)
            self.rotated.add(rt)
            return self._grant()
        return 400, {"error": "unsupported_grant_type"}
