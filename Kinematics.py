from servo import Servo
import time
from machine import Pin
servo1 = Servo(Pin(18)) # change this
servo2 = Servo(Pin(19)) # and this

servo1.write_angle(90)
servo2.write_angle(90)