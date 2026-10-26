from machine import ADC, Pin
from time import sleep_ms

adc_x = ADC(Pin(32)); adc_x.atten(ADC.ATTN_11DB)
adc_y = ADC(Pin(33)); adc_y.atten(ADC.ATTN_11DB)

CENTER_X = 30850
CENTER_Y = 31250
DEADZONE = 10000
CLICK_PEAK = 57000   # between UP max (~48,700) and click (65535)

# stick is rotated 90 degrees: Y axis = left/right, X axis = up/down/click
x_active = False
peak_x = 0
last_y_dir = "CENTER"

def poll():
    """Returns an event string or None.
    LEFT/RIGHT fire when the push starts or changes.
    UP/DOWN/CLICK fire when the stick is released."""
    global x_active, peak_x, last_y_dir

    x = adc_x.read_u16()
    y = adc_y.read_u16()
    dx = x - CENTER_X
    dy = y - CENTER_Y
    event = None

    # --- Y axis: LEFT / RIGHT ---
    if abs(dy) > DEADZONE and abs(dy) > abs(dx):
        d = "LEFT" if dy > 0 else "RIGHT"
        if d != last_y_dir:
            event = d
            last_y_dir = d
    elif abs(dy) < DEADZONE:
        last_y_dir = "CENTER"

    # --- X axis: UP / DOWN / CLICK (classified on release) ---
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

print("Try LEFT, RIGHT, UP, DOWN, and CLICK")
while True:
    e = poll()
    if e:
        print(e)
    sleep_ms(10)