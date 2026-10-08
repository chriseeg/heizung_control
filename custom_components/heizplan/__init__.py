"""Heizplan: Tagesprofile pro Raum und Wochentag, wie bei Eve, aber in Home Assistant.

Die Integration rechnet nur aus, was der Plan gerade sagt (sensor.heizplan_<raum>).
Was das Thermostat daraus macht (Fenster, Anwesenheit, Urlaub), entscheidet die
Konfiguration, die den Sensor liest.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_OFF, STATE_ON, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .const import DOMAIN, OPT_HOMEOFFICE_ENTITY, OPT_WORKDAY_ENTITY, SIGNAL_UPDATED
from .plan import DayFlags
from .services import async_setup_services
from .store import PlanStore
from .websocket_api import async_register_websocket_api

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

PANEL_URL_PATH = "heizplan"
PANEL_COMPONENT = "heizplan-panel"
STATIC_URL = "/heizplan_static"
FRONTEND_DIR = Path(__file__).parent / "frontend"

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass(slots=True)
class HeizplanData:
    """Laufzeitdaten des Config Entries."""

    hass: HomeAssistant
    store: PlanStore
    options: dict[str, Any]

    @property
    def flag_entities(self) -> list[str]:
        return [
            e
            for e in (
                self.options.get(OPT_WORKDAY_ENTITY),
                self.options.get(OPT_HOMEOFFICE_ENTITY),
            )
            if e
        ]

    def _flag(self, option: str) -> bool | None:
        entity_id = self.options.get(option)
        if not entity_id or (state := self.hass.states.get(entity_id)) is None:
            return None
        if state.state == STATE_ON:
            return True
        if state.state == STATE_OFF:
            return False
        return None

    def flags(self) -> DayFlags:
        return DayFlags(
            workday=self._flag(OPT_WORKDAY_ENTITY),
            homeoffice=self._flag(OPT_HOMEOFFICE_ENTITY),
        )


type HeizplanConfigEntry = ConfigEntry[HeizplanData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Dienste, Websocket-API und Dateien des Panels registrieren (einmalig)."""
    async_setup_services(hass)
    async_register_websocket_api(hass)
    await hass.http.async_register_static_paths(
        [StaticPathConfig(STATIC_URL, str(FRONTEND_DIR), cache_headers=False)]
    )
    return True


async def _async_register_panel(hass: HomeAssistant) -> None:
    integration = await async_get_integration(hass, DOMAIN)
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name=PANEL_COMPONENT,
        sidebar_title="Heizpläne",
        sidebar_icon="mdi:calendar-clock",
        # Version im URL: Browser lädt nach einem Update die neue Datei
        module_url=f"{STATIC_URL}/heizplan-panel.js?v={integration.version}",
        require_admin=False,
    )


async def async_setup_entry(hass: HomeAssistant, entry: HeizplanConfigEntry) -> bool:
    """Config Entry einrichten."""
    store = PlanStore(hass)
    await store.async_load()
    entry.runtime_data = HeizplanData(hass=hass, store=store, options=dict(entry.options))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(
        store.async_add_listener(lambda: async_dispatcher_send(hass, SIGNAL_UPDATED))
    )
    await _async_register_panel(hass)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: HeizplanConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: HeizplanConfigEntry) -> bool:
    """Config Entry entladen."""
    frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
