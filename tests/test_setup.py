"""Setup and config flow tests with the Parkly API mocked."""
from datetime import datetime
from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parkly.api import ParklyAuthError
from custom_components.parkly.const import DOMAIN
from custom_components.parkly.coordinator import poll_interval

PERMITS = [
    {"id": 594, "serviceName": "Avtaleparkering: Sone 1 & 3", "totalServiceSpaceCount": 25,
     "activeServiceSpaceCount": 7, "parkingLotName": "Mustad Næringspark", "companyName": "SYKEHUSPARTNER HF",
     "areas": [{"id": 150, "name": "Uteparkering - Område 1"}, {"id": 158, "name": "Uteparkering - Område 3"}]},
    {"id": 595, "serviceName": "Avtaleparkering: Sone 2", "totalServiceSpaceCount": 2,
     "activeServiceSpaceCount": 2, "parkingLotName": "Mustad Næringspark", "companyName": "SYKEHUSPARTNER HF",
     "areas": [{"id": 157, "name": "Uteparkering - Område 2"}]},
]
API = "custom_components.parkly.api.ParklyApi"
CREDS = {CONF_EMAIL: "a@b.c", CONF_PASSWORD: "pw"}


async def test_config_flow_creates_entry(hass):
    with patch(f"{API}.login", AsyncMock()), patch(f"{API}.get_permits", AsyncMock(return_value=PERMITS)):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        assert result["type"] is FlowResultType.FORM
        result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Parkly (SYKEHUSPARTNER HF)"


async def test_wrong_password(hass):
    with patch(f"{API}.login", AsyncMock(side_effect=ParklyAuthError("nope"))):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "auth"}


async def test_sensors_keep_old_entity_ids(hass):
    entry = MockConfigEntry(domain=DOMAIN, data=CREDS, unique_id="a@b.c")
    entry.add_to_hass(hass)
    with patch(f"{API}.get_permits", AsyncMock(return_value=PERMITS)):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    expect = {
        "sensor.parkly_sone1_benyttet": "7", "sensor.parkly_sone1_antall": "25",
        "sensor.parkly_sone1_ledige": "18", "sensor.parkly_sone1_displaynavn": "7/25",
        "sensor.parkly_sone1_navn": "Avtaleparkering: Sone 1 & 3",
        "sensor.parkly_sone2_benyttet": "2", "sensor.parkly_sone2_ledige": "0",
        "sensor.parkly_sone2_displaynavn": "2/2",
    }
    for entity_id, value in expect.items():
        assert hass.states.get(entity_id).state == value, entity_id
    attrs = hass.states.get("sensor.parkly_sone1_benyttet").attributes
    assert attrs["områder"] == ["Uteparkering - Område 1", "Uteparkering - Område 3"]


async def test_auth_failure_starts_reauth(hass):
    entry = MockConfigEntry(domain=DOMAIN, data=CREDS, unique_id="a@b.c")
    entry.add_to_hass(hass)
    with patch(f"{API}.get_permits", AsyncMock(side_effect=ParklyAuthError("expired"))):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert any(f["context"]["source"] == "reauth" for f in hass.config_entries.flow.async_progress())


def test_poll_interval():
    assert poll_interval(datetime(2026, 10, 14, 10, 0)).total_seconds() == 60  # Wednesday 10:00
    assert poll_interval(datetime(2026, 10, 14, 18, 0)).total_seconds() == 900  # evening
    assert poll_interval(datetime(2026, 10, 18, 10, 0)).total_seconds() == 900  # Sunday
    assert poll_interval(datetime(2026, 10, 14, 6, 55)).total_seconds() == 300  # wake at 07:00
