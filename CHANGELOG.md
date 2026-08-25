# Changelog

## [1.15.0] - 2026-08-25

### Changed

- **A disconnect is now checked against the cloud's own record before the
  entities follow it.** The `connected` field on the device record was seen
  reading false for 90 minutes on a zone whose connection history had an
  open session running through the whole period, and whose record simply
  stopped being written. The history is the source that tracks real events:
  every zone on the account closed a session within two minutes of a WiFi
  channel change. That false negative is the "unavailable for hours" this
  started from, and the 15 minute grace added in 1.14.0 covered 15 minutes
  of it.

  A zone flagged disconnected now has its history re-read on each poll.
  While that history still shows an open session the entities stay
  available, to a two hour cap, after which one of the two sources is
  broken and the flag is the safer one to believe. Once both agree, the
  normal 15 minute rule applies. One request per poll per broken zone, and
  none while everything is working.

- Both outcomes are logged at warning level with the zone name: whether the
  history contradicted the flag or backed it. If this turns out to be
  common, the log will say so.

## [1.14.1] - 2026-08-25

### Fixed

- **Connection history was read backwards, and said healthy adapters had
  been down for days.** Each row `/zones/{id}/connection-history` returns is
  a connected **session**, not an outage: `isConnected` is true only on the
  currently open row, so every closed row reads false whatever happened
  during it, and `uptime` is that session's length. The outages are the gaps
  between sessions. The `outages_recorded` attribute counted closed sessions
  and so reported one adapter as having eleven outages in a week when it had
  eleven connected runs and, in total, 29 minutes offline.

  The arithmetic is what catches this and is worth keeping in mind for any
  endpoint that returns intervals: read as outages the rows summed to
  several times the window they covered, which cannot happen.

- `sensor.<zone>_connected_since` now reports `availability_percent`,
  `outages`, `downtime_minutes`, `longest_outage_minutes` and `window_hours`
  instead of a count of rows. A zone that reconnects twenty times a day for
  two minutes each is a different problem from one that goes away for an
  afternoon. The rows themselves are still there as `recent_sessions`,
  labeled as sessions.

The claim in 1.5.0 that this account "had a two day outage that nothing in
Home Assistant would have shown" was the same misreading. It was a two day
connected run. The entry is left as it was written.

## [1.14.0] - 2026-08-25

Everything here came from a week of running the previous build on real
hardware. Three of the four are the integration's fault.

### Fixed

- **One zone's thermostat could go unavailable while its own sensors kept
  working.** Two separate causes, both fixed. A failed `GET /devices/{serial}`
  left an empty record behind, and the climate entity is the only one that
  reads that record for the fields it needs, so it went unavailable until a
  later poll succeeded while the sensors, which read the zone list and the
  per device calls that had worked, carried on. The last known record is now
  kept instead, and the failure is logged rather than passed over at debug
  level. Separately, the cloud's `connected` flag was followed directly, and
  it flips on a single missed beat.
- **A brief disconnect no longer takes the entities down.** A drop has to
  last 15 minutes before the entities follow it. Both edges are logged at
  warning level with the zone name, so the log answers the question
  afterwards. `binary_sensor.<zone>_cloud_connection` still reports the raw
  flag for anyone who wants to see every flap, and
  `sensor.<zone>_connected_since` still carries the history.
- **The temperature offset read 32 degrees.** It was declared as a
  temperature, so Home Assistant converted it the way it converts a reading,
  by scaling *and shifting*, and an offset of 0 C came out as 32 F. It is a
  difference between two temperatures, not a temperature. There is no delta
  device class to use instead, so the class is gone and the entity converts
  the value itself, by Mitsubishi's rule rather than by arithmetic: one
  Fahrenheit step is half a Celsius degree throughout their interface, the
  same rule the setpoint table follows, so an offset doubles rather than
  scaling by 9/5. Confirmed by setting a zone to 5 in the Comfort app and
  reading the field back as 2.5. Arithmetic would have shown 4.5.
- **`sensor.<zone>_next_schedule_change` sat at Unknown on accounts with no
  schedule.** It is now created only for a zone that actually has events, and
  appears within a poll of the first one being saved in the Comfort app.
  `kumo_cloud.get_schedules` reports what the account holds either way.

### Changed

