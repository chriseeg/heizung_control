"""Config Flow und Optionen."""

from __future__ import annotations

from typing import Any, override

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import EntitySelector, EntitySelectorConfig
import voluptuous as vol

from .const import DOMAIN, OPT_HOMEOFFICE_ENTITY, OPT_WORKDAY_ENTITY

TITLE = "Heizplan"


def _schema(defaults: dict[str, Any]) -> vol.Schema:
    selector = EntitySelector(EntitySelectorConfig(domain=["binary_sensor", "input_boolean"]))
    fields: dict[Any, Any] = {}
    for key in (OPT_WORKDAY_ENTITY, OPT_HOMEOFFICE_ENTITY):
        if defaults.get(key):
            fields[vol.Optional(key, default=defaults[key])] = selector
        else:
            fields[vol.Optional(key)] = selector
    return vol.Schema(fields)


class HeizplanConfigFlow(ConfigFlow, domain=DOMAIN):
    """Ein einziger Eintrag; Räume und Profile entstehen im Panel."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title=TITLE, data={}, options=user_input)
        return self.async_show_form(step_id="user", data_schema=_schema({}))

    @staticmethod
    @callback
    @override
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return HeizplanOptionsFlow()


class HeizplanOptionsFlow(OptionsFlow):
    """Werktag- und Homeoffice-Entität ändern."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init", data_schema=_schema(dict(self.config_entry.options))
        )
