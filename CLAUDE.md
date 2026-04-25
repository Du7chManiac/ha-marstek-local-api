# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Home Assistant custom integration that talks to Marstek Venus C/D/E batteries directly over the official Local API (JSON over UDP, default port 30000). Distributed via HACS. The integration code lives in `custom_components/marstek_local_api/`. There is **no** Python package, no requirements file, and no `pip install` step — Home Assistant loads it as a custom component at runtime.

## Common commands

There are no build, lint, or unit-test scripts in this repo. The two ways to exercise the code are:

```bash
# Run the standalone diagnostic CLI against real hardware on the LAN.
# Reuses the integration modules directly (no HA needed).
python3 test/test_tool.py discover
python3 test/test_tool.py discover --ip 192.168.x.x
python3 test/test_tool.py set-test-schedules --ip 192.168.x.x
python3 test/test_tool.py clear-schedules
python3 test/test_tool.py set-passive --power -2000 --duration 3600
python3 test/test_tool.py set-mode auto --ip 192.168.x.x

# Release tooling — interactive wizard or non-interactive flags.
python3 tools/release.py                          # interactive
python3 tools/release.py rc 1.2.0 --skip-github   # next RC
python3 tools/release.py final 1.2.0 --push       # final release
```

CI (`.github/workflows/validate.yml`) runs HACS validation and Home Assistant `hassfest`. Release validation (`release.yml`) checks that the manifest version equals the pushed git tag (without the leading `v`). Note: `release.yml` currently reads `custom_components/marstek/manifest.json` but the actual path is `custom_components/marstek_local_api/manifest.json` — fix the path before relying on that check.

## Architecture

### Single shared UDP socket per port
`api.py` keeps module-level dicts (`_shared_transports`, `_shared_protocols`, `_transport_refcounts`, `_clients_by_port`) so all `MarstekUDPClient` instances bound to the same local port share one socket. Devices respond on the port they were addressed on, so the integration binds to the **device port** with `reuse_port=True`. Handler callbacks are registered/unregistered per command and filter incoming datagrams by message ID. When touching socket lifecycle, the refcount logic must be respected — closing a transport while another client still references it will break every other device.

### Two coordinator shapes
`coordinator.py` has two classes; pick the right one for the entry shape:
- `MarstekDataUpdateCoordinator` — one battery, owns one `MarstekUDPClient`, runs the tiered poll.
- `MarstekMultiDeviceCoordinator` — wraps N device coordinators, drives them in parallel via `asyncio.gather`, and computes `aggregates` for the synthetic **Marstek System** device.

`__init__.py` chooses between them based on whether `entry.data` contains `"devices"` (multi) or `CONF_HOST` (single, legacy). Services, sensors, and buttons must work in both shapes.

### Tiered polling
Base interval is 60s (`DEFAULT_SCAN_INTERVAL`). The coordinator increments `update_count` each tick and gates expensive calls:
- Every tick (`UPDATE_INTERVAL_FAST=1`): `ES.GetStatus`, `Bat.GetStatus`.
- Every 5th tick (`UPDATE_INTERVAL_MEDIUM=5`, ~300s): `EM.GetStatus`, `PV.GetStatus`, `ES.GetMode`.
- Every 10th tick (`UPDATE_INTERVAL_SLOW=10`, ~600s): `Marstek.GetDevice`, `Wifi.GetStatus`, `BLE.GetStatus`.

Polling faster than 60s is known to destabilise devices (CT002/CT003 disconnects) — do not lower `DEFAULT_SCAN_INTERVAL` without good reason.

### Firmware/hardware-aware value scaling
`compatibility.py` holds a matrix keyed by `(base_model, hardware_version, firmware_version)`. `base_model` is `None` for entries that apply across all models on that hardware version, or a specific name (e.g. `"VenusD"`) to override. Lookup filters to the matching hardware version, prefers model-specific rows over wildcard rows, then within the chosen tier picks the highest firmware entry `<=` the device's reported version. Different firmware/HW combos use different divisors (e.g. HW2/<154 vs HW2/154+ vs HW3/139+); the spec-aligned defaults are recorded as wildcard rows and known deviations as overrides. When adding scaling for a new firmware:
1. Add an entry to `compatibility.SCALING_MATRIX`. Use `None` for the model unless the deviation is genuinely model-specific.
2. Apply the multiplier in the coordinator's parsing path, not in the sensor layer.
3. The compatibility matrix is intentionally not maintained for indefinitely old firmware — old entries can be pruned when no longer relevant.
4. Append the verified deviation to the table in `docs/API.md` §5 so future maintainers know which devices it was confirmed on.

`get_base_model` canonicalises the model string to the wildcard-matrix key form: it strips the `" 3.0"` suffix and intra-name whitespace, so `"Venus D"` (FW reports it that way) and `"VenusD"` both resolve to `"VenusD"`. Callers comparing the **raw** `device_model` (e.g. coordinator's PV-only branch on `== "VenusD"`) won't match a `"Venus D"` device — use the canonical form when adding model-gated logic.

The coordinator detects firmware/model changes mid-run via `_update_device_version` and rebuilds the `CompatibilityMatrix`.

The reference for what each field's units actually are per the published spec is `docs/API.md` (especially the cheat sheet in §4 and the verified-deviations table in §5). When integration data looks off by 10×/100×/1000×, start there.

### Command retry and message matching
Outgoing commands carry a unique integer ID (`_msg_id_counter`). The client awaits a matching response, retries up to `COMMAND_MAX_ATTEMPTS=3` with exponential backoff (`COMMAND_BACKOFF_*` constants), and per-method stats (`total_attempts`, `total_success`, `total_timeouts`, `last_latency`) are surfaced in `diagnostics.py`. The Marstek API silently drops packets and frequently rejects the first write — schedule/mode writes need the retry loop, not a single send.

### Schedules are write-only
The device cannot return its current manual-mode schedules. The integration writes one slot at a time (the API rejects batch writes), retrying each slot. `services.py` implements `set_manual_schedule`, `set_manual_schedules` (YAML), `clear_manual_schedules`, and `set_passive_mode`. Because `ES.SetMode` rejects Manual mode without a `manual_cfg`, the integration always sends a disabled placeholder in slot 9 when toggling Manual; users who use slot 9 themselves must reapply it.

### Synthetic "Marstek System" device
The multi-device coordinator emits an `aggregates` dict alongside per-device data. Sensors prefixed `system_` read from this and are attached to a virtual device so the user sees fleet totals (combined SOC, total grid import/export, etc.). When a user adds another battery via the options flow, it joins the existing entry — it does **not** create a new entry. The default HA "Add Device" path bypasses this, so the README steers users to **Configure**.

### Platforms wired in
`PLATFORMS = [SENSOR, BINARY_SENSOR, BUTTON]`. There is no `select` or `switch` platform — mode changes go through three button entities (`auto`/`ai`/`manual`) plus the `set_passive_mode` service. `Passive` mode requires power+duration parameters and cannot be triggered by a button.

## Conventions

- Pin firmware-specific behaviour in the compatibility matrix, not in `if firmware_version > X` branches scattered through the code.
- New API methods: add the `METHOD_*` constant to `const.py`, append to `ALL_API_METHODS`, then call via `MarstekUDPClient.send_command`.
- `test/test_tool.py` deliberately reuses the real integration modules through `importlib` and a fake `custom_components.marstek_local_api` package. When refactoring imports inside the integration, run `test_tool.py discover` against a real device to confirm the standalone loader still works.
- Bumping the release: update `manifest.json` `version`, then tag `v<version>` so the release workflow accepts it.
