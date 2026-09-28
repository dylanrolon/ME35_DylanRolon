from machine import Pin, SoftI2C, PWM
import time
import math
import veml6040
import neopixel

# ---------------- Hardware setup ----------------
button_Play = Pin(34, Pin.IN, Pin.PULL_UP)
button_Train = Pin(35, Pin.IN, Pin.PULL_UP)

i2c = SoftI2C(scl=Pin(22), sda=Pin(21))
print("I2C devices:", i2c.scan())

sensor = veml6040.VEML6040(i2c)
sensor.trigger_measurement()

SERVO_PIN = 18
SERVO_MIN_DUTY = 1638   # ~0.5ms pulse -> 0 degrees (duty_u16, 50Hz)
SERVO_MAX_DUTY = 8192   # ~2.5ms pulse -> 180 degrees
servo = PWM(Pin(SERVO_PIN), freq=50)
current_servo_angle = 90  # assume it starts near neutral

NEOPIXEL_PIN = 15
NUM_PIXELS = 2
lights = neopixel.NeoPixel(Pin(NEOPIXEL_PIN), NUM_PIXELS)

LIGHT_COLORS = {
    "red": (20, 0, 0),
    "blue": (0, 0, 20),
}
LIGHT_OFF = (0, 0, 0)


def set_lights(rgb):
    for i in range(NUM_PIXELS):
        lights[i] = rgb
    lights.write()


def light_up(label, duration_ms=500):
    """Light both pixels the class color, hold, then turn them off."""
    color = LIGHT_COLORS.get(label, LIGHT_OFF)
    set_lights(color)
    if duration_ms:
        time.sleep_ms(duration_ms)
        set_lights(LIGHT_OFF)

# ---------------- Servo helpers ----------------
def angle_to_duty(angle):
    angle = max(0, min(180, angle))
    return int(SERVO_MIN_DUTY + (SERVO_MAX_DUTY - SERVO_MIN_DUTY) * angle / 180)


def servo_move_to(target_angle):
    """Jump the servo directly to target_angle as fast as it can move."""
    global current_servo_angle
    servo.duty_u16(angle_to_duty(target_angle))
    current_servo_angle = target_angle


def sort_for_class(label):
    if label == "red":
        servo_move_to(135)
    elif label == "blue":
        servo_move_to(45)
    else:
        print("Unknown class, not moving servo:", label)
        return
    light_up(label, 500)     # flash the matching color while the object drops/passes
    servo_move_to(90)        # return to neutral, ready for next item


# ---------------- Button handling (IRQ = flags only) ----------------
DEBOUNCE_MS = 200
last_train_press = 0
last_play_press = 0

play_flag = False
start_training_flag = False


def playButton(p):
    global play_flag, last_play_press
    now = time.ticks_ms()
    if time.ticks_diff(now, last_play_press) < DEBOUNCE_MS:
        return
    last_play_press = now
    play_flag = True


def trainButton(p):
    global start_training_flag, last_train_press
    now = time.ticks_ms()
    if time.ticks_diff(now, last_train_press) < DEBOUNCE_MS:
        return
    last_train_press = now
    start_training_flag = True


button_Train.irq(trigger=Pin.IRQ_RISING, handler=trainButton)
button_Play.irq(trigger=Pin.IRQ_RISING, handler=playButton)

# ---------------- Training burst settings ----------------
TRAIN_LABELS = ["red", "blue"]   # 1st press = red, 2nd = blue, then cycles
SAMPLE_INTERVAL_MS = 100
TRAIN_DURATION_MS = 2000

train_label_index = 0
training_active = False
training_start_time = 0
last_sample_time = 0
current_label = ""

# ---------------- Dataset ----------------
data = []  # list of (red, green, blue, label)


def k_nearest_neighbor(x, y, z, k=1):
    distances = []
    for d in data:
        dist = math.sqrt((x - d[0]) ** 2 + (y - d[1]) ** 2 + (z - d[2]) ** 2)
        distances.append([dist, d[3]])

    distances.sort(key=lambda item: item[0])
    distances = distances[:k]
    classes = [dist[1] for dist in distances]
    print("k classes", classes)
    most_common = max(set(classes), key=classes.count)
    print("max class:", most_common)
    return most_common


# ---------------- Main loop ----------------
while True:
    now = time.ticks_ms()

    # --- Start a new training burst if requested and not already running ---
    if start_training_flag and not training_active:
        start_training_flag = False
        if len(data) == 0 or True:  # always allowed to (re)train
            training_active = True
            training_start_time = now
            last_sample_time = now
            current_label = TRAIN_LABELS[train_label_index]
            print("Starting training burst for:", current_label)

    # --- Collect samples during an active training burst ---
    if training_active:
        if time.ticks_diff(now, last_sample_time) >= SAMPLE_INTERVAL_MS:
            last_sample_time = now
            red, green, blue, white = sensor.read_rgbw()
            data.append((red, green, blue, current_label))
            print("sample:", red, green, blue, "->", current_label)

        if time.ticks_diff(now, training_start_time) >= TRAIN_DURATION_MS:
            training_active = False
            print("Finished training burst for:", current_label,
                  "| total samples so far:", len(data))
            train_label_index = (train_label_index + 1) % len(TRAIN_LABELS)

    # --- Play / classify + sort ---
    if play_flag:
        play_flag = False
        if len(data) == 0:
            print("No training data yet, skipping classification.")
        else:
            red, green, blue, white = sensor.read_rgbw()
            what_class = k_nearest_neighbor(red, green, blue, k=3)
            print("Classified as:", what_class)
            sort_for_class(what_class)

    time.sleep_ms(20)  # small idle delay so the loop isn't pegged at 100%