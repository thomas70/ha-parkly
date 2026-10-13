"""Polling coordinator for Parkly."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import ParklyApi, ParklyAuthError, ParklyError
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


def poll_interval(now, options: Mapping[str, Any] | None = None) -> timedelta:
    """Fast during working hours, slow otherwise (but wake up when work starts)."""
    o = {**DEFAULTS, **(options or {})}
    fast = timedelta(seconds=o[CONF_FAST_INTERVAL])
    slow = timedelta(minutes=o[CONF_SLOW_INTERVAL])
    workday = o[CONF_WEEKENDS] or now.weekday() < 5
    if workday and o[CONF_WORK_START] <= now.hour < o[CONF_WORK_END]:
        return fast
    if workday and now.hour < o[CONF_WORK_START]:
        start = now.replace(hour=o[CONF_WORK_START], minute=0, second=0, microsecond=0)
        return max(fast, min(slow, start - now))
    return slow


class ParklyCoordinator(DataUpdateCoordinator[dict[int, dict[str, Any]]]):
    """Fetches the agreement permits; data is {permit id: permit}."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: ParklyApi) -> None:
        super().__init__(
            hass, _LOGGER, name=DOMAIN, config_entry=entry,
            update_interval=poll_interval(dt_util.now(), entry.options),
        )
        self.api = api

    async def _async_update_data(self) -> dict[int, dict[str, Any]]:
        try:
            permits = await self.api.get_permits()
        except ParklyAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except ParklyError as err:
            raise UpdateFailed(str(err)) from err
        finally:
            self.update_interval = poll_interval(dt_util.now(), self.config_entry.options)
        return {p["id"]: p for p in permits if "id" in p}
