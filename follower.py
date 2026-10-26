# FOLLOWER ESP32: moves ONLY when an Onshape mate value changes
# (i.e. when the controller's encoders move). Nothing moves at boot.
from machine import Pin, PWM
from time import sleep, sleep_ms
import network, ujson, ubinascii, math
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
MATE_OFFSET_DEG = (270, 0)   # must match the controller: Onshape angle = sign * servo angle + offset
MATE_SIGN = (1, -1)          # must match the controller
POLL_MS = 300
DEADBAND_DEG = 1.0           # ignore changes smaller than this
STEP_DEG = 3                 # servo moves in steps this big until it reaches the new target

URL = "https://cad.onshape.com/api/v10/assemblies/d/{}/w/{}/e/{}/matevalues".format(DID, WID, EID)
AUTH = "Basic " + ubinascii.b2a_base64("{}:{}".format(ACCESS_KEY, SECRET_KEY).encode()).decode().strip()
HEADERS = {"Authorization": AUTH, "Accept": "application/json"}


class Servo:
    """PWM is only started on the first move, so the servo stays limp/still at boot."""
    def __init__(self, pin, min_us=500, max_us=2500):
        self.pin, self.pwm = pin, None
        self.min_us, self.max_us = min_us, max_us

    def angle(self, deg):
        if self.pwm is None:
            self.pwm = PWM(Pin(self.pin), freq=50)
        deg = max(0, min(180, deg))
        us = self.min_us + (self.max_us - self.min_us) * deg / 180
        self.pwm.duty_u16(int(us / 20000 * 65535))


servos = [Servo(4), Servo(5)]
position = [None, None]      # where each servo currently is (None = not moved yet)
last_seen = [None, None]     # last Onshape target we saw


def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("Connecting to WiFi...")
        wlan.connect(SSID, PASSWORD)
        while not wlan.isconnected():
            sleep(0.5)
    print("Connected:", wlan.ifconfig()[0])


def get_targets():
    """Servo-angle targets (0..180) for each mate, or None on failure."""
    try:
        r = requests.get(URL, headers=HEADERS)
        if r.status_code != 200:
            print("GET failed:", r.status_code, r.text[:200])
            r.close()
            return None
        data = ujson.loads(r.text)
        r.close()
        by_name = {m["mateName"]: m for m in data["mateValues"]}
        out = []
        for name, off, sgn in zip(MATE_NAMES, MATE_OFFSET_DEG, MATE_SIGN):
            deg = math.degrees(by_name[name].get("rotationZ", 0))
            out.append(min(180, (sgn * (deg - off)) % 360))
        return out
    except Exception as e:
        print("GET error:", e)
        return None


def move_to(i, target):
    """Glide servo i to target in small steps, then stop sending commands."""
    cur = position[i] if position[i] is not None else target
    while abs(target - cur) > STEP_DEG:
        cur += STEP_DEG if target > cur else -STEP_DEG
        servos[i].angle(cur)
        sleep_ms(15)
    servos[i].angle(target)
    position[i] = target


connect_wifi()
while True:
    targets = get_targets()
    if targets:
        for i, t in enumerate(targets):
            if last_seen[i] is None:
                last_seen[i] = t          # first reading = baseline only, no movement
                print("Baseline", MATE_NAMES[i], "{:.1f}".format(t))
            elif abs(t - last_seen[i]) >= DEADBAND_DEG:
                last_seen[i] = t
                print("Moving", MATE_NAMES[i], "->", "{:.1f}".format(t))
                move_to(i, t)
    sleep_ms(POLL_MS)