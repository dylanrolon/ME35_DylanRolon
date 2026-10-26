# Milo Data
from machine import I2C, Pin, ADC, PWM
from time import sleep_ms, ticks_ms, ticks_diff
from math import sqrt
import struct
import neopixel

# ---------- pins ----------
SERVO_PIN, BUZZER_PIN, NP_PIN, NUM_LEDS = 18, 23, 15, 2
ADDR, SCALE = 0x19, 0.002
CENTER_X, CENTER_Y, DEADZONE, CLICK_PEAK = 30850, 31250, 10000, 57000

# ---------- recording settings ----------
# (menu name, label saved, tail wags during recording?)
MENU = [
    ("still",          "still", False),
    ("shake",          "shake", False),
    ("tilt",           "tilt",  False),
    ("still + tail wag", "still", True),   # teaches KNN: tail vibration = nothing
]
MENU_COLORS = [(0, 0, 40), (60, 0, 0), (40, 30, 0), (0, 40, 40)]

SAMPLE_MS = 20          # ~50 Hz
WINDOW_SAMPLES = 25     # 0.5 s per window
RECORD_MS = 3000        # 6 rows per recording
FILE = "data.csv"

# ---------- hardware ----------
servo = PWM(Pin(SERVO_PIN), freq=50)
buzzer = PWM(Pin(BUZZER_PIN)); buzzer.duty_u16(0)
np = neopixel.NeoPixel(Pin(NP_PIN), NUM_LEDS)
i2c = I2C(0, scl=Pin(22), sda=Pin(21), freq=400000)
i2c.writeto_mem(ADDR, 0x20, bytes([0x57]))
i2c.writeto_mem(ADDR, 0x23, bytes([0x98]))
adc_x = ADC(Pin(32)); adc_x.atten(ADC.ATTN_11DB)
adc_y = ADC(Pin(33)); adc_y.atten(ADC.ATTN_11DB)
sleep_ms(10)

def set_angle(a):
    a = max(0, min(180, a))
    servo.duty_u16(int((0.5 + a / 180 * 2.0) / 20 * 65535))

def tone(f, ms):
    buzzer.freq(f); buzzer.duty_u16(32768)
    sleep_ms(ms); buzzer.duty_u16(0)

def color(c):
    for i in range(NUM_LEDS):
        np[i] = c
    np.write()

def read_accel():
    d = i2c.readfrom_mem(ADDR, 0x28 | 0x80, 6)
    x, y, z = struct.unpack('<hhh', d)
    return (x >> 4) * SCALE, (y >> 4) * SCALE, (z >> 4) * SCALE

# ---------- joystick events ----------
x_active, peak_x, last_y_dir = False, 0, "CENTER"

def poll():
    global x_active, peak_x, last_y_dir
    x, y = adc_x.read_u16(), adc_y.read_u16()
    dx, dy = x - CENTER_X, y - CENTER_Y
    event = None
    if abs(dy) > DEADZONE and abs(dy) > abs(dx):
        d = "LEFT" if dy > 0 else "RIGHT"
        if d != last_y_dir:
            event = d; last_y_dir = d
    elif abs(dy) < DEADZONE:
        last_y_dir = "CENTER"
    if abs(dx) > DEADZONE and abs(dx) > abs(dy):
        if not x_active:
            x_active = True; peak_x = x
        elif abs(dx) > abs(peak_x - CENTER_X):
            peak_x = x
    elif x_active and abs(dx) < DEADZONE:
        x_active = False
        if peak_x >= CLICK_PEAK: event = "CLICK"
        elif peak_x > CENTER_X: event = "UP"
        else: event = "DOWN"
    return event

# ---------- features: std, range, mean z ----------
def features(xs, ys, zs):
    n = len(xs)
    mags = [sqrt(xs[i]**2 + ys[i]**2 + zs[i]**2) for i in range(n)]
    mean = sum(mags) / n
    std = sqrt(sum((m - mean) ** 2 for m in mags) / n)
    mag_range = max(mags) - min(mags)
    mean_z = sum(zs) / n
    return (std, mag_range, mean_z)

# ---------- recording ----------
def record(label, wagging):
    print("Recording:", label, "(with tail wag)" if wagging else "")
    xs, ys, zs = [], [], []
    rows = 0
    start = last_wag = ticks_ms()
    wag_side = False
    f = open(FILE, "a")
    while ticks_diff(ticks_ms(), start) < RECORD_MS:
        t0 = ticks_ms()
        if wagging and ticks_diff(t0, last_wag) >= 100:
            last_wag = t0
            wag_side = not wag_side
            set_angle(65 if wag_side else 115)
        x, y, z = read_accel()
        xs.append(x); ys.append(y); zs.append(z)
        if len(xs) == WINDOW_SAMPLES:
            s, r, mz = features(xs, ys, zs)
            line = "%s,%.4f,%.4f,%.4f" % (label, s, r, mz)
            f.write(line + "\n")
            print(line)
            rows += 1
            xs, ys, zs = [], [], []
        sleep_ms(max(1, SAMPLE_MS - ticks_diff(ticks_ms(), t0)))
    f.close()
    set_angle(90)
    tone(1500, 150)
    print("Saved %d rows" % rows)

def dump():
    print("----- %s -----" % FILE)
    try:
        with open(FILE) as f:
            for line in f:
                print(line.strip())
    except OSError:
        print("(no data yet)")
    print("----- end -----")

# ---------- main ----------
sel = 0
set_angle(90)
color(MENU_COLORS[sel])
print("LEFT/RIGHT = pick | CLICK = record | DOWN = print file")
print("Selected:", MENU[sel][0])

while True:
    e = poll()
    if e in ("LEFT", "RIGHT"):
        sel = (sel + (1 if e == "RIGHT" else -1)) % len(MENU)
        color(MENU_COLORS[sel])
        print("Selected:", MENU[sel][0])
        for _ in range(sel + 1):
            tone(1000, 60); sleep_ms(80)
    elif e == "CLICK":
        name, label, wagging = MENU[sel]
        print("Get ready:", name, "(2 seconds)")
        sleep_ms(2000)
        tone(2000, 200)
        record(label, wagging)
    elif e == "DOWN":
        dump()
    sleep_ms(10)