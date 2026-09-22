from machine import Pin, PWM
import time
import neopixel
import network
import ujson

try:
    import urequests as requests
except ImportError:
    requests = None  # install with: mip.install("urequests") over a REPL connection
# HARDWARE
SERVO_PIN = 18
NEOPIXEL_PIN = 15
NUM_PIXELS = 2

UPDATE_INTERVAL = 5            # seconds between clock updates

SERVO_MIN_DUTY = 1638           # ~0.5ms pulse -> 0 degrees (duty_u16, 50Hz)
SERVO_MAX_DUTY = 8192           # ~2.5ms pulse -> 180 degrees

AM_COLOR = (40, 40, 0)          # dim yellow
PM_COLOR = (10, 10, 60)         # deep blue
# CALIBRATION
# The dial is 30 minutes ahead, so subtract 7.5 degrees from each angle.
CALIBRATION_OFFSET_DEGREES = 7.5

# Give the servo extra time to settle based on how far it moves.
SERVO_SETTLE_BASE_MS = 150
SERVO_SETTLE_MS_PER_DEGREE = 6
# -# WIFI / WEATHER
SSID = "tufts_eecs"
PASSWORD = "foundedin1883"

# Cupertino, CA coordinates. Open-Meteo needs no API key, good for MicroPython.
CUPERTINO_LAT = 37.3230
CUPERTINO_LON = -122.0322
WEATHER_URL = (
    "https://api.open-meteo.com/v1/forecast"
    "?latitude={lat}&longitude={lon}"
    "&current=temperature_2m&temperature_unit=fahrenheit"
).format(lat=CUPERTINO_LAT, lon=CUPERTINO_LON)
# TIME API
# The API returns hour and minute directly for the Cupertino timezone.
TIME_API_URL = "https://timeapi.io/api/time/current/zone?timeZone=America%2FLos_Angeles"
# -
# The temperature digits are shown on the SAME physical 0-12 dial the clock
# hand uses: 0/12 sit at 0 degrees, and each mark is 15 degrees apart
# (matching set_servo_angle's hour_12 * 15), so 6 sits at 90 degrees.
# Digit d points to angle d * 15; 10 doubles as a separator shown between
# digits (at the "10 o'clock" mark).
DIGIT_UNIT_DEGREES = 15
SEPARATOR_VALUE = 10
DIGIT_HOLD_MS = 1000
SEPARATOR_HOLD_MS = 500

TEMP_BUTTON_PIN = 34        # press: show current temperature on demand, then resume clock
TIME_TEST_BUTTON_PIN = 35   # press: type in a time, servo previews it, then resumes clock

BUTTON_DEBOUNCE_MS = 300
servo = PWM(Pin(SERVO_PIN), freq=50)
lights = neopixel.NeoPixel(Pin(NEOPIXEL_PIN), NUM_PIXELS)

temp_button = Pin(TEMP_BUTTON_PIN, Pin.IN)
time_test_button = Pin(TIME_TEST_BUTTON_PIN, Pin.IN)

# Button interrupts only set flags for the main loop.
temp_button_pressed = False
time_test_button_pressed = False
_last_temp_press_ms = 0
_last_time_test_press_ms = 0

def _temp_button_irq(pin):
    global temp_button_pressed, _last_temp_press_ms
    now = time.ticks_ms()
    if time.ticks_diff(now, _last_temp_press_ms) > BUTTON_DEBOUNCE_MS:
        temp_button_pressed = True
        _last_temp_press_ms = now

def _time_test_button_irq(pin):
    global time_test_button_pressed, _last_time_test_press_ms
    now = time.ticks_ms()
    if time.ticks_diff(now, _last_time_test_press_ms) > BUTTON_DEBOUNCE_MS:
        time_test_button_pressed = True
        _last_time_test_press_ms = now

temp_button.irq(trigger=Pin.IRQ_RISING, handler=_temp_button_irq)
time_test_button.irq(trigger=Pin.IRQ_RISING, handler=_time_test_button_irq)

# Keep track of the last logical servo angle.
_current_logical_angle = 0.0

def angle_to_duty(angle):
    # Correct for the dial being mounted 30 minutes ahead of true.
    angle = angle - CALIBRATION_OFFSET_DEGREES
    angle = max(0, min(180, angle))
    return int(SERVO_MAX_DUTY - (SERVO_MAX_DUTY - SERVO_MIN_DUTY) * angle / 180)

def write_servo_angle(angle):
    """Single choke point for actually commanding the servo. Every
    caller must go through this (never call servo.duty_u16() directly)
    so _current_logical_angle always reflects reality."""
    global _current_logical_angle
    servo.duty_u16(angle_to_duty(angle))
    _current_logical_angle = angle

def get_time_from_api():
    """Fetch the current hour/minute from timeapi.io as JSON. Returns
    (hour, minute) on success, or None if WiFi/urequests/the request
    itself isn't available so the caller can fall back to manual entry."""
    if requests is None:
        print("urequests not available, can't fetch time from API.")
        return None
    try:
        resp = requests.get(TIME_API_URL)
        data = ujson.loads(resp.text)
        resp.close()
        return data["hour"], data["minute"]
    except Exception as e:
        print("Time API fetch failed:", e)
        return None

