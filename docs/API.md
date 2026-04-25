# Marstek Device Open API — Reference

Distilled from the official **Marstek Device Open API** PDF (Rev 2.0, change-log dates 2025-08-09 → 2026-01-06). The PDF lives at `https://static-eu.marstekcloud.com/ems/resource/agreement/MarstekDeviceOpenApi.pdf`. This document is intentionally focused on what the integration needs: the wire format, every method, and the **units** of each field — because most integration bugs trace back to a unit assumption.

> **Authoritative status:** the spec is what the device firmware *should* implement. Real firmware sometimes deviates (different scaling factors on certain hardware/firmware combos). When the spec and a measured device disagree, the device wins, but record the deviation in `compatibility.py` rather than treating the spec as wrong.

## 1. Transport

- **Protocol:** JSON, framed in single UDP datagrams.
- **Default port:** 30000. The user can configure 49152–65535 in the Marstek app.
- **Discovery:** UDP broadcast.
- **Enabling:** the device only responds after the owner enables "Open API" in the Marstek mobile app. Some built-in features become disabled when Open API is on (the spec calls this out without listing which).

### Request envelope

```json
{
  "id": 0,
  "method": "<Component>.<Action>",
  "params": { "...": "..." }
}
```

`id` may be a number or string; the device echoes it back in the response. The integration uses an integer counter and matches replies by `id`.

### Response envelope

Success:

```json
{
  "id": 0,
  "src": "VenusE-24215edb178f",
  "result": { "...": "..." }
}
```

Error:

```json
{
  "id": 0,
  "src": "Venus-24215ee580e7",
  "error": { "code": -32700, "message": "Parse error", "data": 402 }
}
```

`src` is `"<model>-<wifi_mac>"` (or `<ble_mac>` — the spec is inconsistent). `error.code` follows JSON-RPC 2.0:

| Code | Meaning |
|---:|---|
| `-32700` | Parse error |
| `-32600` | Invalid Request |
| `-32601` | Method not found (use this to detect unsupported components per model) |
| `-32602` | Invalid params |
| `-32603` | Internal error |
| `-32000`…`-32099` | Implementation-defined server errors |

## 2. Methods

### 2.1 `Marstek.GetDevice` — discovery / device info

Used as a unicast query and as a broadcast for discovery. Discovery sends `params.ble_mac = "0"`; unicast queries pass a real BLE MAC.

**Response `result`:**

| Field | Type | Unit | Notes |
|---|---|---|---|
| `device` | string | — | Model name. Observed values: `"VenusC"`, `"VenusE"`, `"Venus D"`, `"VenusE 3.0"`. Whitespace and version suffix vary across firmware. |
| `ver` | number | — | Firmware version as integer (e.g. `111`, `147`, `154`, `200`). |
| `ble_mac` | string | — | Bluetooth MAC, lowercase hex, no separators. |
| `wifi_mac` | string | — | Wi-Fi MAC, lowercase hex, no separators. |
| `wifi_name` | string | — | SSID the device is associated with. |
| `ip` | string | — | LAN IP. |

### 2.2 `Wifi.GetStatus`

`params: {"id": <number>}`.

| Field | Type | Unit | Notes |
|---|---|---|---|
| `id` | number | — | Echo of the request id (instance index, always 0 in practice). |
| `wifi_mac` | string | — | |
| `ssid` | string \| null | — | |
| `rssi` | number | dBm | |
| `sta_ip` | string \| null | — | |
| `sta_gate` | string \| null | — | Gateway. |
| `sta_mask` | string \| null | — | Subnet mask. |
| `sta_dns` | string \| null | — | |

### 2.3 `BLE.GetStatus`

`params: {"id": <number>}`.

| Field | Type | Unit | Notes |
|---|---|---|---|
| `state` | string | — | `"connect"` / `"disconnect"`. |
| `ble_mac` | string | — | |

### 2.4 `Bat.GetStatus`

`params: {"id": <number>}`.

| Field | Type | Unit | Notes |
|---|---|---|---|
| `id` | number | — | |
| `soc` | number | % | Spec types this as `string` but devices return a number. |
| `charg_flag` | boolean | — | Charging permitted. |
| `dischrg_flag` | boolean | — | Discharging permitted. |
| `bat_temp` | number \| null | °C | Spec: already in °C. Some HW2 FW ≥154 reports deci-°C; HW3 FW ≥139 reports deca-°C. See `compatibility.py`. |
| `bat_capacity` | number \| null | **Wh** | Remaining capacity. Spec is unambiguous. Older HW2 firmware reportedly returns centi-Wh (÷100). |
| `rated_capacity` | number \| null | Wh | Rated pack capacity. Sums when multiple packs are installed. |

### 2.5 `PV.GetStatus`

Venus D / Venus A only (Venus C/E lack PV inputs). `params: {"id": <number>}`.

