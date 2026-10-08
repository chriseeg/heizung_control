"""Planlogik ohne Home Assistant."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from custom_components.heizplan.plan import (
    DayFlags,
    PlanError,
    Profile,
    Room,
    day_type,
    evaluate,
)

TZ = ZoneInfo("Europe/Berlin")
WERKTAG = Profile.from_dict(
    {
        "id": "werktag",
        "name": "Werktag",
        "points": [
            {"at": "06:00", "temp": 20},
            {"at": "00:00", "temp": 17},
            {"at": "22:30", "temp": 17},
            {"at": "16:00", "temp": 20.5},
            {"at": "08:30", "temp": 18},
        ],
    }
)
HO = Profile.from_dict(
    {
        "id": "ho",
        "name": "Homeoffice",
        "points": [{"at": "00:00", "temp": 17}, {"at": "07:00", "temp": 21}],
    }
)
FREI = Profile.from_dict({"id": "frei", "name": "Frei", "points": [{"at": "00:00", "temp": 19}]})
PROFILES = {p.id: p for p in (WERKTAG, HO, FREI)}
ROOM = Room.from_dict(
    {
        "key": "wohnzimmer",
        "name": "Wohnzimmer",
        "days": {
            **dict.fromkeys(("mon", "tue", "wed", "thu", "fri"), "werktag"),
            "sat": "frei",
            "sun": "frei",
            "homeoffice": "ho",
            "free": "frei",
        },
    },
    PROFILES,
)
MONDAY = date(2026, 10, 5)


def test_points_sorted_and_temp_rounded() -> None:
    assert [p.at for p in WERKTAG.points] == ["00:00", "06:00", "08:30", "16:00", "22:30"]
    p = Profile.from_dict({"id": "x", "name": "X", "points": [{"at": "00:00", "temp": 20.3}]})
    assert p.points[0].temp == 20.5


def test_missing_midnight_point_wraps() -> None:
    p = Profile.from_dict(
        {
            "id": "x",
            "name": "X",
            "points": [{"at": "06:00", "temp": 21}, {"at": "22:00", "temp": 16}],
        }
    )
    assert p.points[0].at == "00:00"
    assert p.points[0].temp == 16


@pytest.mark.parametrize(
    "raw",
    [
        {"id": "x", "name": "X", "points": []},
        {"id": "x", "name": "", "points": [{"at": "00:00", "temp": 20}]},
        {"id": "X Y", "name": "X", "points": [{"at": "00:00", "temp": 20}]},
        {"id": "x", "name": "X", "points": [{"at": "24:00", "temp": 20}]},
        {"id": "x", "name": "X", "points": [{"at": "00:00", "temp": 40}]},
    ],
)
def test_invalid_profiles(raw: dict) -> None:
    with pytest.raises(PlanError):
        Profile.from_dict(raw)


def test_room_rejects_unknown_profile() -> None:
    with pytest.raises(PlanError):
        Room.from_dict({"key": "bad", "name": "Bad", "days": {"mon": "gibtsnicht"}}, PROFILES)


def test_day_type_precedence() -> None:
    assert day_type(MONDAY, None) == ["mon"]
    assert day_type(MONDAY, DayFlags(workday=False, homeoffice=True)) == ["free", "mon"]
    assert day_type(MONDAY, DayFlags(workday=True, homeoffice=True)) == ["homeoffice", "mon"]
    # Wochenende kennt keine Sondertage
    assert day_type(date(2026, 10, 10), DayFlags(workday=False, homeoffice=True)) == ["sat"]


def test_evaluate_weekday() -> None:
    now = datetime(2026, 10, 5, 7, 15, tzinfo=TZ)
    state = evaluate(ROOM, PROFILES, now, DayFlags(workday=True, homeoffice=False))
    assert state is not None
    assert state.temp == 20
    assert state.day_kind == "mon"
    assert state.since == datetime(2026, 10, 5, 6, 0, tzinfo=TZ)
    assert state.next_change == datetime(2026, 10, 5, 8, 30, tzinfo=TZ)
    assert state.next_temp == 18
    assert state.refresh_at == datetime(2026, 10, 5, 8, 30, tzinfo=TZ)


def test_evaluate_homeoffice_and_free() -> None:
    now = datetime(2026, 10, 5, 9, 0, tzinfo=TZ)
    ho = evaluate(ROOM, PROFILES, now, DayFlags(workday=True, homeoffice=True))
    assert ho is not None and ho.temp == 21 and ho.day_kind == "homeoffice"
    free = evaluate(ROOM, PROFILES, now, DayFlags(workday=False))
    assert free is not None and free.temp == 19 and free.day_kind == "free"


def test_next_change_skips_same_temp_and_crosses_midnight() -> None:
    # Freitag 23:00: 17 °C bis Mitternacht, Samstag "Frei" = 19 °C ab 00:00
    now = datetime(2026, 10, 9, 23, 0, tzinfo=TZ)
    state = evaluate(ROOM, PROFILES, now, None)
    assert state is not None
    assert state.temp == 17
    assert state.refresh_at == datetime(2026, 10, 10, 0, 0, tzinfo=TZ)
    assert state.next_change == datetime(2026, 10, 10, 0, 0, tzinfo=TZ)
    assert state.next_temp == 19


def test_no_profile_for_day() -> None:
    room = Room.from_dict({"key": "kz", "name": "KZ", "days": {"mon": "werktag"}}, PROFILES)
    assert evaluate(room, PROFILES, datetime(2026, 10, 6, 9, tzinfo=TZ), None) is None
