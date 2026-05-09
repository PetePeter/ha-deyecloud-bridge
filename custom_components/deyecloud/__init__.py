from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .api import DeyeCloudClient
from .const import (
    DOMAIN,
    CONF_APP_ID, CONF_APP_SECRET, CONF_EMAIL, CONF_PASSWORD,
    CONF_SERVER, CONF_DEVICE_SN, CONF_RATED_POWER, CONF_REFRESH_INTERVAL,
    DEFAULT_RATED_POWER, DEFAULT_REFRESH_INTERVAL, DEFAULT_SERVER,
)
from .coordinator import DeyeCoordinator

PLATFORMS = ["sensor", "select"]


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
    coordinator = DeyeCoordinator(
        hass, client,
        refresh_interval=int(entry.data.get(CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL)),
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
        return True
    return False