The spec lists fields as `pv_power`, `pv_voltage`, `pv_current`, `PV_state`, but the actual response on Venus D returns four channels: `pv1_*`, `pv2_*`, `pv3_*`, `pv4_*` and `pvN_state`.

| Field | Type | Unit | Notes |
|---|---|---|---|
| `pvN_power` | number | W | Solar charging power per channel. |
| `pvN_voltage` | number | V | Per-channel input voltage. Reads 9–10 with no panel attached. |
| `pvN_current` | number | A | |
| `pvN_state` | number | — | `1` = working, `0` = standby. |

### 2.6 `ES.GetStatus`

`params: {"id": <number>}`.

| Field | Type | Unit | Notes |
|---|---|---|---|
| `id` | number \| null | — | |
| `bat_soc` | number \| null | % | |
| `bat_cap` | number \| null | **Wh** | Total battery capacity (sum across packs). |
| `pv_power` | number \| null | W | Live solar power. |
| `ongrid_power` | number \| null | W | Grid-tied power. Sign convention: positive = import. |
| `offgrid_power` | number \| null | W | Off-grid load. |
| `bat_power` | number \| null | W | Battery power. Sign convention: positive = charge, negative = discharge. |
| `total_pv_energy` | number \| null | **Wh** | Lifetime solar energy. |
| `total_grid_output_energy` | number \| null | **Wh** | Lifetime grid export. |
| `total_grid_input_energy` | number \| null | **Wh** | Lifetime grid import. |
| `total_load_energy` | number \| null | **Wh** | Lifetime load (or off-grid) energy. |

> **Important:** the spec puts every energy total in **Wh** with no scaling annotation. Compare against `EM.GetStatus.input_energy` below — that field is explicitly tagged `(*0.1)` and lives in deci-Wh, while the `ES.GetStatus.total_*` fields are not. Don't conflate them.

### 2.7 `ES.SetMode`

Configures the operating mode. `params`:

```json
{
  "id": 0,
  "config": {
    "mode": "Auto" | "AI" | "Manual" | "Passive" | "Ups",
    "auto_cfg":    { "...": "..." },
    "ai_cfg":      { "...": "..." },
    "manual_cfg":  { "...": "..." },
    "passive_cfg": { "...": "..." },
    "ups_cfg":     { "...": "..." }
  }
}
```

Only the sub-config matching `mode` is required.

| Sub-config | Field | Type | Notes |
|---|---|---|---|
| `auto_cfg` | `enable` | number | `1` = on. |
| `ai_cfg` | `enable` | number | `1` = on. |
| `manual_cfg` | `time_num` | number | Slot, Venus C/E supports `0`–`9`. |
| `manual_cfg` | `start_time` / `end_time` | string | `"hh:mm"`. |
| `manual_cfg` | `week_set` | number | 7-bit weekday bitmap, low bit = Mon. `1` = Mon, `3` = Mon+Tue, `127` = every day. Top bit unused. |
| `manual_cfg` | `power` | number | W. Sign convention used by the integration: negative = charge, positive = discharge. |
| `manual_cfg` | `enable` | number | `1` / `0`. |
| `passive_cfg` | `power` | number | W. Same sign convention. |
| `passive_cfg` | `cd_time` | number | Countdown, seconds. |
| `ups_cfg` | `enable` | number | `1` / `0`. |

**Response:** `{ "id": <number>, "set_result": <bool> }`. The spec example contains the typo `"ture"` — the device actually returns `true`/`false`.

> **Manual mode quirk:** the firmware rejects `ES.SetMode` to Manual without a `manual_cfg`. The integration sends a disabled placeholder in slot 9 to satisfy this; user-defined slot 9 schedules need to be reapplied after toggling Manual.

### 2.8 `ES.GetMode`

Reads the active mode and a snapshot of CT data. `params: {"id": <number>}`.

| Field | Type | Unit | Notes |
|---|---|---|---|
| `mode` | string \| null | — | `"Auto"`, `"AI"`, `"Manual"`, `"Passive"`. |
| `ongrid_power`, `offgrid_power` | number \| null | W | |
| `bat_soc` | number \| null | % | |
| `ct_state` | number \| null | — | `0` = not connected, `1` = connected. CT-related fields below are only valid in Auto / AI mode. |
| `a_power`, `b_power`, `c_power`, `total_power` | number \| null | W | Phase + total power. Auto/AI only. |
| `input_energy` | number \| null | **Wh ×0.1** | Spec annotation: `(*0.1)`. Raw value is in deci-Wh; multiply by `0.1` to get Wh, or equivalently divide by `10`. Auto/AI only. |
| `output_energy` | number \| null | **Wh ×0.1** | Same scaling as `input_energy`. |

`ES.GetMode` is the field the README flags as "may be unresponsive on some Venus E v3 firmwares (v137 / v139)". The integration must tolerate a missing reply here.

