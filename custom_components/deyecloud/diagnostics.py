"""Diagnostics: raw Deye Cloud responses for this inverter (secrets redacted)."""
import json
import time
from urllib import request

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN, CONF_APP_ID, CONF_APP_SECRET, CONF_EMAIL, CONF_PASSWORD, CONF_STATION_ID,
)

TO_REDACT = {CONF_APP_ID, CONF_APP_SECRET, CONF_EMAIL, CONF_PASSWORD, "accessToken"}


def _get(client, path: str) -> dict:
    req = request.Request(
        f"{client._base_url}{path}",
        headers={"Authorization": f"bearer {client._get_token()}"},
        method="GET",
    )
    with request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def _safe(fn):
    try:
        return fn()
    except Exception as e:  # diagnostics must never fail as a whole
        return {"error": repr(e)}


def _dynamic_control_read(client) -> dict:
    resp = client._post("/strategy/dynamicControl/read", {"deviceSn": client.device_sn})
    order_id = resp.get("orderId")
    if not order_id:
        return {"response": resp}
    order = {}
    for _ in range(12):
        time.sleep(3)
        order = _get(client, f"/order/{order_id}")
        if order.get("status") not in (0, 100):
            break
    return {"response": resp, "order": order}


def _collect(client, station_id) -> dict:
    sn = client.device_sn
    return {
        "device_latest": _safe(lambda: client._post("/device/latest", {"deviceList": [sn]})),
        "measure_points": _safe(lambda: client._post("/device/measurePoints", {"deviceSn": sn})),
        "config_system": _safe(lambda: client._post("/config/system", {"deviceSn": sn})),
        "config_tou": _safe(lambda: client._post("/config/tou", {"deviceSn": sn})),
        "config_battery": _safe(lambda: client._post("/config/battery", {"deviceSn": sn})),
        "station_latest": _safe(lambda: client._post("/station/latest", {"stationId": int(station_id)}))
        if station_id else {"error": "no station id"},
        "dynamic_control_read": _safe(lambda: _dynamic_control_read(client)),
    }


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    raw = await hass.async_add_executor_job(
        _collect, coordinator.client, entry.data.get(CONF_STATION_ID)
    )
    return {
        "entry_data": async_redact_data(dict(entry.data), TO_REDACT),
        "coordinator_data": coordinator.data,
        "api": async_redact_data(raw, TO_REDACT),
    }
