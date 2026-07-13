"""Config flow for Shower Active."""
from __future__ import annotations

import uuid

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    DOMAIN,
    CONF_SHOWERS,
    CONF_ID,
    CONF_SENSOR,
    CONF_NAME,
    CONF_THRESHOLD,
    CONF_DECLINE_COUNT,
    DEFAULT_THRESHOLD,
    DEFAULT_DECLINE_COUNT,
)


class ShowerActiveConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Shower Active."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(
                title=user_input.get("title", "Shower Active"),
                data=user_input,
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("title", default="Shower Active"): str,
                }
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return ShowerActiveOptionsFlow(config_entry)


class ShowerActiveOptionsFlow(config_entries.OptionsFlow):
    """Handle options for Shower Active (add/remove shower sensors)."""

    def __init__(self, config_entry):
        self._showers = list(
            config_entry.options.get(CONF_SHOWERS, [])
        )

    async def async_step_init(self, user_input=None):
        """Show current showers and allow adding/removing."""
        return await self.async_step_menu()

    async def async_step_menu(self, user_input=None):
        shower_summary = "\n".join(
            f"- {s[CONF_NAME]} ({s[CONF_SENSOR]})"
            for s in self._showers
        ) or "No showers configured yet."

        return self.async_show_menu(
            step_id="menu",
            menu_options=["add_shower", "remove_shower", "finish"],
            description_placeholders={"showers": shower_summary},
        )

    async def async_step_add_shower(self, user_input=None):
        if user_input is not None:
            self._showers.append({
                CONF_ID: uuid.uuid4().hex,
                CONF_NAME: user_input[CONF_NAME],
                CONF_SENSOR: user_input[CONF_SENSOR],
                CONF_THRESHOLD: user_input[CONF_THRESHOLD],
                CONF_DECLINE_COUNT: user_input[CONF_DECLINE_COUNT],
            })
            return await self.async_step_menu()

        return self.async_show_form(
            step_id="add_shower",
            data_schema=vol.Schema({
                vol.Required(CONF_NAME): str,
                vol.Required(CONF_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(device_class="humidity")
                ),
                vol.Optional(CONF_THRESHOLD, default=DEFAULT_THRESHOLD): vol.Coerce(float),
                vol.Optional(CONF_DECLINE_COUNT, default=DEFAULT_DECLINE_COUNT): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=10)
                ),
            }),
        )

    async def async_step_remove_shower(self, user_input=None):
        if not self._showers:
            return await self.async_step_menu()

        if user_input is not None:
            id_to_remove = user_input.get("shower")
            self._showers = [
                s for s in self._showers if self._shower_key(s) != id_to_remove
            ]
            return await self.async_step_menu()

        return self.async_show_form(
            step_id="remove_shower",
            data_schema=vol.Schema({
                vol.Required("shower"): vol.In(
                    {
                        self._shower_key(s): f"{s[CONF_NAME]} ({s[CONF_SENSOR]})"
                        for s in self._showers
                    }
                ),
            }),
        )

    @staticmethod
    def _shower_key(shower: dict) -> str:
        # Showers added before per-shower ids existed fall back to name
        return shower.get(CONF_ID, shower[CONF_NAME])

    async def async_step_finish(self, user_input=None):
        return self.async_create_entry(
            title="",
            data={CONF_SHOWERS: self._showers},
        )
