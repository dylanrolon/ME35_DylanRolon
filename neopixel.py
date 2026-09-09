import time
import neopixel #importing the library
from machine import Pin # another way of importing a library
lights = neopixel.NeoPixel(Pin(15),2) # 0 is the Pin for neopixel and 4 is the number of lights
lights[0] = (0,20,20) # set the color of 0th light to purple
lights[1] = (20,0,0)
lights.write()



