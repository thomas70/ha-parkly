"""Config flow for Parkly."""
from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlowWithReload
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .api import ParklyApi, ParklyAuthError, ParklyConnectionError
from .const import (
    CONF_FAST_INTERVAL,
    CONF_SLOW_INTERVAL,
    CONF_WEEKENDS,
    CONF_WORK_END,
    CONF_WORK_START,
    DEFAULTS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema({vol.Required(CONF_EMAIL): str, vol.Required(CONF_PASSWORD): str})


def _number(low: int, high: int, unit: str) -> NumberSelector:
    return NumberSelector(NumberSelectorConfig(min=low, max=high, step=1, mode=NumberSelectorMode.BOX,
                                               unit_of_measurement=unit))


OPTIONS_SCHEMA = vol.Schema({
    vol.Required(CONF_FAST_INTERVAL): _number(30, 3600, "s"),
    vol.Required(CONF_SLOW_INTERVAL): _number(1, 240, "min"),
    vol.Required(CONF_WORK_START): _number(0, 23, "h"),
    vol.Required(CONF_WORK_END): _number(1, 24, "h"),
    vol.Required(CONF_WEEKENDS): BooleanSelector(),
})


class ParklyConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> ParklyOptionsFlow:
        return ParklyOptionsFlow()

    async def _check(self, user_input: dict[str, Any]) -> tuple[dict[str, str], list[dict[str, Any]]]:
        """Log in and fetch permits. Returns (errors, permits)."""
        api = ParklyApi(async_get_clientsession(self.hass), user_input[CONF_EMAIL], user_input[CONF_PASSWORD])
        try:
            await api.login()
            permits = await api.get_permits()
        except ParklyAuthError:
            return {"base": "auth"}, []
        except ParklyConnectionError:
            return {"base": "cannot_connect"}, []
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unexpected error during Parkly login")
            return {"base": "unknown"}, []
        if not permits:
            return {"base": "no_permits"}, []
        return {}, permits

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_EMAIL].strip().lower())
            self._abort_if_unique_id_configured()
            errors, permits = await self._check(user_input)
            if not errors:
                company = permits[0].get("companyName")
                return self.async_create_entry(
                    title=f"Parkly ({company})" if company else "Parkly", data=user_input
                )
        return self.async_show_form(step_id="user", data_schema=USER_SCHEMA, errors=errors)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            errors, _ = await self._check(user_input)
            if not errors:
                return self.async_update_reload_and_abort(entry, data_updates=user_input)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, {CONF_EMAIL: entry.data.get(CONF_EMAIL)}),
            errors=errors,
        )


class ParklyOptionsFlow(OptionsFlowWithReload):
    """How often to poll, and when working hours are."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            # Number selectors return floats; store whole numbers.
            data = {k: (int(v) if isinstance(v, float) else v) for k, v in user_input.items()}
            if data[CONF_WORK_START] >= data[CONF_WORK_END]:
                errors["base"] = "work_hours"
            else:
                return self.async_create_entry(data=data)
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                OPTIONS_SCHEMA, {**DEFAULTS, **self.config_entry.options, **(user_input or {})}
            ),
            errors=errors,
        )
