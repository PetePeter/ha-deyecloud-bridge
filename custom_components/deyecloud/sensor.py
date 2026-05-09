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

SENSORS = [
    # (key, name, unit, device_class, state_class, icon)
    ("solar_power",             "Solar Power",            "W",   SensorDeviceClass.POWER,   SensorStateClass.MEASUREMENT,   "mdi:solar-power"),
    ("house_load",              "House Load",             "W",   SensorDeviceClass.POWER,   SensorStateClass.MEASUREMENT,   "mdi:home-lightning-bolt"),
    ("grid_power",              "Grid Power",             "W",   SensorDeviceClass.POWER,   SensorStateClass.MEASUREMENT,   "mdi:transmission-tower"),
    ("battery_power",           "Battery Power",          "W",   SensorDeviceClass.POWER,   SensorStateClass.MEASUREMENT,   "mdi:battery-charging"),
    ("ups_power",               "UPS Power",              "W",   SensorDeviceClass.POWER,   SensorStateClass.MEASUREMENT,   "mdi:power-plug"),
    ("battery_soc",             "Battery SOC",            "%",   SensorDeviceClass.BATTERY, SensorStateClass.MEASUREMENT,   None),
    ("battery_voltage",         "Battery Voltage",        "V",   SensorDeviceClass.VOLTAGE, SensorStateClass.MEASUREMENT,   None),
    ("battery_temp",            "Battery Temperature",    "°C",  SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, None),
    ("inverter_temp",           "Inverter Temperature",   "°C",  SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, None),
    ("daily_solar",             "Solar Today",            "kWh", SensorDeviceClass.ENERGY,  SensorStateClass.TOTAL_INCREASING, "mdi:solar-power"),
    ("daily_consumption",       "Consumption Today",      "kWh", SensorDeviceClass.ENERGY,  SensorStateClass.TOTAL_INCREASING, "mdi:home-lightning-bolt"),
    ("total_solar",             "Solar Total",            "kWh", SensorDeviceClass.ENERGY,  SensorStateClass.TOTAL_INCREASING, None),
    ("total_grid_import",       "Grid Import Total",      "kWh", SensorDeviceClass.ENERGY,  SensorStateClass.TOTAL_INCREASING, "mdi:transmission-tower-import"),
    ("total_grid_export",       "Grid Export Total",      "kWh", SensorDeviceClass.ENERGY,  SensorStateClass.TOTAL_INCREASING, "mdi:transmission-tower-export"),
    ("total_battery_charge",    "Battery Charge Total",   "kWh", SensorDeviceClass.ENERGY,  SensorStateClass.TOTAL_INCREASING, None),
    ("total_battery_discharge", "Battery Discharge Total","kWh", SensorDeviceClass.ENERGY,  SensorStateClass.TOTAL_INCREASING, None),
]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: DeyeCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        DeyeSensor(coordinator, entry, key, name, unit, dc, sc, icon)
        for key, name, unit, dc, sc, icon in SENSORS
    )


class DeyeSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry, key, name, unit, device_class, state_class, icon):
        super().__init__(coordinator)
        self._key = key
        self._attr_name = name
        self._attr_unique_id = f"{entry.data[CONF_DEVICE_SN]}_{key}"
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_state_class = state_class
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
