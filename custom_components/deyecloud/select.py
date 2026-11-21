import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import DeyeApiError
from .const import DOMAIN, CONF_DEVICE_SN, WORK_MODE_LABELS, ENERGY_PATTERN_LABELS
from .coordinator import DeyeCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: DeyeCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        DeyeWorkModeSelect(coordinator, entry),
        DeyeEnergyPatternSelect(coordinator, entry),
        DeyeGridChargeSelect(coordinator, entry),
    ])


def _device_info(sn: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, sn)},
        name="Deye Inverter",
        manufacturer="Deye",
        model=sn,
    )


class _LabelledSelect(CoordinatorEntity, SelectEntity):
    """Select backed by an API enum: coordinator key `_key`, labels `_labels` (api value -> label)."""

    _attr_has_entity_name = True
    _key: str
    _labels: dict[str, str]

    def __init__(self, coordinator: DeyeCoordinator, entry: ConfigEntry, unique_suffix: str):
        super().__init__(coordinator)
        sn = entry.data[CONF_DEVICE_SN]
        self._attr_unique_id = f"{sn}_{unique_suffix}"
        self._attr_device_info = _device_info(sn)
        self._attr_options = list(self._labels.values())

    @property
    def current_option(self) -> str | None:
        return self._labels.get((self.coordinator.data or {}).get(self._key))

    def _send(self, value: str) -> None:
        raise NotImplementedError

    async def async_select_option(self, option: str) -> None:
        value = next(k for k, v in self._labels.items() if v == option)
        try:
            await self.hass.async_add_executor_job(self._send, value)
        except DeyeApiError as e:
            _LOGGER.error("Failed to set %s: %s", self._key, e)
            raise HomeAssistantError(f"Deye: could not set {self.name}: {e}") from e
        else:
            self.coordinator.async_set_updated_data({**(self.coordinator.data or {}), self._key: value})
        finally:
            self.coordinator.mark_config_dirty()


class DeyeWorkModeSelect(_LabelledSelect):
    _attr_name = "Work Mode"
    _attr_icon = "mdi:solar-power-variant"
    _key = "work_mode"
    _labels = WORK_MODE_LABELS

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "work_mode")

    def _send(self, value: str) -> None:
        self.coordinator.client.set_work_mode(value)


class DeyeEnergyPatternSelect(_LabelledSelect):
    """Battery First: solar charges the battery before the loads. Load First: the reverse."""

    _attr_name = "Energy Pattern"
    _attr_icon = "mdi:battery-sync"
    _key = "energy_pattern"
    _labels = ENERGY_PATTERN_LABELS

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry, "energy_pattern")

    def _send(self, value: str) -> None:
        self.coordinator.client.set_energy_pattern(value)


class DeyeGridChargeSelect(CoordinatorEntity, RestoreEntity, SelectEntity):
    """Inverter master Grid Charge switch (app: Battery Setting-3). Read from the
    inverter's registers each config cycle; the last known value is restored at startup."""

    _attr_has_entity_name = True
    _attr_name = "Grid Charge"
    _attr_icon = "mdi:transmission-tower-import"
    _attr_options = ["Enable", "Disable"]

    def __init__(self, coordinator: DeyeCoordinator, entry: ConfigEntry):
        super().__init__(coordinator)
        sn = entry.data[CONF_DEVICE_SN]
        self._attr_unique_id = f"{sn}_grid_charge"
        self._attr_device_info = _device_info(sn)
        self._attr_current_option = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._sync_from_data()
        if self._attr_current_option is None:
            last = await self.async_get_last_state()
            if last and last.state in self._attr_options:
                self._attr_current_option = last.state

    def _sync_from_data(self) -> None:
        val = (self.coordinator.data or {}).get("grid_charge")
        if val is not None:
            self._attr_current_option = "Enable" if val else "Disable"

    @callback
    def _handle_coordinator_update(self) -> None:
        self._sync_from_data()
        super()._handle_coordinator_update()

    async def async_select_option(self, option: str) -> None:
        on = option == "Enable"
        try:
            await self.hass.async_add_executor_job(
                self.coordinator.client.set_battery_mode, "GRID_CHARGE", on
            )
        except DeyeApiError as e:
            _LOGGER.error("Failed to set grid charge: %s", e)
            raise HomeAssistantError(f"Deye: could not set Grid Charge: {e}") from e
        else:
            self.coordinator.async_set_updated_data({**(self.coordinator.data or {}), "grid_charge": on})
        finally:
            self.coordinator.mark_config_dirty()
