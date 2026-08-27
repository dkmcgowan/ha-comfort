# Mitsubishi Comfort Integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)

Home Assistant integration for Mitsubishi Electric climate systems that use the
Kumo Cloud / Comfort cloud service (API v3). Provides full climate control,
multi-zone support, and per-zone temperature, humidity, diagnostic, and
wireless-sensor entities.

## Features

- Full climate control: target temperature, HVAC mode, fan speed, vane position
- Heat, Cool, Dry, Fan-only, and Auto (HEAT_COOL) modes with dual setpoints in Auto
- A target temperature in Dry mode on units that support one, with the
  setpoint range following whichever mode the unit is actually in
- Diagnostics the unit reports about itself: filter, defrost, standby, fault
  and status code, remote lockout, and pending firmware updates
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
- Live updates: the integration subscribes to the cloud's push channel, so a
  change made at the wall remote or in the Comfort app shows up in about a
  second rather than at the next poll. Polling continues as a heartbeat and
  as the fallback if the push channel is unavailable
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

Entities marked **off by default** are registered disabled. They are there
for the day something is wrong, and a dozen of them per zone buries the
handful anyone reads daily. Turn one on from its entity page, or several at
once from the device page. This only applies to entities created from now
on: anything Home Assistant registered before it will keep the state it
already has.

Per zone:

| Entity | Notes |
|---|---|
| `climate.<zone>` | Full climate control. Exposes `current_temperature`, `current_humidity` (when the API reports it), target setpoint(s), HVAC mode, fan speed, vane position |
| `sensor.<zone>_temperature` | The room temperature the unit controls against, which is what the climate entity shows. See below |
| `sensor.<zone>_humidity` | Room humidity (when reported) |
| `sensor.<zone>_wifi_signal` | WiFi adapter RSSI (diagnostic) |
| `sensor.<zone>_active_alerts` | Count of unresolved alerts, with the detail in attributes |
| `sensor.<zone>_connected_since` | Start of the current connected session, with availability, outage count and worst outage in attributes |
| `sensor.<zone>_firmware` | WiFi adapter firmware version (diagnostic, off by default) |
| `sensor.<zone>_filter_reminder` | Next filter maintenance date (diagnostic, off by default) |
| `sensor.<zone>_status_code` | The two character code the unit shows on its own display. `A0` is healthy (off by default) |
| `sensor.<zone>_minimum_setpoint_limit` | The adapter's configured lower setpoint bound (off by default) |
| `sensor.<zone>_maximum_setpoint_limit` | The adapter's configured upper setpoint bound (off by default) |
| `sensor.<zone>_remote_lockout` | Which controls the wall remote is locked out of (off by default, the switches below set it) |
| `sensor.<zone>_temperature_offset` | The correction the adapter applies to its reported room temperature (off by default). See below |
| `binary_sensor.<zone>_filter` | The indoor unit's own filter flag |
| `binary_sensor.<zone>_fault` | Set when the unit reports an error |
| `binary_sensor.<zone>_cloud_connection` | Whether the adapter is reaching the cloud, unsmoothed. See below |
| `binary_sensor.<zone>_hold` | A hold is overriding this zone, with its expiry and overrides in attributes |
| `binary_sensor.<zone>_defrost` | Defrost cycle running (off by default) |
| `binary_sensor.<zone>_standby` | Unit in standby (off by default) |
| `binary_sensor.<zone>_hot_adjust` | Hot adjust active (off by default) |
| `binary_sensor.<zone>_firmware_update` | Set when the adapter has an update waiting (off by default) |
| `binary_sensor.<zone>_schedule_active` | A schedule is running on this zone (off by default) |
| `button.<zone>_reset_filter` | Clears the filter reminder |
| `switch.<zone>_status_led` | The WiFi adapter's status light |
| `switch.<zone>_lock_remote_power` | Locks the wall remote out of power |
| `switch.<zone>_lock_remote_mode` | Locks the wall remote out of mode |
| `switch.<zone>_lock_remote_setpoint` | Locks the wall remote out of setpoint |

On a zone with a wireless sensor (PAC-USWHS003-TH-1) paired, four more:
`sensor.<zone>_wireless_sensor_temperature`, `_wireless_sensor_humidity`,
`_wireless_sensor_battery` and `_wireless_sensor_signal`.