### 2.9 `EM.GetStatus`

Energy meter / CT readings.

| Field | Type | Unit | Notes |
|---|---|---|---|
| `ct_state` | number \| null | — | `0` / `1`. |
| `a_power`, `b_power`, `c_power`, `total_power` | number \| null | W | Per-phase + total. |
| `input_energy` | number \| null | **Wh ×0.1** | Same `(*0.1)` annotation as in `ES.GetMode`. |
| `output_energy` | number \| null | **Wh ×0.1** | Same. |

### 2.10 `DOD.SET`

Sets the depth-of-discharge floor. Range `30`–`88`, default `88`.

```json
{ "id": 0, "method": "DOD.SET", "params": { "value": 36 } }
```

Note the parameter key is `value` (lowercase) in the example, even though the parameter table writes it as `Value`.

**Response:** `{ "id": <number>, "set_result": <bool> }`.

### 2.11 `Ble.Adv` (a.k.a. "Ble_block")

Toggles BLE advertising. `params: {"id": <number>, "enable": <number>}` where the spec says `0 = enable, 1 = disable` (yes, inverted from intuition).

### 2.12 `Led.Ctrl`

Front-panel LED. `params: {"id": <number>, "state": <number>}`, `1` = on, `0` = off.

## 3. Component support per device

From spec §IV. Use `-32601` (method not found) at runtime to confirm — firmware varies.

| Component | Venus C | Venus E | Venus D | Venus A |
|---|:-:|:-:|:-:|:-:|
| `Marstek.*` | ✅ | ✅ | ✅ | ✅ |
| `Wifi.*` | ✅ | ✅ | ✅ | ✅ |
| `BLE.*` | ✅ | ✅ | ✅ | ✅ |
| `Bat.*` | ✅ | ✅ | ✅ | ✅ |
| `PV.*` | — | — | ✅ | ✅ |
| `ES.*` | ✅ | ✅ | ✅ | ✅ |
| `EM.*` | ✅ | ✅ | ✅ | ✅ |
| `DOD.SET` | ✅ | ✅ | ✅ | ✅ |
| `Ble.Adv` | ✅ | ✅ | ✅ | ✅ |
| `Led.Ctrl` | ✅ | ✅ | ✅ | ✅ |

## 4. Field unit summary (cheat sheet)

The single most important table for avoiding integration bugs: every numeric field, the unit per the spec, and which fields carry an explicit scaling annotation.

| Method | Field | Spec unit | Scaling note in spec |
|---|---|---|---|
| `Bat.GetStatus` | `bat_temp` | °C | none |
| `Bat.GetStatus` | `bat_capacity`, `rated_capacity` | Wh | none |
| `ES.GetStatus` | `bat_cap` | Wh | none |
| `ES.GetStatus` | `pv_power`, `ongrid_power`, `offgrid_power`, `bat_power` | W | none |
| `ES.GetStatus` | `total_pv_energy`, `total_grid_output_energy`, `total_grid_input_energy`, `total_load_energy` | Wh | **none** (no `*0.1`) |
| `ES.GetMode` | `ongrid_power`, `offgrid_power`, `a_power`, `b_power`, `c_power`, `total_power` | W | none |
| `ES.GetMode` | `input_energy`, `output_energy` | Wh | **`*0.1`** (raw is deci-Wh) |
| `EM.GetStatus` | `a_power`, `b_power`, `c_power`, `total_power` | W | none |
| `EM.GetStatus` | `input_energy`, `output_energy` | Wh | **`*0.1`** (raw is deci-Wh) |
| `PV.GetStatus` | `pvN_power` | W | none |
| `PV.GetStatus` | `pvN_voltage` | V | none |
| `PV.GetStatus` | `pvN_current` | A | none |

If a sensor reads off by an exact factor of 10, 100, or 1000, the first thing to check is whether the integration is double-applying a scale factor (or applying one the spec doesn't specify).

## 5. Verified deviations from spec

Recorded against actual hardware. Update when you confirm new ones.

| Device | Firmware | Field | Behaviour | Source |
|---|---|---|---|---|
| Venus D (HW2) | 147 | `bat_capacity`, `total_grid_input_energy`, `total_grid_output_energy`, `total_load_energy` | Match the spec exactly (Wh, no scaling). | Live read on 192.168.172.211, 2026-04-25 |
| Venus E (HW2) | 154+ | `bat_temp` | deci-°C (÷10 to get °C). | `compatibility.py` matrix entry |
| Venus E (HW3) | 139+ | `bat_temp` | deca-°C (×10 to get °C). | PR #32 (commit b4895fa) |
| Venus E (HW3) | 139+ | `bat_capacity` | deci-Wh (÷10 to get Wh). | PR #32 (commit b4895fa) |

When you confirm a new deviation, add it to `compatibility.SCALING_MATRIX` and append a row here.
