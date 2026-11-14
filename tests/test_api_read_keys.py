"""Telemetry key fallbacks in DeyeCloudClient.read().

api.py is stdlib-only, so it is loaded straight from its file, without the
package __init__ (which needs Home Assistant).
"""
import importlib
import sys
import types
from pathlib import Path

_pkg_dir = Path(__file__).resolve().parents[1] / "custom_components" / "deyecloud"
_pkg = types.ModuleType("deyecloud")
_pkg.__path__ = [str(_pkg_dir)]
sys.modules.setdefault("deyecloud", _pkg)

api = importlib.import_module("deyecloud.api")


def _client(data: dict):
    c = object.__new__(api.DeyeCloudClient)
    c.device_sn = "SN1"
    c._post = lambda path, payload, auth=True: {
        "success": True,
        "deviceDataList": [{"dataList": [{"key": k, "value": v} for k, v in data.items()]}],
    }
    return c


def test_three_phase_keys_still_work():
    r = _client({
        "TotalSolarPower": "3000",
        "TotalEnergyBuy": "120.5",
        "TotalEnergySell": "40",
        "GridVoltageL1": "230",
        "InverterOutputPowerL1": "900",
    }).read()
    assert r["solar_power"] == 3000.0
    assert r["total_grid_import"] == 120.5
    assert r["total_grid_export"] == 40.0
    assert r["grid_voltage_l1"] == 230.0
    assert r["inverter_power_l1"] == 900.0


def test_single_phase_lp1_keys():
    # Values as a SUN-6K LP1 hybrid reports them: TotalSolarPower stays 0.
    r = _client({
        "TotalSolarPower": "0",
        "TotalDCInputPower": "2450",
        "CumulativeEnergyPurchased": "812.3",
        "CumulativeGridFeedIn": "15.1",
        "GridVoltageL1L2": "231.4",
        "InverterOutputPowerL1L2": "1180",
        "PVDailyPowerGenerationActive": "9.8",
        "PVCumulativePowerGenerationActive": "1544",
        "BMSTemperature": "21",
    }).read()
    assert r["solar_power"] == 2450.0
    assert r["total_grid_import"] == 812.3
    assert r["total_grid_export"] == 15.1
    assert r["grid_voltage_l1"] == 231.4
    assert r["inverter_power_l1"] == 1180.0
    assert r["daily_solar"] == 9.8
    assert r["total_solar"] == 1544.0
    assert r["battery_temp"] == 21.0


def test_missing_or_bad_values_default_to_zero():
    r = _client({"TotalDCInputPower": "n/a"}).read()
    assert r["solar_power"] == 0.0
    assert r["total_grid_import"] == 0.0
