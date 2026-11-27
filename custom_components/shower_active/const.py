DOMAIN = "shower_active"

CONF_SHOWERS = "showers"
CONF_ID = "id"
CONF_SENSOR = "sensor"
CONF_NAME = "name"

# Detection settings, per shower (v1.4.0)
CONF_RISE = "rise"
CONF_MIN_HUMIDITY = "min_humidity"
CONF_DROP = "drop"
CONF_QUIET_MINUTES = "quiet_minutes"
CONF_MAX_MINUTES = "max_minutes"

DEFAULT_RISE = 8.0           # points above the recent low that mean "shower started"
DEFAULT_MIN_HUMIDITY = 60.0  # never turn on below this, whatever the rise
DEFAULT_DROP = 3.0           # points below the session peak that mean "shower ended"
DEFAULT_QUIET_MINUTES = 15   # minutes with no new peak that mean "shower ended"
DEFAULT_MAX_MINUTES = 60     # safety cap on one session

# Fixed tuning, not in the UI
BASELINE_WINDOW_MINUTES = 20  # the "recent low" is the lowest reading in this window
PEAK_TOLERANCE = 1.0          # a reading within this of the peak still counts as at the peak

SENSOR_AGGREGATE = "any_shower_active"
