#!/usr/bin/env python3
"""
Deye Cloud bridge for Home Assistant.

Reads credentials from (in priority order):
  1. Environment variables: DEYE_APP_ID, DEYE_APP_SECRET, DEYE_EMAIL,
                            DEYE_PASSWORD, DEYE_DEVICE_SN
  2. config.yaml in the same directory as this script

Usage:
  python3 deye_bridge.py read              -> JSON of all inverter metrics
  python3 deye_bridge.py set SELLING_FIRST
  python3 deye_bridge.py set ZERO_EXPORT_TO_CT
"""

import json, sys, time, hashlib, os
from urllib import request, error
from pathlib import Path

# ── Configuration ─────────────────────────────────────────────────────────────

_CONFIG_TEMPLATE = """\
# Deye Cloud Bridge — configuration
# Sign up at https://developer.deyecloud.com/app to get an App ID and Secret.
# Copy config.example.yaml to config.yaml and fill in your values.

# Deye developer portal: https://developer.deyecloud.com/app
app_id: "YOUR_APP_ID"
app_secret: "YOUR_APP_SECRET"

# Your Deye Cloud account (same login as the Deye app)
email: "you@example.com"
password: "your_password"

# Inverter serial number (Deye app → device → details)
device_sn: "YOUR_INVERTER_SN"

# Inverter rated power in watts
rated_power: 15000

# API base URL — eu1 for Europe/Australia, us1 for Americas
base_url: "https://eu1-developer.deyecloud.com/v1.0"
token_file: "/config/.deye_token.json"
token_ttl: 3000
"""


def load_config():
    cfg = {}
    config_path = Path(__file__).parent / "config.yaml"

    if not config_path.exists():
        config_path.write_text(_CONFIG_TEMPLATE)
        print(
            f"Created {config_path} — fill in your credentials and re-run.\n"
            "Get an App ID + Secret at https://developer.deyecloud.com/app",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        import re
        with open(config_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    m = re.match(r'^(\w+):\s*"?([^"#\n]+)"?\s*$', line)
                    if m:
                        cfg[m.group(1)] = m.group(2).strip()
    except Exception:
        pass

    # Environment variables override config file
    env_map = {
        "app_id":      "DEYE_APP_ID",
        "app_secret":  "DEYE_APP_SECRET",
        "email":       "DEYE_EMAIL",
        "password":    "DEYE_PASSWORD",
        "device_sn":   "DEYE_DEVICE_SN",
        "rated_power": "DEYE_RATED_POWER",
        "base_url":    "DEYE_BASE_URL",
    }
    for key, env_var in env_map.items():
        val = os.environ.get(env_var)
        if val:
            cfg[key] = val

    return cfg


CFG = load_config()
APP_ID      = CFG.get("app_id", "")
APP_SECRET  = CFG.get("app_secret", "")
EMAIL       = CFG.get("email", "")
PASSWORD    = CFG.get("password", "")
DEVICE_SN   = CFG.get("device_sn", "")
RATED_POWER = int(CFG.get("rated_power", 15000))
BASE        = CFG.get("base_url", "https://eu1-developer.deyecloud.com/v1.0")
TOKEN_FILE  = CFG.get("token_file", str(Path(__file__).parent / ".deye_token.json"))
TOKEN_TTL   = int(CFG.get("token_ttl", 3000))

DAYS = ["SUNDAY", "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY"]


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _post(url, payload, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"bearer {token}"
    req = request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    with request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


# ── Auth / token management ───────────────────────────────────────────────────

def get_token():
    try:
        with open(TOKEN_FILE) as f:
            cached = json.load(f)
        if time.time() < cached.get("expires_at", 0) - 60:
            return cached["token"]
    except Exception:
        pass

    if not all([APP_ID, APP_SECRET, EMAIL, PASSWORD]):
        raise RuntimeError("Missing credentials. Set env vars or create config.yaml from config.example.yaml.")

    resp = _post(f"{BASE}/account/token?appId={APP_ID}", {
        "appSecret": APP_SECRET,
        "email": EMAIL,
        "password": hashlib.sha256(PASSWORD.encode()).hexdigest(),
        "companyId": "0",
    })
    if not resp.get("success"):
        raise RuntimeError(f"Auth failed: {resp.get('msg')}")

    token = resp["accessToken"]
    try:
        with open(TOKEN_FILE, "w") as f:
            json.dump({"token": token, "expires_at": time.time() + TOKEN_TTL}, f)
    except Exception:
        pass
    return token


# ── Read inverter data ────────────────────────────────────────────────────────

def read_inverter():
    if not DEVICE_SN:
        raise RuntimeError("DEYE_DEVICE_SN not set.")

    token = get_token()
    resp = _post(f"{BASE}/device/latest", {"deviceList": [DEVICE_SN]}, token)
    if not resp.get("success"):
        raise RuntimeError(f"API error: {resp.get('msg')}")

    raw = {d["key"]: d["value"] for d in resp["deviceDataList"][0]["dataList"] if d.get("key")}

    def f(key, default=0.0):
        try:
            return float(raw.get(key, default))
        except (ValueError, TypeError):
            return float(default)

    return {
        "solar_power":              f("TotalSolarPower"),
        "house_load":               f("TotalConsumptionPower"),
        "grid_power":               f("TotalGridPower"),        # + import, − export
        "battery_power":            f("BatteryPower"),          # + charge, − discharge
        "ups_power":                f("UPSLoadPower"),
        "battery_soc":              f("SOC"),
        "battery_voltage":          f("BatteryVoltage"),
        "battery_temp":             f("Temperature- Battery"),
        "inverter_temp":            f("AC Temperature"),
        "daily_solar":              f("DailyActiveProduction"),
        "daily_consumption":        f("DailyConsumption"),
        "total_solar":              f("TotalActiveProduction"),
        "total_grid_import":        f("TotalEnergyBuy"),
        "total_grid_export":        f("TotalEnergySell"),
        "total_battery_charge":     f("TotalChargeEnergy"),
        "total_battery_discharge":  f("TotalDischargeEnergy"),
    }


# ── Set work mode ─────────────────────────────────────────────────────────────

VALID_MODES = ("SELLING_FIRST", "ZERO_EXPORT_TO_CT")

def set_mode(mode):
    if mode not in VALID_MODES:
        raise ValueError(f"Unknown mode '{mode}'. Valid: {VALID_MODES}")
    if not DEVICE_SN:
        raise RuntimeError("DEYE_DEVICE_SN not set.")

    token = get_token()
    payload = {
        "deviceSn": DEVICE_SN,
        "solarSellAction": "on" if mode == "SELLING_FIRST" else "off",
        "touAction": "on",
        "touDays": DAYS,
        "workMode": mode,
        # API requires exactly 6 time intervals
        "timeUseSettingItems": [
            {"enableGeneration": True, "enableGridCharge": False,
             "power": RATED_POWER, "soc": 10, "time": t}
            for t in ["00:00", "04:00", "08:00", "12:00", "16:00", "20:00"]
        ],
    }
    return _post(f"{BASE}/strategy/dynamicControl", payload, token)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = sys.argv[1:]
    try:
        if not args or args[0] == "read":
            print(json.dumps(read_inverter()))
        elif args[0] == "set" and len(args) == 2:
            result = set_mode(args[1])
            ok = result.get("success", False)
            print(json.dumps({"success": ok, "msg": result.get("msg", "")}))
            sys.exit(0 if ok else 1)
        else:
            print("Usage: deye_bridge.py read | set SELLING_FIRST | set ZERO_EXPORT_TO_CT",
                  file=sys.stderr)
            sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)
