import unittest
from unittest import mock

from mousework import profiles
from mousework import protocol as p
from mousework.profiles import Profile, apply, reconcile


class RecordingMouse:
    """Holds power and CPI like the mouse does and records every write."""

    def __init__(self, power, table):
        self._power = power
        self._table = table
        self.writes = []

    def power(self):
        return self._power

    def cpi_table(self):
        return self._table

    def polling_hz(self):
        return 1000

    def set_power(self, settings):
        self.writes.append("power")
        self._power = settings

    def set_cpi_table(self, table):
        self.writes.append("cpi")
        self._table = table

    def __getattr__(self, name):  # lighting, buttons, wheel, flash
        return lambda *a, **k: self.writes.append(name)


def luzinhas():
    return Profile(cpi_presets=[400, 800, 1200, 1600, 2000], active_cpi=1600,
                   high_efficiency=True, smart_illumination=False, sleep_minutes=20,
                   managed=["lighting", "buttons"])


def matching_mouse(pr):
    power = p.PowerSettings(pr.high_efficiency, 0, 300, pr.sleep_minutes * 60)
    return RecordingMouse(power, p.make_cpi_table(pr.cpi_presets, pr.active_cpi))


@mock.patch.object(profiles.time, "sleep", lambda s: None)
class ReconcileTests(unittest.TestCase):
    """A power write drops the radio link even when nothing changes, so
    reconnect handling must not write settings the mouse already has."""

    def test_matching_mouse_gets_no_power_or_cpi_write(self):
        pr = luzinhas()
        mouse = matching_mouse(pr)
        reconcile(pr, mouse)
        self.assertEqual(mouse.writes, ["set_lighting", "set_buttons", "set_wheel"])

    def test_differences_are_written(self):
        pr = luzinhas()
        mouse = matching_mouse(pr)
        mouse._table = p.make_cpi_table(pr.cpi_presets, 1200)
        mouse._power = p.PowerSettings(False, 0, 300, 1200)
        reconcile(pr, mouse)
        self.assertIn("power", mouse.writes)
        self.assertIn("cpi", mouse.writes)
        self.assertEqual(mouse._table.active_cpi, 1600)
        self.assertTrue(mouse._power.high_efficiency)
        self.assertEqual(mouse._power.idle_lighting_s, 300)  # preserved (§3.3)

    def test_smart_illumination_difference(self):
        pr = luzinhas()
        mouse = matching_mouse(pr)
        mouse._power = p.PowerSettings(True, p.SMART_ILLUMINATION_ON, 300, 1200)
        reconcile(pr, mouse)
        self.assertEqual(mouse.writes.count("power"), 1)
        self.assertFalse(mouse._power.smart_illumination)

    def test_second_reconcile_writes_nothing_new(self):
        pr = luzinhas()
        mouse = matching_mouse(pr)
        mouse._table = p.make_cpi_table(pr.cpi_presets, 1200)
        reconcile(pr, mouse)
        mouse.writes.clear()
        reconcile(pr, mouse)
        self.assertNotIn("power", mouse.writes)
        self.assertNotIn("cpi", mouse.writes)

    def test_apply_skips_matching_power_and_cpi(self):
        pr = luzinhas()
        mouse = matching_mouse(pr)
        apply(pr, mouse)
        self.assertNotIn("power", mouse.writes)
        self.assertNotIn("cpi", mouse.writes)
        self.assertEqual(mouse.writes[-1], "save_to_flash")


if __name__ == "__main__":
    unittest.main()
