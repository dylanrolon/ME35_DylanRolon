from machine import I2C, Pin
from time import sleep_ms, ticks_ms, ticks_diff
import struct
from math import sqrt

# --- settings ---
ADDR = 0x19          # change to 0x18 if the scanner found that
PRINT_MS = 250       # how often a line prints (4 per second)

# --- LIS3DH registers (from the ST datasheet) ---
WHO_AM_I  = 0x0F     # should read 0x33
CTRL_REG1 = 0x20
CTRL_REG4 = 0x23
OUT_X_L   = 0x28

i2c = I2C(0, scl=Pin(22), sda=Pin(21), freq=400000)

# --- sensor setup ---
who = i2c.readfrom_mem(ADDR, WHO_AM_I, 1)[0]
print("WHO_AM_I:", hex(who))
if who != 0x33:
    print("Unexpected ID, check address/wiring")

i2c.writeto_mem(ADDR, CTRL_REG1, bytes([0x57]))  # 100 Hz, XYZ enabled, normal mode
i2c.writeto_mem(ADDR, CTRL_REG4, bytes([0x98]))  # block update, +/-4g, high resolution
sleep_ms(10)

SCALE = 0.002  # g per count at +/-4g in high-res (12-bit) mode

def read_accel():
    # 0x80 bit = auto-increment, reads 6 bytes: X, Y, Z (little-endian 16-bit)
    data = i2c.readfrom_mem(ADDR, OUT_X_L | 0x80, 6)
    x, y, z = struct.unpack('<hhh', data)
    # 12-bit value is left-justified in 16 bits, so shift right by 4
    return (x >> 4) * SCALE, (y >> 4) * SCALE, (z >> 4) * SCALE

# --- main loop ---
last_print = 0

while True:
    x, y, z = read_accel()           # samples every loop (about 50 Hz)
    mag = sqrt(x*x + y*y + z*z)

    now = ticks_ms()
    if ticks_diff(now, last_print) >= PRINT_MS:
        last_print = now
        print("x=%.2f  y=%.2f  z=%.2f  mag=%.2f" % (x, y, z, mag))

    sleep_ms(20)