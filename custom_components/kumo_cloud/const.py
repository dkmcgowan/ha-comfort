"""Constants for the Kumo Cloud integration."""

DOMAIN = "kumo_cloud"

# Config entry keys
CONF_SITE_ID = "site_id"
CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"

# Kumo Cloud REST API
API_BASE_URL = "https://app-prod.kumocloud.com"
API_VERSION = "v3"

# The Comfort app puts most of its endpoints on v3 and nine on v4: every
# schedule season route, and the site hold.
#
# `426 invalidAppVersion` does not mean what it says. No value of
# x-app-version changes it, including the exact one the app sends. It marks
# a route this client may not use, and it shows up in two different
# situations:
#   - There is a working equivalent elsewhere. The schedule family is the
#     example: `/v3/zones/{id}/schedules` is 426 forever, while the season
#     routes on v4 work.
#   - There is no working route at all. `/sites/{id}/toggle-schedules` and
#     the comfort settings endpoints are 426 on every version tried, while
#     the neighboring `/sites/{id}/toggle-notifications` returns 200 on v3.
# So a 426 is worth hunting for an alternative, but finding one is not
# guaranteed.
API_V4 = "v4"
API_APP_VERSION = "3.2.4"
TOKEN_REFRESH_INTERVAL = 1200  # seconds (20 min)
TOKEN_EXPIRY_MARGIN = 300  # refresh this many seconds before expiry

# Kumo operationMode values (raw API; see climate.py for HVACMode mapping)
OPERATION_MODE_OFF = "off"
OPERATION_MODE_COOL = "cool"
OPERATION_MODE_HEAT = "heat"
OPERATION_MODE_DRY = "dry"
OPERATION_MODE_VENT = "vent"
OPERATION_MODE_AUTO = "auto"
OPERATION_MODE_AUTO_COOL = "autoCool"
OPERATION_MODE_AUTO_HEAT = "autoHeat"

# Coordinator polling
DEFAULT_SCAN_INTERVAL = 60

# When the push channel is up, the poll drops back to a heartbeat: it proves
# the account still works, refreshes the fields push never sends (zones,
# profiles, wireless sensors), and replaces records wholesale so a field that
# genuinely went null gets cleared. Push carries the latency-sensitive part.
PUSH_SCAN_INTERVAL = 300

# If push has delivered nothing for this long, stop trusting it and go back
# to the normal poll. Push is event driven and can legitimately go quiet, so
# this is deliberately several times longer than any expected gap.
PUSH_STALE_AFTER = 1800

# How long the cloud has to keep calling an adapter disconnected before its
# entities follow. The flag flips on a single missed beat and flips back the
# same way, and a WiFi adapter on a busy channel does that several times a
# day. Following it directly turns a blip into an unavailable climate entity,
# which breaks automations and leaves a gap in the history for something that
# was over before anyone looked. Longer than the slow poll tier, so a real
# outage is still reported within a few minutes.
DISCONNECT_GRACE = 900
