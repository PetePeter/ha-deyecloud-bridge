import logging

from homeassistant.components.number import NumberEntity, NumberMode, NumberDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import DeyeApiError
from .const import DOMAIN, CONF_DEVICE_SN, CONF_RATED_POWER, DEFAULT_RATED_POWER
from .coordinator import DeyeCoordinator

_LOGGER = logging.getLogger(__name__)

_DEVICE_INFO_CACHE: dict[str, DeviceInfo] = {}


def _device_info(sn: str) -> DeviceInfo:
    if sn not in _DEVICE_INFO_CACHE:
        _DEVICE_INFO_CACHE[sn] = DeviceInfo(
            identifiers={(DOMAIN, sn)},
            name="Deye Inverter",
            manufacturer="Deye",
            model=sn,
        )
    return _DEVICE_INFO_CACHE[sn]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: DeyeCoordinator = hass.data[DOMAIN][entry.entry_id]
    sn = entry.data[CONF_DEVICE_SN]
    rated = entry.data.get(CONF_RATED_POWER, DEFAULT_RATED_POWER)
    async_add_entities([
        DeyeMaxSellPower(coordinator, entry, sn, rated),
        DeyeChargeSoc(coordinator, entry, sn, "charge_soc",    "Charge Target SOC",  "mdi:battery-arrow-up",   10, 100),
        DeyeChargeSoc(coordinator, entry, sn, "discharge_soc", "Discharge Floor SOC","mdi:battery-arrow-down",  5,  50),
    ])


class DeyeMaxSellPower(CoordinatorEntity, NumberEntity):
    _attr_has_entity_name = True
    _attr_name = "Max Sell Power"
    _attr_icon = "mdi:transmission-tower-export"
    _attr_native_unit_of_measurement = "W"
    _attr_native_min_value = 0
    _attr_native_step = 10
    _attr_mode = NumberMode.BOX
    _attr_device_class = NumberDeviceClass.POWER

    def __init__(self, coordinator, entry, sn, rated_power):
        super().__init__(coordinator)
        self._attr_unique_id       = f"{sn}_max_sell_power"
        self._attr_native_max_value = float(rated_power)
        self._attr_device_info     = _device_info(sn)

    @property
    def native_value(self) -> float | None:
        val = (self.coordinator.data or {}).get("max_sell_power")
        return float(val) if val is not None else None

    async def async_set_native_value(self, value: float) -> None:
        try:
            await self.coordinator.hass.async_add_executor_job(
                self.coordinator.client.set_max_sell_power, int(value)
            )
            self.coordinator.async_set_updated_data(
                {**(self.coordinator.data or {}), "max_sell_power": int(value)}
            )
        except DeyeApiError as e:
            _LOGGER.error("Failed to set max sell power: %s", e)


class DeyeChargeSoc(CoordinatorEntity, NumberEntity):
    """Charge target SOC or discharge floor SOC — both control the TOU schedule."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "%"
    _attr_native_step = 5
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator, entry, sn, key, name, icon, min_val, max_val):
        super().__init__(coordinator)
        self._key = key
        self._attr_name            = name
        self._attr_unique_id       = f"{sn}_{key}"
        self._attr_icon            = icon
        self._attr_native_min_value = float(min_val)
        self._attr_native_max_value = float(max_val)
        self._attr_device_info     = _device_info(sn)

    @property
    def native_value(self) -> float | None:
        val = (self.coordinator.data or {}).get(self._key)
        return float(val) if val is not None else None

    async def async_set_native_value(self, value: float) -> None:
        data = self.coordinator.data or {}
        charge_soc    = int(value) if self._key == "charge_soc"    else int(data.get("charge_soc",    100))
        discharge_soc = int(value) if self._key == "discharge_soc" else int(data.get("discharge_soc", 6))
        try:
            await self.coordinator.hass.async_add_executor_job(
                self.coordinator.client.set_tou,
                data.get("charge_start", "11:05"),
                data.get("charge_end",   "13:55"),
                charge_soc,
                discharge_soc,
            )
            self.coordinator.async_set_updated_data(
                {**data, self._key: int(value)}
            )
        except DeyeApiError as e:
            _LOGGER.error("Failed to set %s: %s", self._key, e)
