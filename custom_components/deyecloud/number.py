import logging

from homeassistant.components.number import NumberEntity, NumberMode, NumberDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
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
    rated = int(entry.data.get(CONF_RATED_POWER, DEFAULT_RATED_POWER))
    async_add_entities([
        DeyePowerNumber(coordinator, sn, "max_sell_power",  "MAX_SELL_POWER",  "Max Sell Power",
                        "mdi:transmission-tower-export", rated, 10),
        DeyePowerNumber(coordinator, sn, "max_solar_power", "MAX_SOLAR_POWER", "Max Solar Power",
                        "mdi:solar-power-variant", 2 * rated, 100),
        DeyePowerNumber(coordinator, sn, "zero_export_power", "ZERO_EXPORT_POWER", "Zero Export Power",
                        "mdi:transmission-tower-off", 1000, 10),
        DeyePeakShavingPower(coordinator, sn),
        DeyeChargeSoc(coordinator, sn, "charge_soc",    "Charge Target SOC",   "mdi:battery-arrow-up",   10, 100),
        DeyeChargeSoc(coordinator, sn, "discharge_soc", "Discharge Floor SOC", "mdi:battery-arrow-down",  5,  50),
        DeyeBatteryParamNumber(coordinator, sn, "grid_charge_current", "GRID_CHARGE_AMPERE",
                               "Grid Charge Current", "mdi:current-dc", "A", 0, 120),
        DeyeBatteryParamNumber(coordinator, sn, "max_charge_current", "MAX_CHARGE_CURRENT",
                               "Max Charge Current", "mdi:battery-arrow-up-outline", "A", 0, 120),
        DeyeBatteryParamNumber(coordinator, sn, "max_discharge_current", "MAX_DISCHARGE_CURRENT",
                               "Max Discharge Current", "mdi:battery-arrow-down-outline", "A", 0, 120),
        DeyeBatteryParamNumber(coordinator, sn, "battery_low_soc", "BATT_LOW",
                               "Battery Low SOC", "mdi:battery-low", "%", 5, 50),
    ])


class _DeyeNumber(CoordinatorEntity, NumberEntity):
    """Value read from coordinator data under `_key`; a write updates it optimistically
    and asks for a config re-read on the next poll."""

    _attr_has_entity_name = True
    _key: str

    def __init__(self, coordinator, sn):
        super().__init__(coordinator)
        self._attr_device_info = _device_info(sn)

    @property
    def native_value(self) -> float | None:
        val = (self.coordinator.data or {}).get(self._key)
        try:
            return float(val) if val is not None else None
        except (TypeError, ValueError):
            return None

    async def _write(self, fn, *args, updates: dict) -> None:
        try:
            await self.hass.async_add_executor_job(fn, *args)
        except DeyeApiError as e:
            _LOGGER.error("Failed to set %s: %s", self._key, e)
            raise HomeAssistantError(f"Deye: could not set {self.name}: {e}") from e
        else:
            self.coordinator.async_set_updated_data({**(self.coordinator.data or {}), **updates})
        finally:
            # Re-read either way: an unconfirmed command may still have been applied.
            self.coordinator.mark_config_dirty()


class DeyePowerNumber(_DeyeNumber):
    """Max sell / max solar power (/order/sys/power/update)."""

    _attr_native_unit_of_measurement = "W"
    _attr_native_min_value = 0
    _attr_mode = NumberMode.BOX
    _attr_device_class = NumberDeviceClass.POWER

    def __init__(self, coordinator, sn, key, power_type, name, icon, max_value, step):
        super().__init__(coordinator, sn)
        self._key = key
        self._power_type = power_type
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"{sn}_{key}"
        self._attr_native_max_value = float(max_value)
        self._attr_native_step = step

    async def async_set_native_value(self, value: float) -> None:
        await self._write(self.coordinator.client.set_power, self._power_type, int(value),
                          updates={self._key: int(value)})


class DeyeBatteryParamNumber(_DeyeNumber):
    """Battery parameters (/order/battery/parameter/update)."""

    _attr_native_step = 1
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator, sn, key, param_type, name, icon, unit, min_value, max_value):
        super().__init__(coordinator, sn)
        self._key = key
        self._param_type = param_type
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"{sn}_{key}"
        self._attr_native_unit_of_measurement = unit
        self._attr_native_min_value = float(min_value)
        self._attr_native_max_value = float(max_value)
        if unit == "A":
            self._attr_device_class = NumberDeviceClass.CURRENT

    async def async_set_native_value(self, value: float) -> None:
        await self._write(self.coordinator.client.set_battery_param, self._param_type, int(value),
                          updates={self._key: int(value)})


class DeyePeakShavingPower(RestoreEntity, _DeyeNumber):
    """Grid import cap used by Grid Peak Shaving. The cloud cannot read it back, so the
    value is the last one written (restored at startup). Writing it keeps the switch as is."""

    _attr_name = "Grid Peak Shaving Power"
    _attr_icon = "mdi:transmission-tower-import"
    _attr_native_unit_of_measurement = "W"
    _attr_native_min_value = 0
    _attr_native_max_value = 15000
    _attr_native_step = 100
    _attr_mode = NumberMode.BOX
    _attr_device_class = NumberDeviceClass.POWER
    _key = "peak_shaving_power"

    def __init__(self, coordinator, sn):
        super().__init__(coordinator, sn)
        self._attr_unique_id = f"{sn}_peak_shaving_power"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        data = self.coordinator.data
        if data is not None and data.get(self._key) is None:
            last = await self.async_get_last_state()
            if last is not None:
                try:
                    data[self._key] = int(float(last.state))
                except (TypeError, ValueError):
                    pass

    async def async_set_native_value(self, value: float) -> None:
        on = bool((self.coordinator.data or {}).get("peak_shaving"))
        await self._write(self.coordinator.client.set_grid_peak_shaving, on, int(value),
                          updates={self._key: int(value)})


class DeyeChargeSoc(_DeyeNumber):
    """Charge target SOC or discharge floor SOC — both control the TOU schedule."""

    _attr_native_unit_of_measurement = "%"
    _attr_native_step = 5
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator, sn, key, name, icon, min_val, max_val):
        super().__init__(coordinator, sn)
        self._key = key
        self._attr_name            = name
        self._attr_unique_id       = f"{sn}_{key}"
        self._attr_icon            = icon
        self._attr_native_min_value = float(min_val)
        self._attr_native_max_value = float(max_val)

    async def async_set_native_value(self, value: float) -> None:
        data = self.coordinator.data or {}
        charge_soc    = int(value) if self._key == "charge_soc"    else int(data.get("charge_soc",    100))
        discharge_soc = int(value) if self._key == "discharge_soc" else int(data.get("discharge_soc", 6))
        await self._write(
            self.coordinator.client.set_tou,
            data.get("charge_start", "11:05"),
            data.get("charge_end",   "13:55"),
            charge_soc,
            discharge_soc,
            updates={self._key: int(value)},
        )
