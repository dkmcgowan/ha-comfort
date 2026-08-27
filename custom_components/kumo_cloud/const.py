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
# to the normal poll. With `STATUS_REPORT_INTERVAL` below asking every
# adapter to report once a minute, a healthy channel is never quiet for long,
# so this only has to be generous enough to ride out a run of adapters that
# decline to answer.
PUSH_STALE_AFTER = 1800

# How often each adapter is asked to report its current readings over the
# push channel.
#
# **Nothing arrives unprompted.** A five minute listen on a subscribed socket
# returned the replayed snapshots and then nothing at all, and the cloud's
# record was measured 12.7 hours stale overnight. `GET /devices/{serial}`
# hands back that same record, so polling harder cannot make it fresher; the
# only thing that produces a new reading is asking the adapter for one.
#
# 60 seconds is the Comfort app's own floor, read out of its bundle: its
# `forceAdapterRequest` refuses a repeat inside 60000 ms for the same device
# and block. While a zone screen is open the app is twice as busy as this,
# nudging every 30 seconds (`AUTO_POLLING_INTERVAL`). So this sits at the
# vendor's documented throttle rather than at anything invented here, and it
# costs one socket emit per zone per minute with no REST request at all.
STATUS_REPORT_INTERVAL = 60
