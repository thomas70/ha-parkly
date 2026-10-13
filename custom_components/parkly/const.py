"""Constants for Parkly."""
DOMAIN = "parkly"

# Options (Settings → Devices & services → Parkly → Configure).
CONF_FAST_INTERVAL = "fast_interval"  # seconds, during working hours
CONF_SLOW_INTERVAL = "slow_interval"  # minutes, outside working hours
CONF_WORK_START = "work_start"  # hour, local time
CONF_WORK_END = "work_end"
CONF_WEEKENDS = "weekends"  # treat Saturday/Sunday as working days

DEFAULTS = {
    CONF_FAST_INTERVAL: 60,
    CONF_SLOW_INTERVAL: 15,
    CONF_WORK_START: 7,
    CONF_WORK_END: 17,
    CONF_WEEKENDS: False,
}
