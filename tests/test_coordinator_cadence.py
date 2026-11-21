"""Cadence + dirty-flag logic for DeyeCoordinator.

Exercises the real production methods (_config_due, _carry_forward_config,
mark_config_dirty) without the Home Assistant test harness by building the
instance with object.__new__ and setting only the attributes those methods use.
"""
import asyncio
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


def _make(config_interval=900, settings_interval=21600, settings_retry=1800):
    c = object.__new__(DeyeCoordinator)
    c._config_interval = config_interval
    c._settings_interval = settings_interval
    c._settings_retry = settings_retry
    c._last_config_read = 0.0
    c._next_settings_read = 0.0
    c._config_dirty = False
    c._settings_dirty = False
    c._settings_keys = frozenset()
    c._config_gen = 0
    c.data = None
    return c


class _Client:
    """Records the config reads. read_settings is the only one sent through the logger."""

    def __init__(self, settings_error=None, during_settings=None, settings=None):
        self.calls = []
        self.system = {"work_mode": "SELLING_FIRST"}  # what the cloud cache holds
        self._settings = {"grid_charge": True} if settings is None else settings
        self._settings_error = settings_error
        self._during_settings = during_settings

    def read_system(self):
        self.calls.append("system")
        return dict(self.system)

    def read_tou(self):
        self.calls.append("tou")
        return {"tou_slots": []}

    def read_settings(self):
        self.calls.append("settings")
        if self._during_settings:
            self._during_settings()
        if self._settings_error:
            raise self._settings_error
        return dict(self._settings)

    def read_alerts(self):
        self.calls.append("alerts")
        return {"active_alerts": []}


class _Hass:
    async def async_add_executor_job(self, func, *args):
        return func(*args)


def _read_config(c, client):
    c.client = client
    c.hass = _Hass()
    data = {"battery_soc": 50}
    asyncio.run(c._read_config(data))
    return data


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


def test_settings_command_due_on_first_run():
    assert _make()._settings_due() is True


def test_settings_command_not_due_on_a_regular_config_read(monkeypatch):
    c = _make(config_interval=900, settings_interval=21600)
    now = [1000.0]
    monkeypatch.setattr(coordinator.time, "monotonic", lambda: now[0])
    c._last_config_read = now[0]
    c._next_settings_read = now[0] + 21600
    now[0] += 900  # the 15-min config read is due, the live register read is not
    assert c._config_due() is True
    assert c._settings_due() is False


def test_settings_command_due_after_its_own_interval(monkeypatch):
    c = _make(settings_interval=21600)
    now = [1000.0]
    monkeypatch.setattr(coordinator.time, "monotonic", lambda: now[0])
    c._next_settings_read = now[0] + 21600
    now[0] += 21600
    assert c._settings_due() is True


def test_dirty_flag_forces_settings_command(monkeypatch):
    c = _make()
    now = [1000.0]
    monkeypatch.setattr(coordinator.time, "monotonic", lambda: now[0])
    c._next_settings_read = now[0] + 21600
    assert c._settings_due() is False
    c.mark_config_dirty()
    assert c._settings_due() is True


def test_regular_config_read_skips_the_settings_command(monkeypatch):
    c = _make()
    monkeypatch.setattr(coordinator.time, "monotonic", lambda: 1000.0)
    c._next_settings_read = 1000.0 + 21600
    client = _Client()
    _read_config(c, client)
    assert client.calls == ["system", "tou", "alerts"]


def test_settings_command_sent_when_due_then_rescheduled(monkeypatch):
    c = _make(settings_interval=21600)
    monkeypatch.setattr(coordinator.time, "monotonic", lambda: 1000.0)
    client = _Client()
    data = _read_config(c, client)
    assert client.calls == ["system", "tou", "settings", "alerts"]
    assert data["grid_charge"] is True
    assert c._next_settings_read == 1000.0 + 21600
    assert c._settings_due() is False


def test_failed_settings_command_backs_off(monkeypatch):
    c = _make(settings_retry=1800)
    monkeypatch.setattr(coordinator.time, "monotonic", lambda: 1000.0)
    c.mark_config_dirty()
    _read_config(c, _Client(settings_error=RuntimeError("status 500, error 540")))
    assert c._next_settings_read == 1000.0 + 1800
    assert c._settings_due() is False  # no retry on the next poll, even after a write
    assert c._config_due() is False    # system + TOU were read, so the config read counts


def test_write_during_read_keeps_settings_command_due(monkeypatch):
    c = _make()
    monkeypatch.setattr(coordinator.time, "monotonic", lambda: 1000.0)
    c.data = {"grid_charge": False}  # optimistic value from the write
    data = _read_config(c, _Client(during_settings=c.mark_config_dirty))
    assert data["grid_charge"] is False
    assert c._settings_due() is True
    assert c._config_due() is True


def test_regular_read_keeps_register_values_over_the_cloud_cache(monkeypatch):
    c = _make()
    now = [1000.0]
    monkeypatch.setattr(coordinator.time, "monotonic", lambda: now[0])
    client = _Client(settings={"work_mode": "ZERO_EXPORT_TO_CT", "grid_charge": True})
    c.data = _read_config(c, client)  # first read: the registers win
    assert c.data["work_mode"] == "ZERO_EXPORT_TO_CT"
    now[0] += 900
    data = _read_config(c, client)    # regular read: no command, the cache says SELLING_FIRST
    assert client.calls[-3:] == ["system", "tou", "alerts"]
    assert data["work_mode"] == "ZERO_EXPORT_TO_CT"


def test_failed_settings_command_keeps_the_written_value(monkeypatch):
    c = _make()
    monkeypatch.setattr(coordinator.time, "monotonic", lambda: 1000.0)
    c._settings_keys = frozenset({"work_mode"})
    c.data = {"work_mode": "ZERO_EXPORT_TO_LOAD"}  # optimistic value from a write
    c.mark_config_dirty()
    data = _read_config(c, _Client(settings_error=RuntimeError("status 500, error 540")))
    assert data["work_mode"] == "ZERO_EXPORT_TO_LOAD"  # not the cache's SELLING_FIRST


def test_cloud_cache_still_used_when_the_registers_are_not_reported(monkeypatch):
    c = _make()
    now = [1000.0]
    monkeypatch.setattr(coordinator.time, "monotonic", lambda: now[0])
    client = _Client(settings={})  # a model that does not answer with these registers
    c.data = _read_config(c, client)
    assert c.data["work_mode"] == "SELLING_FIRST"
    client.system = {"work_mode": "ZERO_EXPORT_TO_CT"}
    now[0] += 900
    assert _read_config(c, client)["work_mode"] == "ZERO_EXPORT_TO_CT"


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