- **Most diagnostic entities are registered disabled.** Firmware, filter
  reminder, status code, both setpoint limits, remote lockout, temperature
  offset, defrost, standby, hot adjust, firmware update and schedule active.
  They are there for the day something is wrong, and a dozen per zone buries
  the handful anyone reads daily. Left enabled: WiFi signal, the wireless
  sensor readings, active alerts, connection uptime, filter, fault, cloud
  connection and hold. **This only affects entities created from now on.**
  Anything already registered keeps the state it has, and is disabled from
  its entity page.
- The room temperature sensor says what it actually is. `roomTemp` is the
  reading the equipment controls against: on a zone with a wireless sensor
  that is the sensor's measurement with the adapter's offset added, not the
  indoor unit's own thermistor, which is not separately reported. The README
  spells out the arithmetic between the two temperature entities.
- The schedule sensor and the `get_schedules` service read the zone timezone
  from the device record with the adapter as a fallback, rather than each
  reading one of the two.

### Housekeeping

`binary_sensor.<zone>_status_led` was removed in 1.11.0 and replaced by
`switch.<zone>_status_led`. A removed entity stays in Home Assistant's
registry showing unavailable until it is deleted by hand, so if you upgraded
through 1.11.0 there is a stale one to delete on each zone. Nothing in the
integration can remove it for you.

## [1.13.1] - 2026-08-24

### Fixed

- **`set_auto_dry` accepted values the app does not offer.** The bounds were
  a guess and all three were wrong. Corrected against the constants in the
  app's own bundle: `target_humidity` is 35 to 70 in steps of 5, not 30 to
  80; `overcool` is 0 to 2, not 0 to 10; `offset` is 0 to 5, not -10 to 10.

Reported from the app, where the temperature settings would not go below a
magnitude of 2. That turned out to be one range slider spanning -2 to +5 C
whose two handles stay at least 2 degrees apart, split into two fields on
the way out: `overcool` carries the magnitude of the below-setpoint handle
and `offset` the above-setpoint one.

The service does not enforce the pairing rule between them, only the outer
bounds, because there is no way to read back what a unit made of it either
way. The README says so.

Worth stating plainly: nothing reports these values back, so a wrong bound
here was invisible. It took someone using the app to catch it.

## [1.13.0] - 2026-08-24

Auto Dry becomes available after all, as a service.

1.12.0 left it out on the grounds that a setting nothing reports back has no
honest entity shape. That was right about the entity and wrong about the
conclusion. A service does not have to hold state, so it can offer the write
without pretending to know the result, and what to do about that becomes the
caller's decision rather than a claim the integration makes.

### Added

- **`kumo_cloud.set_auto_dry`**, turning Auto Dry on or off for one zone or
  all of them, with optional `target_humidity`, `overcool` and `offset`.
  Fields left out are not sent, so the unit keeps whatever it had.

### Write only, deliberately

Nothing reports Auto Dry back: the REST route returns null for every zone
and asking the adapter over the push channel returns an empty block. So
there is no state to show and no way to confirm a unit applied the change.
Treat the service as a request rather than a guarantee.

The Comfort app has the same blind spot without looking like it. Its per
zone toggle is fed by a cache on the phone holding what was last pressed
there. Signing out clears it and every zone comes back off, which is how
this was confirmed on a real account: three zones that had shown on for days
came back off, because nothing existed to restore them from.

## [1.12.0] - 2026-08-24

Settings can now be read straight off an adapter over the push channel,
rather than only from REST. Wall remote lockouts use it, so a lock changed
at the unit appears in seconds instead of on the slow poll.

This also closes out Auto Dry, which is what sent us looking for the
mechanism in the first place. It is not shipping, and now for a definite
reason rather than an unexplained one.

### Added

- **Adapter block reads over the push channel.** The app asks a unit to
  report part of itself with `force_adapter_request` and handles the reply
  on a matching `<block>_update` event. Lockout state is read this way on
  every refresh, throttled to one request per unit per minute as the app
  does, and immediately after a write.

### Changed

- Lockout switches no longer wait for the slow REST tier to notice a change
  made at the wall remote.

### Auto Dry: closed

The cloud does not hold an Auto Dry value, so there is nothing to build a
control on.

The app does not read `/devices/{serial}/auto-dry` either; it asks the
adapter over the socket and renders the reply. Doing exactly that returns an
empty block for every unit, including immediately after a write the cloud
answers 200 to. The same request for `prohibits` returns full data in about
a second, so the request is well formed and the mechanism works.

