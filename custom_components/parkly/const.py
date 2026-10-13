"""Constants for Parkly."""
DOMAIN = "parkly"

# Poll often while people arrive and leave, rarely otherwise.
WORK_DAYS = range(0, 5)  # Monday–Friday
WORK_START = 7  # hour, local time
WORK_END = 17
FAST_INTERVAL = 60  # seconds
SLOW_INTERVAL = 15 * 60
