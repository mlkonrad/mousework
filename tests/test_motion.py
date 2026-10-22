import unittest

import random

from mousework.motion import STYLE_GG, MotionFilter, decel_percent, isqrt


def run(f, reports, dt):
    dts = dt if isinstance(dt, list) else [dt] * len(reports)
    return [f.process(dx, dy, t) for (dx, dy), t in zip(reports, dts)]


class IsqrtTests(unittest.TestCase):
    def test_quirks(self):
        # §3.7.0: one above floor(sqrt) just below some perfect squares
        self.assertEqual([isqrt(n) for n in (2400, 2600, 9800, 10200)], [49, 51, 99, 101])
        self.assertEqual([isqrt(n) for n in (0, 100, 2500, 5200)], [0, 10, 50, 72])


def gg(**kw):
    return MotionFilter(style=STYLE_GG, **kw)


class AccelTests(unittest.TestCase):
    """Spec §3.7.1 vectors (GG arithmetic)."""

    def test_a1(self):
        self.assertEqual(run(gg(accel=5, cpi=800), [(10, 0)], 10), [(15, 0)])

    def test_a2_remainder(self):
        f = gg(accel=5, cpi=800)
        self.assertEqual(run(f, [(3, 4)], 10), [(3, 5)])
        self.assertEqual((f._x.remainder, f._y.remainder), (75, 0))

    def test_a3_below_first_step(self):
        self.assertEqual(run(gg(accel=10, cpi=1600), [(1, 0)], 10), [(1, 0)])

    def test_a7_reversal_resets(self):
        f = gg(accel=5, cpi=800)
        self.assertEqual(run(f, [(3, 4), (-3, -4)], 10), [(3, 5), (-3, -5)])

    def test_a8_idle_resets(self):
        f = gg(accel=5, cpi=800)
        self.assertEqual(run(f, [(3, 4), (3, 4)], [10, 1000]), [(3, 5), (3, 4)])

    def test_a9(self):
        self.assertEqual(run(gg(accel=10, cpi=800), [(100, 0)], 80), [(200, 0)])

    def test_a10(self):
        f = gg(accel=3, cpi=800)
        self.assertEqual(run(f, [(7, -2)] * 3, 10), [(8, -2), (8, -2), (9, -3)])


class DecelTests(unittest.TestCase):
    """Smooth ten-band deceleration (our deliberate deviation from GG)."""

    def test_fades_out(self):
        values = [decel_percent(10, v) for v in (0, 614, 615, 5000, 8204, 8205, 11999, 12000)]
        self.assertEqual(values, [50, 50, 45, 20, 10, 5, 5, 0])
        self.assertEqual(decel_percent(0, 0), 0)

    def test_a4_same_as_gg(self):
        self.assertEqual(run(MotionFilter(decel=10, cpi=800), [(2, 0)], 10), [(1, 0)])

    def test_carries_remainder(self):
        # v = 1250 -> smooth decel 45 %, gain 55 %: remainder carries, no 1-0 reset
        f = MotionFilter(decel=10, cpi=800)
        self.assertEqual(run(f, [(1, 0)] * 4, 10), [(0, 0), (1, 0), (0, 0), (1, 0)])

    def test_combined(self):
        # v = 5000: accel +40 %, smooth decel -20 % -> 120 % (GG would give 90 %)
        f = MotionFilter(accel=10, decel=10, cpi=800)
        self.assertEqual(run(f, [(4, 0)] * 3, 10), [(4, 0), (5, 0), (5, 0)])


class SmoothStyleTests(unittest.TestCase):
    """Smooth style must not lose or stall slow movement."""

    def slow_drift(self, n=2000, seed=1):
        rng = random.Random(seed)
        return [(rng.choice((1, 1, 2)), rng.choice((0, 0, 0, 1))) for _ in range(n)]

    def dead_run(self, reports, out):
        run = best = 0
        for (a, b), (c, d) in zip(reports, out):
            run = run + 1 if (a or b) and not (c or d) else 0
            best = max(best, run)
        return best

    def test_smoothing_conserves_motion(self):
        reports = self.slow_drift()
        for level in (2, 4, 10):
            out = run(MotionFilter(smoothing=level, cpi=1200), reports, 10)
            for axis in (0, 1):
                total_in = sum(r[axis] for r in reports)
                total_out = sum(o[axis] for o in out)
                self.assertLessEqual(abs(total_in - total_out), 2, (level, axis))

    def test_decel_plus_smoothing_does_not_stall(self):
        reports = self.slow_drift()
        smooth = run(MotionFilter(decel=5, smoothing=4, cpi=1200), reports, 10)
        stalled = run(gg(decel=5, smoothing=4, cpi=1200), reports, 10)
        self.assertLessEqual(self.dead_run(reports, smooth), 5)
        self.assertGreater(self.dead_run(reports, stalled), 5)  # GG's rounding stalls

    def test_reversal_drops_backlog(self):
        f = MotionFilter(smoothing=4, cpi=800)
        run(f, [(1, 1)] * 3, 80)
        self.assertEqual(f.process(-1, -1, 80), (-1, -1))


class GgDecelTests(unittest.TestCase):
    """Spec §3.7.1 vectors A4-A6 with GG's single-step deceleration."""

    def f(self, **kw):
        return MotionFilter(cpi=800, style=STYLE_GG, **kw)

    def test_single_step(self):
        values = [decel_percent(10, v, STYLE_GG) for v in (0, 5000, 8205, 8206)]
        self.assertEqual(values, [50, 50, 50, 0])

    def test_a4(self):
        self.assertEqual(run(self.f(decel=10), [(2, 0)], 10), [(1, 0)])

    def test_a5(self):
        self.assertEqual(run(self.f(decel=10), [(1, 0)] * 4, 10),
                         [(1, 0), (0, 0), (1, 0), (0, 0)])

    def test_a6(self):
        self.assertEqual(run(self.f(accel=10, decel=10), [(4, 0)] * 3, 10),
                         [(3, 0), (4, 0), (3, 0)])


class SmoothingTests(unittest.TestCase):
    """Spec §3.7.2 vectors."""

    def check(self, level, dt, reports, expected):
        self.assertEqual(run(gg(smoothing=level, cpi=800), reports, dt), expected)

    def test_s1(self):
        self.check(3, 80, [(3, 0), (3, 1), (3, 0), (3, 1)], [(3, 0), (3, 0), (3, 0), (3, 1)])

    def test_s2_fast_flushes(self):
        self.check(3, 80, [(3, 1), (3, 1), (20, 0)], [(3, 1), (3, 1), (20, 0)])

    def test_s3_reversal_flushes(self):
        self.check(3, 80, [(3, 1), (2, 1), (-3, -1)], [(3, 1), (2, 1), (-3, -1)])

    def test_s4_window_of_one(self):
        self.check(1, 80, [(5, 2), (1, 0)], [(5, 2), (1, 0)])

    def test_s5(self):
        self.check(10, 10, [(1, 0), (0, 1), (1, 0), (0, 0), (1, 1)],
                   [(1, 0), (0, 0), (1, 0), (0, 0), (1, 0)])

    def test_s6(self):
        self.check(2, 10, [(1, 0), (2, 0)], [(1, 0), (2, 0)])

    def test_s7(self):
        self.check(4, 80, [(-1, 0), (-2, 0), (-2, 1), (-2, 0), (-1, 0)],
                   [(-1, 0), (-1, 0), (-2, 0), (-2, 0), (-2, 0)])


if __name__ == "__main__":
    unittest.main()
