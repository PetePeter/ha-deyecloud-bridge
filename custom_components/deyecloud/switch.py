import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import DeyeApiError
from .const import DOMAIN, CONF_DEVICE_SN
from .coordinator import DeyeCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: DeyeCoordinator = hass.data[DOMAIN][entry.entry_id]
    sn = entry.data[CONF_DEVICE_SN]
    async_add_entities([
        DeyeSolarSellSwitch(coordinator, sn),
        DeyeTimeOfUseSwitch(coordinator, sn),
        DeyePeakShavingSwitch(coordinator, sn),
    ])


class _DeyeSwitch(CoordinatorEntity, SwitchEntity):
    _attr_has_entity_name = True
    _key: str

    def __init__(self, coordinator: DeyeCoordinator, sn: str, unique_suffix: str):
        super().__init__(coordinator)
        self._attr_unique_id = f"{sn}_{unique_suffix}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, sn)},
            name="Deye Inverter",
            manufacturer="Deye",
            model=sn,
        )

    @property
    def is_on(self) -> bool | None:
        val = (self.coordinator.data or {}).get(self._key)
        return None if val is None else bool(val)

    def _send(self, on: bool) -> None:
        raise NotImplementedError

    async def _set(self, on: bool) -> None:
        try:
            await self.hass.async_add_executor_job(self._send, on)
        except DeyeApiError as e:
            _LOGGER.error("Failed to set %s: %s", self._key, e)
            raise HomeAssistantError(f"Deye: could not switch {self.name}: {e}") from e
        else:
            self.coordinator.async_set_updated_data({**(self.coordinator.data or {}), self._key: on})
        finally:
            self.coordinator.mark_config_dirty()

    async def async_turn_on(self, **kwargs) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._set(False)


class DeyeSolarSellSwitch(_DeyeSwitch):
    """Allow exporting solar surplus to the grid (still capped by Max Sell Power)."""

    _attr_name = "Solar Sell"
    _attr_icon = "mdi:solar-power"
    _key = "solar_sell"

    def __init__(self, coordinator, sn):
        super().__init__(coordinator, sn, "solar_sell")

    def _send(self, on: bool) -> None:
        self.coordinator.client.set_solar_sell(on)


class DeyeTimeOfUseSwitch(_DeyeSwitch):
    """Enable the inverter's time-of-use schedule. The 6 slots are in the attributes."""

    _attr_name = "Time of Use"
    _attr_icon = "mdi:clock-time-four-outline"
    _key = "time_of_use"

    def __init__(self, coordinator, sn):
        super().__init__(coordinator, sn, "time_of_use")

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data or {}
        val = data.get("time_of_use", data.get("tou_enabled"))
        return None if val is None else bool(val)

    @property
    def extra_state_attributes(self) -> dict:
        slots = (self.coordinator.data or {}).get("tou_slots")
        return {"slots": slots} if slots else {}

    def _send(self, on: bool) -> None:
        self.coordinator.client.set_time_of_use(on)


class DeyePeakShavingSwitch(RestoreEntity, _DeyeSwitch):
    """Grid Peak Shaving: cap grid import at Grid Peak Shaving Power; PV and battery cover
    the rest. Write-only in the cloud API, so the state is the last one written."""

    _attr_name = "Grid Peak Shaving"
    _attr_icon = "mdi:chart-bell-curve-cumulative"
    _key = "peak_shaving"

    def __init__(self, coordinator, sn):
        super().__init__(coordinator, sn, "peak_shaving")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        data = self.coordinator.data
        if data is not None and data.get(self._key) is None:
            last = await self.async_get_last_state()
            if last is not None and last.state in ("on", "off"):
                data[self._key] = last.state == "on"

    def _send(self, on: bool) -> None:
        power = (self.coordinator.data or {}).get("peak_shaving_power")
        self.coordinator.client.set_grid_peak_shaving(on, power)
