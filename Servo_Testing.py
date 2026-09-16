from machine import Pin, PWM
import time
pwm = PWM(Pin(18))
pwm.freq(50)

# (0.5/20)*1023
# 0 Degrees
pwm.duty(26)
time.sleep_ms(1000)
# (1.5/20)*1023
# 90 Degrees
pwm.duty(77)
time.sleep_ms(1000)
# (2.5/20)*1023
# 180 Degrees
pwm.duty(128)
time.sleep_ms(1000)



