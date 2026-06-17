"""Cadence + dirty-flag logic for DeyeCoordinator.

Exercises the real production methods (_config_due, _carry_forward_config,
mark_config_dirty) without the Home Assistant test harness by building the
instance with object.__new__ and setting only the attributes those methods use.
"""
import sys
import types
from pathlib import Path

# Stub the HA modules the coordinator imports at module load, so the real
# coordinator module can be imported standalone.
_duc = types.ModuleType("homeassistant.helpers.update_coordinator")
class _DUC:  # minimal stand-in for DataUpdateCoordinator
    pass
class _UpdateFailed(Exception):
    pass
_duc.DataUpdateCoordinator = _DUC
_duc.UpdateFailed = _UpdateFailed
sys.modules.setdefault("homeassistant", types.ModuleType("homeassistant"))
sys.modules.setdefault("homeassistant.helpers", types.ModuleType("homeassistant.helpers"))
sys.modules["homeassistant.helpers.update_coordinator"] = _duc

# Register the package by path WITHOUT running its __init__.py (which pulls in
# heavy HA modules). coordinator.py only needs the stubbed update_coordinator
# plus its stdlib-only siblings (.api, .const).
_pkg_dir = Path(__file__).resolve().parents[1] / "custom_components" / "deyecloud"
_pkg = types.ModuleType("deyecloud")
_pkg.__path__ = [str(_pkg_dir)]
sys.modules["deyecloud"] = _pkg

import importlib
coordinator = importlib.import_module("deyecloud.coordinator")
DeyeCoordinator = coordinator.DeyeCoordinator


def _make(config_interval=900):
    c = object.__new__(DeyeCoordinator)
    c._config_interval = config_interval
    c._last_config_read = 0.0
    c._config_dirty = False
    c.data = None
    return c


def test_config_due_on_first_run():
    c = _make()
    assert c._config_due() is True  # _last_config_read == 0 → must read


def test_config_not_due_within_interval(monkeypatch):
    c = _make(config_interval=900)
    now = [1000.0]
    monkeypatch.setattr(coordinator.time, "monotonic", lambda: now[0])
    c._last_config_read = now[0]
    now[0] += 300  # 5 min later, < 15 min
    assert c._config_due() is False


def test_config_due_after_interval(monkeypatch):
    c = _make(config_interval=900)
    now = [1000.0]
    monkeypatch.setattr(coordinator.time, "monotonic", lambda: now[0])
    c._last_config_read = now[0]
    now[0] += 900  # exactly 15 min later
    assert c._config_due() is True


def test_dirty_flag_forces_read(monkeypatch):
    c = _make(config_interval=900)
    now = [1000.0]
    monkeypatch.setattr(coordinator.time, "monotonic", lambda: now[0])
    c._last_config_read = now[0]
    now[0] += 60  # only 1 min later
    assert c._config_due() is False
    c.mark_config_dirty()
    assert c._config_due() is True  # override regardless of interval


def test_carry_forward_fills_missing_config():
    c = _make()
    c.data = {"work_mode": "SELLING_FIRST", "max_sell_power": 8000,
              "charge_start": "11:05", "charge_soc": 100, "discharge_soc": 6}
    fresh = {"battery_soc": 92}  # telemetry only, no config keys
    c._carry_forward_config(fresh)
    assert fresh["work_mode"] == "SELLING_FIRST"
    assert fresh["max_sell_power"] == 8000
    assert fresh["discharge_soc"] == 6
    assert fresh["battery_soc"] == 92  # telemetry untouched


def test_carry_forward_does_not_overwrite_fresh_values():
    c = _make()
    c.data = {"work_mode": "ZERO_EXPORT_TO_CT"}
    fresh = {"work_mode": "SELLING_FIRST"}  # just read from cloud
    c._carry_forward_config(fresh)
    assert fresh["work_mode"] == "SELLING_FIRST"  # not clobbered by stale value


def test_carry_forward_noop_when_no_prior_data():
    c = _make()
    c.data = None
    fresh = {"battery_soc": 50}
    c._carry_forward_config(fresh)
    assert fresh == {"battery_soc": 50}
