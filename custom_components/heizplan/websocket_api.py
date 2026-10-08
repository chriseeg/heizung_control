"""Websocket-API für das Panel. Lesen darf jeder angemeldete Nutzer, ändern nur Admins."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_connect
import voluptuous as vol

from .const import (
    DAY_LABELS,
    DOMAIN,
    MAX_POINTS,
    OPT_HOMEOFFICE_ENTITY,
    OPT_WORKDAY_ENTITY,
    SIGNAL_UPDATED,
    SPECIAL_DAYS,
    TEMP_MAX,
    TEMP_MIN,
    TEMP_STEP,
    WEEKDAYS,
)
from .plan import PlanError

if TYPE_CHECKING:
    from . import HeizplanData

DAY = vol.In([*WEEKDAYS, *SPECIAL_DAYS])


@callback
def async_register_websocket_api(hass: HomeAssistant) -> None:
    for command in (
        ws_subscribe,
        ws_save_profile,
        ws_delete_profile,
        ws_save_room,
        ws_delete_room,
        ws_assign,
    ):
        websocket_api.async_register_command(hass, command)


def loaded_data(hass: HomeAssistant) -> HeizplanData | None:
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        data: HeizplanData = entry.runtime_data
        return data
    return None


def snapshot(data: HeizplanData) -> dict[str, Any]:
    """Gesamter Zustand für das Panel."""
    store = data.store
    flags = data.flags()
    return {
        "profiles": [
            {**p.as_dict(), "usage": [{"room": r, "day": d} for r, d in store.usage(p.id)]}
            for p in store.profiles.values()
        ],
        "rooms": [r.as_dict() for r in store.rooms.values()],
        "days": [{"id": d, "label": DAY_LABELS[d]} for d in (*WEEKDAYS, *SPECIAL_DAYS)],
        "flags": {
            "workday_entity": data.options.get(OPT_WORKDAY_ENTITY),
            "homeoffice_entity": data.options.get(OPT_HOMEOFFICE_ENTITY),
            "workday": flags.workday,
            "homeoffice": flags.homeoffice,
        },
        "limits": {
            "temp_min": TEMP_MIN,
            "temp_max": TEMP_MAX,
            "temp_step": TEMP_STEP,
            "max_points": MAX_POINTS,
        },
    }


def _data_or_error(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> HeizplanData | None:
    data = loaded_data(hass)
    if data is None:
        connection.send_error(msg["id"], "not_loaded", "Heizplan ist nicht eingerichtet")
    return data


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/subscribe"})
@callback
def ws_subscribe(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    if (data := _data_or_error(hass, connection, msg)) is None:
        return

    @callback
    def _send() -> None:
        if (current := loaded_data(hass)) is not None:
            connection.send_message(websocket_api.event_message(msg["id"], snapshot(current)))

    connection.subscriptions[msg["id"]] = async_dispatcher_connect(hass, SIGNAL_UPDATED, _send)
    connection.send_result(msg["id"])
    connection.send_message(websocket_api.event_message(msg["id"], snapshot(data)))


async def _run(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    action: Any,
) -> None:
    if (data := _data_or_error(hass, connection, msg)) is None:
        return
    try:
        result = await action(data)
    except PlanError as err:
        connection.send_error(msg["id"], "invalid", str(err))
        return
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/profile/save",
        vol.Required("profile"): dict,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_save_profile(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    async def action(data: HeizplanData) -> dict[str, Any]:
        profile = await data.store.async_save_profile(msg["profile"])
        return {"id": profile.id}

    await _run(hass, connection, msg, action)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/profile/delete",
        vol.Required("profile_id"): cv.string,
        vol.Optional("replacement"): vol.Any(None, cv.string),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_delete_profile(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    async def action(data: HeizplanData) -> None:
        await data.store.async_delete_profile(msg["profile_id"], msg.get("replacement"))

    await _run(hass, connection, msg, action)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/room/save",
        vol.Required("room"): dict,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_save_room(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    async def action(data: HeizplanData) -> dict[str, Any]:
        room, created = await data.store.async_save_room(msg["room"])
        return {"key": room.key, "created": created}

    await _run(hass, connection, msg, action)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/room/delete",
        vol.Required("key"): cv.string,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_delete_room(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    async def action(data: HeizplanData) -> None:
        await data.store.async_delete_room(msg["key"])

    await _run(hass, connection, msg, action)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/assign",
        vol.Required("key"): cv.string,
        vol.Required("days"): [DAY],
        vol.Required("profile"): vol.Any(None, cv.string),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_assign(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    async def action(data: HeizplanData) -> None:
        await data.store.async_assign(msg["key"], msg["days"], msg["profile"])

    await _run(hass, connection, msg, action)
