from datetime import timedelta
import logging

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import DeyeCloudClient, DeyeApiError
from .const import DOMAIN, DEFAULT_REFRESH_INTERVAL

_LOGGER = logging.getLogger(__name__)


class DeyeCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, client: DeyeCloudClient, refresh_interval: int = DEFAULT_REFRESH_INTERVAL):
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=refresh_interval),
        )
        self.client = client

    async def _async_update_data(self) -> dict:
        try:
            return await self.hass.async_add_executor_job(self.client.read)
        except DeyeApiError as e:
            raise UpdateFailed(str(e)) from e
