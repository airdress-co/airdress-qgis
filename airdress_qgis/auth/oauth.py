"""The hub's OAuth 2.1 authorization server, as a public client sees it.

PKCE S256 with a loopback redirect, the RFC 8628 device code for machines
where a browser cannot reach the loopback, rotating refresh tokens, and
RFC 7009 revocation. Every grant names one RFC 8707 resource.

No QGIS import here: the transport is a callable, so the flows are tested
without a network or a QGIS instance.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlencode

# post(url, form: dict, headers: dict) -> (status, json-or-None)
Post = Callable[[str, dict, dict], "tuple[int, dict | None]"]


class OAuthError(Exception):
    """The server answered with an OAuth error code."""

    def __init__(self, code: str, description: str = ""):
        super().__init__(code if not description else f"{code}: {description}")
        self.code = code


class NetworkError(Exception):
    """No usable answer: the request did not complete, or the body was not JSON."""


@dataclass
class Tokens:
    access_token: str
    expires_at: float
    refresh_token: str | None


@dataclass
class DeviceStart:
    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str | None
    expires_at: float
    interval: int


def pkce_pair() -> tuple[str, str]:
    """A (verifier, S256 challenge) pair, per RFC 7636."""
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


class AuthorizationServer:
    def __init__(self, issuer: str, client_id: str, post: Post, clock: Callable[[], float] = time.time):
        self.issuer = issuer.rstrip("/")
        self.client_id = client_id
        self._post = post
        self._clock = clock

    def endpoint(self, path: str) -> str:
        return self.issuer + path

    # --- authorization code + PKCE -------------------------------------

    def authorize_url(self, redirect_uri: str, resource: str, scope: str, state: str, challenge: str) -> str:
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self.client_id,
                "redirect_uri": redirect_uri,
                "scope": scope,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "resource": resource,
            }
        )
        return self.endpoint("/oauth/authorize") + "?" + query

    def exchange_code(self, code: str, verifier: str, redirect_uri: str, resource: str) -> Tokens:
        return self._token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": redirect_uri,
                "resource": resource,
            }
        )

    # --- device code ----------------------------------------------------

    def start_device(self, resource: str, scope: str) -> DeviceStart:
        status, body = self._call(
            "/oauth/device_authorization",
            {"client_id": self.client_id, "resource": resource, "scope": scope},
        )
        if status != 200 or not body:
            raise _error(body, status)
        now = self._clock()
        return DeviceStart(
            device_code=body["device_code"],
            user_code=body["user_code"],
            verification_uri=body["verification_uri"],
            verification_uri_complete=body.get("verification_uri_complete"),
            expires_at=now + int(body.get("expires_in", 600)),
            interval=max(1, int(body.get("interval", 5))),
        )

    def poll_device(self, device_code: str) -> Tokens | None:
        """Tokens once approved; None while pending. `slow_down` and every
        other refusal raise OAuthError, so the caller can widen its interval
        or stop."""
        try:
            return self._token(
                {"grant_type": "urn:ietf:params:oauth:grant-type:device_code", "device_code": device_code}
            )
        except OAuthError as err:
            if err.code == "authorization_pending":
                return None
            raise

    # --- refresh and revoke ---------------------------------------------

    def refresh(self, refresh_token: str, resource: str) -> Tokens:
        return self._token({"grant_type": "refresh_token", "refresh_token": refresh_token, "resource": resource})

    def revoke(self, refresh_token: str) -> None:
        # RFC 7009: 200 whether or not the token was known. Anything else is
        # reported, but the local session ends regardless (the caller's job).
        status, body = self._call(
            "/oauth/revoke",
            {"client_id": self.client_id, "token": refresh_token, "token_type_hint": "refresh_token"},
        )
        if status != 200:
            raise _error(body, status)

    # --- plumbing ---------------------------------------------------------

    def _token(self, form: dict) -> Tokens:
        form = dict(form, client_id=self.client_id)
        status, body = self._call("/oauth/token", form)
        if status != 200 or not body or "access_token" not in body:
            raise _error(body, status)
        return Tokens(
            access_token=body["access_token"],
            expires_at=self._clock() + int(body.get("expires_in", 900)),
            refresh_token=body.get("refresh_token"),
        )

    def _call(self, path: str, form: dict) -> tuple[int, dict | None]:
        return self._post(self.endpoint(path), form, {})


def _error(body: dict | None, status: int) -> Exception:
    if isinstance(body, dict) and isinstance(body.get("error"), str):
        return OAuthError(body["error"], str(body.get("error_description", "")))
    return NetworkError(f"unexpected answer (HTTP {status})")
