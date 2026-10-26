from machine import I2C, Pin, ADC, PWM
from time import sleep_ms, ticks_ms, ticks_diff
from math import sqrt, sin, pi
import struct
import neopixel

# SETTINGS
TEST_MODE = True            # True: intervals are in SECONDS. False: real MINUTES.
INTERVALS = [15, 30, 45, 60]
START_IDX = 1
REBARK_MS = 15000
UNIT_MS = 1000 if TEST_MODE else 60000
MAX_MS = max(INTERVALS) * UNIT_MS
DEBUG = True                # print each classified window

# Milo's voice
PITCH = 0.5                 # scales barks, beeps, and the happy tune
WHINE_PITCH = 1.0           # scales the whine only (0.8 lower, 1.2 higher)
VOLUME = 32768

# pins
SERVO_PIN = 18
BUZZER_PIN = 23
NP_PIN = 15
NUM_LEDS = 2
# accelerometer I2C: SDA 21, SCL 22 | joystick: X 32, Y 33

# servo (tail)
TAIL_MIN = 0
TAIL_MAX = 180
WAG_CENTER = 90             # every wag swings around this angle and ends on it
WAG_HOLD_MS = 400           # pause at 90 before the gauge takes over again

# accelerometer / KNN
ADDR = 0x19
SCALE = 0.002
SAMPLE_MS = 20              # must match the data collection script
WINDOW_SAMPLES = 25         # 0.5 s windows, same as collection
K = 5
SETTLE_MS = 600             # ignore motion right after Milo moves or makes sound
WHINE_GAP_MS = 3000         # minimum time between whines

# joystick (measured)
CENTER_X, CENTER_Y = 30850, 31250
DEADZONE = 10000
CLICK_PEAK = 57000

# HARDWARE SETUP
servo = PWM(Pin(SERVO_PIN), freq=50)
buzzer = PWM(Pin(BUZZER_PIN))
buzzer.duty_u16(0)
np = neopixel.NeoPixel(Pin(NP_PIN), NUM_LEDS)

i2c = I2C(0, scl=Pin(22), sda=Pin(21), freq=400000)
i2c.writeto_mem(ADDR, 0x20, bytes([0x57]))
i2c.writeto_mem(ADDR, 0x23, bytes([0x98]))
sleep_ms(10)

adc_x = ADC(Pin(32)); adc_x.atten(ADC.ATTN_11DB)
adc_y = ADC(Pin(33)); adc_y.atten(ADC.ATTN_11DB)

# MOTION WINDOW
xs, ys, zs = [], [], []
quiet_until = 0

def flush():
    # drop the partial window and ignore motion briefly
    # (called after Milo makes his own vibration: tones, wags, big tail moves)
    global quiet_until
    xs.clear(); ys.clear(); zs.clear()
    quiet_until = ticks_ms() + SETTLE_MS

# OUTPUT HELPERS
def set_angle(angle):
    angle = max(0, min(180, angle))
    pulse_ms = 0.5 + (angle / 180) * 2.0
    servo.duty_u16(int(pulse_ms / 20 * 65535))

def tone(freq, ms):
    buzzer.freq(max(100, int(freq * PITCH)))
    buzzer.duty_u16(VOLUME)
    sleep_ms(ms)
    buzzer.duty_u16(0)
    flush()

def glide(f0, f1, ms, vib_hz=0, vib_depth=0, fade=False):
    # smooth pitch slide from f0 to f1 with optional vibrato (wobble)
    # fade True lowers the volume toward the end, like a whine trailing off
    f0 *= WHINE_PITCH
    f1 *= WHINE_PITCH
    vib_depth *= WHINE_PITCH
    step = 10
    t = 0
    while t < ms:
        frac = t / ms
        f = f0 + (f1 - f0) * frac
        if vib_hz:
            f += vib_depth * sin(2 * pi * vib_hz * t / 1000)
        buzzer.freq(max(100, int(f)))
        duty = VOLUME
        if fade and frac > 0.6:
            duty = int(VOLUME * (1 - (frac - 0.6) / 0.4 * 0.7))
        buzzer.duty_u16(duty)
        sleep_ms(step)
        t += step
    buzzer.duty_u16(0)

def bark():
    for f in range(1800, 600, -150):
        tone(f, 25)

def double_bark():
    bark(); sleep_ms(120); bark()

def happy_tune():
    for f, ms in ((1047, 100), (1319, 100), (1568, 100), (2093, 200)):
        tone(f, ms)
        sleep_ms(30)

