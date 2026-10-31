"""Host-side acceleration, deceleration and smoothing (spec 3.7).

Pure arithmetic with no I/O, fed one mouse report at a time. Two styles:

STYLE_GG follows the spec bit for bit: deceleration is a single step
(spec 3.7.1), and both scaling and smoothing round small movements away.

STYLE_SMOOTH is our own: deceleration fades out over the ten bands, which is
what the table's shape implies; scaling carries its remainder instead of
applying GG's minimum-motion rule; and smoothing keeps a per-axis balance of
input minus output, so rounding never silently drops movement. At 1000 Hz
most reports are 1-2 counts, where GG's rounding stalls slow movement.
"""

from dataclasses import dataclass

DEFAULT_CPI = 1600
RESET_INTERVAL = 1000  # 100 ms in 100 us units
SMOOTHING_SPEED_LIMIT = 3 * 800  # thousandths of in/s (spec 3.7.2)

STYLE_SMOOTH = "smooth"
STYLE_GG = "gg"
STYLES = (STYLE_SMOOTH, STYLE_GG)

ACCEL_THRESHOLDS = tuple(1200 * k for k in range(1, 11))

# spec 3.7.1 deceleration thresholds TD_0..TD_9 per level, thousandths of in/s
DECEL_THRESHOLDS = {
    1: (0, 61, 126, 196, 270, 351, 441, 542, 663, 820),
    2: (0, 123, 253, 392, 540, 702, 882, 1085, 1326, 1641),
    3: (0, 184, 380, 588, 811, 1054, 1323, 1628, 1990, 2461),
    4: (0, 246, 506, 784, 1081, 1405, 1764, 2170, 2653, 3282),
    5: (0, 307, 633, 980, 1352, 1757, 2205, 2713, 3316, 4102),
    6: (0, 369, 760, 1176, 1622, 2108, 2646, 3256, 3980, 4923),
    7: (0, 431, 886, 1372, 1893, 2460, 3087, 3799, 4643, 5743),
    8: (0, 492, 1013, 1568, 2163, 2811, 3528, 4341, 5306, 6564),
    9: (0, 554, 1140, 1764, 2434, 3163, 3969, 4884, 5970, 7384),
    10: (0, 615, 1266, 1960, 2704, 3514, 4410, 5427, 6633, 8205),
}