The app still shows per zone Auto Dry state because it persists its whole
query cache to the phone and the toggle writes an optimistic value into it.
That is a record of what was pressed on that device, not anything the cloud
knows, and it survives force closing the app. So the app and this
integration can disagree about Auto Dry, and the app is not the authority.

The write is accepted and echoed back, but with no way to read the value
there is no way to confirm a unit ever applied it.

### Answers are not attributable in bulk

Worth recording for anyone extending this. The `<block>_update` replies
carry no device serial, even though the app's own handlers read one off the
payload. Matching replies to requests in the order sent looks correct and is
not: asking four units at once, with a lockout set on the second, brought
that lockout back in the third reply, which would have put one unit's state
on another. Requests are serialized instead, so only one is ever
outstanding. Both behaviors are covered by tests.

## [1.11.0] - 2026-08-24

The status LED and the wall remote lockouts become real controls. Both were
previously read only, on the mistaken conclusion that they could not be
written at all.

### Added

- **`switch.<zone>_status_led`**, which actually turns the adapter's light
  on and off.
- **`switch.<zone>_lock_remote_power`, `_lock_remote_mode` and
  `_lock_remote_setpoint`**, which lock the wall remote out of each control.
  They report the unit's `effective` state, and expose where a lock came
  from in their attributes, because an account-wide lock cannot be cleared
  from here.

### Removed

- `binary_sensor.<zone>_status_led`, replaced by the switch above.

### The endpoint

Both go through `POST /v3/devices/{serial}/relay-command`, which is a
separate path from `/devices/send-command` and is the one that carries
adapter settings rather than climate commands:

    {"serial": ..., "adapter": {"status": {"ledDisabled": bool}}}
    {"serial": ..., "indoorUnit": {"prohibits": {"local": {power, mode, setpoint}}}}

Everything previously tried sent the right fields to the wrong endpoint,
which returns 200 and silently discards them. Found by disassembling the
app's Hermes bytecode rather than decompiling it: `useZoneDetails` exports
`updateLedLights` and `updateProhibits`, neither of which calls an API
directly. They write into a ref that a 1.5 second debounced sender flushes
through `useRelayCommandQuery`. Both are verified by changing the real value
and reading it back.

Prohibits are re-read immediately after a write rather than waiting for the
slow tier, so the switch does not appear to snap back.

### Still not reachable

**Auto Dry.** The same endpoint accepts `adapter.autodry` and echoes the
settings back with a 200, but the Comfort app still shows the feature off
afterwards, so the write is discarded. The state is not readable either.
Both halves would have to work before this is worth shipping.

## [1.10.1] - 2026-08-24

### Fixed

- **hassfest rejected `services.yaml`.** The `operation_mode` options were
  written unquoted, and YAML reads a bare `off` as the boolean false, so the
  validator found a null where a string belonged. Quoted, with a note saying
  why.

### Documentation

- **The README now shows how to call every service**, with worked examples
  for reading schedules into a `response_variable`, writing or clearing a
  zone's timetable, toggling scheduling, and using a hold as Away mode.
- **The read-only settings say plainly why they are read only:** nobody has
  worked out how to write them. The cloud accepts the value, returns
  success, and changes nothing, and every payload shape the app itself
  builds has been tried. Reading works, so they are sensors.
- **Auto Dry and Comfort Settings are documented as unreachable rather than
  unimplemented**, with what was actually checked.
- **The excluded configuration surface is spelled out**, screen by screen,
  as a deliberate line rather than a backlog.

## [1.10.0] - 2026-08-24

Filling the gaps found by walking the Comfort app screen by screen.

### Added

- **`kumo_cloud.set_hold`**, which is what the app calls Away mode. A hold
  pins chosen settings on a zone, or on every zone, until it is cleared or
  expires at the next scheduled change. Anything not given keeps the zone's
  current value.

  Working out the payload took some doing: the zone key is `id` rather than
  `zoneId`, every settings field has to be present, and anything less returns
  `400 {"zones": "Required"}` naming the array rather than the key actually
  missing.
- **`switch.<site>_schedules`**, a toggle for whether the schedule season is
  running, so scheduling can be turned on and off without calling a service.
- **`sensor.<zone>_temperature_offset`**, the correction the adapter applies
  to its reported room temperature. Useful when a zone reads differently
  from a wireless sensor in the same room, because the room reading already
  has this added.

### Documentation

