import unittest

from mousework.battery import BatteryMonitor


def feed(levels):
    monitor = BatteryMonitor()
    out = []
    for level in levels:
        w = monitor.update(level)
        out.append(None if w is None else ("critical" if w.critical else "low"))
    return out


class BatteryMonitorTests(unittest.TestCase):
    def test_warns_once_per_threshold(self):
        self.assertEqual(feed([30, 16, 15, 14, 15, 6, 5, 4, 3]),
                         [None, None, "low", None, None, None, "critical", None, None])

    def test_first_reading_already_critical_warns_once(self):
        self.assertEqual(feed([4, 3, 10, 14]), ["critical", None, None, None])

    def test_hovering_does_not_repeat(self):
        self.assertEqual(feed([15, 16, 17, 15, 16, 14]), ["low", None, None, None, None, None])

    def test_new_battery_rearms(self):
        self.assertEqual(feed([15, 100, 15]), ["low", None, "low"])

    def test_unknown_ignored(self):
        self.assertEqual(feed([101, None, -1]), [None, None, None])

    def test_message(self):
        w = BatteryMonitor().update(12)
        self.assertEqual(w.summary, "Mouse battery low")
        self.assertIn("12 %", w.body)


class SettingTests(unittest.TestCase):
    def test_store_round_trip(self):
        import os
        import tempfile
        from mousework.profiles import Store
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "profiles.json")
            self.assertTrue(Store(path).battery_warnings)  # default on
            s = Store(path)
            s.battery_warnings = False
            s.save()
            self.assertFalse(Store(path).battery_warnings)

    def test_service_respects_off(self):
        from mousework import filterd
        sent = []
        original = filterd.battery.notify
        self.addCleanup(setattr, filterd.battery, "notify", original)
        filterd.battery.notify = sent.append
        svc = filterd.Service()
        svc.settings.battery_warnings = False
        svc.battery_level(10)
        self.assertEqual(sent, [])
        svc.settings.battery_warnings = True
        svc.battery_level(10)
        self.assertEqual(len(sent), 1)


if __name__ == "__main__":
    unittest.main()
