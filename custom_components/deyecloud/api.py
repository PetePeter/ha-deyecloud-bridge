"""Deye Cloud API client — stdlib only, no external dependencies."""
import hashlib
import json
import time
from urllib import request, error

from .const import BASE_URL, TOKEN_TTL, DAYS


class DeyeApiError(Exception):
    pass


class DeyeCloudClient:
    def __init__(self, app_id, app_secret, email, password, device_sn, rated_power=15000):
        self._app_id = app_id
        self._app_secret = app_secret
        self._email = email
        self._password = password
        self.device_sn = device_sn
        self.rated_power = rated_power
        self._token = None
        self._token_expires = 0

    def _post(self, path, payload, auth=True):
        headers = {"Content-Type": "application/json"}
        if auth:
            headers["Authorization"] = f"bearer {self._get_token()}"
        url = f"{BASE_URL}{path}"
        req = request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers=headers,
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=15) as r:
                return json.loads(r.read().decode())
        except error.URLError as e:
            raise DeyeApiError(f"Network error: {e}") from e

    def _get_token(self):
        if self._token and time.time() < self._token_expires - 60:
            return self._token

        pwd_hash = hashlib.sha256(self._password.encode()).hexdigest()
        resp = self._post(
            f"/account/token?appId={self._app_id}",
            {
                "appSecret": self._app_secret,
                "email": self._email,
                "password": pwd_hash,
                "companyId": "0",
            },
            auth=False,
        )
        if not resp.get("success"):
            raise DeyeApiError(f"Auth failed: {resp.get('msg')}")
        self._token = resp["accessToken"]
        self._token_expires = time.time() + TOKEN_TTL
        return self._token

    def read(self) -> dict:
        resp = self._post("/device/latest", {"deviceList": [self.device_sn]})
        if not resp.get("success"):
            raise DeyeApiError(f"Read failed: {resp.get('msg')}")

        raw = {
            d["key"]: d["value"]
            for d in resp["deviceDataList"][0]["dataList"]
            if d.get("key")
        }

        def f(key, default=0.0):
            try:
                return float(raw.get(key, default))
            except (ValueError, TypeError):
                return float(default)

        return {
            "solar_power":             f("TotalSolarPower"),
            "house_load":              f("TotalConsumptionPower"),
            "grid_power":              f("TotalGridPower"),
            "battery_power":           f("BatteryPower"),
            "ups_power":               f("UPSLoadPower"),
            "battery_soc":             f("SOC"),
            "battery_voltage":         f("BatteryVoltage"),
            "battery_temp":            f("Temperature- Battery"),
            "inverter_temp":           f("AC Temperature"),
            "daily_solar":             f("DailyActiveProduction"),
            "daily_consumption":       f("DailyConsumption"),
            "total_solar":             f("TotalActiveProduction"),
            "total_grid_import":       f("TotalEnergyBuy"),
            "total_grid_export":       f("TotalEnergySell"),
            "total_battery_charge":    f("TotalChargeEnergy"),
            "total_battery_discharge": f("TotalDischargeEnergy"),
        }

    def set_work_mode(self, mode: str) -> None:
        payload = {
            "deviceSn": self.device_sn,
            "solarSellAction": "on" if mode == "SELLING_FIRST" else "off",
            "touAction": "on",
            "touDays": DAYS,
            "workMode": mode,
            "timeUseSettingItems": [
                {
                    "enableGeneration": True,
                    "enableGridCharge": False,
                    "power": self.rated_power,
                    "soc": 10,
                    "time": t,
                }
                for t in ["00:00", "04:00", "08:00", "12:00", "16:00", "20:00"]
            ],
        }
        resp = self._post("/strategy/dynamicControl", payload)
        if not resp.get("success"):
            raise DeyeApiError(f"Set mode failed: {resp.get('msg')}")
