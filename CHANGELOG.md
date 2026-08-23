# Changelog

## [1.8.0] - 2026-08-23

Schedules, which turned out not to be blocked at all.

The `426 invalidAppVersion` that made them look unreachable had nothing to
do with the app version. The schedule endpoints are on **API v4** and this
integration only ever spoke v3, so the v3 router was rejecting a route it
does not have, with a badly chosen error. The Comfort app passes
`apiVersion: '4'` on exactly nine of its 97 endpoints: every schedule season
route, and the site hold. Everything else, including everything this
integration already called, is correctly on v3.

### Added

- **`sensor.<zone>_next_schedule_change`**, the timestamp of the next
  scheduled change with the mode and setpoints it will apply in its
  attributes. Events carry weekdays and a time but no date, so the next
  occurrence is computed in the zone's own timezone.
- **`kumo_cloud.get_schedules`**, a service returning every zone's schedule
  as response data, including the next change per zone.
- **`kumo_cloud.set_season`**, to make a schedule season active.
- **`kumo_cloud.set_schedules_enabled`**, to turn scheduling on or off for
  the site.
- **`kumo_cloud.clear_season_events`**, to delete every event in a season.

Creating and editing individual events is deliberately not exposed. The
payload is a whole per-zone weekly timetable, and a service schema for that
would be worse than the Comfort app's own editor.

### Fixed

- **The README and release notes claimed schedules were unreachable.** They
  are not, and both now describe what actually works.

### Known unverified

`set_season`, `set_schedules_enabled` and `clear_season_events` all write,
and none has been fired against a real account. Reading is fully verified
against a live schedule. The two bodies that could not be read out of the
app, the season status flag and the site schedule toggle, are inferred from
the field names in the records they change.

## [1.7.0] - 2026-08-23

### Added

- **A whole-house climate entity**, one per site, alongside the per-zone
  ones. Setting it applies to every zone, the same as the Comfort app's
  "Control all zones". Home Assistant has no climate group helper, so this
  otherwise takes a script that loops over every unit. It offers only modes
  every zone supports, and when the zones disagree it reports the most
  common mode and the mean setpoint with `zones_in_sync: false` and a
  per-zone breakdown in its attributes.
- **Hold**, as a binary sensor per zone, with the expiry and whatever the
  hold is pinning in its attributes. This is the app's temporary override.
  The data was already in a payload fetched every poll and nothing read it.
- **Schedule active**, a binary sensor per zone.
- **Connected since**, a per-zone timestamp with recent connect and
  disconnect history in its attributes. The account this was built against
  had a two day outage that nothing in Home Assistant would have shown.
- **A reset filter button** per zone.
- **A status LED switch** per zone, for the WiFi adapter's light.

### Documentation

- The README now says plainly what is out of scope and why: Kumo Station and
  its accessories, MHK2 and air handler coils, because the author has none of
  that hardware and will not ship an untestable guess; everything touching
  the account, because credentials and postal addresses have no business in a
  home automation system; and provisioning. This release also claimed
  schedules were permanently blocked, which was wrong; see 1.8.0.

### Known unverified

The reset filter button and the status LED switch both **write**, and
neither write has been fired against a real account. Reading `ledDisabled`
is confirmed; setting it through the cloud command endpoint is inferred,
because the app changes it over a channel this integration does not use. If
the LED switch flips back a second later, the command was accepted and
ignored. Both are marked in their own source files.

## [1.6.0] - 2026-08-23

Live updates. The cloud runs a push channel that the Comfort app uses
instead of polling, and this release subscribes to it. Changes made at the
wall remote or in the app now reach Home Assistant in about a second rather
than up to a minute later.

### Added

- **Push updates over the cloud's Socket.IO channel.** It accepts the same
  bearer token the REST API already uses, so setup is unchanged and no extra
  credential is involved. Subscriptions are re-sent on every reconnect, and
  an unauthorized socket triggers a token refresh and a retry, which is what
  the Comfort app does.
