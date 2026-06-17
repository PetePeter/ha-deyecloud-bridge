import logging
import time

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import DeyeCloudClient, DeyeApiError
from .const import DOMAIN, CONFIG_READ_INTERVAL

_LOGGER = logging.getLogger(__name__)

# Config keys carried forward between system/TOU reads.
_CONFIG_KEYS = ("work_mode", "max_sell_power",
                "charge_start", "charge_end", "charge_soc", "discharge_soc")


class DeyeCoordinator(DataUpdateCoordinator):
    """Polls telemetry every cycle; work mode + TOU only every CONFIG_READ_INTERVAL
    (or immediately after an HA-side change, via mark_config_dirty)."""

    def __init__(self, hass, client: DeyeCloudClient,
                 config_interval: int = CONFIG_READ_INTERVAL):
        # update_interval is left unset — refreshes are driven by a clock-aligned
        # time trigger registered in __init__.py so polls land on the 5-min marks.
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=None)
        self.client = client
        self._config_interval = config_interval
        self._last_config_read = 0.0
        self._config_dirty = False

    def mark_config_dirty(self) -> None:
        """Force a work mode + TOU re-read on the next telemetry poll."""
        self._config_dirty = True

    def _config_due(self) -> bool:
        if self._config_dirty or self._last_config_read == 0.0:
            return True
        return (time.monotonic() - self._last_config_read) >= self._config_interval

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

        self._carry_forward_config(data)  # fill any keys a failed read left missing

        if ok:
            self._last_config_read = time.monotonic()
            self._config_dirty = False

    def _carry_forward_config(self, data: dict) -> None:
        if not self.data:
            return
        for key in _CONFIG_KEYS:
            if key not in data and key in self.data:
                data[key] = self.data[key]
