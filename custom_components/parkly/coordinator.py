"""Polling coordinator for Parkly."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
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

# Shorter stops (driving through Område 1, a minute in a full zone) are not a parking.
MIN_PARKING = timedelta(minutes=5)
HISTORY_INTERVAL = timedelta(hours=1)
HISTORY_RECHECK = timedelta(minutes=5)  # history can lag a little behind leaving


def parked_zone(permits: Mapping[int, Mapping[str, Any]]) -> dict[str, Any] | None:
    """The permit where one of the account's own cars is parked right now."""
    for permit in permits.values():
        if permit.get("activeLicensePlatesForAssignment"):
            return dict(permit)
    return None


def last_parking(activity: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Newest finished segment that lasted at least MIN_PARKING."""
    for item in activity:
        start = dt_util.parse_datetime(item.get("startTime") or "")
        end = dt_util.parse_datetime(item.get("endTime") or "")
        if start and end and end - start >= MIN_PARKING:
            return {**item, "start": start, "end": end}
    return None


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
        self.last_parking: dict[str, Any] | None = None
        self._history_at: datetime | None = None  # None = fetch on next update
        self._was_parked = False

    async def _async_update_data(self) -> dict[int, dict[str, Any]]:
        try:
            permits = await self.api.get_permits()
        except ParklyAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except ParklyError as err:
            raise UpdateFailed(str(err)) from err
        finally:
            self.update_interval = poll_interval(dt_util.now(), self.config_entry.options)
        data = {p["id"]: p for p in permits if "id" in p}
        await self._update_history(parked_zone(data) is not None)
        return data

    async def _update_history(self, parked: bool) -> None:
        """Fetch the (large) history at start, after leaving, and otherwise hourly."""
        now = dt_util.utcnow()
        left = self._was_parked and not parked
        self._was_parked = parked
        if not left and self._history_at and now < self._history_at:
            return
        try:
            self.last_parking = last_parking(await self.api.get_activity())
        except ParklyError as err:
            _LOGGER.debug("Could not fetch parking history: %s", err)
        self._history_at = now + (HISTORY_RECHECK if left else HISTORY_INTERVAL)