def whine():
    # "hnnn yiiip... hnnn": rises with a shaky wobble, hangs, then sags and fades
    glide(550, 950, 350, vib_hz=7, vib_depth=15)               # rising
    glide(950, 1000, 250, vib_hz=9, vib_depth=40)              # held, trembling
    glide(1000, 650, 450, vib_hz=8, vib_depth=30, fade=True)   # sagging down
    sleep_ms(180)
    glide(500, 800, 250, vib_hz=7, vib_depth=15)               # second, smaller whine
    glide(800, 480, 400, vib_hz=8, vib_depth=25, fade=True)
    flush()

def color(r, g, b):
    for i in range(NUM_LEDS):
        np[i] = (r, g, b)
    np.write()

BLUE = (0, 0, 40)
GREEN = (0, 40, 0)
YELLOW = (40, 30, 0)
RED = (60, 0, 0)
PURPLE = (30, 0, 40)
RAINBOW = [(60, 0, 0), (60, 30, 0), (0, 60, 0), (0, 0, 60)]

# tail as a progress gauge
def setting_angle():
    return TAIL_MIN + INTERVALS[idx] * UNIT_MS * (TAIL_MAX - TAIL_MIN) // MAX_MS

def progress_angle(remaining):
    total = INTERVALS[idx] * UNIT_MS
    remaining = max(0, min(remaining, total))
    elapsed = total - remaining
    return TAIL_MIN + elapsed * (TAIL_MAX - TAIL_MIN) // total

def wag(times, amplitude, speed_ms, rest_angle=None):
    # rest_angle is ignored: every wag is centered on WAG_CENTER and ends there
    for i in range(times):
        set_angle(WAG_CENTER - amplitude)
        np[0] = RAINBOW[i % 4]
        np[1] = RAINBOW[(i + 2) % 4]
        np.write()
        sleep_ms(speed_ms)
        set_angle(WAG_CENTER + amplitude)
        sleep_ms(speed_ms)
    set_angle(WAG_CENTER)
    sleep_ms(WAG_HOLD_MS)
    flush()

# ACCELEROMETER
def read_accel():
    d = i2c.readfrom_mem(ADDR, 0x28 | 0x80, 6)
    x, y, z = struct.unpack('<hhh', d)
    return (x >> 4) * SCALE, (y >> 4) * SCALE, (z >> 4) * SCALE

def features(xs, ys, zs):
    # same three features as the data collection script
    n = len(xs)
    mags = [sqrt(xs[i] ** 2 + ys[i] ** 2 + zs[i] ** 2) for i in range(n)]
    mean = sum(mags) / n
    std = sqrt(sum((m - mean) ** 2 for m in mags) / n)
    return (std, max(mags) - min(mags), sum(zs) / n)

# KNN CLASSIFIER
def load_training():
    rows = []
    with open("data.csv") as f:
        for line in f:
            p = line.strip().split(",")
            if len(p) == 4:
                rows.append((p[0], (float(p[1]), float(p[2]), float(p[3]))))
    return rows

try:
    _rows = load_training()
except OSError:
    print("No data.csv found. Run the data collection script first.")
    raise

LO = [min(r[1][i] for r in _rows) for i in range(3)]
SPAN = [max(max(r[1][i] for r in _rows) - LO[i], 1e-6) for i in range(3)]

def norm(v):
    return [(v[i] - LO[i]) / SPAN[i] for i in range(3)]

TRAIN = [(label, norm(v)) for label, v in _rows]
print("KNN loaded:", len(TRAIN), "training rows")

def classify(feat):
    v = norm(feat)
    d = []
    for label, u in TRAIN:
        d.append(((v[0] - u[0]) ** 2 + (v[1] - u[1]) ** 2 + (v[2] - u[2]) ** 2, label))
    d.sort()
    votes = {}
    for _, label in d[:K]:
        votes[label] = votes.get(label, 0) + 1
    return max(votes, key=votes.get)

# JOYSTICK
x_active = False
peak_x = 0
last_y_dir = "CENTER"

