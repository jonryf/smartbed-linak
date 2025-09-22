"""Constants for the Linak Bed Controller integration."""

DOMAIN = "linak_bed_controller"

# Connection configuration optimized for ESP32 Bluetooth proxies
CONNECTION_TIMEOUT = 10  # seconds
CONNECTION_RETRY_DELAY = 2  # seconds (reduced from 5)
MAX_CONNECTION_ATTEMPTS = 3  # reduced from 6
GATT_AUTH_TIMEOUT = 3  # seconds (reduced from 10)
POST_CONNECTION_DELAY = 0.3  # seconds (reduced from 1.5)

# ESP32 Bluetooth proxy optimizations
ESP32_MTU_SIZE = 185  # Optimal MTU for ESP32