Once per site:

| Entity | Notes |
|---|---|
| `climate.<site>_all_zones` | One thermostat for the whole house, see below |
| `switch.<site>_schedules` | Whether the schedule season is running |
| `sensor.<site>_outdoor_temperature` | Outdoor conditions for the site's location |
| `sensor.<site>_outdoor_humidity` | Outdoor conditions for the site's location |

### Schedules

Schedules created in the Comfort app are readable, and the parts worth
automating can be driven from Home Assistant.

`sensor.<zone>_next_schedule_change` gives the timestamp of the next change,
with the mode and setpoints it will apply in its attributes. Events carry
weekdays and a time but no date, so the next occurrence is worked out in
each zone's own timezone.

**It is only created for a zone that has events.** On an account that runs
no schedules there is nothing for it to report, and a sensor sitting at
Unknown forever reads as broken rather than as empty. Save a schedule in the
Comfort app and the sensor appears within a poll. `kumo_cloud.get_schedules`
reports what the account holds either way, including whether the season is
running, which is the thing to call if you expected a schedule and no sensor
turned up.

## Services

Seven, all callable from automations. Setpoints are in Celsius everywhere,
because that is what the API stores.

| Service | What it does |
|---|---|
| `kumo_cloud.get_schedules` | Returns every zone's schedule as response data, with the next change per zone |
| `kumo_cloud.set_schedule` | Replaces one zone's timetable. An empty event list clears it |
| `kumo_cloud.set_season` | Makes a schedule season the active one |
| `kumo_cloud.set_schedules_enabled` | Starts or stops the running season |
| `kumo_cloud.clear_season_events` | Deletes every event in a season. This cannot be undone |
| `kumo_cloud.set_hold` | Pins settings on a zone, or all of them. This is Away mode |
| `kumo_cloud.set_auto_dry` | Turns Auto Dry on or off. Write only, see below |

### Reading schedules

Returns response data rather than setting state, so use `response_variable`:

```yaml
action: kumo_cloud.get_schedules
response_variable: schedules
```

You then have `schedules.season`, `schedules.zones`, and per zone
`event_count`, `events`, `next_change` and `next_event`. For example, to act
only when the Den has something coming up:

```yaml
- action: kumo_cloud.get_schedules
  response_variable: schedules
- condition: template
  value_template: "{{ schedules.zones['Den'].next_change is not none }}"
```

### Writing a schedule

`set_schedule` replaces that zone's whole timetable, because that is what the
API does. Whatever you pass becomes the schedule:

```yaml
action: kumo_cloud.set_schedule
data:
  zone: Den
  events:
    - days: [Mo, Tu, We, Th, Fr]
      start_time: "0715"
      operation_mode: cool
      cool_setpoint: 22.0
      heat_setpoint: 19.0
    - days: [Sa, Su]
      start_time: "0930"
      operation_mode: cool
      fan_speed: low
      cool_setpoint: 23.0
      heat_setpoint: 19.0
```

`days` are two letter codes (`Mo Tu We Th Fr Sa Su`) and `start_time` is
`"HHMM"`, quoted so YAML does not read it as a number. To clear a zone:

```yaml
action: kumo_cloud.set_schedule
data:
  zone: Den
  events: []
```

### Turning scheduling on and off

Either the switch on the site device, or:

```yaml
action: kumo_cloud.set_schedules_enabled
data:
  enabled: false
```

### Away mode

A hold pins settings until you clear it. Leave `zone` out to hold every
zone, which is what the app's Away mode does:

```yaml
action: kumo_cloud.set_hold
data:
  enabled: true
  hold_type: permanent
  operation_mode: cool
  cool_setpoint: 27.0
```

Anything you leave out keeps that zone's current value. `hold_type` is
either `permanent`, which lasts until you clear it, or `until_next_event`,
which releases at the next scheduled change. To end it:

```yaml
action: kumo_cloud.set_hold
data:
  enabled: false
```

Each zone has a `binary_sensor.<zone>_hold` showing whether a hold is active,
with its expiry and the settings it is pinning in the attributes.

For most Home Assistant setups an automation is a better tool than a hold,
since it can react to presence, weather and everything else HA knows. The
hold is here for parity with the app, and because it keeps working if Home
Assistant is down.

### Auto Dry

