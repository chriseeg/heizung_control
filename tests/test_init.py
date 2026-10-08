"""Einrichtung, Sensor, Websocket und Dienst."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.heizplan.const import DOMAIN

WORKDAY = "binary_sensor.workday_sensor"
HOMEOFFICE = "binary_sensor.homeoffice"
SENSOR = "sensor.heizplan_wohnzimmer"
WEEK = {d: "werktag" for d in ("mon", "tue", "wed", "thu", "fri")} | {
    "sat": "zuhause",
    "sun": "zuhause",
}


@pytest.fixture
async def entry(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> MockConfigEntry:
    await hass.config.async_set_time_zone("Europe/Berlin")
    # Montag 07:15
    freezer.move_to(datetime(2026, 10, 5, 7, 15, tzinfo=dt_util.get_default_time_zone()))
    hass.states.async_set(WORKDAY, "on")
    hass.states.async_set(HOMEOFFICE, "off")
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        options={"workday_entity": WORKDAY, "homeoffice_entity": HOMEOFFICE},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _ws(hass: HomeAssistant, hass_ws_client: WebSocketGenerator, msg: dict[str, Any]) -> Any:
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(msg)
    return await client.receive_json()


async def _add_room(hass: HomeAssistant, hass_ws_client: WebSocketGenerator) -> None:
    res = await _ws(
        hass,
        hass_ws_client,
        {
            "type": "heizplan/room/save",
            "room": {"key": "wohnzimmer", "name": "Wohnzimmer", "days": WEEK},
        },
    )
    assert res["success"], res
    assert res["result"] == {"key": "wohnzimmer", "created": True}
    await hass.async_block_till_done()


async def test_setup_and_defaults(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert entry.state is ConfigEntryState.LOADED
    assert set(entry.runtime_data.store.profiles) == {"werktag", "zuhause", "sparen"}
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_room_sensor_follows_plan(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    freezer: FrozenDateTimeFactory,
) -> None:
    await _add_room(hass, hass_ws_client)
    state = hass.states.get(SENSOR)
    assert state is not None
    assert float(state.state) == 20
    assert state.attributes["profil"] == "Werktag"
    assert state.attributes["tag"] == "Montag"
    assert state.attributes["naechste_temperatur"] == 18

    # 08:30 -> Sparphase
    freezer.move_to(datetime(2026, 10, 5, 8, 30, 1, tzinfo=dt_util.get_default_time_zone()))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert float(hass.states.get(SENSOR).state) == 18


async def test_homeoffice_profile(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    await _add_room(hass, hass_ws_client)
    res = await _ws(
        hass,
        hass_ws_client,
        {
            "type": "heizplan/assign",
            "key": "wohnzimmer",
            "days": ["homeoffice"],
            "profile": "zuhause",
        },
    )
    assert res["success"], res
    await hass.async_block_till_done()
    assert float(hass.states.get(SENSOR).state) == 20  # kein Homeoffice: Werktag
    hass.states.async_set(HOMEOFFICE, "on")
    await hass.async_block_till_done()
    state = hass.states.get(SENSOR)
    assert state.attributes["tag"] == "Homeoffice"
    assert float(state.state) == 20.5
    # Feiertag schlägt Homeoffice
    hass.states.async_set(WORKDAY, "off")
    await hass.async_block_till_done()
    assert hass.states.get(SENSOR).attributes["tagestyp"] == "mon"  # kein Profil für frei


async def test_service_assign_and_delete_profile(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    await _add_room(hass, hass_ws_client)
    await hass.services.async_call(
        DOMAIN,
        "assign",
        {"raum": "wohnzimmer", "tage": ["mon"], "profil": "sparen"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert float(hass.states.get(SENSOR).state) == 17

    res = await _ws(
        hass, hass_ws_client, {"type": "heizplan/profile/delete", "profile_id": "sparen"}
    )
    assert not res["success"]
    res = await _ws(
        hass,
        hass_ws_client,
        {"type": "heizplan/profile/delete", "profile_id": "sparen", "replacement": "zuhause"},
    )
    assert res["success"], res
    await hass.async_block_till_done()
    assert hass.states.get(SENSOR).attributes["profil"] == "Zu Hause"


async def test_save_profile_and_subscribe(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "heizplan/subscribe"})
    assert (await client.receive_json())["success"]
    first = await client.receive_json()
    assert len(first["event"]["profiles"]) == 3

    await client.send_json_auto_id(
        {
            "type": "heizplan/profile/save",
            "profile": {"name": "Kita-Tag", "points": [{"at": "00:00", "temp": 18}]},
        }
    )
    msgs = [await client.receive_json(), await client.receive_json()]
    result = next(m for m in msgs if m["type"] == "result")
    assert result["result"] == {"id": "kita_tag"}
    event = next(m for m in msgs if m["type"] == "event")
    assert {p["id"] for p in event["event"]["profiles"]} >= {"kita_tag"}

    await client.send_json_auto_id(
        {"type": "heizplan/profile/save", "profile": {"name": "X", "points": []}}
    )
    res = await client.receive_json()
    assert not res["success"]
    assert res["error"]["code"] == "invalid"


async def test_delete_room_removes_entity(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    await _add_room(hass, hass_ws_client)
    assert er.async_get(hass).async_get(SENSOR) is not None
    res = await _ws(hass, hass_ws_client, {"type": "heizplan/room/delete", "key": "wohnzimmer"})
    assert res["success"]
    await hass.async_block_till_done()
    assert er.async_get(hass).async_get(SENSOR) is None
    assert hass.states.get(SENSOR) is None


async def test_store_persists(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    await _add_room(hass, hass_ws_client)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert "wohnzimmer" in entry.runtime_data.store.rooms
    assert float(hass.states.get(SENSOR).state) == 20
