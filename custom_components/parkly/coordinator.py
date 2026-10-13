"""Polling coordinator for Parkly."""
from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import ParklyApi, ParklyAuthError, ParklyError
from .const import DOMAIN, FAST_INTERVAL, SLOW_INTERVAL, WORK_DAYS, WORK_END, WORK_START

_LOGGER = logging.getLogger(__name__)


def poll_interval(now) -> timedelta:
    """Every minute on weekdays 07–17, otherwise every 15 minutes (but wake up at 07)."""
    workday = now.weekday() in WORK_DAYS
    if workday and WORK_START <= now.hour < WORK_END:
        return timedelta(seconds=FAST_INTERVAL)
    slow = timedelta(seconds=SLOW_INTERVAL)
    if workday and now.hour < WORK_START:
        start = now.replace(hour=WORK_START, minute=0, second=0, microsecond=0)
        return max(timedelta(seconds=FAST_INTERVAL), min(slow, start - now))
    return slow


class ParklyCoordinator(DataUpdateCoordinator[dict[int, dict[str, Any]]]):
    """Fetches the agreement permits; data is {permit id: permit}."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: ParklyApi) -> None:
        super().__init__(
            hass, _LOGGER, name=DOMAIN, config_entry=entry,
            update_interval=poll_interval(dt_util.now()),
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
            self.update_interval = poll_interval(dt_util.now())
        return {p["id"]: p for p in permits if "id" in p}