- The README now lists the settings that are readable but not writable, and
  says why: the cloud accepts the value, returns success and ignores it. That
  covers the status LED, the temperature offset, and the per-unit setpoint
  limits. All three track correctly when changed in the app.
- Away mode is documented, with the note that a Home Assistant automation is
  usually the better tool, since it can react to presence and everything else
  HA knows. The hold is there for parity and because it survives HA being
  down.

### Still not reachable

- **Auto Dry.** With three zones on and one off, every REST document is
  byte-identical and the socket carries nothing about it. Not exposed
  anywhere this client can see.
- **Comfort Settings**, which is what the app calls presets. Every endpoint
  in that family returns `426` on every API version tried.

## [1.9.2] - 2026-08-24

### Fixed

- **The climate card flicked back to the old value for about a second.**
  Change a unit from dry to cool and the card showed cool, reverted to dry,
  then settled on cool. Reported from a real install.

  The integration holds a just-sent value in place while the cloud catches
  up, which can take up to a minute. It was releasing that hold by comparing
  the client's clock against the server's `updatedAt` and letting go as soon
  as `updatedAt` was the newer of the two. That fails two ways: any clock
  skew between Home Assistant and the cloud releases it immediately, and
  `updatedAt` moves whenever the record changes for any reason, not only
  when the command lands, so an unrelated telemetry update releases it early.
  Either one lets the old value flash back.

  The hold is now released when the server reports the value that was
  actually asked for, which involves no clocks at all, with a 90 second
  timeout so a command the equipment refused stops being displayed. Setpoints
  compare with a tolerance, because floats do not round trip exactly.

  The logic moved to `command_cache.py`, which imports nothing from Home
  Assistant and has tests covering the reported case, per-device and
  per-field isolation, the refusal timeout, and partial push payloads that
  omit the field entirely.

## [1.9.1] - 2026-08-23

### Fixed

- **The integration failed to set up.** `climate.py` imported `whole_home.py`
  for the all-zones entity, and `whole_home.py` imported `climate.py` back
  for a type annotation. Home Assistant loads each platform separately, so
  that cycle only breaks at load time, with
  `ImportError: cannot import name 'KumoCloudClimate' from partially
  initialized module`. The annotation import is now behind `TYPE_CHECKING`,
  where it does not run.

  This shipped because nothing in the local checks imports anything. `ruff`
  does not detect import cycles and `compileall` compiles without importing,
  so both were green on broken code. `tests/test_imports.py` now imports
  every module, including the two platforms in the order that reproduces the
  cycle. It runs in CI, where Home Assistant is available, and skips
  elsewhere.

## [1.9.0] - 2026-08-23

Every write path is now fired against a real account. Three were wrong and
one turned out to be impossible.

### Fixed

- **The filter reset button did nothing.** The endpoint is a **PATCH**, not
  a POST. POST, PUT, DELETE and GET all return 404 on that route. Verified:
  the reminder date moves.
- **Clearing season events did nothing.** The call needs the schedule ids in
  its body, `{"schedules": ["<id>", ...]}`, or it returns
  `400 {"error": {"schedules": "Required"}}`. Verified: returns 204 and every
  named schedule ends with zero events.
- **Enabling and disabling schedules used a route that does not work.**
  `/sites/{id}/toggle-schedules` returns `426` on every API version tried.
  The service now starts and stops the running season instead, which does
  the same job and is verified in both directions.

### Removed

- **The status LED switch.** The cloud accepts `ledDisabled` through both
  `/devices/send-command` and a PATCH on the device record, returns 200 for
  each, and changes nothing: the value reads back unchanged a minute later,
  and the PATCH response echoes the old value. The app sets this over a
  channel that is not the cloud API. Shipping a control that silently does
  nothing is worse than not shipping it, so the LED is now a read-only
  diagnostic binary sensor. The state was always correct; only the write
  was fiction.

### Added

- **`kumo_cloud.set_schedule`**, now that the payload shape is known and
  proven. It replaces one zone's timetable outright, because that is what
  the API does. An empty event list clears the zone.

### Changed

- **The note about `426 invalidAppVersion` was too confident.** 1.8.0 framed
  it as always meaning "wrong version prefix". It does not. It marks a route
  this client may not use, and sometimes there is a working equivalent
  elsewhere, as with the schedule seasons on v4, and sometimes there is none
  at all, as with `toggle-schedules` and the comfort settings.

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
