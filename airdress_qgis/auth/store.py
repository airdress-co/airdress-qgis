"""The refresh token in QGIS's encrypted auth database, or nowhere.

`storeAuthSetting(…, encrypt=True)` needs the QGIS master password; when
the person declines one, saving fails and the session lives in memory for
this run only. There is no plaintext fallback, deliberately.
"""

from __future__ import annotations

from typing import Optional

from qgis.core import QgsApplication

from .. import config
from .session import Store


class AuthDbStore(Store):
    def __init__(self, key: str = config.REFRESH_SETTING):
        self.key = key

    def _manager(self):
        return QgsApplication.authManager()

    def load(self) -> Optional[str]:
        manager = self._manager()
        # existsAuthSetting needs no master password: nobody who never signed
        # in is ever asked for one.
        if not manager.existsAuthSetting(self.key):
            return None
        value = manager.authSetting(self.key, None, True)
        return str(value) if value else None

    def save(self, refresh_token: str) -> bool:
        return bool(self._manager().storeAuthSetting(self.key, refresh_token, True))

    def delete(self) -> None:
        manager = self._manager()
        if manager.existsAuthSetting(self.key):
            manager.removeAuthSetting(self.key)
