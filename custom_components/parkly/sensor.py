"""Occupancy sensors per agreement zone, plus where my own car is."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import ParklyConfigEntry
from .const import DOMAIN
from .coordinator import ParklyCoordinator, parked_zone

NOT_PARKED = "Ikke parkert"


def _total(p: dict[str, Any]) -> int | None:
    return p.get("totalServiceSpaceCount")


def _used(p: dict[str, Any]) -> int | None:
    return p.get("activeServiceSpaceCount")


def _free(p: dict[str, Any]) -> int | None:
    total, used = _total(p), _used(p)
    return None if total is None or used is None else max(0, total - used)


def _display(p: dict[str, Any]) -> str | None:
    total, used = _total(p), _used(p)
    return None if total is None or used is None else f"{used}/{total}"


@dataclass(frozen=True, kw_only=True)
class ParklySensorDescription(SensorEntityDescription):
    value: Callable[[dict[str, Any]], Any]


# Keys match the old YAML sensors (sensor.parkly_sone<n>_<key>) so dashboards keep working.
SENSORS = (
    ParklySensorDescription(key="benyttet", translation_key="benyttet", icon="mdi:car",
                            state_class=SensorStateClass.MEASUREMENT, value=_used),
    ParklySensorDescription(key="ledige", translation_key="ledige", icon="mdi:parking",
                            state_class=SensorStateClass.MEASUREMENT, value=_free),
    ParklySensorDescription(key="antall", translation_key="antall", icon="mdi:counter",
                            value=_total),
    ParklySensorDescription(key="displaynavn", translation_key="displaynavn", icon="mdi:car-multiple",
                            value=_display),
    ParklySensorDescription(key="navn", translation_key="navn", icon="mdi:sign-text",
                            value=lambda p: p.get("serviceName")),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ParklyConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        ParklySensor(coordinator, permit_id, zone, desc)
        for zone, permit_id in enumerate(sorted(coordinator.data), start=1)
        for desc in SENSORS
    )
    async_add_entities([MyCarSensor(coordinator), LastParkingSensor(coordinator)])


def _short(service_name: str | None) -> str | None:
    """'Avtaleparkering: Sone 1 & 3' -> 'Sone 1 & 3'."""
    return service_name.split(":", 1)[-1].strip() if service_name else None


class ParklySensor(CoordinatorEntity[ParklyCoordinator], SensorEntity):
    _attr_has_entity_name = True
    entity_description: ParklySensorDescription

    def __init__(self, coordinator: ParklyCoordinator, permit_id: int, zone: int,
                 desc: ParklySensorDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = desc
        self._permit_id = permit_id
        self._attr_unique_id = f"{permit_id}_{desc.key}"
        # Only a suggestion: after the first start the entity registry owns the id.
        self.entity_id = f"sensor.parkly_sone{zone}_{desc.key}"
        p = coordinator.data[permit_id]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(permit_id))},
            name=p.get("serviceName") or f"Parkly sone {zone}",
            manufacturer="Parkly",
            model=p.get("parkingLotName"),
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def _permit(self) -> dict[str, Any] | None:
        return (self.coordinator.data or {}).get(self._permit_id)

    @property
    def available(self) -> bool:
        return super().available and self._permit is not None

    @property
    def native_value(self) -> Any:
        return self.entity_description.value(self._permit) if self._permit else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        p = self._permit
        if not p or self.entity_description.key != "benyttet":
            return None
        return {
            "parkeringsplass": p.get("parkingLotName"),
            "områder": [a.get("name") for a in p.get("areas") or []],
            "firma": p.get("companyName"),
        }


class ParklyAccountSensor(CoordinatorEntity[ParklyCoordinator], SensorEntity):
    """Sensors about the account's own car (one device per Parkly account)."""

    _attr_has_entity_name = True
    key: str

    def __init__(self, coordinator: ParklyCoordinator) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_translation_key = self.key
        self._attr_unique_id = f"{entry.unique_id}_{self.key}"
        self.entity_id = f"sensor.parkly_{self.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
            name="Parkly",
            manufacturer="Parkly",
            entry_type=DeviceEntryType.SERVICE,
        )


class MyCarSensor(ParklyAccountSensor):
    """Zone my car is parked in now, or «Ikke parkert»."""

    key = "min_bil"

    @property
    def _zone(self) -> dict[str, Any] | None:
        return parked_zone(self.coordinator.data or {})

    @property
    def icon(self) -> str:
        return "mdi:car-brake-parking" if self._zone else "mdi:car-off"

    @property
    def native_value(self) -> str:
        zone = self._zone
        return (_short(zone.get("serviceName")) or "Parkert") if zone else NOT_PARKED

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        zone = self._zone
        if not zone:
            return {"skilt": []}
        return {
            "skilt": zone.get("activeLicensePlatesForAssignment"),
            "parkeringsplass": zone.get("parkingLotName"),
            "områder": [a.get("name") for a in zone.get("areas") or []],
        }


class LastParkingSensor(ParklyAccountSensor):
    """Start of the last finished parking (shorter stops ignored)."""

    key = "siste_parkering"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:history"

    @property
    def native_value(self) -> Any:
        last = self.coordinator.last_parking
        return last["start"] if last else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        last = self.coordinator.last_parking
        if not last:
            return None
        return {
            "område": last.get("parkingLotAreaName"),
            "sone": _short(last.get("serviceName")),
            "parkeringsplass": last.get("parkingLotName"),
            "slutt": last["end"].isoformat(),
            "varighet_min": round((last["end"] - last["start"]).total_seconds() / 60),
            "skilt": last.get("licensePlateNumber"),
        }
