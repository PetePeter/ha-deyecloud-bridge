from datetime import timedelta
import logging

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import DeyeCloudClient, DeyeApiError
from .const import DOMAIN, DEFAULT_REFRESH_INTERVAL

_LOGGER = logging.getLogger(__name__)


class DeyeCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, client: DeyeCloudClient,
                 refresh_interval: int = DEFAULT_REFRESH_INTERVAL):
        super().__init__(
            hass, _LOGGER, name=DOMAIN,
            update_interval=timedelta(seconds=refresh_interval),
        )
        self.client = client

    async def _async_update_data(self) -> dict:
        try:
            data = await self.hass.async_add_executor_job(self.client.read)
        except DeyeApiError as e:
            raise UpdateFailed(str(e)) from e

        # TOU read failure is non-fatal — keep prior values if available
        try:
            tou = await self.hass.async_add_executor_job(self.client.read_tou)
            data.update(tou)
        except Exception as e:
            _LOGGER.debug("TOU read failed (non-fatal): %s", e)
            if self.data:
                for key in ("charge_start", "charge_end", "charge_soc", "discharge_soc"):
                    if key in self.data:
                        data[key] = self.data[key]

        return data
