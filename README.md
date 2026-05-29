# Mitsubishi Comfort Integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)

Home Assistant integration for Mitsubishi Electric climate systems that use the
Kumo Cloud / Comfort cloud service (API v3). Provides full climate control,
multi-zone support, and per-zone temperature, humidity, diagnostic, and
wireless-sensor entities.

## Features

- Full climate control: target temperature, HVAC mode, fan speed, vane position
- Heat, Cool, Dry, Fan-only, and Auto (HEAT_COOL) modes with dual setpoints in Auto
- Per-zone temperature and humidity sensor entities
- Wireless sensor support (PAC-USWHS003-TH-1): battery, signal strength,
  temperature, humidity — auto-detected via the zone's `hasSensor` flag
- Diagnostic sensors: WiFi adapter firmware version, WiFi signal strength,
  filter maintenance reminders
- Comfort-app-accurate fan speed and vane position labels (no raw API strings
  surfacing in the UI)
- Mitsubishi-accurate Fahrenheit/Celsius conversion (no setpoint drift)
- `HVACAction.IDLE` reported when a zone is at setpoint, so tiles, energy
  dashboards, and automations don't see a unit as always heating/cooling
- Command caching to prevent state bouncing while the cloud API catches up
  (the API can lag the actual device by up to a minute)
- Automatic token refresh, rate-limit handling with exponential backoff,
  graceful degradation through transient API failures

## Supported devices

Any Mitsubishi Electric indoor unit paired with a Kumo Cloud / Comfort cloud
adapter and visible through the Mitsubishi Comfort app. Optional
PAC-USWHS003-TH-1 wireless temperature/humidity sensors are detected
automatically.

## Installation

### HACS (recommended)

1. Install [HACS](https://hacs.xyz) if you haven't already
2. Go to **HACS → Integrations → ⋮ menu → Custom repositories**
3. Add `JoeQuantum/comfort_HA` with category **Integration**
4. Search for **Mitsubishi Comfort** and install
5. Restart Home Assistant

### Manual

1. Copy `custom_components/kumo_cloud/` into your Home Assistant
   `config/custom_components/` directory
2. Restart Home Assistant

## Configuration

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **Mitsubishi Comfort**
3. Enter your Kumo Cloud / Comfort app credentials
4. Select a site if your account has more than one

All zones in the selected site are discovered automatically. A re-auth prompt
appears if your password changes; you don't need to delete and re-add the
integration.

## Entities created

Per zone:

| Entity | Notes |
|---|---|
| `climate.<zone>` | Full climate control. Exposes `current_temperature`, `current_humidity` (when the API reports it), target setpoint(s), HVAC mode, fan speed, vane position |
| `sensor.<zone>_temperature` | Room temperature |
| `sensor.<zone>_humidity` | Room humidity (when reported) |
| `sensor.<zone>_firmware` | WiFi adapter firmware version (diagnostic) |
| `sensor.<zone>_wifi_signal` | WiFi adapter RSSI (diagnostic) |
| `sensor.<zone>_filter_reminder` | Next filter maintenance date (diagnostic) |

When a PAC-USWHS003-TH-1 wireless sensor is attached:

| Entity | Notes |
|---|---|
| `sensor.<zone>_wireless_sensor_battery` | Battery level |
| `sensor.<zone>_wireless_sensor_signal` | Wireless sensor RSSI |
| `sensor.<zone>_wireless_sensor_temperature` | Wireless sensor temperature |
| `sensor.<zone>_wireless_sensor_humidity` | Wireless sensor humidity |

## Behavior notes

### HVAC idle inference

The Kumo Cloud V3 API does not expose a "compressor running" signal — only the
configured operation mode and power state. Without inference, `hvac_action`
would report `HEATING`/`COOLING` continuously whenever a unit is on in that
mode, which is wrong for tile glow, energy dashboards, history graphs, and any
automation keyed on `hvac_action`.

The integration infers `HVACAction.IDLE` from the current vs. target
temperature delta: in HEAT, COOL, AUTO_HEAT, and AUTO_COOL, it flips to `IDLE`
once the room is past setpoint by 1.0 °F. This is a proxy — inverter mini
splits modulate, so a unit reading `IDLE` may still be drawing a small amount
of power.

### Command caching

The Comfort cloud API can take up to a minute to reflect a command. The
integration caches commands locally with a timestamp and keeps them applied
to the entity state until the server's `updatedAt` field confirms the command
was processed. This eliminates the visible "bounce" where a slider would snap
back to its previous value a second after you moved it.

### Temperature conversion

Mitsubishi systems store temperatures in 0.5 °C steps but use a proprietary
Fahrenheit-to-Celsius mapping that diverges from standard arithmetic at
several setpoints (64–66 °F and 69–72 °F). The integration uses Mitsubishi's
lookup table for setpoints and display, eliminating the ~1 °F drift that
standard rounding causes for Fahrenheit users. Values outside the lookup
table fall back to standard conversion.

### Authentication failures

A 403 from the Kumo Cloud API raises `KumoCloudAuthError`, which Home Assistant
maps to `ConfigEntryAuthFailed` — surfacing the re-authentication prompt in
the UI rather than entering a retry loop.

## Fan Speed Reference

| HA Label | Comfort App | API Value |
|----------|-------------|-----------|
| auto     | Auto        | auto      |
| quiet    | Quiet       | superQuiet |
| low      | Low         | quiet     |
| medium   | Medium      | low       |
| high     | High        | powerful  |
| powerful | Powerful    | superPowerful |

## Vane Position Reference

| HA Label | Comfort App | API Value |
|----------|-------------|-----------|
| auto     | Auto        | auto      |
| swing    | Swing       | swing     |
| lowest   | Lowest      | vertical  |
| low      | Low         | midvertical |
| middle   | Middle      | midpoint  |
| high     | High        | midhorizontal |
| highest  | Highest     | horizontal |

## Credits

- [jjustinwilson](https://github.com/jjustinwilson/comfort_HA) — Original integration and V3 API reverse engineering
- [ekiczek](https://github.com/ekiczek/comfort_HA) — Mitsubishi F/C temperature lookup tables (PR #23, hass-kumo PR #199)
- [smack000](https://github.com/smack000/comfort_HA) — Command caching, coordinator refactor, sensor entities, auto heat/cool mode
- [tw3rp](https://github.com/jjustinwilson/comfort_HA/pull/2#issuecomment-2974732965) — Dual setpoint support for auto heat/cool, improved entity availability, API rate limiting with exponential backoff
- [greginno](https://github.com/jjustinwilson/comfort_HA/issues/26) — Reported and prototyped the `current_humidity` property mapping
- [mataiwilson](https://github.com/jjustinwilson/comfort_HA/pull/29) — Identified and fixed the swallowed `KumoCloudAuthError` in `login()`

## License

MIT — see [LICENSE](LICENSE).
