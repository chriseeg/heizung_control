"""Konstanten."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "heizplan"

STORAGE_KEY: Final = f"{DOMAIN}.data"
STORAGE_VERSION: Final = 1

# Optionen: Entität, die an Werktagen "on" ist (Workday-Integration), und optional eine
# Entität, die an Homeoffice-Tagen "on" ist.
OPT_WORKDAY_ENTITY: Final = "workday_entity"
OPT_HOMEOFFICE_ENTITY: Final = "homeoffice_entity"

SIGNAL_UPDATED: Final = f"{DOMAIN}_updated"
SIGNAL_ROOM_ADDED: Final = f"{DOMAIN}_room_added"

TEMP_MIN: Final = 5.0
TEMP_MAX: Final = 30.0
TEMP_STEP: Final = 0.5
MAX_POINTS: Final = 12
NAME_MAX_LEN: Final = 40

WEEKDAYS: Final = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
# Sondertage, optional pro Raum; ohne Zuordnung gilt der Wochentag
DAY_FREE: Final = "free"
DAY_HOMEOFFICE: Final = "homeoffice"
SPECIAL_DAYS: Final = (DAY_FREE, DAY_HOMEOFFICE)
DAY_LABELS: Final = {
    "mon": "Montag",
    "tue": "Dienstag",
    "wed": "Mittwoch",
    "thu": "Donnerstag",
    "fri": "Freitag",
    "sat": "Samstag",
    "sun": "Sonntag",
    DAY_FREE: "Freier Tag",
    DAY_HOMEOFFICE: "Homeoffice",
}


def room_device_identifier(key: str) -> tuple[str, str]:
    return (DOMAIN, f"room_{key}")
