# Huawei AH100 / Honor CH100 Smart Scale for Home Assistant

[![HACS / Marketplace Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)

On-demand Bluetooth Low Energy (BLE) custom integration for **Huawei AH100** and **Honor CH100** smart body-fat scales (Chipsea CST34M97 chipset) in Home Assistant OS.

Instead of polling continuously in the background, you trigger a weigh-in on demand (via a Zigbee/Matter button, smartwatch, or dashboard button) and receive live status transitions (`searching` → `connected` → `measuring` → `complete`).

## Features

- **UI Configuration (Config Flow & Options Flow):** Enter your scale MAC address, height (cm), age, gender, and reference weight directly in Home Assistant — no YAML or Python editing required.
- **Bluetooth Auto-Discovery:** Automatically discovers `AH100` / `CH100` scales via Home Assistant's built-in Bluetooth stack or ESPHome Bluetooth Proxies.
- **Full Body Composition:** Pushes encrypted `CMD_USER_INFO` (with the `v2.5.4` / openScale #1449 `declaredLen=14` fix) and maintains a 2-second `CMD_HEART_BEAT` so the scale completes impedance/BMI measurements without showing `--`.
- **Persistent Native Sensors (Long-Term Statistics):**
  - `sensor.<name>_weight` (`kg`, `device_class: weight`, `state_class: measurement`)
  - `sensor.<name>_bmi` (`BMI`, `state_class: measurement`)
  - `sensor.<name>_body_fat` (`%`, `state_class: measurement`)
  - `sensor.<name>_impedance` (`Ω`, `state_class: measurement`)
  - `sensor.<name>_status` (`idle`, `searching`, `connected`, `measuring`, `complete`, `timeout`)
- **Start Measurement Button:** `button.<name>_start_measurement` — trigger from any Zigbee button, Wear OS / Apple Watch tile, or dashboard card.
- **Optional Google Health Sync (Cloud Push):** Optionally link your Google Cloud OAuth2 credentials to automatically (or manually) push weight and body fat % to the **Google Health API v4** (`switch.<name>_google_health_auto_sync` and `button.<name>_push_to_google_health`).
- **Guided Weigh-In Blueprint:** Optional automation blueprint that announces *"Searching"*, *"Connected – step on scale"*, and *"Measurement complete"* on a Google Mini / Sonos speaker and sends watch notifications.

## Installation (HACS / Marketplace)

1. Open **Settings → Marketplace** (or **HACS**) in Home Assistant.
2. Add this repository as a custom repository (`Integration`):
   `https://github.com/Varazir/ha-huawei-ah100`
3. Download **Huawei AH100 / Honor CH100 Smart Scale** and restart Home Assistant.
4. Go to **Settings → Devices & Services → Add Integration** and search for **Huawei AH100**.
5. Fill in your scale's MAC address (or accept the auto-discovered device) along with your height, age, gender, and approximate current weight.

## Guided Weigh-In Blueprint

[![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FVarazir%2Fha-huawei-ah100%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fhuawei_ah100_guided_weigh_in.yaml)

Use the included blueprint (`blueprints/automation/huawei_ah100_guided_weigh_in.yaml`) to get voice guidance on your Google Home / Nest Mini and vibration alerts on your smartwatch:

1. Press your physical button (e.g. IKEA TRADFRI remote) or watch tile to press `button.<name>_start_measurement`.
2. Speaker announces: *"Searching for scale. Tap the scale to wake it up."*
3. Briefly tap the scale with your foot to wake it up.
4. As soon as Bluetooth connects and unlocks, the speaker announces: *"Scale connected. Step onto the scale now."*
5. Step onto the scale — once weight and body fat finish, your measurements are saved permanently and announced aloud.

## Optional: Push Measurements to Google Health

You can optionally push your weight (`weightGrams`) and body fat (`percentage`) to **Google Health** using the official **Google Health API v4** (`health.googleapis.com/v4`):

1. In [Google Cloud Console](https://console.cloud.google.com/), ensure the **Google Health API** is enabled and you have a Web Application **OAuth 2.0 Client ID & Secret** with redirect URI `https://my.home-assistant.io/redirect/oauth`.
2. In Home Assistant, go to **Settings → Devices & Services → Application Credentials** (top-right `⋮` menu) and add your Client ID & Secret for **Huawei AH100 / Honor CH100 Scale**.
3. Either check **Also connect Google Health** during initial setup, or click **`⋮` → Reconfigure → Connect / Reconnect Google Health** on your existing scale entry.
4. Once connected, two new entities appear on your scale device:
   - **`switch.<name>_google_health_auto_sync`**: Automatically push weight & body fat after every completed weigh-in (includes `last_sync` and `last_error` attributes).
   - **`button.<name>_push_to_google_health`**: Manually push the latest measurement on demand.

## Credits & Open-Source Attribution

Portions of the Huawei AH100 / Honor CH100 BLE wire protocol implementation — including GATT UUIDs, XOR obfuscation, AES-128-CTR key derivation and decryption, command/notification opcodes, the `CMD_USER_INFO` length-byte quirk (issue #1449), the 2-second heartbeat keep-alive, and protocol test fixtures — are derived from **[openScale](https://github.com/oliexdev/openScale)**:

- `BluetoothHuaweiAH100.java` (v2.5.4) — Copyright (C) 2014 `olie.xdev`
- `HuaweiAhCh100Handler.kt`, `HuaweiAhCh100HandlerTest.kt`, and `HuaweiUserRecordWireTest.kt` — Copyright (C) 2026 openScale contributors

## License

In compliance with openScale's open-source license, this project is licensed under the **GNU General Public License v3.0 or later (GPL-3.0-or-later)**. See [LICENSE](LICENSE) for full details.
