import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback

from .api import DeyeCloudClient, DeyeApiError
from .const import (
    DOMAIN,
    CONF_APP_ID, CONF_APP_SECRET, CONF_EMAIL, CONF_PASSWORD,
    CONF_DEVICE_SN, CONF_RATED_POWER, DEFAULT_RATED_POWER,
)

STEP_SCHEMA = vol.Schema({
    vol.Required(CONF_APP_ID):      str,
    vol.Required(CONF_APP_SECRET):  str,
    vol.Required(CONF_EMAIL):       str,
    vol.Required(CONF_PASSWORD):    str,
    vol.Required(CONF_DEVICE_SN):   str,
    vol.Optional(CONF_RATED_POWER, default=DEFAULT_RATED_POWER): int,
})


class DeyeCloudConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                client = DeyeCloudClient(
                    app_id=user_input[CONF_APP_ID],
                    app_secret=user_input[CONF_APP_SECRET],
                    email=user_input[CONF_EMAIL],
                    password=user_input[CONF_PASSWORD],
                    device_sn=user_input[CONF_DEVICE_SN],
                )
                await self.hass.async_add_executor_job(client.read)
            except DeyeApiError as e:
                errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(user_input[CONF_DEVICE_SN])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Deye Inverter {user_input[CONF_DEVICE_SN]}",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_SCHEMA,
            errors=errors,
        )
