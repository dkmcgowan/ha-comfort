"""Constants for the Kumo Cloud integration."""

DOMAIN = "kumo_cloud"

# Config entry keys
CONF_SITE_ID = "site_id"
CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"

# Kumo Cloud REST API
API_BASE_URL = "https://app-prod.kumocloud.com"
API_VERSION = "v3"

# The Comfort app puts 88 of its 97 endpoints on v3 and nine on v4: every
# schedule season route, and the site hold. Calling a v4 route on v3 returns
# `426 invalidAppVersion`, which reads like an app version problem and is
# not one. No header value fixes it; only the version prefix does.
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