def poll():
    global x_active, peak_x, last_y_dir
    x = adc_x.read_u16()
    y = adc_y.read_u16()
    dx = x - CENTER_X
    dy = y - CENTER_Y
    event = None

    if abs(dy) > DEADZONE and abs(dy) > abs(dx):
        d = "LEFT" if dy > 0 else "RIGHT"
        if d != last_y_dir:
            event = d
            last_y_dir = d
    elif abs(dy) < DEADZONE:
        last_y_dir = "CENTER"

    if abs(dx) > DEADZONE and abs(dx) > abs(dy):
        if not x_active:
            x_active = True
            peak_x = x
        elif abs(dx) > abs(peak_x - CENTER_X):
            peak_x = x
    elif x_active and abs(dx) < DEADZONE:
        x_active = False
        if peak_x >= CLICK_PEAK:
            event = "CLICK"
        elif peak_x > CENTER_X:
            event = "UP"
        else:
            event = "DOWN"
    return event

# MILO'S STATE MACHINE
IDLE, RUNNING, ALERTING = 0, 1, 2

state = IDLE
idx = START_IDX
deadline = 0
last_bark = 0
last_whine = 0
last_color = None
last_angle = None

def set_color_once(c):
    global last_color
    if c != last_color:
        color(*c)
        last_color = c

def set_tail_once(a):
    global last_angle
    if a != last_angle:
        big_move = last_angle is None or abs(a - last_angle) > 15
        set_angle(a)
        last_angle = a
        if big_move:
            flush()      # a big servo swing shakes the box; don't read it as motion

def start_timer():
    global state, deadline
    deadline = ticks_ms() + INTERVALS[idx] * UNIT_MS
    state = RUNNING

def after_wag():
    global last_color, last_angle
    last_color = None    # redraw mood color
    last_angle = None    # redraw tail position (gauge takes over again)
    flush()

print("Milo is awake! Interval:", INTERVALS[idx])
set_tail_once(setting_angle())
set_color_once(BLUE)
tone(1500, 100)
last_sample = ticks_ms()

while True:
    t0 = ticks_ms()
    now = t0

    # sample accelerometer; classify once per full window
    if ticks_diff(t0, last_sample) > 5 * SAMPLE_MS:
        flush()          # we were busy, so the window has a gap
    last_sample = t0

    x, y, z = read_accel()
    xs.append(x); ys.append(y); zs.append(z)

    motion = None
    if len(xs) >= WINDOW_SAMPLES:
        feat = features(xs, ys, zs)
        xs.clear(); ys.clear(); zs.clear()
        if ticks_diff(t0, quiet_until) >= 0:
            motion = classify(feat)
            if DEBUG:
                print(motion, "std=%.3f range=%.3f z=%.2f" % feat)

    shake = (motion == "shake")
    e = poll()

    # tilt makes Milo whine (any state)
    if motion == "tilt" and ticks_diff(now, last_whine) >= WHINE_GAP_MS:
        color(*PURPLE)
        whine()
        last_whine = ticks_ms()
        after_wag()
        print("Milo whines (tilted)")

    # timer logic
    if state == IDLE:
        set_color_once(BLUE)
        set_tail_once(setting_angle())
        if e == "LEFT" and idx > 0:
            idx -= 1
            tone(800, 60)
            print("Interval:", INTERVALS[idx])
        elif e == "RIGHT" and idx < len(INTERVALS) - 1:
            idx += 1
            tone(1200, 60)
            print("Interval:", INTERVALS[idx])
        elif e == "CLICK":
            start_timer()
            happy_tune()
            print("Timer started:", INTERVALS[idx])
        elif shake:
            wag(6, 20, 100)
            after_wag()

    elif state == RUNNING:
        remaining = ticks_diff(deadline, now)
        set_tail_once(progress_angle(remaining))

        if remaining < INTERVALS[idx] * UNIT_MS // 10:
            set_color_once(YELLOW)
        else:
            set_color_once(GREEN)

        if e == "CLICK":
            state = IDLE
            tone(500, 200)
            after_wag()
            print("Timer cancelled")
        elif shake:
            wag(6, 20, 100)
            after_wag()
        elif remaining <= 0:
            state = ALERTING
            last_bark = now
            set_color_once(RED)
            set_tail_once(TAIL_MAX)
            double_bark()
            print("Time's up! Shake Milo!")

    elif state == ALERTING:
        set_color_once(RED)
        set_tail_once(TAIL_MAX)
        if shake:
            happy_tune()
            wag(10, 25, 100)
            after_wag()
            print("Confirmed. Timer restarted.")
            start_timer()
        elif ticks_diff(now, last_bark) >= REBARK_MS:
            last_bark = now
            double_bark()
            after_wag()

    sleep_ms(max(1, SAMPLE_MS - ticks_diff(ticks_ms(), t0)))