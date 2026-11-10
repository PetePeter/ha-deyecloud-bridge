from homeassistant.components.sensor import (
    SensorEntity, SensorDeviceClass, SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_DEVICE_SN
from .coordinator import DeyeCoordinator

P, E, V, A, T, F = (SensorDeviceClass.POWER, SensorDeviceClass.ENERGY, SensorDeviceClass.VOLTAGE,
                    SensorDeviceClass.CURRENT, SensorDeviceClass.TEMPERATURE, SensorDeviceClass.FREQUENCY)
M, TI = SensorStateClass.MEASUREMENT, SensorStateClass.TOTAL_INCREASING
DIAG = EntityCategory.DIAGNOSTIC

# (key, name, unit, device_class, state_class, icon, display_precision, entity_category)
SENSORS = [
    # Power flow
    ("solar_power",       "Solar Power",        "W", P, M, "mdi:solar-power",           0, None),
    ("pv1_power",         "PV1 Power",          "W", P, M, "mdi:solar-panel",           0, None),
    ("pv2_power",         "PV2 Power",          "W", P, M, "mdi:solar-panel",           0, None),
    ("house_load",        "House Load",         "W", P, M, "mdi:home-lightning-bolt",   0, None),
    ("grid_power",        "Grid Power",         "W", P, M, "mdi:transmission-tower",    0, None),
    ("battery_power",     "Battery Power",      "W", P, M, "mdi:battery-charging",      0, None),
    ("ups_power",         "UPS Power",          "W", P, M, "mdi:power-plug",            0, None),
    ("inverter_power_l1", "Inverter Output Power", "W", P, M, "mdi:lightning-bolt",     0, None),
    # Battery
    ("battery_soc",       "Battery SOC",        "%", SensorDeviceClass.BATTERY, M, None, 1, None),
    ("battery_voltage",   "Battery Voltage",    "V", V, M, None,                        2, None),
    ("battery_current",   "Battery Current",    "A", A, M, "mdi:current-dc",            1, None),
    ("battery_temp",      "Battery Temperature", "°C", T, M, None,                      1, None),
    # Energy
    ("daily_solar",             "Solar Today",             "kWh", E, TI, "mdi:solar-power",               2, None),
    ("daily_consumption",       "Consumption Today",       "kWh", E, TI, "mdi:home-lightning-bolt",       2, None),
    ("daily_grid_import",       "Grid Import Today",       "kWh", E, TI, "mdi:transmission-tower-import", 2, None),
    ("daily_grid_export",       "Grid Export Today",       "kWh", E, TI, "mdi:transmission-tower-export", 2, None),
    ("daily_battery_charge",    "Battery Charge Today",    "kWh", E, TI, "mdi:battery-arrow-up",          2, None),
    ("daily_battery_discharge", "Battery Discharge Today", "kWh", E, TI, "mdi:battery-arrow-down",        2, None),
    ("total_solar",             "Solar Total",             "kWh", E, TI, None,                            2, None),
    ("total_consumption",       "Consumption Total",       "kWh", E, TI, "mdi:home-lightning-bolt",       2, None),
    ("total_grid_import",       "Grid Import Total",       "kWh", E, TI, "mdi:transmission-tower-import", 2, None),
    ("total_grid_export",       "Grid Export Total",       "kWh", E, TI, "mdi:transmission-tower-export", 2, None),
    ("total_battery_charge",    "Battery Charge Total",    "kWh", E, TI, None,                            2, None),
    ("total_battery_discharge", "Battery Discharge Total", "kWh", E, TI, None,                            2, None),
    # Grid and inverter electrical detail
    ("grid_voltage_l1",     "Grid Voltage",            "V",   V, M, "mdi:sine-wave",       1, None),
    ("grid_current",        "Grid Current",            "A",   A, M, "mdi:current-ac",      2, DIAG),
    ("grid_frequency",      "Grid Frequency",          "Hz",  F, M, "mdi:sine-wave",       2, DIAG),
    ("grid_reactive_power", "Grid Reactive Power",     "var", SensorDeviceClass.REACTIVE_POWER, M, None, 0, DIAG),
    ("load_voltage",        "Load Voltage",            "V",   V, M, "mdi:sine-wave",       1, DIAG),
    ("inverter_voltage",    "Inverter Output Voltage", "V",   V, M, "mdi:sine-wave",       1, DIAG),
    ("inverter_current",    "Inverter Output Current", "A",   A, M, "mdi:current-ac",      2, DIAG),
    ("inverter_frequency",  "Inverter Output Frequency", "Hz", F, M, "mdi:sine-wave",      2, DIAG),
    ("power_factor",        "Power Factor",            None,  SensorDeviceClass.POWER_FACTOR, M, None, 2, DIAG),
    ("pv1_voltage",         "PV1 Voltage",             "V",   V, M, "mdi:solar-panel",     1, DIAG),
    ("pv2_voltage",         "PV2 Voltage",             "V",   V, M, "mdi:solar-panel",     1, DIAG),
    ("pv1_current",         "PV1 Current",             "A",   A, M, "mdi:solar-panel",     2, DIAG),
    ("pv2_current",         "PV2 Current",             "A",   A, M, "mdi:solar-panel",     2, DIAG),
    ("inverter_temp",       "Inverter Temperature",    "°C",  T, M, None,                  1, None),
    ("dc_temp",             "DC Temperature",          "°C",  T, M, None,                  1, DIAG),
    # BMS
    ("bms_voltage",                 "BMS Voltage",                 "V", V, M, None,              2, DIAG),
    ("bms_current",                 "BMS Current",                 "A", A, M, "mdi:current-dc",  1, DIAG),
    ("bms_temperature",             "BMS Temperature",             "°C", T, M, None,             1, DIAG),
    ("bms_soc",                     "BMS SOC",                     "%", SensorDeviceClass.BATTERY, M, None, 0, DIAG),
    ("bms_charge_voltage",          "BMS Charge Voltage",          "V", V, M, None,              2, DIAG),
    ("bms_charge_current_limit",    "BMS Charge Current Limit",    "A", A, M, "mdi:current-dc",  0, DIAG),
    ("bms_discharge_current_limit", "BMS Discharge Current Limit", "A", A, M, "mdi:current-dc",  0, DIAG),
    # Configuration read back (writable ones are number/select/switch entities)
    ("max_sell_power",       "Max Sell Power",        "W",  P, M,    "mdi:transmission-tower-export", 0, DIAG),
    ("battery_capacity_ah",  "Battery Capacity",      "Ah", None, None, "mdi:battery-high",           0, DIAG),
    ("battery_shutdown_soc", "Battery Shutdown SOC",  "%",  None, None, "mdi:battery-off-outline",    0, DIAG),
    ("rated_power",          "Rated Power",           "W",  P, None, "mdi:flash",                     0, DIAG),
]

# (key, name, icon)
TEXT_SENSORS = [
    ("grid_relay_status", "Grid Relay",      "mdi:electric-switch"),
    ("firmware_main",     "Firmware (Main)", "mdi:chip"),
    ("firmware_hmi",      "Firmware (HMI)",  "mdi:chip"),
]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: DeyeCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = [DeyeSensor(coordinator, entry, *row) for row in SENSORS]
    entities += [DeyeTextSensor(coordinator, entry, *row) for row in TEXT_SENSORS]
    entities.append(DeyeAlertsSensor(coordinator, entry))
    async_add_entities(entities)


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.data[CONF_DEVICE_SN])},
        name="Deye Inverter",
        manufacturer="Deye",
        model=entry.data.get(CONF_DEVICE_SN, ""),
    )


class DeyeSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry, key, name, unit, device_class, state_class,
                 icon, precision, category):
        super().__init__(coordinator)
        self._key = key
        self._attr_name                        = name
        self._attr_unique_id                   = f"{entry.data[CONF_DEVICE_SN]}_{key}"
        self._attr_native_unit_of_measurement  = unit
        self._attr_device_class                = device_class
        self._attr_state_class                 = state_class
        self._attr_suggested_display_precision = precision
        self._attr_entity_category             = category
        if icon:
            self._attr_icon = icon
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self):
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self._key)


class DeyeAlertsSensor(CoordinatorEntity, SensorEntity):
    """Open inverter alerts; the 10 most recent of the last 7 days are in the attributes."""

    _attr_has_entity_name = True
    _attr_name = "Active Alerts"
    _attr_icon = "mdi:alert-circle-outline"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_SN]}_active_alerts"
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("active_alerts")

    @property
    def extra_state_attributes(self) -> dict:
        return {"recent": (self.coordinator.data or {}).get("recent_alerts") or []}


class DeyeTextSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry, key, name, icon):
        super().__init__(coordinator)
        self._key = key
        self._attr_name      = name
        self._attr_icon      = icon
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_SN]}_{key}"
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get(self._key)