- **`python-socketio`** as the integration's first requirement.

### Changed

- **Polling continues as a heartbeat.** Push is event driven and can go
  quiet for long stretches with nothing wrong, so silence alone cannot tell
  you the socket died. While push is healthy the poll drops to every five
  minutes, and it returns to every minute the moment push disconnects or
  stops delivering. The poll also still carries everything push does not
  send: zones, profiles, wireless sensors, weather and alerts.
- **The integration degrades to polling** if the push channel will not open.
  That is logged, not raised.

### Fixed

- **Nulls in a pushed payload no longer clear fields.** Observed live: two of
  four adapters sent `spHeat: null` in a delta a second after a full snapshot
  had given them real setpoints. Treating that as a value would blank a heat
  setpoint until the next poll.

## [1.5.0] - 2026-08-23

First release from the fork at
[dkmcgowan/ha-comfort](https://github.com/dkmcgowan/ha-comfort). Fixes two
bugs that stopped the integration working properly on units in dry mode and
on hardware added after setup, and surfaces a large amount of state the API
was already returning and nothing read.

Every field read here was verified against a live account before it shipped.

### Fixed

- **Dry mode accepted no target temperature.** On units whose profile
  reports `usesSetPointInDryMode`, Home Assistant showed no setpoint control
  at all, and calling `climate.set_temperature` while in dry built an empty
  command and returned without sending anything or reporting a problem. Dry
  reuses the cool setpoint. Units that do not support one still correctly
  show no control.
- **Setpoint range merged heat and cool.** `min_temp` and `max_temp` took
  the widest of the two, so a unit that allows heat down to 10 C but cool
  only to 16 C offered a cooling setpoint 11 F below what it accepts. The
  range now follows the current mode.
- **Hardware added after setup never appeared.** Pairing a wireless sensor
  in the Comfort app, or adding a zone, produced no entities until the
  config entry was reloaded by hand, because the entity list was built once
  during setup. Both platforms now add on every refresh.
- **Setpoints could bounce back.** They were read from the zone adapter
  while the command cache writes to the device record, so a change could
  visibly revert until the next poll caught up.
- **Asking for a setpoint in a mode that has none** now raises a clear
  error instead of silently doing nothing.
- **Humidity reported five decimal places.** Whole percent on the climate
  entity; the sensors keep the resolution and set a display precision.
- **`manifest.json` carried an invalid `homeassistant` key**, which
  hassfest rejects. The minimum version belongs in `hacs.json`, where it
  already was.

### Added

- **Brand images.** The integration showed a blank placeholder everywhere.
  Home Assistant 2026.3 and newer serve these from the integration itself.
- **Binary sensors** for filter, defrost, standby, hot adjust, fault, cloud
  connectivity and firmware update. The filter one reads the indoor unit's
  own flag, which is a different thing from the existing filter reminder
  sensor, that being a 30 day calendar.
- **Sensors** for the status code the unit displays, the adapter's
  configured setpoint limits, which controls the wall remote is locked out
  of, and a count of unresolved alerts.
- **Outdoor temperature and humidity**, on a new site device that every
  indoor unit now hangs off. These come from the weather service the
  Comfort app uses for the site's location. They are not a reading from
  your equipment.
- **Diagnostics** now include the new data, with the site's postal address
  and coordinates redacted alongside the existing credentials.

### Changed

- **Renamed to "Mitsubishi Comfort (Kumo Cloud)".** Home Assistant Core
  shipped a first-party `mitsubishi_comfort` integration in 2026.6 under
  exactly the previous name, so the two were indistinguishable in the Add
  Integration list. The domain is unchanged, so this remains a drop-in
  replacement and no config entry is affected.
- **Four new endpoints** back the additions. The two that are per unit run
  every tenth refresh rather than every minute, because firmware state and
  remote lockout do not change by the minute.

## [1.4.1] - 2026-05-29

A cohesion pass: aligns module headers, finishes the exception-narrowing
work started in 1.3.0, drops dead constants, centralizes token keys,
removes vestigial helpers, and clarifies a couple of design choices in
inline comments. No runtime behavior changes; entity registry IDs
preserved.

### Added

- **Comparison to other Mitsubishi integrations** in the README. Side-by-side
  framing of when to pick this integration vs. HA Core `mitsubishi_comfort`
  vs. dlarrick/hass-kumo.
- **`CONF_ACCESS_TOKEN` / `CONF_REFRESH_TOKEN`** constants. Token keys were
  previously bare string literals repeated across `__init__.py` and
  `config_flow.py`.

### Changed

- **Complete exception-narrowing pass.** Three remaining bare
  `except Exception` sites that the 1.3.0 narrowing missed:
  `coordinator.async_refresh_device`, `KumoCloudDevice.send_command`,
  and `config_flow.validate_auth`. Programming errors now propagate
  with real tracebacks; only the network/timeout family is caught.
- **`coordinator.py` module header.** Adds the missing module docstring
  and `from __future__ import annotations` for parity with the rest
  of the integration.
- **`climate.py` cleanup.** Removed the redundant `_debug()` wrapper
  around `_LOGGER.debug` (the latter already short-circuits when
  DEBUG is disabled); dropped the misleading leading-underscore
  aliases on `c_to_f` / `f_to_c` imports.
- **Fork-heritage attributions** removed from module docstrings.
  Contributors are credited in the README's Credits section.

### Removed

- **Dead constants** `DEVICE_SERIAL`, `ZONE_ID`, `SITE_ID` from
  `const.py`. They were never imported; the code uses string literals
  inline.

### Documentation

- `last_hvac_mode.py`: docstring now explains why the cache lives on
  `hass.data[DOMAIN]` instead of `entry.runtime_data` (must survive
  config-entry reload).
- `coordinator.py`: a brief comment above the reactive-auth-refresh
  branch describes its relationship to `api._ensure_token_valid`.

## [1.4.0] - 2026-05-29

A handful of additions inspired by patterns from
[dlarrick/hass-kumo](https://github.com/dlarrick/hass-kumo). Cloud-only
architecture is unchanged; nothing in this release requires a network
change.

### Added

- **HA Download Diagnostics support.** The integration page and each
  device page now have a "Download Diagnostics" button that produces
  a JSON snapshot of the coordinator's state. Credentials, tokens,
  serial numbers, MAC addresses, and SSIDs are redacted from the
  output. See `diagnostics.py`.
- **Remember last HVAC mode across off/on cycles.** When a user turns
  a unit off and back on via the HA UI, restore whichever mode they
  had set previously instead of falling back to the device-reported
  mode (which can stale to cool). In-memory only; an HA restart while
  a unit is off falls back to the previous behavior. See
  `last_hvac_mode.py`.
- **DHCP discovery.** Five Mitsubishi WiFi-adapter MAC prefixes
  (24CD8D, 388D3D, 5026EF, 707414, 7087A7) are now registered. HA's
  "Discovered" panel will surface the integration when a Mitsubishi
  adapter joins the network. Clicking through routes to the normal
  credentials step, or aborts cleanly if the account is already set up.
- **Declared HA minimum version `2025.1.0`** in both `manifest.json`
  and `hacs.json`. HACS now gates installs on the HA version.

### Changed

- **F<->C conversion extracted into `temperature.py`.** The Mitsubishi
  lookup tables and helper functions are now an independent module,
  unit-testable in isolation. No behavior change for `climate.py`
  callers.

### Dev infrastructure

- **`.pre-commit-config.yaml` + `.codespellrc`** added. Contributors
  who install pre-commit get automatic ruff lint/format, codespell
  typo detection, and basic file-hygiene hooks. Not used at runtime.

## [1.3.0] - 2026-05-29

A quality pass aligning the integration with current Home Assistant
patterns, partly inspired by the upstream `mitsubishi_comfort`
integration that landed in HA Core (`dev` branch, May 2026). No
runtime behavior changes; entity registry IDs are preserved.

### Added

- **`KumoCloudEntity` base class** in `entity.py`. Shared scaffolding
  (coordinator wiring, `device_info`, `has_entity_name = True`) lifted
  out of every entity. Side effect: sensors now also report `model`,
  `sw_version`, and `serial_number` -- previously only the climate
  entity did.
- **HACS Validation workflow** runs `hacs/action` on every push and PR
  (the `brands` check is ignored pending an upstream brands submission).

### Changed

- **`hvac_action` now uses lookup tables** (`_DIRECT_MODE_ACTIONS`,
  `_DELTA_MODE_ACTIONS`) instead of a ~70-line if/elif chain. The
  1.0 °F deadband is now a single tunable `HVAC_ACTION_DEADBAND_F`
  module constant.
- **Coordinator is stored on `entry.runtime_data`** instead of
  `hass.data[DOMAIN][entry.entry_id]`. New typed alias
  `KumoCloudConfigEntry = ConfigEntry[KumoCloudDataUpdateCoordinator]`.
- **`PARALLEL_UPDATES = 1`** on both climate and sensor platforms to
  prevent bursty Lovelace calls from piling up against the cloud API.
- **`_enable_turn_on_off_backwards_compatibility = False`** on the
  climate entity (opts out of the deprecated HA shim).
- **Coordinator `_async_update_data` catches narrower exceptions**
  (`aiohttp.ClientError`, `OSError`, `asyncio.TimeoutError`) instead
  of a bare `except Exception`. Programming errors propagate normally.
- **Manifest:** added `integration_type: hub`, `quality_scale: bronze`;
  dropped the `aiohttp>=3.8.0` pin (HA pins its own).

### Fixed

- **`string.json` -> `strings.json`.** HA's loader expects the plural
  form; the mistyped filename meant translations were silently ignored
  and config flow strings fell back to keys.

### Removed

- **Unused legacy constants:** `KUMO_FAN_SPEEDS`, `KUMO_AIR_DIRECTIONS`,
  and the `FAN_SPEED_*` / `AIR_DIRECTION_*` set in `const.py` that only
  fed those lists. Live fan/vane handling has used the `API_TO_UI_*` /
  `UI_TO_API_*` mapping dicts for some time.
- **Duplicate `device_info` properties** across all entity classes
  (replaced by `KumoCloudEntity.device_info`).

## [1.2.1] - 2026-05-29

### Changed

- **CI: HACS validation workflow.** Adds `validate.yml` running `hacs/action` against this repo as an integration on every push and pull request, catching HACS-side problems (missing fields, disabled Issues, missing topics) before they surface to end users. The `brands` check is currently ignored.
- **CI: release notes now auto-populated from CHANGELOG.md.** The tag-triggered release workflow extracts the matching `## [VERSION]` section from `CHANGELOG.md` and uses it as the GitHub release body. The workflow hard-fails if the tag has no corresponding entry, preventing empty releases from shipping.

No runtime changes: the `kumo_cloud` integration artifact is identical to v1.2.0.

## [1.2.0] - 2026-05-29

### Added
- **`current_humidity` property on climate entities.** The V3 API adapter payload
  includes a humidity reading for zones with a wireless sensor (PAC-USWHS003-TH-1).
  Mapping it to `ClimateEntity`'s canonical property means standard HA cards
  (tile, thermostat) render humidity automatically, no templating needed.
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
  in that mode, which is wrong for tile glow, energy dashboards, history graphs, and
  any automation keyed on `hvac_action`. Mirrors the generic-AUTO branch's
  existing temp-delta heuristic: HEAT/COOL/AUTO_HEAT/AUTO_COOL flip to `IDLE`
  once the room passes setpoint by >=1.0 °F.
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
- **`refresh_access_token()` gets the same treatment**: DNS/socket errors during a token
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
