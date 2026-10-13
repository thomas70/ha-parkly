"""Parkly integration: agreement parking occupancy (read-only, cloud polling)."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ParklyApi
from .coordinator import ParklyCoordinator

PLATFORMS = [Platform.SENSOR]

type ParklyConfigEntry = ConfigEntry[ParklyCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: ParklyConfigEntry) -> bool:
    api = ParklyApi(async_get_clientsession(hass), entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD])
    coordinator = ParklyCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ParklyConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
