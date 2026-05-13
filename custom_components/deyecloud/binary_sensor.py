from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_DEVICE_SN
from .coordinator import DeyeCoordinator

_GRID_VOLTAGE_THRESHOLD = 100.0   # V — below this on all phases = grid absent
_GRID_FREQUENCY_MIN     = 45.0    # Hz
_GRID_FREQUENCY_MAX     = 55.0    # Hz


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: DeyeCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([DeyeGridConnectedSensor(coordinator, entry)])


class DeyeGridConnectedSensor(CoordinatorEntity, BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Grid Connected"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_icon = "mdi:transmission-tower"

    def __init__(self, coordinator: DeyeCoordinator, entry: ConfigEntry):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_SN]}_grid_connected"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.data[CONF_DEVICE_SN])},
            name="Deye Inverter",
            manufacturer="Deye",
            model=entry.data.get(CONF_DEVICE_SN, ""),
        )

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        if data is None:
            return None
        l1 = data.get("grid_voltage_l1", 0.0)
        l2 = data.get("grid_voltage_l2", 0.0)
        l3 = data.get("grid_voltage_l3", 0.0)
        freq = data.get("grid_frequency", 0.0)
        voltage_ok = max(l1, l2, l3) > _GRID_VOLTAGE_THRESHOLD
        frequency_ok = _GRID_FREQUENCY_MIN <= freq <= _GRID_FREQUENCY_MAX
        return voltage_ok and frequency_ok
