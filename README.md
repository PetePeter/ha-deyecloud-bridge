# ha-deyecloud-bridge

Home Assistant integration for Deye solar inverters via the **Deye Cloud OpenAPI**.

Useful when the inverter's local TCP port (8899) is blocked by the LSW5 datalogger firmware
(common on cloud-managed devices). All data is fetched from `eu1-developer.deyecloud.com`
every 5 minutes.

---

## Two installation modes

### Option A — HACS custom integration (recommended)

Full UI config flow, one device with 16 sensors + a Work Mode selector. Automatic 5-minute polling.

**Install**

1. In HACS → **Custom repositories** → add `https://github.com/PetePeter/ha-deyecloud-bridge` (type: Integration).
2. Install **Deye Cloud Inverter**.
3. Restart Home Assistant.
4. Settings → Devices & Services → **Add Integration** → search *Deye Cloud Inverter*.
5. Fill in your credentials (see below) and device serial number.

**Entities created (all under device "Deye Inverter")**

| Entity | Description |
|--------|-------------|
| `sensor.deye_inverter_solar_power` | PV generation (W) |
| `sensor.deye_inverter_house_load` | House consumption (W) |
| `sensor.deye_inverter_grid_power` | Grid flow +import/−export (W) |
| `sensor.deye_inverter_battery_power` | Battery flow +charge/−discharge (W) |
| `sensor.deye_inverter_ups_power` | UPS/backup load (W) |
| `sensor.deye_inverter_battery_soc` | Battery state of charge (%) |
| `sensor.deye_inverter_battery_voltage` | Battery voltage (V) |
| `sensor.deye_inverter_battery_temperature` | Battery temperature (°C) |
| `sensor.deye_inverter_inverter_temperature` | Inverter temperature (°C) |
| `sensor.deye_inverter_solar_today` | Daily PV production (kWh) |
| `sensor.deye_inverter_consumption_today` | Daily consumption (kWh) |
| `sensor.deye_inverter_solar_total` | Lifetime PV production (kWh) |
| `sensor.deye_inverter_grid_import_total` | Lifetime grid import (kWh) |
| `sensor.deye_inverter_grid_export_total` | Lifetime grid export (kWh) |
| `sensor.deye_inverter_battery_charge_total` | Lifetime battery charge (kWh) |
| `sensor.deye_inverter_battery_discharge_total` | Lifetime battery discharge (kWh) |
| `select.deye_inverter_work_mode` | Work mode: *Zero Export to CT* / *Zero Export to Load* / *Selling First* |

---

### Option B — Plain Python + YAML package (no HACS)

Drop two files into your HA config and you're done.

**Install**

1. Copy `deye_bridge.py` to `/config/deye_bridge.py`.
2. Create `/config/config.yaml` from `config.example.yaml` and fill in your credentials.
3. Copy `deye_battery.yaml` to `/config/packages/deye_battery.yaml`.
4. Enable packages in `configuration.yaml` (if not already):
   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```
5. Restart Home Assistant.

**Sensors created** (same 16 metrics, prefixed `deye_`):
`sensor.deye_solar_power`, `sensor.deye_battery_soc`, `sensor.deye_grid_power`, etc.

**Work mode automation** included: switches to *Selling First* at 18:00, back to *Zero Export to CT* at 21:00 daily. Override manually via `input_select.deye_work_mode`.

---

## Getting API credentials

You need a **Deye Cloud Developer** account. This is separate from the regular Deye app account, but uses the same email.

### Step-by-step

1. **Create a Deye Cloud account** (if you don't have one) — download the Deye app or sign up at [deye.com](https://www.deye.com). Your inverter must already be claimed to a station in the app.

2. **Register as a developer** at [developer.deyecloud.com/app](https://developer.deyecloud.com/app):
   - Sign in with your existing Deye Cloud email + password
   - Click **Create Application**
   - Fill in a name (e.g. "Home Assistant") and description
   - Note the generated **App ID** and **App Secret**

3. **Find your Device Serial Number** — in the Deye app: Me → Device Management → select your inverter → the numeric serial shown in details (not the logger SN on the label).

4. **Choose the right API region:**

   | Region | Base URL |
   |--------|----------|
   | Europe / Australia | `https://eu1-developer.deyecloud.com/v1.0` |
   | Americas | `https://us1-developer.deyecloud.com/v1.0` |
   | Asia Pacific | `https://apc1-developer.deyecloud.com/v1.0` |

   Use the region matching where your Deye Cloud account was created (check which server the Deye app connects to if unsure).

---

## Bridge script commands

