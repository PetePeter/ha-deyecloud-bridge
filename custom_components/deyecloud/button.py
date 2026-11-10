from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, CONF_DEVICE_SN
from .coordinator import DeyeCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: DeyeCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([DeyeRefreshSettingsButton(coordinator, entry.data[CONF_DEVICE_SN])])


class DeyeRefreshSettingsButton(ButtonEntity):
    """Re-read every inverter setting now instead of waiting for the 15-minute cycle."""

    _attr_has_entity_name = True
    _attr_name = "Refresh Settings"
    _attr_icon = "mdi:refresh"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: DeyeCoordinator, sn: str):
        self._coordinator = coordinator
        self._attr_unique_id = f"{sn}_refresh_settings"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, sn)},
            name="Deye Inverter",
            manufacturer="Deye",
            model=sn,
        )

    async def async_press(self) -> None:
        self._coordinator.mark_config_dirty()
        await self._coordinator.async_refresh()
