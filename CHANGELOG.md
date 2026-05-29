# Changelog

## [1.2.0] - 2026-05-29

### Added
- **`current_humidity` property on climate entities.** The V3 API adapter payload
  includes a humidity reading for zones with a wireless sensor (PAC-USWHS003-TH-1).
  Mapping it to `ClimateEntity`'s canonical property means standard HA cards
  (tile, thermostat) render humidity automatically — no templating needed.
  Requested in jjustinwilson/comfort_HA#26 by @greginno.

### Changed
- **Breaking: removed the `humidity` extra_state_attribute.** The same value is
  now exposed as `current_humidity` (see above). Templates that previously
  referenced `state_attr('climate.X', 'humidity')` should switch to
  `state_attr('climate.X', 'current_humidity')`.

### Fixed
- **`hvac_action` now reports `IDLE` when at setpoint.** The Kumo Cloud V3 API
  does not expose a real "compressor running" signal, so the integration
  previously reported `HEATING`/`COOLING` continuously whenever a unit was on
  in that mode — wrong for tile glow, energy dashboards, history graphs, and
  any automation keyed on `hvac_action`. Mirrors the generic-AUTO branch's
  existing temp-delta heuristic: HEAT/COOL/AUTO_HEAT/AUTO_COOL flip to `IDLE`
  once the room passes setpoint by ≥1.0 °F.
- **Wrong password at initial login now triggers re-auth, not a retry loop.**
  `KumoCloudAuthError` raised on HTTP 403 was being swallowed by the broad
  `except Exception` handler in `login()` and re-wrapped as
  `KumoCloudConnectionError`, so HA saw `ConfigEntryNotReady` (retry forever)
  instead of `ConfigEntryAuthFailed` (re-auth prompt in the UI).
  Inspired by jjustinwilson/comfort_HA#29 by @mataiwilson.

## [1.1.1] - 2026-05-11

### Fixed
- **Transient DNS/network failures no longer permanently break setup.** During HA boot, if
  `app-prod.kumocloud.com` is unreachable (DNS general failure, connection refused, socket
  error), `async_setup_entry` now raises `ConfigEntryNotReady` instead of propagating a raw
  exception. HA will retry with exponential backoff until the cloud API is reachable.
- **`_request()` now wraps all connection-layer errors.** `aiohttp.ClientError` and `OSError`
  (which includes `aiodns.error.DNSError` surfaced as `ClientConnectorDNSError`) are caught
  and re-raised as `KumoCloudConnectionError` so they never propagate raw to the setup machinery.
- **`refresh_access_token()` gets the same treatment** — DNS/socket errors during a token
  refresh are now wrapped as `KumoCloudConnectionError`.
- **403 responses now trigger the reauth flow** (not a connection error). A 403 from the API
  raises `KumoCloudAuthError`, which maps to `ConfigEntryAuthFailed` in setup.
- **Coordinator token-refresh retry path can no longer leak bare exceptions.** A connection
  error that occurs while retrying after a 401 is now wrapped in `UpdateFailed` so the
  coordinator degrades gracefully instead of crashing.

## [1.1.0] - 2026-03-09

### Added
- Mitsubishi proprietary F/C temperature lookup tables (ekiczek PR #23, PR #199)
- Fan speed mapping: API values now correctly translate to Comfort app labels
- Vane position mapping: API values now correctly translate to Comfort app labels
- Command caching with `updatedAt` comparison to prevent state bounce (smack000)
- Standalone temperature and humidity sensor entities per zone (smack000)
- Wireless sensor support: battery level, signal strength (RSSI), temperature, and humidity
  from PAC-USWHS003-TH-1 sensors via /v3/devices/{serial}/sensor endpoint
- Diagnostic sensors: WiFi adapter firmware version and signal strength via /v3/devices/{serial}/status
- Filter maintenance tracking via /v3/zones/{id}/notification-preferences
- Updated API app version from 3.0.9 to 3.2.4 to match current Comfort app
- Auto heat/cool mode with dual setpoint support (smack000 / tw3rp)
- Refactored architecture: API client and coordinator in separate modules (smack000)
- API retry logic with exponential backoff for 429 rate limits (smack000 / tw3rp)
- Improved entity availability: prevents false automation triggers during transient API errors (tw3rp)
- Debug logging for fan speed and vane position translations

### Fixed
- Temperature setpoints now match the Comfort app exactly (no more ~1 F drift)
- Fan speed display matches Comfort app labels (was showing raw API values)
- Vane position display matches Comfort app labels (was showing raw API values)
- State bouncing after sending commands (cached commands maintained until server confirms)
- Sensor entities now inherit from CoordinatorEntity for automatic updates

## [0.1.1-alpha.1] - Previous upstream release
- Initial Kumo Cloud V3 API integration by jjustinwilson
