"""Dienste für Automationen: Profil an Tagen eines Raums zuweisen."""

from __future__ import annotations

from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
import voluptuous as vol

from .const import DOMAIN, SPECIAL_DAYS, WEEKDAYS
from .plan import PlanError

SERVICE_ASSIGN = "assign"

ASSIGN_SCHEMA = vol.Schema(
    {
        vol.Required("raum"): vol.All(cv.ensure_list, [cv.string]),
        vol.Required("tage"): vol.All(cv.ensure_list, [vol.In([*WEEKDAYS, *SPECIAL_DAYS])]),
        vol.Required("profil"): vol.Any(None, cv.string),
    }
)


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    async def _assign(call: ServiceCall) -> None:
        from .websocket_api import loaded_data  # noqa: PLC0415

        data = loaded_data(hass)
        if data is None:
            raise ServiceValidationError("Heizplan ist nicht eingerichtet")
        try:
            for key in call.data["raum"]:
                await data.store.async_assign(key, call.data["tage"], call.data["profil"])
        except PlanError as err:
            raise ServiceValidationError(str(err)) from err

    hass.services.async_register(DOMAIN, SERVICE_ASSIGN, _assign, schema=ASSIGN_SCHEMA)
