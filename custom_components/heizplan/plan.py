"""Reine Planlogik ohne Home Assistant: welches Profil gilt, welche Temperatur, wann der
nächste Wechsel kommt.

Ein Profil beschreibt einen ganzen Tag. Der erste Punkt liegt immer auf 00:00, jeder Punkt
gilt bis zum nächsten.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
import re
from typing import Any

from .const import (
    DAY_FREE,
    DAY_HOMEOFFICE,
    MAX_POINTS,
    NAME_MAX_LEN,
    SPECIAL_DAYS,
    TEMP_MAX,
    TEMP_MIN,
    TEMP_STEP,
    WEEKDAYS,
)

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_KEY_RE = re.compile(r"^[a-z0-9_]{1,32}$")


class PlanError(ValueError):
    """Ungültige Eingabe, Text ist für das Panel gedacht."""


def parse_time(value: str) -> time:
    match = _TIME_RE.match(value)
    if not match:
        raise PlanError(f"Ungültige Uhrzeit: {value}")
    return time(int(match[1]), int(match[2]))


def clean_temp(value: Any) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise PlanError("Temperatur fehlt")
    temp = round(float(value) / TEMP_STEP) * TEMP_STEP
    if not TEMP_MIN <= temp <= TEMP_MAX:
        raise PlanError(f"Temperatur muss zwischen {TEMP_MIN:g} und {TEMP_MAX:g} °C liegen")
    return temp


def clean_name(value: Any) -> str:
    name = str(value or "").strip()
    if not name:
        raise PlanError("Name fehlt")
    return name[:NAME_MAX_LEN]


def clean_key(value: Any) -> str:
    key = str(value or "").strip()
    if not _KEY_RE.match(key):
        raise PlanError("Kürzel: nur a-z, 0-9 und _ (höchstens 32 Zeichen)")
    return key


@dataclass(slots=True, frozen=True)
class Point:
    """Ab dieser Uhrzeit gilt diese Temperatur."""

    at: str  # "HH:MM"
    temp: float

    @property
    def minutes(self) -> int:
        t = parse_time(self.at)
        return t.hour * 60 + t.minute


@dataclass(slots=True)
class Profile:
    """Benanntes Tagesmuster, in beliebig vielen Räumen und Tagen verwendbar."""

    id: str
    name: str
    points: list[Point]

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Profile:
        raw_points = raw.get("points")
        if not isinstance(raw_points, list) or not raw_points:
            raise PlanError("Ein Profil braucht mindestens einen Zeitpunkt")
        if len(raw_points) > MAX_POINTS:
            raise PlanError(f"Höchstens {MAX_POINTS} Zeitpunkte pro Profil")
        points: dict[str, Point] = {}
        for item in raw_points:
            if not isinstance(item, dict):
                raise PlanError("Ungültiger Zeitpunkt")
            at = str(item.get("at", ""))
            parse_time(at)
            points[at] = Point(at=at, temp=clean_temp(item.get("temp")))
        ordered = sorted(points.values(), key=lambda p: p.minutes)
        if ordered[0].at != "00:00":
            # Der Tag beginnt mit der Temperatur des ersten Punkts
            ordered.insert(0, Point(at="00:00", temp=ordered[-1].temp))
        return cls(id=clean_key(raw.get("id")), name=clean_name(raw.get("name")), points=ordered)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "points": [{"at": p.at, "temp": p.temp} for p in self.points],
        }

    def temp_at(self, minutes: int) -> tuple[float, Point]:
        current = self.points[0]
        for point in self.points:
            if point.minutes <= minutes:
                current = point
            else:
                break
        return current.temp, current


@dataclass(slots=True)
class Room:
    """Raum mit Zuordnung Tag -> Profil."""

    key: str
    name: str
    days: dict[str, str | None] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any], profiles: dict[str, Profile]) -> Room:
        days_raw = raw.get("days") or {}
        if not isinstance(days_raw, dict):
            raise PlanError("Ungültige Tageszuordnung")
        days: dict[str, str | None] = {}
        for day in (*WEEKDAYS, *SPECIAL_DAYS):
            pid = days_raw.get(day)
            if pid in (None, ""):
                days[day] = None
                continue
            if pid not in profiles:
                raise PlanError(f"Unbekanntes Profil: {pid}")
            days[day] = str(pid)
        return cls(key=clean_key(raw.get("key")), name=clean_name(raw.get("name")), days=days)

    def as_dict(self) -> dict[str, Any]:
        return {"key": self.key, "name": self.name, "days": dict(self.days)}


@dataclass(slots=True, frozen=True)
class DayFlags:
    """Was über heute bekannt ist. None = unbekannt (Entität fehlt oder offline)."""

    workday: bool | None = None
    homeoffice: bool | None = None


def day_type(day: date, flags: DayFlags | None) -> list[str]:
    """Tagestypen in absteigendem Vorrang; der Wochentag steht immer am Ende.

    Freier Tag = Montag bis Freitag, aber kein Werktag (Feiertag, Brückentag, Urlaub).
    Homeoffice gilt nur an Werktagen.
    """
    weekday = WEEKDAYS[day.weekday()]
    types: list[str] = []
    if flags is not None and day.weekday() < 5:
        if flags.workday is False:
            types.append(DAY_FREE)
        elif flags.homeoffice:
            types.append(DAY_HOMEOFFICE)
    types.append(weekday)
    return types


def profile_for(
    room: Room, profiles: dict[str, Profile], day: date, flags: DayFlags | None
) -> tuple[Profile | None, str]:
    """Profil und Tagestyp, der es geliefert hat."""
    for kind in day_type(day, flags):
        pid = room.days.get(kind)
        if pid and pid in profiles:
            return profiles[pid], kind
    return None, WEEKDAYS[day.weekday()]


@dataclass(slots=True, frozen=True)
class PlanState:
    """Was der Plan für einen Raum gerade sagt."""

    temp: float
    profile: Profile
    day_kind: str
    since: datetime
    next_change: datetime | None
    next_temp: float | None
    # Nächster Zeitpunkt, an dem neu gerechnet werden muss (Punkt heute oder Mitternacht)
    refresh_at: datetime


def evaluate(
    room: Room,
    profiles: dict[str, Profile],
    now: datetime,
    flags: DayFlags | None,
) -> PlanState | None:
    """Aktuellen Stand berechnen. now muss zeitzonenbewusst sein (lokale Zeit)."""
    today = now.date()
    profile, kind = profile_for(room, profiles, today, flags)
    if profile is None:
        return None
    minutes = now.hour * 60 + now.minute
    temp, point = profile.temp_at(minutes)
    midnight = datetime.combine(today + timedelta(days=1), time(0), tzinfo=now.tzinfo)
    since = datetime.combine(today, parse_time(point.at), tzinfo=now.tzinfo)

    later_today = [p for p in profile.points if p.minutes > minutes]
    refresh_at = (
        datetime.combine(today, parse_time(later_today[0].at), tzinfo=now.tzinfo)
        if later_today
        else midnight
    )

    # Nächster echter Temperaturwechsel; morgen zählt nur der Wochentag, weil Feiertag
    # und Homeoffice erst am Tag selbst feststehen.
    next_change: datetime | None = None
    next_temp: float | None = None
    for p in later_today:
        if p.temp != temp:
            next_change = datetime.combine(today, parse_time(p.at), tzinfo=now.tzinfo)
            next_temp = p.temp
            break
    if next_change is None:
        tomorrow, _ = profile_for(room, profiles, today + timedelta(days=1), None)
        if tomorrow is not None:
            for p in tomorrow.points:
                if p.temp != temp:
                    next_change = datetime.combine(
                        today + timedelta(days=1), parse_time(p.at), tzinfo=now.tzinfo
                    )
                    next_temp = p.temp
                    break
    return PlanState(
        temp=temp,
        profile=profile,
        day_kind=kind,
        since=since,
        next_change=next_change,
        next_temp=next_temp,
        refresh_at=refresh_at,
    )


def default_profiles() -> list[Profile]:
    """Startprofile für eine frische Installation."""
    return [
        Profile.from_dict(
            {
                "id": "werktag",
                "name": "Werktag",
                "points": [
                    {"at": "00:00", "temp": 17},
                    {"at": "06:00", "temp": 20},
                    {"at": "08:30", "temp": 18},
                    {"at": "16:00", "temp": 20.5},
                    {"at": "22:30", "temp": 17},
                ],
            }
        ),
        Profile.from_dict(
            {
                "id": "zuhause",
                "name": "Zu Hause",
                "points": [
                    {"at": "00:00", "temp": 17},
                    {"at": "07:00", "temp": 20.5},
                    {"at": "23:00", "temp": 17},
                ],
            }
        ),
        Profile.from_dict(
            {"id": "sparen", "name": "Sparen", "points": [{"at": "00:00", "temp": 17}]}
        ),
    ]
