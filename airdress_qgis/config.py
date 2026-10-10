"""Where the plugin talks to, and the names it keeps things under.

Everything here is public: a hostname, a client id. The two origins can be
overridden through the environment for a local test service; nothing else
can, so a project file or a setting can never redirect a token.
"""

import os

MAPS_ORIGIN = os.environ.get("AIRDRESS_QGIS_MAPS_ORIGIN", "https://maps.airdress.co").rstrip("/")
HUB_ISSUER = os.environ.get("AIRDRESS_QGIS_HUB_ISSUER", "https://account.airdress.co").rstrip("/")

# The hub's own API, as an RFC 8707 resource: the token the plugin
# exchanges for a maps token is issued for exactly this audience.
HUB_RESOURCE = HUB_ISSUER + "/api"

CLIENT_ID = "airdress-qgis"
SCOPES = "offline_access"

# Settings, auth-setting and custom-property keys all start here.
PREFIX = "airdress/"
REFRESH_SETTING = PREFIX + "refresh"
LAYER_PROPERTY = PREFIX + "layer"

LICENSES_URL = MAPS_ORIGIN + "/licenses"

# Renew any token with this much (or less) of its life left.
RENEW_MARGIN_SECONDS = 120
