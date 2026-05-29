"""Constants for the Kumo Cloud integration."""

DOMAIN = "kumo_cloud"

# Configuration constants
CONF_SITE_ID = "site_id"

# API constants
API_BASE_URL = "https://app-prod.kumocloud.com"
API_VERSION = "v3"
API_APP_VERSION = "3.2.4"

# Token refresh constants
TOKEN_REFRESH_INTERVAL = 1200  # 20 minutes in seconds
TOKEN_EXPIRY_MARGIN = 300  # 5 minutes margin in seconds

# Device constants
DEVICE_SERIAL = "deviceSerial"
ZONE_ID = "zoneId"
SITE_ID = "siteId"

# Operation modes
OPERATION_MODE_OFF = "off"
OPERATION_MODE_COOL = "cool"
OPERATION_MODE_HEAT = "heat"
OPERATION_MODE_DRY = "dry"
OPERATION_MODE_VENT = "vent"
OPERATION_MODE_AUTO = "auto"
OPERATION_MODE_AUTO_COOL = "autoCool"
OPERATION_MODE_AUTO_HEAT = "autoHeat"

# Default scan interval in seconds
DEFAULT_SCAN_INTERVAL = 60
