"""Persistenz von Profilen und Räumen."""

from __future__ import annotations

from collections.abc import Callable
import logging
from typing import Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.util import slugify

from .const import STORAGE_KEY, STORAGE_VERSION
from .plan import PlanError, Profile, Room, clean_key, default_profiles

_LOGGER = logging.getLogger(__name__)

type StoreListener = Callable[[], None]


class PlanStore:
    """Profile und Räume, gespeichert in .storage/heizplan.data."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.profiles: dict[str, Profile] = {}
        self.rooms: dict[str, Room] = {}
        self._listeners: list[StoreListener] = []

    async def async_load(self) -> None:
        raw = await self._store.async_load()
        if raw is None:
            self.profiles = {p.id: p for p in default_profiles()}
            await self._async_save()
            return
        for item in raw.get("profiles", []):
            try:
                profile = Profile.from_dict(item)
            except PlanError as err:
                _LOGGER.warning("Profil verworfen (%s): %s", err, item)
                continue
            self.profiles[profile.id] = profile
        for item in raw.get("rooms", []):
            try:
                room = Room.from_dict(item, self.profiles)
            except PlanError as err:
                _LOGGER.warning("Raum verworfen (%s): %s", err, item)
                continue
            self.rooms[room.key] = room

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "profiles": [p.as_dict() for p in self.profiles.values()],
                "rooms": [r.as_dict() for r in self.rooms.values()],
            }
        )

    @callback
    def async_add_listener(self, listener: StoreListener) -> CALLBACK_TYPE:
        self._listeners.append(listener)

        @callback
        def _remove() -> None:
            self._listeners.remove(listener)

        return _remove

    async def _async_changed(self) -> None:
        await self._async_save()
        for listener in list(self._listeners):
            listener()

    def new_profile_id(self, name: str) -> str:
        base = (slugify(name) or "profil")[:28]
        key, n = base, 2
        while key in self.profiles:
            key, n = f"{base}_{n}", n + 1
        return key

    def usage(self, profile_id: str) -> list[tuple[str, str]]:
        """(Raum, Tag) für jede Verwendung eines Profils."""
        return [
            (room.key, day)
            for room in self.rooms.values()
            for day, pid in room.days.items()
            if pid == profile_id
        ]

    async def async_save_profile(self, raw: dict[str, Any]) -> Profile:
        data = dict(raw)
        if not data.get("id"):
            data["id"] = self.new_profile_id(str(data.get("name", "")))
        profile = Profile.from_dict(data)
        self.profiles[profile.id] = profile
        await self._async_changed()
        return profile

    async def async_delete_profile(self, profile_id: str, replacement: str | None) -> None:
        if profile_id not in self.profiles:
            raise PlanError("Profil gibt es nicht")
        used = self.usage(profile_id)
        if used and (replacement is None or replacement not in self.profiles):
            raise PlanError("Profil wird noch verwendet, bitte Ersatz wählen")
        if replacement == profile_id:
            raise PlanError("Ersatz muss ein anderes Profil sein")
        for room_key, day in used:
            self.rooms[room_key].days[day] = replacement
        del self.profiles[profile_id]
        await self._async_changed()

    async def async_save_room(self, raw: dict[str, Any]) -> tuple[Room, bool]:
        """Raum anlegen oder ändern. Ein Wochentag ohne Profil macht den Sensor an dem Tag
        nicht verfügbar; das Panel belegt deshalb beim Anlegen alle Wochentage vor."""
        room = Room.from_dict(raw, self.profiles)
        created = room.key not in self.rooms
        self.rooms[room.key] = room
        await self._async_changed()
        return room, created

    async def async_assign(self, key: str, days: list[str], profile_id: str | None) -> Room:
        key = clean_key(key)
        if (room := self.rooms.get(key)) is None:
            raise PlanError("Raum gibt es nicht")
        if profile_id is not None and profile_id not in self.profiles:
            raise PlanError("Profil gibt es nicht")
        for day in days:
            if day not in room.days:
                raise PlanError(f"Unbekannter Tag: {day}")
            room.days[day] = profile_id
        await self._async_changed()
        return room

    async def async_delete_room(self, key: str) -> None:
        if self.rooms.pop(key, None) is None:
            raise PlanError("Raum gibt es nicht")
        await self._async_changed()
