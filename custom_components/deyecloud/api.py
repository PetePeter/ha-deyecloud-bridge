"""Deye Cloud API client — stdlib only, no external dependencies."""
import hashlib
import http.client
import json
import threading
import time
from urllib import request

from .const import SERVERS, DEFAULT_SERVER, TOKEN_TTL, DEFAULT_RATED_POWER, DAYS

# /order/{id} status values
ORDER_PENDING = (0, 100)
ORDER_SUCCESS = 666

ORDER_TIMEOUT = 60        # seconds to wait for the inverter to confirm a command
ORDER_POLL = 2            # seconds between /order/{id} polls
BUSY_RETRIES = 3          # retries when the cloud says another command is still running
BUSY_WAIT = 10            # seconds between those retries

# Telemetry: result key -> candidate /device/latest keys (first present wins).
# Single-phase LP1 inverters report L1L2 keys; three-phase ones report L1/L2/L3.
NUMERIC_KEYS: dict[str, tuple[str, ...]] = {
    "solar_power":             ("TotalDCInputPower", "TotalSolarPower"),
    "pv1_power":               ("DCPowerPV1",),
    "pv2_power":               ("DCPowerPV2",),
    "pv1_voltage":             ("DCVoltagePV1",),
    "pv2_voltage":             ("DCVoltagePV2",),
    "pv1_current":             ("DCCurrentPV1",),
    "pv2_current":             ("DCCurrentPV2",),
    "house_load":              ("TotalConsumptionPower",),
    "grid_power":              ("TotalGridPower",),
    "ups_power":               ("UPSLoadPower",),
    "battery_power":           ("BatteryPower",),
    "battery_current":         ("BatteryCurrent",),
    "battery_soc":             ("SOC",),
    "battery_voltage":         ("BatteryVoltage",),
    "battery_temp":            ("Temperature- Battery", "BMSTemperature"),
    "inverter_temp":           ("AC Temperature",),
    "dc_temp":                 ("DC Temperature",),
    "daily_solar":             ("DailyActiveProduction", "PVDailyPowerGenerationActive"),
    "daily_consumption":       ("DailyConsumption",),
    "daily_grid_import":       ("DailyEnergyPurchased",),
    "daily_grid_export":       ("DailyGridFeedIn",),
    "daily_battery_charge":    ("DailyChargingEnergy",),
    "daily_battery_discharge": ("DailyDischargingEnergy",),
    "total_solar":             ("TotalActiveProduction", "PVCumulativePowerGenerationActive"),
    "total_consumption":       ("CumulativeConsumption",),
    "total_grid_import":       ("CumulativeEnergyPurchased", "TotalEnergyBuy"),
    "total_grid_export":       ("CumulativeGridFeedIn", "TotalEnergySell"),
    "total_battery_charge":    ("TotalChargeEnergy",),
    "total_battery_discharge": ("TotalDischargeEnergy",),
    "grid_voltage_l1":         ("GridVoltageL1L2", "GridVoltageL1"),
    "grid_voltage_l2":         ("GridVoltageL2",),
    "grid_voltage_l3":         ("GridVoltageL3",),
    "grid_current":            ("GridCurrentL1L2", "GridCurrentL1"),
    "grid_frequency":          ("GridFrequency",),
    "grid_reactive_power":     ("GridTotalReactivePower",),
    "load_voltage":            ("LoadVoltageL1L2", "LoadVoltageL1"),
    "inverter_power_l1":       ("InverterOutputPowerL1L2", "InverterOutputPowerL1"),
    "inverter_power_l2":       ("InverterOutputPowerL2",),
    "inverter_power_l3":       ("InverterOutputPowerL3",),
    "inverter_voltage":        ("ACVoltageRUA",),
    "inverter_current":        ("ACCurrentRUA",),
    "inverter_frequency":      ("ACOutputFrequencyR",),
    "power_factor":            ("PowerFactor",),
    "rated_power":             ("RatedPower",),
    "bms_voltage":             ("BMSVoltage",),
    "bms_current":             ("BMSCurrent",),
    "bms_temperature":         ("BMSTemperature",),
    "bms_soc":                 ("BMSSOC",),
    "bms_charge_voltage":      ("BMSChargeVoltage",),
    "bms_charge_current_limit":    ("ChargeCurrentLimit",),
    "bms_discharge_current_limit": ("DischargeCurrentLimit",),
}
TEXT_KEYS: dict[str, tuple[str, ...]] = {
    "grid_relay_status": ("GridRelayStatus",),
    "firmware_main":     ("MAIN",),
    "firmware_hmi":      ("HMI",),
}

