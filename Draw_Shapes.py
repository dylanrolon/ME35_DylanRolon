from machine import Pin, PWM
from time import ticks_ms, ticks_diff, ticks_add, sleep_ms

# ======================= SETTINGS =======================
CSV_FILE = "servo_angles.csv"   # copy this file to the ESP32 filesystem (same folder as main.py)

# --- iPhone Live Photo timing ---
# A Live Photo records ~3 s in total: about 1.5 s before and 1.5 s after you press the shutter.
# Every digit is drawn in exactly DIGIT_DRAW_SEC seconds, however long or short the digit is.
# Keep it under 3 s. The smaller it is, the more room you have for timing the shutter, but the faster the servos move.
DIGIT_DRAW_SEC = 2.5
LEAD_MS = 1500           # wait between pressing button 1 and the light starting to draw

# True : the arm parks at the start of each digit (light off) and waits for you to press button 1.
# False: it waits DIGIT_PAUSE_MS by itself between digits (and START_DELAY_MS before the first one).
WAIT_FOR_BUTTON = True
DIGIT_PAUSE_MS = 6000
START_DELAY_MS = 5000

FRAME_MS = 20            # servos read a new position every 20 ms, so drawing runs in 20 ms frames
TRAVEL_DELAY_MS = 20     # pause between steps when moving to a digit's start point (light off)
MAX_STEP_DEG = 1.0       # biggest servo step on those start-point moves; bigger moves are split up

DIGITS_TO_DRAW = None    # None = all digits, or a set such as {1, 2, 3}

# Calibration: servo_deg = (180 - theta if INVERT else theta) + OFFSET
# Adjust these if the drawing is mirrored or shifted on the real arm.
INVERT1, OFFSET1 = False, 0
INVERT2, OFFSET2 = False, 0
# ========================================================


class Count:
    """Quadrature encoder counter using interrupts on both lines."""
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
        self.pwm.duty_u16(int(us / 20000 * 65535))  # 20 ms period at 50 Hz


class Knob:
    """Turns encoder movement into a clamped 0-180 angle (manual jog mode)."""
    def __init__(self, enc, servo, name="Knob", counts_per_deg=4, start=90, invert=False):
        self.enc, self.servo, self.name = enc, servo, name
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
            # Accumulate then clamp, so spinning past the end doesn't "wind up"
            self.angle += self.sign * delta / self.cpd
            self.angle = max(0, min(180, self.angle))
            self.servo.angle(self.angle)
            print("{}: servo angle = {:.1f} deg, encoder = {}".format(self.name, self.angle, now))

    def sync(self, angle):
        """Take over a new angle (e.g. after drawing) and ignore encoder movement during that time."""
        self.angle = angle
        self.last = self.enc.counter


# --- Servo knobs ---
enc1 = Count(32, 39)   # Motor1 encoder -> base servo
enc2 = Count(25, 33)   # Motor2 encoder -> top servo
servo1 = Servo(18)
servo2 = Servo(19)
knob1 = Knob(enc1, servo1, name="Servo 1 (pin 18)", counts_per_deg=4)
knob2 = Knob(enc2, servo2, name="Servo 2 (pin 19)", counts_per_deg=4)

# --- LED (light indicator) + buttons ---
led = Pin(23, Pin.OUT)   # LED on the tip of arm 2: ON = drawing (light painting), OFF = travel moves
btn = Pin(34, Pin.IN)    # START button (input-only: needs external 10k pull-up to 3.3V)
btn2 = Pin(35, Pin.IN)   # STOP button  (input-only: needs external 10k pull-up to 3.3V)

DEBOUNCE_MS = 200
last_press = 0
start_requested = False
stop_requested = False


def button_handler(pin):
    global last_press, start_requested
    now = ticks_ms()
    if ticks_diff(now, last_press) > DEBOUNCE_MS and pin.value() == 0:
        last_press = now
        start_requested = True


def button_handler2(pin):
    global last_press, stop_requested
    now = ticks_ms()
    if ticks_diff(now, last_press) > DEBOUNCE_MS and pin.value() == 0:
        last_press = now
        stop_requested = True


btn.irq(trigger=Pin.IRQ_FALLING, handler=button_handler)
btn2.irq(trigger=Pin.IRQ_FALLING, handler=button_handler2)


