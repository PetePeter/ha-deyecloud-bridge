import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.selector import (
    SelectSelector, SelectSelectorConfig, SelectSelectorMode,
    NumberSelector, NumberSelectorConfig, NumberSelectorMode,
)

from .api import DeyeCloudClient, DeyeApiError
from .const import (
    DOMAIN,
    CONF_APP_ID, CONF_APP_SECRET, CONF_EMAIL, CONF_PASSWORD,
    CONF_SERVER, CONF_STATION_ID, CONF_DEVICE_SN,
    CONF_RATED_POWER, CONF_REFRESH_INTERVAL,
    DEFAULT_RATED_POWER, DEFAULT_REFRESH_INTERVAL, DEFAULT_SERVER, SERVERS,
)

_SERVER_OPTIONS = [{"value": k, "label": k} for k in SERVERS]

CREDS_SCHEMA = vol.Schema({
    vol.Required(CONF_SERVER, default=DEFAULT_SERVER): SelectSelector(
        SelectSelectorConfig(options=_SERVER_OPTIONS, mode=SelectSelectorMode.DROPDOWN)
    ),
    vol.Required(CONF_APP_ID):     str,
    vol.Required(CONF_APP_SECRET): str,
    vol.Required(CONF_EMAIL):      str,
    vol.Required(CONF_PASSWORD):   str,
    vol.Optional(CONF_RATED_POWER, default=DEFAULT_RATED_POWER): int,
    vol.Optional(CONF_REFRESH_INTERVAL, default=DEFAULT_REFRESH_INTERVAL):
        NumberSelector(NumberSelectorConfig(min=30, max=3600, step=30,
                                            mode=NumberSelectorMode.BOX)),
})


class DeyeCloudConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self._data: dict = {}
        self._stations: list[dict] = []
        self._devices: list[dict] = []
        self._client: DeyeCloudClient | None = None

    # ── Step 1: credentials + region ─────────────────────────────────────────

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                client = DeyeCloudClient(
                    app_id=user_input[CONF_APP_ID],
                    app_secret=user_input[CONF_APP_SECRET],
                    email=user_input[CONF_EMAIL],
                    password=user_input[CONF_PASSWORD],
                    server=user_input[CONF_SERVER],
                )
                stations = await self.hass.async_add_executor_job(client.list_stations)
                if not stations:
                    errors["base"] = "no_stations"
                else:
                    self._client   = client
                    self._data     = dict(user_input)
                    self._stations = stations
                    return await self.async_step_station()
            except DeyeApiError:
                errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user", data_schema=CREDS_SCHEMA, errors=errors,
        )

    # ── Step 2: select station ────────────────────────────────────────────────

    async def async_step_station(self, user_input=None):
        errors = {}
        if user_input is not None:
            station_id = user_input[CONF_STATION_ID]
            try:
                devices = await self.hass.async_add_executor_job(
                    self._client.list_devices, station_id
                )
                if not devices:
                    errors["base"] = "no_devices"
                else:
                    self._data[CONF_STATION_ID] = station_id
                    self._devices = devices
                    if len(devices) == 1:
                        self._data[CONF_DEVICE_SN] = devices[0]["sn"]
                        return await self._create_entry(devices[0]["sn"])
                    return await self.async_step_device()
            except DeyeApiError:
                errors["base"] = "cannot_connect"

        options = [{"value": s["id"], "label": s["name"]} for s in self._stations]
        schema = vol.Schema({
            vol.Required(CONF_STATION_ID): SelectSelector(
                SelectSelectorConfig(options=options, mode=SelectSelectorMode.DROPDOWN)
            )
        })
        return self.async_show_form(step_id="station", data_schema=schema, errors=errors)

    # ── Step 3: select device (only when station has multiple inverters) ───────

    async def async_step_device(self, user_input=None):
        if user_input is not None:
            sn = user_input[CONF_DEVICE_SN]
            self._data[CONF_DEVICE_SN] = sn
            return await self._create_entry(sn)

        options = [
            {"value": d["sn"], "label": f"{d['name']} ({d['sn']})"} for d in self._devices
        ]
        schema = vol.Schema({
            vol.Required(CONF_DEVICE_SN): SelectSelector(
                SelectSelectorConfig(options=options, mode=SelectSelectorMode.DROPDOWN)
            )
        })
        return self.async_show_form(step_id="device", data_schema=schema)

    # ── Helper ────────────────────────────────────────────────────────────────

    async def _create_entry(self, device_sn: str):
        await self.async_set_unique_id(device_sn)
        self._abort_if_unique_id_configured()
        station_name = next(
            (s["name"] for s in self._stations if s["id"] == self._data.get(CONF_STATION_ID)),
            device_sn,
        )
        return self.async_create_entry(title=f"Deye — {station_name}", data=self._data)
