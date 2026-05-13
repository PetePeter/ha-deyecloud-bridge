from homeassistant.components.sensor import (
    SensorEntity, SensorDeviceClass, SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_DEVICE_SN
from .coordinator import DeyeCoordinator

# (key, name, unit, device_class, state_class, icon, display_precision)
SENSORS = [
    ("solar_power",             "Solar Power",            "W",   SensorDeviceClass.POWER,       SensorStateClass.MEASUREMENT,    "mdi:solar-power",               0),
    ("house_load",              "House Load",             "W",   SensorDeviceClass.POWER,       SensorStateClass.MEASUREMENT,    "mdi:home-lightning-bolt",       0),
    ("grid_power",              "Grid Power",             "W",   SensorDeviceClass.POWER,       SensorStateClass.MEASUREMENT,    "mdi:transmission-tower",        0),
    ("battery_power",           "Battery Power",          "W",   SensorDeviceClass.POWER,       SensorStateClass.MEASUREMENT,    "mdi:battery-charging",          0),
    ("ups_power",               "UPS Power",              "W",   SensorDeviceClass.POWER,       SensorStateClass.MEASUREMENT,    "mdi:power-plug",                0),
    ("battery_soc",             "Battery SOC",            "%",   SensorDeviceClass.BATTERY,     SensorStateClass.MEASUREMENT,    None,                            1),
    ("battery_voltage",         "Battery Voltage",        "V",   SensorDeviceClass.VOLTAGE,     SensorStateClass.MEASUREMENT,    None,                            2),
    ("battery_temp",            "Battery Temperature",    "°C",  SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT,    None,                            1),
    ("inverter_temp",           "Inverter Temperature",   "°C",  SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT,    None,                            1),
    ("daily_solar",             "Solar Today",            "kWh", SensorDeviceClass.ENERGY,      SensorStateClass.TOTAL_INCREASING, "mdi:solar-power",             2),
    ("daily_consumption",       "Consumption Today",      "kWh", SensorDeviceClass.ENERGY,      SensorStateClass.TOTAL_INCREASING, "mdi:home-lightning-bolt",     2),
    ("total_solar",             "Solar Total",            "kWh", SensorDeviceClass.ENERGY,      SensorStateClass.TOTAL_INCREASING, None,                          2),
    ("total_grid_import",       "Grid Import Total",      "kWh", SensorDeviceClass.ENERGY,      SensorStateClass.TOTAL_INCREASING, "mdi:transmission-tower-import", 2),
    ("total_grid_export",       "Grid Export Total",      "kWh", SensorDeviceClass.ENERGY,      SensorStateClass.TOTAL_INCREASING, "mdi:transmission-tower-export", 2),
    ("total_battery_charge",    "Battery Charge Total",   "kWh", SensorDeviceClass.ENERGY,      SensorStateClass.TOTAL_INCREASING, None,                          2),
    ("total_battery_discharge", "Battery Discharge Total","kWh", SensorDeviceClass.ENERGY,      SensorStateClass.TOTAL_INCREASING, None,                          2),
    ("max_sell_power",          "Max Sell Power",         "W",   SensorDeviceClass.POWER,       SensorStateClass.MEASUREMENT,    "mdi:transmission-tower-export", 0),
    ("inverter_power_l1",       "Inverter Output L1",     "W",   SensorDeviceClass.POWER,       SensorStateClass.MEASUREMENT,    "mdi:lightning-bolt",            0),
    ("inverter_power_l2",       "Inverter Output L2",     "W",   SensorDeviceClass.POWER,       SensorStateClass.MEASUREMENT,    "mdi:lightning-bolt",            0),
    ("inverter_power_l3",       "Inverter Output L3",     "W",   SensorDeviceClass.POWER,       SensorStateClass.MEASUREMENT,    "mdi:lightning-bolt",            0),
]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: DeyeCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        DeyeSensor(coordinator, entry, *row) for row in SENSORS
    )


class DeyeSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry, key, name, unit, device_class, state_class, icon, precision):
        super().__init__(coordinator)
        self._key = key
        self._attr_name                       = name
        self._attr_unique_id                  = f"{entry.data[CONF_DEVICE_SN]}_{key}"
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class               = device_class
        self._attr_state_class                = state_class
        self._attr_suggested_display_precision = precision
        if icon:
            self._attr_icon = icon
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.data[CONF_DEVICE_SN])},
            name="Deye Inverter",
            manufacturer="Deye",
            model=entry.data.get(CONF_DEVICE_SN, ""),
        )

    @property
    def native_value(self):
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self._key)