def get_start_time_manual():
    print("Enter the current time to start the clock.")
    hour = int(input("Current hour (0-23): "))
    minute = int(input("Current minute (0-59): "))
    return hour, minute

def get_start_time():
    """Try the JSON time API first (this is the 'grab time from a date
    API' path); fall back to manual entry if that fails for any reason."""
    result = get_time_from_api()
    if result is not None:
        hour, minute = result
        print("Got time from API: {:02d}:{:02d}".format(hour, minute))
        return hour, minute
    print("Falling back to manual time entry.")
    return get_start_time_manual()

def set_servo_angle(hour, minute):
    hour_12 = hour % 12
    angle = hour_12 * 15 + minute * 0.25   # 180 degrees split across 12 hours
    write_servo_angle(angle)
    return angle

def set_lights(hour):
    color = AM_COLOR if hour < 12 else PM_COLOR
    lights[0] = color
    lights[1] = color
    lights.write()

# WiFi + weather (only used for the periodic temperature check)

def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("Connecting to WiFi...")
        wlan.connect(SSID, PASSWORD)
        while not wlan.isconnected():
            time.sleep(0.5)
    print("Connected! IP address:", wlan.ifconfig()[0])
    return wlan

def get_cupertino_temperature():
    if requests is None:
        print("urequests not available, skipping fetch.")
        return None
    try:
        resp = requests.get(WEATHER_URL)
        data = ujson.loads(resp.text)
        resp.close()
        return data["current"]["temperature_2m"]
    except Exception as e:
        print("Weather fetch failed:", e)
        return None

# Temperature display

def move_to_position(position):
    """Move the servo directly to a dial position (0-10) in one command,
    then wait for it to physically finish arriving."""
    target_angle = position * DIGIT_UNIT_DEGREES
    distance = abs(target_angle - _current_logical_angle)
    write_servo_angle(target_angle)
    settle_ms = SERVO_SETTLE_BASE_MS + int(distance * SERVO_SETTLE_MS_PER_DEGREE)
    time.sleep_ms(settle_ms)

def display_number(value):
    """Point to each digit of value in turn, separated by the '10' marker."""
    digits = str(int(round(value)))
    print("Displaying temperature:", digits)
    for i, ch in enumerate(digits):
        if not ch.isdigit():
            continue  # skip a leading '-' on negative temps
        if i > 0:
            move_to_position(SEPARATOR_VALUE)
            time.sleep_ms(SEPARATOR_HOLD_MS)
        move_to_position(int(ch))
        time.sleep_ms(DIGIT_HOLD_MS)

def show_cupertino_temperature():
    connect_wifi()
    temp_f = get_cupertino_temperature()
    if temp_f is not None:
        display_number(temp_f)
    else:
        print("No temperature reading this cycle.")

def test_time_on_servo(hold_seconds=3):
    """D35: let the user type in a time and preview it on the servo.
    Does not change the real clock — the next loop iteration snaps the
    servo back to the actual current time."""
    print("Enter a test time to preview on the servo.")
    try:
        hour = int(input("Test hour (0-23): "))
        minute = int(input("Test minute (0-59): "))
    except ValueError:
        print("Invalid input, skipping time test.")
        return
    angle = set_servo_angle(hour, minute)
    print("Previewing {:02d}:{:02d} -> angle {:.1f}".format(hour, minute, angle))
    time.sleep(hold_seconds)
# -
# Main
# -
def main():
    global temp_button_pressed, time_test_button_pressed

    # Connect to WiFi right away on boot, rather than waiting for the first temperature check 
    connect_wifi()

    start_hour, start_minute = get_start_time()
    start_time = time.time()
    last_temp_trigger_minute = None  # tracks which :00/:30 mark that has occured.

    while True:
        elapsed_minutes = (time.time() - start_time) / 60
        total_minutes = start_hour * 60 + start_minute + elapsed_minutes
        hour = int(total_minutes // 60) % 24
        minute = int(total_minutes % 60)

        angle = set_servo_angle(hour, minute)
        set_lights(hour)

        print("Time: {:02d}:{:02d}  Angle: {:.1f}".format(hour, minute, angle))

        # Show the temperature whenever the DISPLAYED clock hits :00 or :30,
        if minute in (0, 30) and minute != last_temp_trigger_minute:
            show_cupertino_temperature()
            last_temp_trigger_minute = minute
        elif minute not in (0, 30):
            last_temp_trigger_minute = None

        # Sleep in short chunks instead of one long time.sleep(), so a button
        # press during this window is caught right away instead of waiting
        # for the next full clock update.
        slept_ms = 0
        chunk_ms = 200
        while slept_ms < UPDATE_INTERVAL * 1000:
            if temp_button_pressed:
                temp_button_pressed = False
                print("D34 pressed: showing current temperature on demand.")
                show_cupertino_temperature()
                # Clock resumes automatically on the next while-True iteration.
                break

            if time_test_button_pressed:
                time_test_button_pressed = False
                print("D35 pressed: entering time test mode.")
                test_time_on_servo()
                break

            time.sleep_ms(chunk_ms)
            slept_ms += chunk_ms

main()