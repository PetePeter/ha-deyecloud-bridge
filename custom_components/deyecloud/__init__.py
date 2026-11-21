import re

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.event import async_track_time_change

from .api import DeyeCloudClient, DeyeApiError
from .const import (
    DOMAIN,
    CONF_APP_ID, CONF_APP_SECRET, CONF_EMAIL, CONF_PASSWORD,
    CONF_SERVER, CONF_DEVICE_SN, CONF_RATED_POWER,
    DEFAULT_RATED_POWER, DEFAULT_SERVER,
    DEFAULT_REFRESH_INTERVAL, SERVICE_SET_TOU_SCHEDULE,
)
from .coordinator import DeyeCoordinator

PLATFORMS = ["binary_sensor", "sensor", "select", "number", "time", "switch", "button"]

# Minutes (clock-aligned) at which telemetry is polled — every 5 min on the hour.
_POLL_MINUTES = list(range(0, 60, DEFAULT_REFRESH_INTERVAL // 60))

_HHMM = re.compile(r"^([01]\d|2[0-3]):?[0-5]\d(:00)?$")


def _time(value) -> str:
    value = str(value).strip()
    if not _HHMM.match(value):
        raise vol.Invalid(f"time must be HH:MM, got {value!r}")
    return value[:5] if ":" in value[:3] else f"{value[:2]}:{value[2:4]}"


SLOT_SCHEMA = vol.Schema({
    vol.Required("time"): _time,
    vol.Optional("grid_charge", default=False): cv.boolean,
    vol.Optional("generator", default=False): cv.boolean,
    vol.Required("soc"): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
    vol.Optional("power"): vol.All(vol.Coerce(int), vol.Range(min=0)),
})
SET_TOU_SCHEMA = vol.Schema({
    vol.Required("slots"): vol.All(cv.ensure_list, [SLOT_SCHEMA], vol.Length(min=1, max=6)),
})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    client = DeyeCloudClient(
        app_id=entry.data[CONF_APP_ID],
        app_secret=entry.data[CONF_APP_SECRET],
        email=entry.data[CONF_EMAIL],
        password=entry.data[CONF_PASSWORD],
        device_sn=entry.data[CONF_DEVICE_SN],
        rated_power=entry.data.get(CONF_RATED_POWER, DEFAULT_RATED_POWER),
        server=entry.data.get(CONF_SERVER, DEFAULT_SERVER),
    )
    coordinator = DeyeCoordinator(hass, client)
    await coordinator.async_config_entry_first_refresh()

    # Clock-aligned telemetry poll: fires on :00/:05/:10.../:55.
    async def _poll(_now):
        await coordinator.async_request_refresh()

    entry.async_on_unload(
        async_track_time_change(hass, _poll, minute=_POLL_MINUTES, second=0)
    )

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    if not hass.services.has_service(DOMAIN, SERVICE_SET_TOU_SCHEDULE):
        async def _set_tou_schedule(call: ServiceCall) -> None:
            slots = call.data["slots"]
            for coord in list(hass.data.get(DOMAIN, {}).values()):
                try:
                    await hass.async_add_executor_job(coord.client.set_tou_slots, slots)
                except DeyeApiError as e:
                    raise HomeAssistantError(f"Deye: could not set the schedule: {e}") from e
                coord.mark_config_dirty()
                await coord.async_request_refresh()

        hass.services.async_register(
            DOMAIN, SERVICE_SET_TOU_SCHEDULE, _set_tou_schedule, schema=SET_TOU_SCHEMA
        )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, SERVICE_SET_TOU_SCHEDULE)
        return True
    return False