Auto Dry runs dry mode to pull humidity down without letting the room get
cold. Leave `zone` out to set every zone:

```yaml
action: kumo_cloud.set_auto_dry
data:
  enabled: true
  zone: Den
  target_humidity: 50
```

`target_humidity`, `overcool` and `offset` are optional, and anything left
out is not sent, so the unit keeps whatever it had. The bounds match the
app's own sliders:

| Field | Range | Notes |
|---|---|---|
| `target_humidity` | 35 to 70 % | In steps of 5 |
| `overcool` | 0 to 2 °C | How far below the setpoint it may cool while drying |
| `offset` | 0 to 5 °C | How far above it may run |

In the app those last two are one range slider from -2 to +5, whose handles
stay at least 2 degrees apart, so it will not offer you a low `overcool`
together with a low `offset`. This service does not enforce that pairing,
because there is no way to read back what a unit made of it either way.

**This is write only, and it is a service rather than a switch for a
reason.** Nothing reports Auto Dry back. `GET /devices/{serial}/auto-dry`
returns null for every zone, and asking the adapter directly over the push
channel returns an empty block. So there is no state to show and no way to
confirm a unit applied the change. A switch would have had to invent a
state; a service only claims to send the request, which leaves what to do
about it up to you and your automations.

The Comfort app has the same blind spot, though it does not look like it.
It shows a per zone toggle, but that comes from a cache on the phone holding
what was last pressed there, not from anything the cloud knows. Signing out
of the app clears it and every zone comes back off, which is how this was
confirmed. So if the app and this integration disagree about Auto Dry,
neither one is reading the unit, and the app is not the authority.

Worth knowing before you automate on it: since nothing can confirm the
setting took, treat `set_auto_dry` as a request rather than a guarantee.

### Adapter settings

The status LED and the wall remote lockouts are real controls, not just
readings. They go through a different endpoint from climate commands, which
is why they took a while to find:

- `switch.<zone>_status_led` turns the adapter's light on and off
- `switch.<zone>_lock_remote_power`, `_lock_remote_mode` and
  `_lock_remote_setpoint` lock the wall remote out of each control

The lockout switches report the unit's `effective` state, which is what it
is actually enforcing. A lock can also be applied account-wide, and those
show in the attributes but cannot be cleared from here.

Lockout state also comes over the push channel, so a change made at the wall
remote shows up in seconds rather than waiting for the next slow poll.

### Settings you can see but not change

Two remain read only:

- **The temperature display offset**, `sensor.<zone>_temperature_offset`
- **The per-unit setpoint limits**, `sensor.<zone>_minimum_setpoint_limit`
  and `_maximum_setpoint_limit`

The cloud accepts a new value for these, returns success, and leaves them
alone. Set them in the Comfort app; Home Assistant reflects the change.

### Comfort Settings

**Comfort Settings**, which the app also calls presets, returns
`426 invalidAppVersion` on every endpoint in the family and on every API
version tried, including the exact headers the Comfort app sends.

Both are wanted. Neither is reachable yet.

### Controlling the whole house

Home Assistant has no climate group helper, so a site-wide climate entity is
created alongside the per-zone ones. Setting it applies to every zone, the
same as the Comfort app's "Control all zones". There is no group behind it
on the cloud side; it sends one command per zone, which is exactly what the
app does.

It only offers modes that **every** zone supports, so it can never ask a
unit for something it will refuse. When the zones disagree it reports the
most common mode and the mean setpoint, and puts `zones_in_sync: false` plus
a per-zone breakdown in its attributes, so a disagreement is visible rather
than averaged away.

When a PAC-USWHS003-TH-1 wireless sensor is attached:

