import logging
import time

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import DeyeCloudClient, DeyeApiError
from .const import (
    DOMAIN, CONFIG_READ_INTERVAL, SETTINGS_READ_INTERVAL, SETTINGS_RETRY_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

# Config keys carried forward between system/TOU/settings reads.
_CONFIG_KEYS = (
    "work_mode", "max_sell_power", "max_solar_power", "zero_export_power", "energy_pattern",
    "battery_capacity_ah", "battery_low_soc", "battery_shutdown_soc",
    "max_charge_current", "max_discharge_current",
    "grid_charge", "grid_charge_current", "solar_sell", "time_of_use",
    "charge_start", "charge_end", "charge_soc", "discharge_soc",
    "tou_enabled", "tou_slots",
    "active_alerts", "recent_alerts",
    # Write-only in the cloud API: last value written, seeded from restored entity state.
    "peak_shaving", "peak_shaving_power",
)


class DeyeCoordinator(DataUpdateCoordinator):
    """Polls telemetry every cycle; work mode + TOU only every CONFIG_READ_INTERVAL
    (or immediately after an HA-side change, via mark_config_dirty). The live
    register read is a command through the logger, so it runs on its own, much
    longer interval: at start, after an HA-side change and every SETTINGS_READ_INTERVAL."""

    def __init__(self, hass, client: DeyeCloudClient,
                 config_interval: int = CONFIG_READ_INTERVAL,
                 settings_interval: int = SETTINGS_READ_INTERVAL,
                 settings_retry: int = SETTINGS_RETRY_INTERVAL):
        # update_interval is left unset — refreshes are driven by a clock-aligned
        # time trigger registered in __init__.py so polls land on the 5-min marks.
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=None)
        self.client = client
        self._config_interval = config_interval
        self._settings_interval = settings_interval
        self._settings_retry = settings_retry
        self._last_config_read = 0.0
        self._next_settings_read = 0.0
        self._config_dirty = False
        self._settings_dirty = False
        self._settings_keys = frozenset()  # keys the last live register read returned
        self._config_gen = 0  # bumped by every HA-side write

    def mark_config_dirty(self) -> None:
        """Force a config re-read, live registers included, on the next telemetry poll."""
        self._config_dirty = True
        self._settings_dirty = True
        self._config_gen += 1

    def _config_due(self) -> bool:
        if self._config_dirty or self._last_config_read == 0.0:
            return True
        return (time.monotonic() - self._last_config_read) >= self._config_interval

    def _settings_due(self) -> bool:
        return self._settings_dirty or time.monotonic() >= self._next_settings_read

    async def _async_update_data(self) -> dict:
        try:
            data = await self.hass.async_add_executor_job(self.client.read)
        except DeyeApiError as e:
            raise UpdateFailed(str(e)) from e

        if self._config_due():
            await self._read_config(data)
        else:
            self._carry_forward_config(data)

        return data

    async def _read_config(self, data: dict) -> None:
        """Read work mode + TOU. Failures are non-fatal — keep prior values."""
        ok = True
        gen = self._config_gen

        try:
            data.update(await self.hass.async_add_executor_job(self.client.read_system))
        except Exception as e:
            ok = False
            _LOGGER.debug("System read failed (non-fatal): %s", e)

        try:
            data.update(await self.hass.async_add_executor_job(self.client.read_tou))
        except Exception as e:
            ok = False
            _LOGGER.debug("TOU read failed (non-fatal): %s", e)

        # Live register read: authoritative for grid charge, solar sell, TOU on/off
        # and the currents. Not every model supports it, so a failure is not fatal.
        settings_tried = self._settings_due()
        settings_read = False
        if settings_tried:
            try:
                settings = await self.hass.async_add_executor_job(self.client.read_settings)
                data.update(settings)
                self._settings_keys = frozenset(settings)
                self._next_settings_read = time.monotonic() + self._settings_interval
                settings_read = True
            except Exception as e:
                self._next_settings_read = time.monotonic() + self._settings_retry
                _LOGGER.debug("Settings read failed (non-fatal): %s", e)
        if not settings_read and self.data:
            # The cloud caches read above lag the inverter: keep the register values.
            for key in self._settings_keys:
                if key in self.data:
                    data[key] = self.data[key]

        try:
            data.update(await self.hass.async_add_executor_job(self.client.read_alerts))
        except Exception as e:
            _LOGGER.debug("Alert read failed (non-fatal): %s", e)

        if gen != self._config_gen and self.data:
            # A write landed while we were reading: what we read may predate it, so keep
            # the written (optimistic) values and stay dirty to re-read next poll.
            for key in _CONFIG_KEYS:
                if key in self.data:
                    data[key] = self.data[key]
            return

        self._carry_forward_config(data)  # fill any keys a failed read left missing

        if settings_tried:
            self._settings_dirty = False
        if ok:
            self._last_config_read = time.monotonic()
            self._config_dirty = False

    def _carry_forward_config(self, data: dict) -> None:
        if not self.data:
            return
        for key in _CONFIG_KEYS:
            if key not in data and key in self.data:
                data[key] = self.data[key]
