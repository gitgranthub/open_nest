"""Blink an LED on a Raspberry Pi -- and still run on your Mac.

There are two kinds of code in a Raspberry Pi project:

  RUNS ON THIS MAC        the thinking part: when to turn the light on, how long to wait
  RUNS ON THE PI          the part that actually touches a pin

This file keeps them apart. The thinking part is at the bottom and you can run it right
now, on your Mac, with no hardware plugged in. The pin part is behind `Lights`, which
uses the real Pi pins when you run it on a Pi and just prints what it *would* do when
you run it here.

That means you can build and test the whole idea before you own a single wire.
"""

import time

# Which pin the LED is on. This is a BCM pin number, the same numbering the Pi's own
# documentation uses. Change it to match how you actually wire yours up.
LED_PIN = 17

# Short on purpose: this finishes quickly so you can see the whole thing happen when you
# press Test on Mac. A real robot would loop until you stopped it, and that works too --
# the Stop button ends it whenever you like.
BLINKS = 3
ON_SECONDS = 0.3
OFF_SECONDS = 0.3


class Lights:
    """Turning a pin on and off -- for real on a Pi, pretend anywhere else.

    RUNS ON THE PI. On your Mac there is no GPIO hardware to talk to, so this prints
    each change instead. Same code, same order, same timing.
    """

    def __init__(self, pin):
        self.pin = pin
        self.gpio = None

        try:
            import RPi.GPIO as GPIO
        except ImportError:
            # Not on a Pi. That is the normal case while you are building.
            print("No Raspberry Pi hardware here, so I will describe what would happen.")
            return

        self.gpio = GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(pin, GPIO.OUT)
        print(f"Talking to the real LED on BCM pin {pin}.")

    @property
    def is_real(self):
        return self.gpio is not None

    def on(self):
        if self.is_real:
            self.gpio.output(self.pin, self.gpio.HIGH)
        else:
            print(f"  LED on pin {self.pin}: ON")

    def off(self):
        if self.is_real:
            self.gpio.output(self.pin, self.gpio.LOW)
        else:
            print(f"  LED on pin {self.pin}: off")

    def finish(self):
        if self.is_real:
            self.gpio.cleanup()


def blink(lights, times, on_seconds, off_seconds):
    """RUNS ON THIS MAC. Just the plan -- no pins anywhere in here."""
    for count in range(1, times + 1):
        print(f"Blink {count} of {times}")
        lights.on()
        time.sleep(on_seconds)
        lights.off()
        time.sleep(off_seconds)


lights = Lights(LED_PIN)
try:
    blink(lights, BLINKS, ON_SECONDS, OFF_SECONDS)
finally:
    lights.finish()

print("Done.")
