# CONTROLLER ESP32: encoders -> servos move IMMEDIATELY.
# A background thread sends the latest angles to Onshape; it never blocks the servos.
from machine import Pin, PWM
from time import sleep_ms, sleep
import network, ujson, ubinascii, math, _thread
import urequests as requests

# ---------- CONFIG ----------
SSID = "tufts_eecs"
PASSWORD = "foundedin1883"

ACCESS_KEY = "on_fgONQsYFFrSzMZi5hZ2vt"
SECRET_KEY = "KCjvuuiibq92ZsdDzqscCYaEYkMWqVhptRS6ZE5SnIPWn474"

# From the assembly tab URL: cad.onshape.com/documents/<DID>/w/<WID>/e/<EID>
DID = "6a7f51e191a2177f3e4d21bc"
WID = "8c9532c0822f87a540b45a77"
EID = "355ef89134bd64ad749524db"

MATE_NAMES = ("Servo 1", "Servo 2")

# Onshape angle = sign * servo angle + offset (degrees, wrapped to -180..180).
# Servo 1: servo 0 shows as 270 in Onshape -> offset 270 (same as -90).
# Servo 2: no offset.
MATE_OFFSET_DEG = (270, 0)
# Direction: 1 = same, -1 = mirrored. Onshape angle = sign * servo + offset.
MATE_SIGN = (1, -1)

MIN_CHANGE_DEG = 1.0     # don't POST for changes smaller than this
POST_PAUSE_MS = 50       # breather between POSTs

URL = "https://cad.onshape.com/api/v10/assemblies/d/{}/w/{}/e/{}/matevalues".format(DID, WID, EID)
AUTH = "Basic " + ubinascii.b2a_base64("{}:{}".format(ACCESS_KEY, SECRET_KEY).encode()).decode().strip()
HEADERS = {"Authorization": AUTH, "Content-Type": "application/json", "Accept": "application/json"}
USE_FULL_BODY = False    # True: send every mate back (use if the 2-mate POST gets a 400)


# ---------- HARDWARE ----------
class Count:
    def __init__(self, A, B, pull=None):
        self.A = Pin(A, Pin.IN, pull)
        self.B = Pin(B, Pin.IN, pull)
        self.counter = 0
        self.A.irq(self.cb, Pin.IRQ_FALLING | Pin.IRQ_RISING)
        self.B.irq(self.cb, Pin.IRQ_FALLING | Pin.IRQ_RISING)

    def cb(self, pin):
        other, inc = (self.B, 1) if pin == self.A else (self.A, -1)
        self.counter += -inc if pin.value() != other.value() else inc


class Servo:
    def __init__(self, pin, min_us=500, max_us=2500):
        self.pwm = PWM(Pin(pin), freq=50)
        self.min_us, self.max_us = min_us, max_us

    def angle(self, deg):
        deg = max(0, min(180, deg))
        us = self.min_us + (self.max_us - self.min_us) * deg / 180
        self.pwm.duty_u16(int(us / 20000 * 65535))


class Knob:
    def __init__(self, enc, servo, counts_per_deg=4, start=90, invert=False):
        self.enc, self.servo = enc, servo
        self.cpd = counts_per_deg
        self.sign = -1 if invert else 1
        self.angle = start
        self.last = enc.counter
        servo.angle(start)

    def update(self):
        now = self.enc.counter
        delta = now - self.last
        self.last = now
        if delta:
            self.angle = max(0, min(180, self.angle + self.sign * delta / self.cpd))
            self.servo.angle(self.angle)


knobs = [
    Knob(Count(32, 39), Servo(18)),
    Knob(Count(25, 33), Servo(19)),
]


# ---------- WIFI + ONSHAPE ----------
def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("Connecting to WiFi...")
        wlan.connect(SSID, PASSWORD)
        while not wlan.isconnected():
            sleep(0.5)
    print("Connected:", wlan.ifconfig()[0])


def wrap180(d):
    d = (d + 180) % 360 - 180
    return d


TEMPLATES = {}
ALL_MATES = []


def load_templates():
    global ALL_MATES
    r = requests.get(URL, headers=HEADERS)
    data = ujson.loads(r.text)
    r.close()
    ALL_MATES = data["mateValues"]
    for m in ALL_MATES:
        if m["mateName"] in MATE_NAMES:
            TEMPLATES[m["mateName"]] = m
    for name in MATE_NAMES:
        if name not in TEMPLATES:
            raise RuntimeError("Mate not found in Onshape: " + name)
    print("Found mates:", list(TEMPLATES))


def post_angles(angles_deg):
    for name, a, off, sgn in zip(MATE_NAMES, angles_deg, MATE_OFFSET_DEG, MATE_SIGN):
        TEMPLATES[name]["rotationZ"] = math.radians(wrap180(sgn * a + off))
    mates = ALL_MATES if USE_FULL_BODY else [TEMPLATES[n] for n in MATE_NAMES]
    try:
        r = requests.post(URL, data=ujson.dumps({"mateValues": mates}), headers=HEADERS)
        ok = 200 <= r.status_code < 300
        if not ok:
            print("POST failed:", r.status_code, r.text[:200])
        r.close()
        return ok
    except Exception as e:
        print("POST error:", e)
        return False


def onshape_worker():
    """Runs on its own thread: ships the newest knob angles whenever they've changed."""
    last_sent = [None, None]
    while True:
        current = [k.angle for k in knobs]
        if any(s is None or abs(c - s) >= MIN_CHANGE_DEG for c, s in zip(current, last_sent)):
            if post_angles(current):
                last_sent = current
                print("Posted:", ["{:.1f}".format(a) for a in current])
        sleep_ms(POST_PAUSE_MS)


# ---------- MAIN ----------
connect_wifi()
load_templates()
_thread.stack_size(24 * 1024)       # HTTPS needs a bigger stack than the default
_thread.start_new_thread(onshape_worker, ())

while True:                          # servos follow encoders, nothing else in this loop
    for k in knobs:
        k.update()
    sleep_ms(5)
