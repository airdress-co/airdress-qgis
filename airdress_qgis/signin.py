"""The sign-in dialog: browser first, a device code when the browser
cannot reach QGIS. Nothing is ever pasted into QGIS."""

from __future__ import annotations

import secrets
import time

from qgis.PyQt.QtCore import Qt, QTimer, QUrl
from qgis.PyQt.QtGui import QDesktopServices, QFont, QGuiApplication
from qgis.PyQt.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from . import config
from .auth.loopback import LoopbackReceiver
from .auth.oauth import AuthorizationServer, NetworkError, OAuthError, pkce_pair

LOOPBACK_TIMEOUT_S = 120


class SignInDialog(QDialog):
    def __init__(self, server: AuthorizationServer, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sign in to Airdress")
        self.server = server
        self.tokens = None
        self.error = None

        self.message = QLabel("Your browser opened. Sign in there, then come back to QGIS.")
        self.message.setWordWrap(True)
        self.code = QLabel("")
        font = QFont()
        font.setPointSize(22)
        font.setBold(True)
        self.code.setFont(font)
        self.code.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.code.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.code.hide()

        self.use_code = QPushButton("Use a code instead")
        self.copy = QPushButton("Copy code")
        self.copy.hide()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self.use_code.clicked.connect(self.start_device)
        self.copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.code.text()))

        buttons = QHBoxLayout()
        buttons.addWidget(self.use_code)
        buttons.addWidget(self.copy)
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        layout = QVBoxLayout(self)
        layout.addWidget(self.message)
        layout.addWidget(self.code)
        layout.addLayout(buttons)

        self._timer = QTimer(self)
        self._receiver = None
        self._device = None
        self._interval = 5
        self._next_poll = 0.0

    # --- loopback ------------------------------------------------------

    def start_browser(self) -> None:
        self._verifier, challenge = pkce_pair()
        self._state = secrets.token_urlsafe(16)
        self._receiver = LoopbackReceiver()
        self._receiver.start()
        self._deadline = time.monotonic() + LOOPBACK_TIMEOUT_S
        url = self.server.authorize_url(
            self._receiver.redirect_uri, config.HUB_RESOURCE, config.SCOPES, self._state, challenge
        )
        QDesktopServices.openUrl(QUrl(url))
        self._timer.timeout.connect(self._check_loopback)
        self._timer.start(200)

    def _check_loopback(self) -> None:
        if self._receiver is None:
            return
        if not self._receiver.done():
            if time.monotonic() > self._deadline:
                self.message.setText("The browser did not come back. Use a code instead.")
                self._stop_loopback()
            return
        result = self._receiver.result or {}
        self._stop_loopback()
        if result.get("state") != self._state or "code" not in result:
            self.message.setText("Sign-in did not complete. Try again, or use a code instead.")
            return
        try:
            self.tokens = self.server.exchange_code(
                result["code"], self._verifier, self._receiver_uri, config.HUB_RESOURCE
            )
        except (OAuthError, NetworkError) as err:
            self.error = err
            self.message.setText("Sign-in was refused. Try again, or use a code instead.")
            return
        self.accept()

    def _stop_loopback(self) -> None:
        self._timer.stop()
        try:
            self._timer.timeout.disconnect(self._check_loopback)
        except TypeError:
            pass
        if self._receiver is not None:
            self._receiver_uri = self._receiver.redirect_uri
            self._receiver.cancel()
            self._receiver = None

    # --- device code (RFC 8628) -------------------------------------------

    def start_device(self) -> None:
        self._stop_loopback()
        try:
            self._device = self.server.start_device(config.HUB_RESOURCE, config.SCOPES)
        except (OAuthError, NetworkError) as err:
            self.error = err
            self.message.setText("A code could not be requested. Check your connection and try again.")
            return
        self._interval = self._device.interval
        self._next_poll = time.monotonic() + self._interval
        uri = self._device.verification_uri
        self.message.setText(
            f'On any device, open <a href="{uri}">{uri}</a>, sign in, and enter this code:'
        )
        self.message.setOpenExternalLinks(True)
        self.code.setText(self._device.user_code)
        self.code.show()
        self.copy.show()
        self.use_code.hide()
        self._timer.timeout.connect(self._poll_device)
        self._timer.start(500)

    def _poll_device(self) -> None:
        if self._device is None or time.monotonic() < self._next_poll:
            return
        if time.time() > self._device.expires_at:
            self._timer.stop()
            self.message.setText("The code expired. Close this and sign in again.")
            return
        self._next_poll = time.monotonic() + self._interval
        try:
            tokens = self.server.poll_device(self._device.device_code)
        except OAuthError as err:
            if err.code == "slow_down":
                self._interval += 5
                return
            self._timer.stop()
            self.error = err
            self.message.setText(
                "The request was declined." if err.code == "access_denied" else "The code expired. Sign in again."
            )
            return
        except NetworkError:
            return  # try again at the next interval
        if tokens is not None:
            self._timer.stop()
            self.tokens = tokens
            self.accept()

    def done(self, result: int) -> None:  # noqa: A003 - QDialog API
        self._stop_loopback()
        self._timer.stop()
        super().done(result)
