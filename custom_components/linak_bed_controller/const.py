"""Constants for the Linak Bed Controller integration."""

DOMAIN = "linak_bed_controller"

# GATT UUIDs (Linak DPG control box)
SERVICE_CONTROL = "99fa0001-338a-1024-8a49-009c0215f78a"
CHAR_COMMAND = "99fa0002-338a-1024-8a49-009c0215f78a"
# Position feedback characteristics (notify + read), on service 99fa0020. On a
# 2-motor bed the "back" actuator is the head rest and "leg" is the foot rest.
CHAR_POSITION_HEAD = "99fa0028-338a-1024-8a49-009c0215f78a"
CHAR_POSITION_FOOT = "99fa0027-338a-1024-8a49-009c0215f78a"

# Default raw position range of the actuators. The real range is learned
# automatically (from notifications and end-stop detection) and persisted
# in the config entry options.
DEFAULT_RAW_MAX_HEAD = 820
DEFAULT_RAW_MAX_FOOT = 548

CONF_RAW_MAX_HEAD = "raw_max_head"
CONF_RAW_MAX_FOOT = "raw_max_foot"

# Movement engine tuning
KEEPALIVE_INTERVAL = 0.2  # seconds between move-command refreshes
DEADBAND_PCT = 2.0  # close enough to target, stop commanding
STALL_TIMEOUT = 3.0  # no position change while commanding -> end stop
POSITION_PROBE_TIMEOUT = 3.0  # give up if no position feedback arrives
MAX_MOVE_DURATION = 75.0  # hard safety cap on a single movement
STOP_WRITE_RETRIES = 3
# A stall while targeting 100% only recalibrates the top if it happens at
# least this far up the currently known range; lower stalls are obstructions.
END_STOP_TOLERANCE = 0.85
RAW_MAX_SAVE_DELAY = 10.0  # debounce for persisting learned ranges

# Dead-reckoning fallback, used when a control box exposes no position
# feedback (e.g. some TD4 Standard configurations): movement is timed against
# an assumed full-travel duration and re-synced at the physical end stops.
DEAD_RECKON_FULL_TRAVEL = 30.0  # seconds for 0% -> 100%
DEAD_RECKON_RESYNC_SECONDS = 6.0  # extra drive past an end to guarantee the stop

# Connection
CONNECTION_TIMEOUT = 20  # seconds, overall budget for establish_connection
RECONNECT_INITIAL_DELAY = 1.0
RECONNECT_MAX_DELAY = 300.0
