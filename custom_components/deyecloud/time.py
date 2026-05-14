import logging
from datetime import time as dt_time

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import DeyeApiError
from .const import DOMAIN, CONF_DEVICE_SN
from .coordinator import DeyeCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: DeyeCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        DeyeChargeWindowTime(coordinator, entry, "start"),
        DeyeChargeWindowTime(coordinator, entry, "end"),
    ])


class DeyeChargeWindowTime(CoordinatorEntity, TimeEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: DeyeCoordinator, entry: ConfigEntry, which: str):
        super().__init__(coordinator)
        self._which = which  # "start" or "end"
        sn = entry.data[CONF_DEVICE_SN]
        self._attr_name      = f"Grid Charge {'Start' if which == 'start' else 'End'}"
        self._attr_unique_id = f"{sn}_charge_{which}"
        self._attr_icon      = "mdi:battery-charging" if which == "start" else "mdi:battery-charging-outline"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, sn)},
            name="Deye Inverter",
            manufacturer="Deye",
            model=sn,
        )

    @property
    def native_value(self) -> dt_time | None:
        key = f"charge_{self._which}"
        val = (self.coordinator.data or {}).get(key)
        if not val:
            return None
        try:
            h, m = int(val[:2]), int(val[3:])
            return dt_time(h, m)
        except (ValueError, IndexError):
            return None

    async def async_set_value(self, value: dt_time) -> None:
        data = self.coordinator.data or {}
        start = f"{value.hour:02d}:{value.minute:02d}" if self._which == "start" else data.get("charge_start", "11:00")
        end   = f"{value.hour:02d}:{value.minute:02d}" if self._which == "end"   else data.get("charge_end",   "14:00")
        try:
            await self.coordinator.hass.async_add_executor_job(
                self.coordinator.client.set_tou,
                start, end,
                int(data.get("charge_soc", 100)),
                int(data.get("discharge_soc", 6)),
            )
            self.coordinator.async_set_updated_data(
                {**data, f"charge_{self._which}": f"{value.hour:02d}:{value.minute:02d}"}
            )
        except DeyeApiError as e:
            _LOGGER.error("Failed to set charge window %s: %s", self._which, e)