def isqrt(n):
    """The driver's Newton iteration, including its rounding quirks (spec 3.7.0)."""
    if n == 0:
        return 0
    x, history = 15, [15]
    while True:
        nxt = (n // x + x) // 2
        if nxt == x:
            return nxt
        if len(history) >= 2 and nxt == history[-2]:
            return nxt  # oscillation; matches the spec 3.7.0 examples
        history.append(nxt)
        x = nxt


def _round_half_away(value):
    return int(value + 0.5) if value >= 0 else -int(-value + 0.5)


def _sign(value):
    return (value > 0) - (value < 0)


def _trunc_div(a, b):
    """Integer division truncated toward zero."""
    q = abs(a) // b
    return q if a >= 0 else -q


def accel_percent(level, v):
    if not level:
        return 0
    steps = sum(1 for t in ACCEL_THRESHOLDS if t <= v)
    return steps * 10 * level // 10


def decel_percent(level, v, style=STYLE_SMOOTH):
    """Smooth: fades from 5 x level % at rest to 0 at 1.2 x level in/s.
    GG: the full 5 x level % up to the last threshold, then 0."""
    if not level:
        return 0
    if style == STYLE_GG:
        return 5 * level if v <= DECEL_THRESHOLDS[level][-1] else 0
    if v >= 1200 * level:
        return 0
    band = sum(1 for t in DECEL_THRESHOLDS[level] if t <= v)  # 1..10
    return 5 * level * (11 - band) // 10


@dataclass
class _Axis:
    remainder: int = 0
    nonzero: bool = False
    sign: int = 0
    prev_sign: int = 0

    def reset(self):
        self.remainder = 0
        self.nonzero = False

    @property
    def reversed(self):
        return self.sign != 0 and self.sign == -self.prev_sign

    def scale(self, d, gain, carry=False):
        """Scale by gain percent. carry=True keeps the remainder instead of
        applying GG's minimum-motion rule."""
        s = d * gain + self.remainder
        out = _trunc_div(s, 100)
        self.remainder = s - 100 * out
        if out > 32767 or out < -32768:
            clamped = max(-32768, min(32767, out))
            self.remainder += (out - clamped) * 100
            out = clamped
        if carry:
            return out
        # Minimum-motion rule
        if out != 0:
            self.nonzero = True
        elif self.nonzero:
            self.nonzero = False
            self.remainder = 0
        elif d != 0:
            out = _sign(d)
            self.remainder = 0
            self.nonzero = True
        else:
            self.nonzero = False
        return out


class MotionFilter:
    def __init__(self, accel=0, decel=0, smoothing=0, cpi=DEFAULT_CPI, style=STYLE_SMOOTH):
        self.accel = accel
        self.decel = decel
        self.style = style
        self.smoothing = smoothing
        self.cpi = cpi or DEFAULT_CPI
        self._x, self._y = _Axis(), _Axis()
        self._window = []
        self._balance = [0.0, 0.0]  # smooth style: input minus output per axis
        self._last_time = None

    @property
    def active(self):
        return bool(self.accel or self.decel or self.smoothing)

    def interval(self, timestamp):
        """Report interval in 100 us units from a timestamp in seconds."""
        if self._last_time is None:
            dt = RESET_INTERVAL
        else:
            dt = max(1, int((timestamp - self._last_time) * 10000))
        self._last_time = timestamp
        return dt

    def speed(self, dx, dy, dt):
        r = isqrt(100 * (dx * dx + dy * dy))
        return r, (1000000 // self.cpi) * r // dt

    def process(self, dx, dy, dt):
        """Filter one report. dt is the report interval in 100 us units."""
        dt = max(1, dt)
        r, v = self.speed(dx, dy, dt)
        jitter = r == 10 and dt == 1
        for axis, d in ((self._x, dx), (self._y, dy)):
            axis.prev_sign, axis.sign = axis.sign, _sign(d)

        if (self.accel or self.decel) and (dx or dy) and not jitter:
            if dt >= RESET_INTERVAL or self._x.reversed or self._y.reversed:
                self._x.reset()
                self._y.reset()
            gain = 100 + accel_percent(self.accel, v) - decel_percent(self.decel, v, self.style)
            carry = self.style == STYLE_SMOOTH
            dx, dy = self._x.scale(dx, gain, carry), self._y.scale(dy, gain, carry)

        if self.smoothing:
            reversed_both = self._x.reversed and self._y.reversed
            if (not jitter and v > SMOOTHING_SPEED_LIMIT) or reversed_both:
                self._window.clear()
                if reversed_both:
                    self._balance = [0.0, 0.0]  # direction changed; drop the backlog
            self._window.append((dx, dy))
            del self._window[:-self.smoothing]
            if self.style == STYLE_GG:
                dx, dy = (self._average([e[i] for e in self._window]) for i in (0, 1))
            else:
                dx, dy = (self._balanced(i, d) for i, d in ((0, dx), (1, dy)))
        return dx, dy

    def _balanced(self, axis, d):
        """Move toward the window average while paying back the backlog, so
        the total output follows the total input."""
        avg = sum(e[axis] for e in self._window) / len(self._window)
        self._balance[axis] += d
        out = _round_half_away(avg + 0.5 * (self._balance[axis] - avg))
        self._balance[axis] -= out
        return out

    @staticmethod
    def _average(values):
        n, total = len(values), sum(values)
        out = _trunc_div(total, n)
        if abs(total) % n > n // 2:
            out += _sign(total)
        return out
