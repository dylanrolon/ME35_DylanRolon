from machine import Pin, PWM
from time import ticks_ms, ticks_diff, sleep_ms


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
    """Turns encoder movement into a clamped 0-180 angle."""
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


# --- Servo knobs ---
enc1 = Count(32, 39)   # Motor1 encoder -> base servo
enc2 = Count(25, 33)   # Motor2 encoder -> top servo
knob1 = Knob(enc1, Servo(18), name="Servo 1 (pin 18)", counts_per_deg=4)
knob2 = Knob(enc2, Servo(19), name="Servo 2 (pin 19)", counts_per_deg=4)

# --- LED + buttons ---
led = Pin(23, Pin.OUT)   # external LED on the arm: pin 23 -> 220 ohm resistor -> LED -> GND
btn = Pin(34, Pin.IN)    # ON button  (input-only: needs external 10k pull-up to 3.3V)
btn2 = Pin(35, Pin.IN)   # OFF button (input-only: needs external 10k pull-up to 3.3V)

DEBOUNCE_MS = 200
last_press = 0


def button_handler(pin):
    global last_press
    now = ticks_ms()
    if ticks_diff(now, last_press) > DEBOUNCE_MS:
        if pin.value() == 0:
            last_press = now
            led.value(1)
            print("Button 1 pressed: LED on")


def button_handler2(pin):
    global last_press
    now = ticks_ms()
    if ticks_diff(now, last_press) > DEBOUNCE_MS:
        if pin.value() == 0:
            last_press = now
            led.value(0)
            print("Button 2 pressed: LED off")


btn.irq(trigger=Pin.IRQ_FALLING, handler=button_handler)
btn2.irq(trigger=Pin.IRQ_FALLING, handler=button_handler2)

# --- Main loop ---
while True:
    knob1.update()
    knob2.update()
    sleep_ms(10)