```
python3 deye_bridge.py read            # JSON of all inverter metrics + work_mode + max_sell_power
python3 deye_bridge.py set MODE        # Switch work mode (see below)
python3 deye_bridge.py set_power WATTS # Set MAX_SELL_POWER via /order/sys/power/update
python3 deye_bridge.py keys            # Dump all raw telemetry key names from /device/latest
```

`read` makes two API calls per poll: `/device/latest` (telemetry) and `/config/system` (work mode + max sell power). `/device/latest` is telemetry-only and does not report control strategy state.

`set_power` uses `POST /order/sys/power/update` with `powerType: MAX_SELL_POWER`. It does **not** touch TOU settings.

## API reference

Full Swagger/OpenAPI spec is saved locally at [`openapi.json`](./openapi.json) — fetched from `https://eu1-developer.deyecloud.com/v2/api-docs`.

---

## Work mode API notes

Work mode changes are sent through the dedicated `/order/sys/workMode/update` endpoint using
only `deviceSn` and `workMode`, so the integration does not overwrite existing solar-sell or
time-of-use settings that were configured elsewhere.

Valid work modes: `ZERO_EXPORT_TO_CT`, `ZERO_EXPORT_TO_LOAD`, `SELLING_FIRST`

## API surfaces discovered

These are the Deye Cloud API surfaces we have actually verified or extracted from Deye's own docs bundle:

| Purpose | Endpoint | Status |
|--------|----------|--------|
| Inverter telemetry | `POST /device/latest` | Verified live. Returns a flat key-value list of inverter-reported measurements. |
| Station summary | `POST /station/latest` | Verified live. |
| Station devices | `POST /station/device` | Verified live. |
| Device history | `POST /device/history` | Documented and used as normal telemetry/history path. |
| Read battery config | `POST /config/battery` | Present in Swagger spec. |
| Read system config | `POST /config/system` | Present in Swagger spec. |
| Read TOU config | `POST /config/tou` | Verified live with body `{"deviceSn":"..."}`. Returns `touAction` + 6 TOU slots. |
| Work mode write | `POST /order/sys/workMode/update` | Verified live. Accepts `deviceSn` + `workMode`. |
| Legacy combined work-mode write | `POST /strategy/dynamicControl` | Verified live earlier, but broader than necessary for mode-only changes. |
| TOU write | `POST /order/sys/tou/update` | Extracted from Deye's Quick Start bundle. |
| Battery charge mode control | `POST /order/battery/modeControl` | Present in Swagger spec. Controls `GRID_CHARGE` / `GEN_CHARGE`. |
| Battery parameter update | `POST /order/battery/parameter/update` | Present in Swagger spec. |
| Grid peak shaving control | `POST /order/gridPeakShaving/control` | Present in Swagger spec. |
| Command status | `GET /order/{orderId}` | Extracted from Deye's Quick Start bundle. |

### Important notes

- `/device/latest` is telemetry only. It does **not** return current TOU, solar-sell, or work-mode strategy state.
- `/config/tou` is the public read endpoint for saved TOU configuration. In live testing, `{"deviceSn":"YOUR_DEVICE_SN"}` returned `touAction` and the 6 saved slots.
- Older examples often bundled `solarSellAction`, `touAction`, `touDays`, and six `timeUseSettingItems` into `/strategy/dynamicControl`.
- The integration now uses the dedicated `/order/sys/workMode/update` endpoint for mode-only changes instead of the broader dynamic-control endpoint.
- A public TOU read endpoint exists, but a public full-strategy read endpoint for the combined current work-mode / solar-sell payload still has not been confirmed.
- Likely read-style candidates under `/strategy/...` and `/order/sys/tou/...` were probed and returned `404`, which is why `/config/tou` matters so much here.

### Example: read TOU configuration

```json
{
  "deviceSn": "YOUR_DEVICE_SN"
}
```

Live response shape:

```json
{
  "touAction": "on",
  "timeUseSettingItems": [
    {"power":15000,"voltage":49,"time":"0000","enableGridCharge":false,"enableGeneration":false,"soc":10},
    {"power":15000,"voltage":49,"time":"1100","enableGridCharge":false,"enableGeneration":false,"soc":100},
    {"power":15000,"voltage":49,"time":"1400","enableGridCharge":false,"enableGeneration":false,"soc":10},
    {"power":15000,"voltage":49,"time":"2320","enableGridCharge":false,"enableGeneration":false,"soc":10},
    {"power":15000,"voltage":49,"time":"0000","enableGridCharge":false,"enableGeneration":false,"soc":10},
    {"power":15000,"voltage":49,"time":"0000","enableGridCharge":false,"enableGeneration":false,"soc":10}
  ]
}
```
