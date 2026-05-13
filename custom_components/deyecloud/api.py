"""Deye Cloud API client — stdlib only, no external dependencies."""
import hashlib
import json
import time
from urllib import request, error

from .const import SERVERS, DEFAULT_SERVER, TOKEN_TTL, DEFAULT_RATED_POWER


class DeyeApiError(Exception):
    pass


class DeyeCloudClient:
    def __init__(self, app_id, app_secret, email, password, device_sn="",
                 rated_power=DEFAULT_RATED_POWER, server=DEFAULT_SERVER):
        self._app_id       = app_id
        self._app_secret   = app_secret
        self._email        = email
        self._password     = password
        self.device_sn     = device_sn
        self._rated_power  = int(rated_power)
        self._base_url     = SERVERS.get(server, SERVERS[DEFAULT_SERVER])
        self._token        = None
        self._token_expires = 0

    # ── HTTP ──────────────────────────────────────────────────────────────────

    def _post(self, path, payload, auth=True):
        headers = {"Content-Type": "application/json"}
        if auth:
            headers["Authorization"] = f"bearer {self._get_token()}"
        req = request.Request(
            f"{self._base_url}{path}",
            data=json.dumps(payload).encode(),
            headers=headers,
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=15) as r:
                return json.loads(r.read().decode())
        except error.URLError as e:
            raise DeyeApiError(f"Network error: {e}") from e

    # ── Auth ──────────────────────────────────────────────────────────────────

    def _get_token(self):
        if self._token and time.time() < self._token_expires - 60:
            return self._token
        pwd_hash = hashlib.sha256(self._password.encode()).hexdigest()
        resp = self._post(
            f"/account/token?appId={self._app_id}",
            {"appSecret": self._app_secret, "email": self._email,
             "password": pwd_hash, "companyId": "0"},
            auth=False,
        )
        if not resp.get("success"):
            raise DeyeApiError(f"Auth failed: {resp.get('msg')}")
        self._token = resp["accessToken"]
        self._token_expires = time.time() + TOKEN_TTL
        return self._token

    # ── Discovery ─────────────────────────────────────────────────────────────

    def list_stations(self) -> list[dict]:
        resp = self._post("/station/list", {"page": 1, "size": 100})
        if not resp.get("success"):
            raise DeyeApiError(f"Station list failed: {resp.get('msg')}")
        stations = resp.get("stationList") or resp.get("infos") or []
        return [
            {"id": str(s.get("id") or s.get("stationId", "")),
             "name": s.get("name") or s.get("stationName") or str(s.get("id", ""))}
            for s in stations
        ]

    def list_devices(self, station_id: str) -> list[dict]:
        resp = self._post("/station/device", {"page": 1, "size": 100,
                                               "stationIds": [station_id]})
        if not resp.get("success"):
            raise DeyeApiError(f"Device list failed: {resp.get('msg')}")
        devices = (resp.get("deviceListItems")
                   or resp.get("infos")
                   or resp.get("deviceList")
                   or [])
        return [
            {"sn":   d.get("deviceSn") or d.get("sn", ""),
             "name": d.get("deviceName") or d.get("name") or d.get("deviceSn", "")}
            for d in devices
        ]

    # ── Read ──────────────────────────────────────────────────────────────────

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

        result = {
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
            "grid_voltage_l1":         f("GridVoltageL1"),
            "grid_voltage_l2":         f("GridVoltageL2"),
            "grid_voltage_l3":         f("GridVoltageL3"),
            "grid_frequency":          f("GridFrequency"),
            "inverter_power_l1":       f("InverterOutputPowerL1"),
            "inverter_power_l2":       f("InverterOutputPowerL2"),
            "inverter_power_l3":       f("InverterOutputPowerL3"),
        }

        # /config/system: work mode + max sell power (not in telemetry)
        try:
            sys_resp = self._post("/config/system", {"deviceSn": self.device_sn})
            if sys_resp.get("success"):
                result["work_mode"]      = sys_resp.get("systemWorkMode", "UNKNOWN")
                result["max_sell_power"] = int(sys_resp.get("maxSellPower", 0))
        except Exception:
            result["work_mode"]      = "UNKNOWN"
            result["max_sell_power"] = 0

        return result

    def read_tou(self) -> dict:
        """Read TOU config and return the active charge window."""
        resp = self._post("/config/tou", {"deviceSn": self.device_sn})
        if not resp.get("success"):
            raise DeyeApiError(f"Read TOU failed: {resp.get('msg')}")

        items = resp.get("timeUseSettingItems", [])

        def fmt(hhmm: str) -> str:
            return f"{hhmm[:2]}:{hhmm[2:]}"

        charge_idx = next((i for i, s in enumerate(items) if s.get("enableGridCharge")), None)
        if charge_idx is not None and charge_idx + 1 < len(items):
            charge = items[charge_idx]
            end    = items[charge_idx + 1]
            return {
                "charge_start":  fmt(charge.get("time", "1105")),
                "charge_end":    fmt(end.get("time", "1355")),
                "charge_soc":    int(charge.get("soc", 100)),
                "discharge_soc": int(items[0].get("soc", 6)),
            }

        return {"charge_start": "11:05", "charge_end": "13:55",
                "charge_soc": 100, "discharge_soc": 6}

    # ── Control ───────────────────────────────────────────────────────────────

    def set_work_mode(self, mode: str) -> None:
        resp = self._post("/order/sys/workMode/update",
                          {"deviceSn": self.device_sn, "workMode": mode})
        if not resp.get("success"):
            raise DeyeApiError(f"Set mode failed: {resp.get('msg')}")

    def set_max_sell_power(self, power_w: int) -> None:
        resp = self._post("/order/sys/power/update", {
            "deviceSn":  self.device_sn,
            "powerType": "MAX_SELL_POWER",
            "value":     int(power_w),
        })
        if not (resp.get("success", False) or resp.get("status") == 666):
            raise DeyeApiError(f"Set max sell power failed: {resp.get('msg', resp)}")

    def set_tou(self, charge_start: str, charge_end: str,
                charge_soc: int, discharge_soc: int) -> None:
        """Write 3-window TOU. Times are 'HH:MM', snapped to 5-min boundary."""
        def snap(hhmm: str) -> str:
            h = int(hhmm[:2])
            m = int(hhmm[3:] if ":" in hhmm else hhmm[2:])
            return f"{h:02d}:{(m // 5) * 5:02d}"

        def slot(t, grid_charge, soc):
            return {"time": t, "enableGridCharge": grid_charge,
                    "enableGeneration": False, "power": self._rated_power, "soc": int(soc)}

        slots = [
            slot("00:00",          False, discharge_soc),
            slot(snap(charge_start), True,  charge_soc),
            slot(snap(charge_end),   False, discharge_soc),
            slot("00:00",          False, discharge_soc),
            slot("00:00",          False, discharge_soc),
            slot("00:00",          False, discharge_soc),
        ]
        resp = self._post("/order/sys/tou/update",
                          {"deviceSn": self.device_sn, "timeUseSettingItems": slots})
        if not (resp.get("success", False) or resp.get("status") == 666):
            raise DeyeApiError(f"Set TOU failed: {resp.get('msg', resp)}")