# --- Drawing ---
class Plotter:
    """Plays back the CSV angles on the two servos, one digit at a time."""
    def __init__(self):
        self.cur1 = knob1.angle   # current servo angles (after calibration)
        self.cur2 = knob2.angle

    @staticmethod
    def to_servo(theta, offset, invert):
        return (180 - theta if invert else theta) + offset

    def set_angles(self, a1, a2):
        self.cur1, self.cur2 = a1, a2
        servo1.angle(a1)
        servo2.angle(a2)

    def move_to(self, a1, a2, delay_ms):
        """Move to (a1, a2); big jumps are split into steps of at most MAX_STEP_DEG."""
        d1, d2 = a1 - self.cur1, a2 - self.cur2
        steps = int(max(abs(d1), abs(d2)) / MAX_STEP_DEG) + 1
        s1, s2 = self.cur1, self.cur2
        for i in range(1, steps + 1):
            self.set_angles(s1 + d1 * i / steps, s2 + d2 * i / steps)
            if steps > 1:
                sleep_ms(delay_ms)

    def pause(self, total_ms):
        """Wait total_ms, but stop early if the STOP button is pressed."""
        waited = 0
        while waited < total_ms and not stop_requested:
            sleep_ms(20)
            waited += 20

    def read_digits(self):
        """Yield (digit, rows) one digit at a time so the whole CSV never sits in memory.
        Each row is (light, servo1_angle, servo2_angle) with calibration applied."""
        with open(CSV_FILE) as f:
            f.readline()  # skip header: digit,x_mm,y_mm,light_on,theta1_deg,theta2_deg
            current, rows = None, []
            for line in f:
                parts = line.strip().split(",")
                if len(parts) < 6:
                    continue
                digit = int(parts[0])
                if digit != current:
                    if rows:
                        yield current, rows
                    current, rows = digit, []
                rows.append((int(parts[3]),
                             self.to_servo(float(parts[4]), OFFSET1, INVERT1),
                             self.to_servo(float(parts[5]), OFFSET2, INVERT2)))
            if rows:
                yield current, rows

    def play_digit(self, rows):
        """Draw one digit in exactly DIGIT_DRAW_SEC seconds, at a steady speed along the path."""
        n = len(rows)
        if n < 2:
            return
        frames = max(1, int(DIGIT_DRAW_SEC * 1000) // FRAME_MS)
        light = 0
        led.value(0)
        t0 = ticks_ms()
        for k in range(1, frames + 1):
            if stop_requested:
                break
            u = (n - 1) * k / frames          # position along the path, in rows
            i = int(u)
            if i > n - 2:
                i = n - 2
            frac = u - i
            _, p1, p2 = rows[i]
            new_light, q1, q2 = rows[i + 1]
            if new_light != light:            # the light state of the segment we are drawing
                light = new_light
                led.value(light)
            self.set_angles(p1 + (q1 - p1) * frac, p2 + (q2 - p2) * frac)
            # Fixed schedule from t0, so timing errors never add up
            wait = ticks_diff(ticks_add(t0, k * FRAME_MS), ticks_ms())
            if wait > 0:
                sleep_ms(wait)
        led.value(0)

    def draw_csv(self):
        global start_requested, stop_requested
        first = True
        led.value(0)

        for digit, rows in self.read_digits():
            if stop_requested:
                break
            if DIGITS_TO_DRAW is not None and digit not in DIGITS_TO_DRAW:
                continue

            # 1) Park at the digit's start point with the light off
            print("Digit", digit, "- moving to its start point")
            self.move_to(rows[0][1], rows[0][2], TRAVEL_DELAY_MS)

            # 2) Wait for your signal
            if WAIT_FOR_BUTTON:
                print("Digit {} ready: start the iPhone timer, then press button 1".format(digit))
                start_requested = False
                while not start_requested and not stop_requested:
                    sleep_ms(20)
                start_requested = False
            elif not first:
                print("Pausing {} ms".format(DIGIT_PAUSE_MS))
                self.pause(DIGIT_PAUSE_MS)
            first = False

            # 3) Lead time, then draw the digit
            self.pause(LEAD_MS)
            if stop_requested:
                break
            print("Drawing digit", digit)
            self.play_digit(rows)

        if stop_requested:
            print("Stopped by button")
        led.value(0)
        print("Done")


plotter = Plotter()


def run_drawing():
    global start_requested, stop_requested
    start_requested = False
    stop_requested = False
    if not WAIT_FOR_BUTTON:
        print("Start in {} s - open the camera shutter now".format(START_DELAY_MS // 1000))
        led.value(0)
        sleep_ms(START_DELAY_MS)
        if stop_requested:
            print("Cancelled")
            stop_requested = False
            return
    print("Start")
    try:
        plotter.draw_csv()
    except OSError:
        print("Could not read", CSV_FILE, "- copy it to the ESP32 first")
    # Hand the current position back to the knobs so manual jogging continues from here
    knob1.sync(plotter.cur1)
    knob2.sync(plotter.cur2)
    stop_requested = False
    start_requested = False


# --- Main loop ---
print("Ready: knobs jog the servos, button 1 = start drawing, button 2 = stop")
while True:
    if start_requested:
        run_drawing()
    knob1.update()
    knob2.update()
    plotter.cur1, plotter.cur2 = knob1.angle, knob2.angle
    sleep_ms(10)