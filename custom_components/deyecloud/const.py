DOMAIN = "deyecloud"

CONF_APP_ID          = "app_id"
CONF_APP_SECRET      = "app_secret"
CONF_EMAIL           = "email"
CONF_PASSWORD        = "password"
CONF_STATION_ID      = "station_id"
CONF_DEVICE_SN       = "device_sn"
CONF_RATED_POWER     = "rated_power"
CONF_REFRESH_INTERVAL = "refresh_interval"

DEFAULT_RATED_POWER      = 15000
DEFAULT_REFRESH_INTERVAL = 120  # seconds

TOKEN_TTL = 3000  # seconds — refresh after ~50 min

CONF_SERVER = "server"

# Deye Cloud regional API endpoints
SERVERS: dict[str, str] = {
    "Europe":   "https://eu1-developer.deyecloud.com/v1.0",
    "Americas": "https://us1-developer.deyecloud.com/v1.0",
    "Asia Pacific": "https://apc1-developer.deyecloud.com/v1.0",
}
DEFAULT_SERVER = "Europe"

DAYS = ["SUNDAY", "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY"]

WORK_MODE_SELLING_FIRST = "SELLING_FIRST"
WORK_MODE_ZERO_EXPORT   = "ZERO_EXPORT_TO_CT"
WORK_MODE_ZERO_EXPORT_LOAD = "ZERO_EXPORT_TO_LOAD"
WORK_MODES = [WORK_MODE_ZERO_EXPORT, WORK_MODE_ZERO_EXPORT_LOAD, WORK_MODE_SELLING_FIRST]
WORK_MODE_LABELS = {
    WORK_MODE_ZERO_EXPORT:   "Zero Export to CT",
    WORK_MODE_ZERO_EXPORT_LOAD: "Zero Export to Load",
    WORK_MODE_SELLING_FIRST: "Selling First",
}
