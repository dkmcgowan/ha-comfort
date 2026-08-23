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
  temperature, humidity, auto-detected via the zone's `hasSensor` flag
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
- Remembers the last HVAC mode you set, so toggling a unit off and back on
  through the HA UI restores your previous mode instead of defaulting to cool
- DHCP discovery: when a Mitsubishi WiFi adapter joins the LAN, HA's
  "Discovered" panel surfaces the integration as a setup prompt
- HA Download Diagnostics support on the integration and device pages,
  with credentials, tokens, serials, and MACs redacted

## Supported devices

Any Mitsubishi Electric indoor unit paired with a Kumo Cloud / Comfort cloud
adapter and visible through the Mitsubishi Comfort app. Optional
PAC-USWHS003-TH-1 wireless temperature/humidity sensors are detected
automatically.

## Installation

### HACS (recommended)

1. Install [HACS](https://hacs.xyz) if you haven't already
2. Go to **HACS → Integrations → ⋮ menu → Custom repositories**
3. Add `dkmcgowan/ha-comfort` with category **Integration**
4. Search for **Mitsubishi Comfort (Kumo Cloud)** and install
5. Restart Home Assistant

### Manual

1. Copy `custom_components/kumo_cloud/` into your Home Assistant
   `config/custom_components/` directory
2. Restart Home Assistant

## Configuration

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **Mitsubishi Comfort (Kumo Cloud)**
3. Enter your Kumo Cloud / Comfort app credentials
4. Select a site if your account has more than one

All zones in the selected site are discovered automatically. A re-auth prompt
appears if your password changes; you don't need to delete and re-add the
integration.

If a Mitsubishi WiFi adapter is already on your network when HA boots, the
integration will also appear in **Settings → Devices & Services → Discovered**
as a one-click setup prompt.

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

All entities for a given indoor unit are grouped under a single HA device. The device page shows the model (e.g. `MSZ-FH09NA`), the unit's firmware (`serialProfile`), and the serial number reported by the Comfort cloud.

## Behavior notes

### HVAC idle inference

The Kumo Cloud V3 API does not expose a "compressor running" signal, only the
configured operation mode and power state. Without inference, `hvac_action`
would report `HEATING`/`COOLING` continuously whenever a unit is on in that
mode, which is wrong for tile glow, energy dashboards, history graphs, and any
automation keyed on `hvac_action`.

The integration infers `HVACAction.IDLE` from the current vs. target
temperature delta: in HEAT, COOL, AUTO_HEAT, and AUTO_COOL, it flips to `IDLE`
once the room is past setpoint by 1.0 °F. This is a proxy: inverter mini
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
several setpoints (64 to 66 °F and 69 to 72 °F). The integration uses Mitsubishi's
lookup table for setpoints and display, eliminating the ~1 °F drift that
standard rounding causes for Fahrenheit users. Values outside the lookup
table fall back to standard conversion.

### Authentication failures

A 403 from the Kumo Cloud API raises `KumoCloudAuthError`, which Home Assistant
maps to `ConfigEntryAuthFailed`, which surfaces the re-authentication prompt in
the UI rather than entering a retry loop.

## Comparison to other Mitsubishi integrations

Several Home Assistant integrations talk to Mitsubishi mini-splits. They make
different tradeoffs; pick whichever matches your setup.

### vs. HA Core [`mitsubishi_comfort`](https://github.com/home-assistant/core/tree/dev/homeassistant/components/mitsubishi_comfort)

Home Assistant Core gained a first-party `mitsubishi_comfort` integration in
the 2026.6 release. It declares `iot_class: local_polling` and is built on the
`mitsubishi-comfort` PyPI library, so it talks to the adapter on your LAN
rather than to the Kumo Cloud V3 API this integration uses.

**Choose `mitsubishi_comfort` if** you want the lowest-maintenance path and
only need climate control. Bugfixes ship with Home Assistant releases.

**Choose this integration if you also want:**
- Per-zone **standalone temperature and humidity sensor entities**, independent
  of the climate entity, usable in history graphs, templates, and automations
  without `state_attr()` indirection
- **Wireless sensor (PAC-USWHS003-TH-1) entities**: battery, signal strength,
  temperature, humidity
- **Filter maintenance reminder** sensor
- **WiFi adapter firmware and signal strength** as diagnostic sensors
- **Last-mode memory** across off/on cycles

Different domain names (`kumo_cloud` vs `mitsubishi_comfort`) mean both can be
installed simultaneously without conflict.

### vs. [dlarrick/hass-kumo](https://github.com/dlarrick/hass-kumo)

`hass-kumo` is the long-running community integration. Architecturally it's
**local-first**: it controls units over your LAN via the encrypted CoAP
protocol (using the [`pykumo`](https://github.com/dlarrick/pykumo) library),
with the Kumo Cloud contacted only during initial setup.

**Choose `hass-kumo` if you want:**
- **Local control**: no cloud round-trips during normal operation; works
  during internet outages
- **Outdoor temperature** reporting from a Kumo Station accessory
- The Mitsubishi Kumo Station thermostat hub features

**Choose this integration if you want:**
- **Pure cloud setup** with no LAN requirements: your HA instance and your
  mini-splits don't need to be on the same network
- Standalone per-zone sensor entities (in `hass-kumo` these live on the
  climate entity's attributes)
- **Filter maintenance reminders**
- No `pykumo` dependency

Different domain names (`kumo_cloud` vs `kumo`) mean both can be installed
simultaneously without conflict.

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

This integration is a fork of
[JoeQuantum/comfort_HA](https://github.com/JoeQuantum/comfort_HA), which
carried the work below forward from the original project. Everything before
the fork point is theirs.

### Individual contributors

- [JoeQuantum](https://github.com/JoeQuantum/comfort_HA): the fork base, including the sensor platform, diagnostics, DHCP discovery, and last-mode memory
- [jjustinwilson](https://github.com/jjustinwilson/comfort_HA): original integration and V3 API reverse engineering
- [ekiczek](https://github.com/ekiczek/comfort_HA): Mitsubishi F/C temperature lookup tables (PR #23, hass-kumo PR #199)
- [smack000](https://github.com/smack000/comfort_HA): command caching, coordinator refactor, sensor entities, auto heat/cool mode
- [tw3rp](https://github.com/jjustinwilson/comfort_HA/pull/2#issuecomment-2974732965): dual setpoint support for auto heat/cool, improved entity availability, API rate limiting with exponential backoff
- [greginno](https://github.com/jjustinwilson/comfort_HA/issues/26): reported and prototyped the `current_humidity` property mapping
- [mataiwilson](https://github.com/jjustinwilson/comfort_HA/pull/29): identified and fixed the swallowed `KumoCloudAuthError` in `login()`

### Patterns adapted from sibling projects

- [dlarrick/hass-kumo](https://github.com/dlarrick/hass-kumo): diagnostics support, last-HVAC-mode memory pattern, DHCP MAC prefixes, pre-commit configuration, temperature-module extraction.
- HA Core [mitsubishi_comfort](https://github.com/home-assistant/core/tree/dev/homeassistant/components/mitsubishi_comfort) (by [@nikolairahimi](https://github.com/nikolairahimi)): `KumoCloudEntity` base class, `ConfigEntry.runtime_data` migration, `hvac_action` lookup-table style.

## License

MIT, see [LICENSE](LICENSE).
