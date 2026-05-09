import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import DeyeApiError
from .const import DOMAIN, CONF_DEVICE_SN, WORK_MODES, WORK_MODE_LABELS
from .coordinator import DeyeCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: DeyeCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([DeyeWorkModeSelect(coordinator, entry)])


class DeyeWorkModeSelect(SelectEntity):
    _attr_has_entity_name = True
    _attr_name = "Work Mode"
    _attr_icon = "mdi:solar-power-variant"
    _attr_options = list(WORK_MODE_LABELS.values())

    def __init__(self, coordinator: DeyeCoordinator, entry: ConfigEntry):
        self._coordinator = coordinator
        self._device_sn = entry.data[CONF_DEVICE_SN]
        self._attr_unique_id = f"{self._device_sn}_work_mode"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._device_sn)},
            name="Deye Inverter",
            manufacturer="Deye",
            model=self._device_sn,
        )
        self._current_option = WORK_MODE_LABELS["ZERO_EXPORT_TO_CT"]

    @property
    def current_option(self) -> str:
        return self._current_option

    async def async_select_option(self, option: str) -> None:
        mode_key = next(k for k, v in WORK_MODE_LABELS.items() if v == option)
        try:
            await self._coordinator.hass.async_add_executor_job(
                self._coordinator.client.set_work_mode, mode_key
            )
            self._current_option = option
            self.async_write_ha_state()
        except DeyeApiError as e:
            _LOGGER.error("Failed to set work mode: %s", e)
