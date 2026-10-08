"""Ein Sensor pro Raum: Solltemperatur laut Plan, mit Profil und nächstem Wechsel."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import UnitOfTemperature
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_point_in_time, async_track_state_change_event
from homeassistant.util import dt as dt_util

from . import HeizplanConfigEntry, HeizplanData
from .const import DAY_LABELS, SIGNAL_UPDATED, room_device_identifier
from .plan import PlanState, evaluate


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HeizplanConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    data = entry.runtime_data
    known: set[str] = set()

    @callback
    def _sync_rooms() -> None:
        new = [RoomPlanSensor(data, key) for key in data.store.rooms if key not in known]
        known.update(e.room_key for e in new)
        if new:
            async_add_entities(new)
        dev_reg = dr.async_get(hass)
        for key, room in data.store.rooms.items():
            device = dev_reg.async_get_device_by_identifier(
                room_device_identifier(key), config_entry_id=entry.entry_id
            )
            if device is not None and device.name != device_name(room.name):
                dev_reg.async_update_device(device.id, name=device_name(room.name))
        for key in list(known - data.store.rooms.keys()):
            known.discard(key)
            device = dev_reg.async_get_device_by_identifier(
                room_device_identifier(key), config_entry_id=entry.entry_id
            )
            if device is not None:
                dev_reg.async_update_device(device.id, remove_config_entry_id=entry.entry_id)

    _sync_rooms()
    entry.async_on_unload(async_dispatcher_connect(hass, SIGNAL_UPDATED, _sync_rooms))


def device_name(room_name: str) -> str:
    return f"{room_name} Heizplan"


class RoomPlanSensor(SensorEntity):
    """Solltemperatur laut Heizplan für einen Raum."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_should_poll = False
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_suggested_display_precision = 1
    _attr_translation_key = "plan"

    def __init__(self, data: HeizplanData, room_key: str) -> None:
        self._data = data
        self.room_key = room_key
        room = data.store.rooms[room_key]
        self._attr_unique_id = f"room_{room_key}"
        # Gerät "<Raum> Heizplan" im Bereich des Raums; die Entity-ID trägt das
        # Feature-Präfix, damit Templates sensor.heizplan_<kürzel> nutzen können.
        self.entity_id = f"sensor.heizplan_{room_key}"
        self._attr_device_info = DeviceInfo(
            identifiers={room_device_identifier(room_key)},
            name=device_name(room.name),
            manufacturer="Heizplan",
            model="Raum",
            suggested_area=room.name,
            entry_type=dr.DeviceEntryType.SERVICE,
        )
        self._state: PlanState | None = None
        self._unsub_timer: CALLBACK_TYPE | None = None

    @property
    def available(self) -> bool:
        return self._state is not None

    @property
    def native_value(self) -> float | None:
        return self._state.temp if self._state else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        state = self._state
        if state is None:
            return {"raum": self.room_key}
        return {
            "raum": self.room_key,
            "profil": state.profile.name,
            "profil_id": state.profile.id,
            "tag": DAY_LABELS.get(state.day_kind, state.day_kind),
            "tagestyp": state.day_kind,
            "seit": state.since.isoformat(),
            "naechster_wechsel": state.next_change.isoformat() if state.next_change else None,
            "naechste_temperatur": state.next_temp,
            "heute": [{"at": p.at, "temp": p.temp} for p in state.profile.points],
        }

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(self.hass, SIGNAL_UPDATED, self._refresh))
        if self._data.flag_entities:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, self._data.flag_entities, self._flag_changed
                )
            )
        self.async_on_remove(self._cancel_timer)
        self._recompute()

    @callback
    def _cancel_timer(self) -> None:
        if self._unsub_timer is not None:
            self._unsub_timer()
            self._unsub_timer = None

    @callback
    def _flag_changed(self, event: Event[EventStateChangedData]) -> None:
        self._refresh()

    @callback
    def _timer(self, now: datetime) -> None:
        self._unsub_timer = None
        self._refresh()

    @callback
    def _refresh(self) -> None:
        if self.room_key not in self._data.store.rooms:
            # Raum gelöscht: _sync_rooms entfernt Gerät und Entität
            self._cancel_timer()
            return
        self._recompute()
        self.async_write_ha_state()

    @callback
    def _recompute(self) -> None:
        room = self._data.store.rooms[self.room_key]
        self._state = evaluate(room, self._data.store.profiles, dt_util.now(), self._data.flags())
        self._cancel_timer()
        if self._state is not None:
            self._unsub_timer = async_track_point_in_time(
                self.hass, self._timer, self._state.refresh_at
            )
        else:
            # Kein Profil für heute: um Mitternacht erneut prüfen
            self._unsub_timer = async_track_point_in_time(
                self.hass, self._timer, dt_util.start_of_local_day() + timedelta(days=1)
            )