# /strategy/dynamicControl/read register map of single-phase LP1 hybrids
# (hex address -> setting). Other models answer with other addresses; then
# these settings are simply left out.
_REG_WORK_MODE = "00F4"
_REG_TOU = "00F8"
_WORK_MODE_BY_VALUE = {0: "SELLING_FIRST", 1: "ZERO_EXPORT_TO_LOAD", 2: "ZERO_EXPORT_TO_CT"}
_INT_REGISTERS = {
    "00E6": "grid_charge_current",
    "00D2": "max_charge_current",
    "00D3": "max_discharge_current",
    "00F5": "max_sell_power",
    "0035": "max_solar_power",
}
_BOOL_REGISTERS = {"00E8": "grid_charge", "00F7": "solar_sell"}


def decode_settings(registers: dict) -> dict:
    regs = {str(k).upper().zfill(4): v for k, v in (registers or {}).items()}
    if _REG_WORK_MODE not in regs or _REG_TOU not in regs:
        return {}

    def num(addr):
        try:
            return int(float(regs[addr]))
        except (KeyError, TypeError, ValueError):
            return None

    out = {}
    mode = num(_REG_WORK_MODE)
    if mode in _WORK_MODE_BY_VALUE:
        out["work_mode"] = _WORK_MODE_BY_VALUE[mode]
    tou = num(_REG_TOU)
    if tou is not None:
        out["time_of_use"] = bool(tou & 1)
    for addr, key in _INT_REGISTERS.items():
        if (v := num(addr)) is not None:
            out[key] = v
    for addr, key in _BOOL_REGISTERS.items():
        if (v := num(addr)) is not None:
            out[key] = bool(v)
    return out


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
        # The cloud runs one command per inverter at a time: serialize ours.
        self._order_lock   = threading.Lock()

    # ── HTTP ──────────────────────────────────────────────────────────────────

    def _http(self, method, path, payload=None, auth=True):
        headers = {"Content-Type": "application/json"}
        if auth:
            headers["Authorization"] = f"bearer {self._get_token()}"
        req = request.Request(
            f"{self._base_url}{path}",
            data=json.dumps(payload).encode() if payload is not None else None,
            headers=headers,
            method=method,
        )
        try:
            with request.urlopen(req, timeout=15) as r:
                return json.loads(r.read().decode())
        except (OSError, http.client.HTTPException, ValueError) as e:
            # URLError and TimeoutError are OSErrors; ValueError covers a non-JSON body.
            raise DeyeApiError(f"Network error on {path}: {e!r}") from e

    def _post(self, path, payload, auth=True):
        return self._http("POST", path, payload, auth)

    def _get(self, path):
        return self._http("GET", path)

    def _order(self, path: str, payload: dict) -> dict:
        """Send a command and wait until the inverter confirms it (status 666)."""
        with self._order_lock:
            for attempt in range(BUSY_RETRIES + 1):
                resp = self._post(path, payload)
                if resp.get("success"):
                    break
                msg = str(resp.get("msg") or resp)
                if "concurrent" in msg and attempt < BUSY_RETRIES:
                    time.sleep(BUSY_WAIT)
                    continue
                raise DeyeApiError(f"{path} rejected: {msg}")
            order_id = resp.get("orderId")
            if not order_id:
                return resp  # applied synchronously
            deadline = time.monotonic() + ORDER_TIMEOUT
            order: dict = {}
            while time.monotonic() < deadline:
                time.sleep(ORDER_POLL)
                try:
                    order = self._get(f"/order/{order_id}")
                except DeyeApiError:
                    continue  # one failed poll is not a failed command: keep polling
                status = order.get("status")
                if status == ORDER_SUCCESS:
                    return order
                # None: a non-success reply or the order not visible yet — still pending.
                if status is not None and status not in ORDER_PENDING:
                    raise DeyeApiError(
                        f"{path} failed on the inverter: status {status}, error {order.get('error')}"
                    )
            raise DeyeApiError(f"{path} not confirmed within {ORDER_TIMEOUT} s (last status {order.get('status')})")

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
        """Telemetry only (/device/latest) — polled every cycle."""
        resp = self._post("/device/latest", {"deviceList": [self.device_sn]})
        if not resp.get("success"):
            raise DeyeApiError(f"Read failed: {resp.get('msg')}")

        raw = {
            d["key"]: d["value"]
            for d in resp["deviceDataList"][0]["dataList"]
            if d.get("key")
        }

        # A key this model does not report (or a bad value) is None, not 0: a fake 0
        # would look like a counter reset to the TOTAL_INCREASING energy sensors.
        result: dict = {}
        for key, candidates in NUMERIC_KEYS.items():
            src = next((c for c in candidates if c in raw), None)
            try:
                result[key] = float(raw[src]) if src else None
            except (ValueError, TypeError):
                result[key] = None
        for key, candidates in TEXT_KEYS.items():
            src = next((c for c in candidates if c in raw), None)
            result[key] = str(raw[src]).strip() if src else None
        return result

    def read_system(self) -> dict:
        """System settings (/config/system) plus battery config — not in telemetry."""
        resp = self._post("/config/system", {"deviceSn": self.device_sn})
        if not resp.get("success"):
            raise DeyeApiError(f"Read system failed: {resp.get('msg')}")
        result = {
            "work_mode":         resp.get("systemWorkMode", "UNKNOWN"),
            "max_sell_power":    int(resp.get("maxSellPower", 0)),
            "max_solar_power":   resp.get("maxSolarPower"),
            "zero_export_power": resp.get("zeroExportPower"),
            "energy_pattern":    resp.get("energyPattern"),
        }
        try:
            result.update(self.read_battery())
        except DeyeApiError:
            pass
        return result

    def read_battery(self) -> dict:
        """Battery config (/config/battery)."""
        resp = self._post("/config/battery", {"deviceSn": self.device_sn})
        if not resp.get("success"):
            raise DeyeApiError(f"Read battery failed: {resp.get('msg')}")
        return {
            "battery_capacity_ah":   resp.get("battCapacity"),
            "battery_low_soc":       resp.get("battLowCapacity"),
            "battery_shutdown_soc":  resp.get("battShutDownCapacity"),
            "max_charge_current":    resp.get("maxChargeCurrent"),
            "max_discharge_current": resp.get("maxDischargeCurrent"),
        }

    def read_settings(self) -> dict:
        """Live inverter settings via /strategy/dynamicControl/read (an order, ~5 s)."""
        order = self._order("/strategy/dynamicControl/read", {"deviceSn": self.device_sn})
        registers = order.get("analysisResult")
        if isinstance(registers, str):
            try:
                registers = json.loads(registers)
            except ValueError:
                registers = {}
        return decode_settings(registers or {})

    def read_tou(self) -> dict:
        """Read TOU config: the active charge window plus the full schedule."""
        resp = self._post("/config/tou", {"deviceSn": self.device_sn})
        if not resp.get("success"):
            raise DeyeApiError(f"Read TOU failed: {resp.get('msg')}")

        items = resp.get("timeUseSettingItems", [])

        def fmt(hhmm: str) -> str:
            hhmm = str(hhmm).replace(":", "").zfill(4)
            return f"{hhmm[:2]}:{hhmm[2:]}"

        schedule = {
            "tou_enabled": resp.get("touAction") == "on",
            "tou_slots": [
                {"time": fmt(s.get("time", "0000")),
                 "grid_charge": bool(s.get("enableGridCharge")),
                 "generator": bool(s.get("enableGeneration")),
                 "soc": int(s.get("soc", 0)),
                 "power": int(s.get("power", 0))}
                for s in items
            ],
        }

        charge_idx = next((i for i, s in enumerate(items) if s.get("enableGridCharge")), None)
        if charge_idx is not None and charge_idx + 1 < len(items):
            charge = items[charge_idx]
            end    = items[charge_idx + 1]
            return {
                **schedule,
                "charge_start":  fmt(charge.get("time", "1105")),
                "charge_end":    fmt(end.get("time", "1355")),
                "charge_soc":    int(charge.get("soc", 100)),
                "discharge_soc": int(items[0].get("soc", 6)),
            }

        return {**schedule, "charge_start": "11:00", "charge_end": "14:00",
                "charge_soc": 100, "discharge_soc": 6}

    # ── Control ───────────────────────────────────────────────────────────────

    def set_work_mode(self, mode: str) -> None:
        self._order("/order/sys/workMode/update",
                    {"deviceSn": self.device_sn, "workMode": mode})

    def set_energy_pattern(self, pattern: str) -> None:
        """pattern: BATTERY_FIRST or LOAD_FIRST."""
        self._order("/order/sys/energyPattern/update",
                    {"deviceSn": self.device_sn, "energyPattern": pattern})

    def set_power(self, power_type: str, power_w: int) -> None:
        """power_type: MAX_SELL_POWER, MAX_SOLAR_POWER or ZERO_EXPORT_POWER."""
        self._order("/order/sys/power/update", {
            "deviceSn":  self.device_sn,
            "powerType": power_type,
            "value":     int(power_w),
        })

    def set_max_sell_power(self, power_w: int) -> None:
        self.set_power("MAX_SELL_POWER", power_w)

    def set_solar_sell(self, on: bool) -> None:
        self._order("/order/sys/solarSell/control",
                    {"deviceSn": self.device_sn, "action": "on" if on else "off"})

    def set_time_of_use(self, on: bool) -> None:
        """TOU schedule on (every day) or off; the slots themselves are kept.
        'days' must be sent explicitly: without it an LP1 inverter ends up with TOU
        enabled but no active day (register 00F8 = 1 instead of 255)."""
        payload = {"deviceSn": self.device_sn, "action": "on" if on else "off"}
        if on:
            payload["days"] = list(DAYS)
        self._order("/order/sys/tou/switch", payload)

    def set_grid_peak_shaving(self, on: bool, power_w: int | None = None) -> None:
        """Cap grid import at power_w (PV and battery cover the rest). Power kept if omitted."""
        payload = {"deviceSn": self.device_sn, "action": "on" if on else "off"}
        if power_w is not None:
            payload["power"] = int(power_w)
        self._order("/order/gridPeakShaving/control", payload)

    def read_alerts(self, days: int = 7) -> dict:
        """Inverter alerts of the last `days` days (/device/alertList, max 30 days)."""
        now = int(time.time())
        resp = self._post("/device/alertList", {
            "deviceSn": self.device_sn,
            "startTimestamp": now - days * 86400,
            "endTimestamp": now,
            "page": 1,
            "size": 50,
        })
        if not resp.get("success"):
            raise DeyeApiError(f"Read alerts failed: {resp.get('msg')}")
        alerts = sorted(resp.get("alertList") or [],
                        key=lambda a: a.get("alertStartTime") or 0, reverse=True)
        return {
            "active_alerts": sum(1 for a in alerts if a.get("status") == 1),
            "recent_alerts": [
                {k: a.get(k) for k in ("alertName", "level", "status", "alertStartTime",
                                       "alertEndTime", "description", "reason", "solution")}
                for a in alerts[:10]
            ],
        }

    def set_battery_param(self, param_type: str, value: int) -> None:
        """param_type: MAX_CHARGE_CURRENT, MAX_DISCHARGE_CURRENT, GRID_CHARGE_AMPERE, BATT_LOW."""
        self._order("/order/battery/parameter/update", {
            "deviceSn":     self.device_sn,
            "paramterType": param_type,  # sic, the Deye API spells it this way
            "value":        int(value),
        })

    def set_battery_mode(self, mode_type: str, on: bool) -> None:
        """mode_type: GRID_CHARGE or GEN_CHARGE (the inverter's master enable switches)."""
        self._order("/order/battery/modeControl", {
            "deviceSn":        self.device_sn,
            "batteryModeType": mode_type,
            "action":          "on" if on else "off",
        })

    @staticmethod
    def _snap(hhmm: str) -> str:
        """'HH:MM' (or 'HHMM') snapped down to a 5-minute boundary."""
        hhmm = str(hhmm).strip()
        h = int(hhmm[:2])
        m = int(hhmm[3:] if ":" in hhmm else hhmm[2:4])
        return f"{h:02d}:{(m // 5) * 5:02d}"

    def set_tou_slots(self, slots: list[dict]) -> None:
        """Write the full schedule: up to 6 slots of {time, grid_charge, soc, power?}.
        Missing slots are padded with 00:00 copies of the last one."""
        if not 1 <= len(slots) <= 6:
            raise DeyeApiError("A schedule needs 1 to 6 slots")
        items = [
            {"time": self._snap(s["time"]),
             "enableGridCharge": bool(s.get("grid_charge", False)),
             "enableGeneration": bool(s.get("generator", False)),
             "power": int(s.get("power") or self._rated_power),
             "soc": int(s["soc"])}
            for s in slots
        ]
        while len(items) < 6:
            items.append({**items[-1], "time": "00:00", "enableGridCharge": False})
        self._order("/order/sys/tou/update",
                    {"deviceSn": self.device_sn, "timeUseSettingItems": items})

    def set_tou(self, charge_start: str, charge_end: str,
                charge_soc: int, discharge_soc: int) -> None:
        """Simple 3-window TOU: grid charge from start to end, floor SOC otherwise."""
        self.set_tou_slots([
            {"time": "00:00",        "grid_charge": False, "soc": discharge_soc},
            {"time": charge_start,   "grid_charge": True,  "soc": charge_soc},
            {"time": charge_end,     "grid_charge": False, "soc": discharge_soc},
            {"time": "00:00",        "grid_charge": False, "soc": discharge_soc},
            {"time": "00:00",        "grid_charge": False, "soc": discharge_soc},
            {"time": "00:00",        "grid_charge": False, "soc": discharge_soc},
        ])