| Entity | Notes |
|---|---|
| `sensor.<zone>_wireless_sensor_battery` | Battery level |
| `sensor.<zone>_wireless_sensor_signal` | Wireless sensor RSSI |
| `sensor.<zone>_wireless_sensor_temperature` | Wireless sensor temperature. Reads a few tenths off `sensor.<zone>_temperature` even with no offset. [Why](#why-the-wireless-sensor-reads-differently) |
| `sensor.<zone>_wireless_sensor_humidity` | Wireless sensor humidity |

All entities for a given indoor unit are grouped under a single HA device. The device page shows the model (e.g. `MSZ-FH09NA`), the unit's firmware (`serialProfile`), and the serial number reported by the Comfort cloud. Each indoor unit sits under a site device, which carries the outdoor conditions.

### About outdoor temperature

The outdoor sensors report the weather where your site is, from the same
service the Comfort app uses. They are **not** a reading from your
equipment. A real outdoor coil temperature needs a Kumo Station accessory,
and without one the field the cloud would report it in stays empty.

## What this integration does not do

**Kumo Station and its accessories.** The cloud API exposes a Kumo Station,
its accessory channels, relay outputs, MHK2 thermostats and air handler coil
settings. None of it is implemented, for one reason: the author does not own
any of that hardware, so none of it could be tested against a real device.
Guessing at an interface for equipment nobody can try is how you ship
something that looks finished and does not work. If you have this hardware
and want it supported, open an issue.

The same goes for outdoor temperature from the equipment itself. The field
exists, but it belongs to the Kumo Station, so it stays empty without one.
The outdoor sensors here come from a weather service instead, and are
labeled as such.

**Configuration and account management, on purpose.** Roughly a third of the
app's API surface is settings, and none of it is here. That means everything
under the app's Settings screens: location details and address, timezone,
notification preferences, transferring or deleting a location, adding a
contractor or requesting service, changing your password or username, email
verification, the temperature display preference, third-party integration
links, terms and privacy.

Provisioning is out for the same reason: claiming and unregistering
adapters, pairing codes, and the installer-level settings of an indoor unit.
So is deleting a zone.

This is a deliberate line, not a backlog. None of it belongs in a home
automation system, and staying out of it means a bug here can never touch
your credentials, your address, or your equipment's commissioning. Set your
system up in the Comfort app; use this to run it.

**Comfort Settings** is absent because it cannot be reached, not because it
was skipped. See above.

## Behavior notes

### Which temperature is which

`sensor.<zone>_temperature` and the climate entity's `current_temperature`
are the same number: `roomTemp`, the reading the equipment controls against.
It is not a raw thermistor value. Where a wireless sensor is paired it is
that sensor's measurement, and either way the adapter's display offset has
already been added, so on a zone with a sensor you should expect:

    sensor.<zone>_temperature = sensor.<zone>_wireless_sensor_temperature + offset

Read against a live account, all four zones match that to the half degree
the offset is stored in: 23.5 against a sensor at 21.10 with an offset of
2.5, 22.5 against 21.45 with an offset of 1, and so on.

The indoor unit's own thermistor is not reported separately when a wireless
sensor is the source, so there is no third reading to expose. `tempSource`
and `activeThermistor` are null on all hardware seen.

#### Why the wireless sensor reads differently

Even with the offset cleared, `sensor.<zone>_wireless_sensor_temperature`
will not equal `sensor.<zone>_temperature`. This is expected. Two things
separate them, and both are deliberate.

**`roomTemp` is rounded before you see it.** The cloud stores it in half
degree Celsius steps, so a sensor reading 21.8 °C is stored as 22.0 °C. The
room temperature is the sensor's value snapped to that grid, then offset.

**They are converted by different rules.** Mitsubishi does not convert
Celsius to Fahrenheit by arithmetic; it uses a lookup table, and that table
is what the Comfort app and the wall remote display. `roomTemp` sits exactly
on the half degree steps the table maps, so it goes through the table and
matches the app. The wireless sensor reports to two decimals on no
particular grid, which makes it a real continuous measurement rather than a
display value, so it is converted by ordinary arithmetic and keeps its
precision. The table has nothing to say about a value between its steps.

Put together, on a Fahrenheit system with no offset:

| | Stored | Shown | Why |
|---|---|---|---|
| `_wireless_sensor_temperature` | 21.8 °C | 71.2 °F | Arithmetic, one decimal |
| `_temperature` | 22.0 °C | 71 °F | Rounded to 0.5 °C, then the table |

Both are correct. The second is what your equipment is actually working
from and what the app shows you; the first is the finer measurement, and the
better one to graph or trigger automations on if you want resolution.

The same reasoning is why `sensor.<site>_outdoor_temperature` uses
arithmetic: it comes from a weather service, not from Mitsubishi.

The offset itself is `sensor.<zone>_temperature_offset`, off by default. It
is a **difference** between two temperatures rather than a temperature, so
it carries no device class: Home Assistant converts a temperature by scaling
and shifting, which is right for a reading and wrong for a gap between two,
and displayed an offset of 0 C as 32 F.

The conversion follows Mitsubishi's own rule instead. One Fahrenheit step is
half a Celsius degree throughout their interface, the same rule their
setpoints follow, so an offset doubles rather than scaling by 9/5. Set a zone
to 5 in the Comfort app and the API stores 2.5; this entity shows 5 again, so
it matches what you set.

### How a reading stays current

**Nothing arrives from the cloud unprompted.** A five minute listen on a
subscribed push socket returned the snapshots it replays on subscribe and
then silence, and the cloud's stored record for all four zones was measured
12.7 hours stale overnight while every adapter was reachable and the Comfort
app worked. `GET /devices/{serial}` returns that same stored record, and the
zone list carries a copy of it with the identical timestamp, so polling
harder cannot make it fresher. There is nothing newer to poll.

What produces a new reading is asking an adapter for one. So every minute,
each adapter is asked to report its `iuStatus` block over the push socket,
and the answer comes back in well under a second carrying room temperature,
setpoints, mode, fan, humidity and signal strength. Measured on a live
account: the request went out and all four zones had answered 0.37 seconds
later.

The cadence is the Comfort app's own. Its `forceAdapterRequest` refuses a
repeat inside 60 seconds for the same device and block, and this integration
uses that same limit, enforced the same way. While a zone screen is open the
app is twice as busy as this, nudging every 30 seconds. So the traffic is
one socket message per zone per minute on a connection that is already open,
and **no REST request at all**. The REST poll stays on its five minute
heartbeat.

The same request goes out on startup, before the first minute has elapsed,
because the record the setup poll just read can be hours old. That is what
stops a thermostat showing last night's temperature for a minute after Home
Assistant restarts.

### When a zone goes unavailable

Almost never, on purpose. A zone's entities go unavailable only when there
is genuinely nothing to report for it: no device record has ever arrived, or
the config entry failed to set up. A failed poll does not do it, and neither
does anything the cloud says about the adapter's connection.

**The cloud's `connected` field is not a liveness signal and nothing keys
availability on it.** Measured against a live account on 2026-08-26: all
four adapters read `connected: false`, all four carried the identical
`updatedAt` to within 600 milliseconds, all four had an open session in
`/zones/{id}/connection-history` that had been running for between one and
six days, and all four were reporting current room temperatures. A field
that flips on every adapter at once, on one cloud-side write, while the
hardware is plainly talking, is a record of something else.

Following that field is what made every thermostat here disappear from Home
Assistant overnight while the Comfort app showed nothing wrong, and brought
them back the moment anything touched a unit and the cloud wrote `true`
again. A grace period was tried first and only changed how long it took. An
entity is unavailable when Home Assistant cannot say what the state is, not
when a vendor field reads false.

The connection is still reported, just not acted on.
`binary_sensor.<zone>_cloud_connection` follows the session history, which
does track real events: every zone closed a session within two minutes of a
WiFi channel change. Its `cloud_connected_flag` attribute carries the device
record's field alongside it, so the disagreement stays visible.
`sensor.<zone>_connected_since` reports the start of the current session.

That sensor's attributes are the ones worth reading when a zone misbehaves.
`availability_percent`, `outages`, `longest_outage_minutes` and
`downtime_minutes` cover the whole window the cloud has kept, which is
several days. A zone that reconnects twenty times a day for two minutes each
is a different problem from one that goes away for an afternoon, and a
reconnect count on its own does not tell them apart.

Each row the cloud returns is a connected **session**, not an outage, and
`recent_sessions` is presented that way. The outages are the gaps between
sessions, which is what the figures above count.

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

Verified against the Comfort app on a live account with the display offsets
cleared: zones storing 22.0 °C and 21.5 °C show 71 °F and 70 °F there.
Arithmetic would have given 72 and 71, wrong on both.

The table applies to everything Mitsubishi stores on its own half degree
grid: setpoints, `roomTemp`, and the adapter's setpoint limits. It does not
apply to readings that are not on that grid, which is the wireless sensor
and the outdoor weather feed. See
[Why the wireless sensor reads differently](#why-the-wireless-sensor-reads-differently).

On a Celsius system the stored value is shown as-is, with no table involved.
This is true of the sensors; the climate entity still assumes Fahrenheit.

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
