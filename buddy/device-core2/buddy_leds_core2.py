"""Side LED bars on the M5Stack Core2 for AWS IoT EduKit.

The AWS edition's battery base has two bars of five SK6812 RGB LEDs
(ten in all) chained on GPIO25. A plain Core2 has no LED bars (GPIO25
is just an M-Bus pin there), and the app can't tell the two apart, so
it assumes the bars are present whenever the Core2 is on USB power.

One use: while a permission request is outstanding, both bars flash
briefly once every 5 s. They stay off on battery (see power.md).

The pin is only touched once there is something to show on USB, so a
Core2 that never sees a request on USB never drives GPIO25.
"""

import time

_PIN = 25
_COUNT = 10  # two bars of five
_PERIOD_MS = 5000  # one flash every 5 s
_ON_MS = 200  # how long each flash stays lit
_COLOR = (160, 60, 0)  # amber, not full brightness
_OFF = (0, 0, 0)


def _open():
    """Return a ``show((r, g, b))`` function for all ten LEDs, or None
    if neither MicroPython's ``neopixel`` nor UIFlow's ``hardware.RGB``
    is available."""
    try:
        import machine
        import neopixel

        np = neopixel.NeoPixel(machine.Pin(_PIN, machine.Pin.OUT), _COUNT)

        def show(rgb):
            np.fill(rgb)
            np.write()

        return show
    except Exception as e:
        first = e
    try:
        # UIFlow 2.5's Core2 firmware has no ``neopixel`` module, so
        # this is the path it takes. RGB is NeoPixel-like (fill/write,
        # GRB order, brightness 1.0 by default).
        from hardware import RGB

        bars = RGB(io=_PIN, n=_COUNT, type="SK6812")

        def show(rgb):
            bars.fill(rgb)
            bars.write()

        return show
    except Exception as e:
        print("buddy_leds_core2: LED bars unavailable:", first, e)
        return None


class LedBars:
    """Flash pattern for an outstanding request. Call ``tick()`` from
    the main loop; it writes to the LEDs only when they change."""

    def __init__(self):
        self._show = None
        self._tried = False
        self._lit = False
        self._since = None  # ticks_ms at the start of the current period

    def tick(self, request_open: bool, on_usb: bool):
        if not (request_open and on_usb):
            self._since = None
            self.off()
            return
        if not self._tried:
            self._tried = True
            self._show = _open()
        if self._show is None:
            return
        now = time.ticks_ms()
        if self._since is None:
            self._since = now  # flash right away when a request opens
        elapsed = time.ticks_diff(now, self._since)
        if elapsed >= _PERIOD_MS:
            # Move the start forward a whole number of periods, so a
            # request left open for days never hits ticks_ms wraparound.
            skip = elapsed - elapsed % _PERIOD_MS
            self._since = time.ticks_add(self._since, skip)
            elapsed -= skip
        self._set(elapsed < _ON_MS)

    def off(self):
        """Turn the bars off if they're lit (also used on exit: the
        LEDs keep their colour across a reset while they have power)."""
        if self._lit:
            self._set(False)

    def _set(self, lit: bool):
        if lit == self._lit or self._show is None:
            return
        try:
            self._show(_COLOR if lit else _OFF)
            self._lit = lit
        except Exception as e:
            print("buddy_leds_core2: write failed:", e)
            self._show = None  # stop trying; the bars stay as they are
