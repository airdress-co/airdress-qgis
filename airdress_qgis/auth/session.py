"""One person's signed-in state: the grant, and the tokens derived from it.

    refresh token (AS)   persisted, encrypted, by the store (or memory only)
    access token  (AS)   memory; audience = the hub's API
    maps token           memory; minted by the hub at /api/maps/token, 900 s

`ensure_fresh()` is the only thing that does network I/O, and it is called
from the main thread by a timer, never from the request preprocessor. The
preprocessor only ever reads what this left in `Credentials`.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

from .. import config
from .credentials import Credentials
from .oauth import AuthorizationServer, NetworkError, OAuthError, Tokens

# get/post with a bearer: (url, body-or-None, headers) -> (status, json-or-None)
Call = Callable[[str, Optional[dict], dict], "tuple[int, Optional[dict]]"]


class SignedOut(Exception):
    """The grant is gone (revoked, expired, refused); sign in again."""


class Store:
    """Where the refresh token lives between QGIS runs."""

    def load(self) -> Optional[str]:  # pragma: no cover - interface
        raise NotImplementedError

    def save(self, refresh_token: str) -> bool:  # pragma: no cover - interface
        """True when persisted; False means memory only for this run."""
        raise NotImplementedError

    def delete(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class MemoryStore(Store):
    def __init__(self) -> None:
        self.value: Optional[str] = None

    def load(self) -> Optional[str]:
        return self.value

    def save(self, refresh_token: str) -> bool:
        self.value = refresh_token
        return True

    def delete(self) -> None:
        self.value = None


@dataclass
class _Held:
    token: str
    expires_at: float


class Session:
    def __init__(
        self,
        server: AuthorizationServer,
        mint_maps: Call,
        store: Store,
        credentials: Credentials,
        clock: Callable[[], float] = time.time,
    ):
        self._server = server
        self._mint_maps = mint_maps
        self._store = store
        self._credentials = credentials
        self._clock = clock
        self._lock = threading.RLock()
        self._refresh: Optional[str] = None
        self._access: Optional[_Held] = None
        self._maps: Optional[_Held] = None
        self.persisted = False
        self._restored = False

    # --- state ------------------------------------------------------------

    @property
    def signed_in(self) -> bool:
        with self._lock:
            self._restore()
            return self._refresh is not None or self._access is not None

    def _restore(self) -> None:
        # Lazy: reading the auth DB may ask for the master password, so it
        # happens on first need, never at plugin load (NFR-1).
        if not self._restored:
            self._restored = True
            stored = self._store.load()
            if stored:
                self._refresh = stored
                self.persisted = True

    # --- sign-in ------------------------------------------------------------

    def adopt(self, tokens: Tokens) -> None:
        """Take the result of a completed sign-in flow."""
        with self._lock:
            self._restored = True
            self._access = _Held(tokens.access_token, tokens.expires_at)
            self._maps = None
            self._take_refresh(tokens.refresh_token)

    def _take_refresh(self, refresh_token: Optional[str]) -> None:
        if refresh_token is None:
            return
        self._refresh = refresh_token
        self.persisted = bool(self._store.save(refresh_token))

    # --- tokens ---------------------------------------------------------------

    def _fresh(self, held: Optional[_Held]) -> bool:
        return held is not None and held.expires_at - self._clock() > config.RENEW_MARGIN_SECONDS

    def access_token(self) -> str:
        with self._lock:
            self._restore()
            if self._fresh(self._access):
                return self._access.token
            if self._refresh is None:
                self._drop()
                raise SignedOut()
            try:
                tokens = self._server.refresh(self._refresh, config.HUB_RESOURCE)
            except OAuthError as err:
                # invalid_grant: revoked, expired, or a reused (rotated)
                # token. The grant is gone either way.
                self._forget()
                raise SignedOut() from err
            self._access = _Held(tokens.access_token, tokens.expires_at)
            self._take_refresh(tokens.refresh_token)
            return self._access.token

    def ensure_fresh(self) -> Optional[float]:
        """Make sure a maps token with life left is in Credentials. Returns
        when to call again (epoch seconds), or None when signed out.
        NetworkError propagates: the caller retries later, the session stays."""
        with self._lock:
            if self._fresh(self._maps):
                return self._maps.expires_at - config.RENEW_MARGIN_SECONDS
            access = self.access_token()
            status, body = self._mint_maps(
                config.HUB_ISSUER + "/api/maps/token", {}, {"Authorization": "Bearer " + access}
            )
            if status == 200 and body and isinstance(body.get("token"), str):
                expires_at = self._clock() + _seconds_until(body.get("expiresAt"), self._clock(), 900)
                self._maps = _Held(body["token"], expires_at)
                self._credentials.set(config.MAPS_ORIGIN, self._maps.token)
                return expires_at - config.RENEW_MARGIN_SECONDS
            if status in (401,):
                # The access token was refused: drop it and let the next call
                # refresh. One retry, never a loop.
                self._access = None
                raise NetworkError("access token refused; will refresh")
            raise MintRefused(status, (body or {}).get("error") if isinstance(body, dict) else None)

    def expire_maps(self) -> None:
        """A 403 token_expired came back: forget the maps token so the next
        ensure_fresh mints a new one."""
        with self._lock:
            self._maps = None

    # --- sign-out ---------------------------------------------------------

    def sign_out(self) -> Optional[Exception]:
        """Revoke the grant at the hub, then forget everything locally. The
        local half always happens; a failed revoke is returned, not raised."""
        with self._lock:
            self._restore()
            failure: Optional[Exception] = None
            if self._refresh is not None:
                try:
                    self._server.revoke(self._refresh)
                except (OAuthError, NetworkError) as err:
                    failure = err
            self._forget()
            return failure

    def _forget(self) -> None:
        self._refresh = None
        self._store.delete()
        self.persisted = False
        self._drop()

    def _drop(self) -> None:
        self._access = None
        self._maps = None
        self._credentials.clear()


class MintRefused(Exception):
    def __init__(self, status: int, code: Optional[str]):
        super().__init__(f"maps token refused (HTTP {status}, {code})")
        self.status = status
        self.code = code


def _seconds_until(rfc3339: Optional[str], now: float, default: int) -> float:
    if not rfc3339:
        return default
    from datetime import datetime

    try:
        when = datetime.fromisoformat(rfc3339.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return default
    return max(0.0, min(float(default), when - now))
