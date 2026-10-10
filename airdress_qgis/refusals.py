"""One sentence per refusal, in the person's language.

The codes are the map service's and the hub's own. A code not listed here
is shown as the generic sentence, never as the raw code.
"""

from __future__ import annotations

MESSAGES = {
    "en": {
        "not_allowed": "Your Airdress account does not have access to the map yet.",
        "sign_in_required": "Sign in to Airdress to show the map.",
        "token_expired": "Your map session expired. Renewing it…",
        "check_unavailable": "The map service cannot check your access right now. Try again in a minute.",
        "maps_paused": "The Airdress map is paused for the rest of the month (its spending limit was reached).",
        "geocoder_starting": "Search is starting up. Try again in {seconds} seconds.",
        "rate_limited": "Too many map requests from your network. Wait a minute, then pan or search again.",
        "signed_out": "You were signed out of Airdress. Sign in again to show the map.",
        "session_only": "Signed in for this session only. Set a QGIS master password to stay signed in.",
        "network": "Airdress could not be reached. Check your connection.",
        "generic": "The Airdress map did not answer as expected. Try again later.",
    },
    "de": {
        "not_allowed": "Dein Airdress-Konto hat noch keinen Zugang zur Karte.",
        "sign_in_required": "Melde dich bei Airdress an, um die Karte zu sehen.",
        "token_expired": "Deine Kartensitzung ist abgelaufen. Sie wird erneuert …",
        "check_unavailable": "Der Kartendienst kann deinen Zugang gerade nicht prüfen. Versuch es in einer Minute noch einmal.",
        "maps_paused": "Die Airdress-Karte ist für den Rest des Monats pausiert (ihr Ausgabenlimit ist erreicht).",
        "geocoder_starting": "Die Suche startet gerade. Versuch es in {seconds} Sekunden noch einmal.",
        "rate_limited": "Zu viele Kartenanfragen aus deinem Netz. Warte eine Minute und verschiebe oder suche dann erneut.",
        "signed_out": "Du wurdest bei Airdress abgemeldet. Melde dich erneut an, um die Karte zu sehen.",
        "session_only": "Nur für diese Sitzung angemeldet. Lege in QGIS ein Master-Passwort fest, um angemeldet zu bleiben.",
        "network": "Airdress ist nicht erreichbar. Prüfe deine Verbindung.",
        "generic": "Die Airdress-Karte hat nicht wie erwartet geantwortet. Versuch es später noch einmal.",
    },
}


def language(locale: str) -> str:
    return "de" if (locale or "").lower().startswith("de") else "en"


def sentence(code: str, locale: str = "en", **values) -> str:
    table = MESSAGES[language(locale)]
    text = table.get(code, table["generic"])
    return text.format(**values) if values else text


def code_for(status: int, error: str | None) -> str:
    """Map an HTTP answer from our hosts to a refusal code."""
    if error in MESSAGES["en"]:
        return error
    if status == 429:
        return "rate_limited"
    if status == 403:
        return "sign_in_required"
    return "generic"
