import os
import tempfile
import unittest
from unittest import mock

from rivalgg import cli, device, profiles
from rivalgg import protocol as p
from rivalgg.profiles import Profile, Store, apply_changes


class FakeMouse:
    def __init__(self, reachable=True):
        self.calls = []
        self.reachable = reachable

    def __enter__(self):
        if not self.reachable:
            raise device.MouseUnreachable("asleep")
        return self

    def __exit__(self, *exc):
        pass

    def power(self):
        return p.PowerSettings()

    def polling_hz(self):
        return None

    def __getattr__(self, name):
        return lambda *a, **k: self.calls.append(name)


def gaming():
    pr = Profile(cpi_presets=[1600], active_cpi=1600, managed=["lighting"])
    pr.lighting.effect = p.EFFECT_REACTIVE
    return pr


class ApplyChangesTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(profiles.time, "sleep")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_writes_only_differences_and_never_flash(self):
        m = FakeMouse()
        apply_changes(gaming(), Profile(), m)
        self.assertEqual(sorted(m.calls), ["set_cpi_table", "set_lighting"])

    def test_identical_profiles_write_nothing(self):
        m = FakeMouse()
        apply_changes(Profile(), Profile(), m)
        self.assertEqual(m.calls, [])

    def test_polling_change_written(self):
        m = FakeMouse()
        apply_changes(Profile(polling_hz=500), Profile(), m)
        self.assertEqual(m.calls, ["set_polling_hz"])


class SwitchTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, "profiles.json")
        s = Store(self.path)
        s.profiles["Gaming"] = gaming()
        s.save()
        self.mouse = FakeMouse()
        for patcher in (mock.patch.object(Store.__init__, "__defaults__", (self.path,)),
                        mock.patch.object(cli.device, "Mouse", lambda: self.mouse),
                        mock.patch.object(profiles.time, "sleep"),
                        mock.patch("builtins.print")):
            patcher.start()
            self.addCleanup(patcher.stop)

    def store(self):
        return Store(self.path)

    def test_temporary_switch(self):
        cli.main(["profile", "use", "Gaming", "--temporary"])
        self.assertEqual(sorted(self.mouse.calls), ["set_cpi_table", "set_lighting"])
        s = self.store()
        self.assertEqual((s.active, s.saved_profile, s.mouse_may_differ),
                         ("Gaming", "Default", True))

    def test_normal_switch_saves_and_records(self):
        cli.main(["profile", "use", "Gaming"])
        self.assertIn("save_to_flash", self.mouse.calls)
        s = self.store()
        self.assertEqual((s.active, s.saved_profile, s.mouse_may_differ),
                         ("Gaming", "Gaming", False))

    def test_next_temporary(self):
        cli.main(["profile", "next", "--temporary"])
        self.assertNotIn("save_to_flash", self.mouse.calls)
        self.assertEqual(self.store().active, "Gaming")

    def test_unreachable_mouse_leaves_store_unchanged(self):
        self.mouse.reachable = False
        with self.assertRaises(SystemExit):
            cli.main(["profile", "use", "Gaming", "--temporary"])
        self.assertEqual(self.store().active, "Default")

    def test_setting_change_after_temporary_saves_everything(self):
        cli.main(["profile", "use", "Gaming", "--temporary"])
        cli.main(["polling", "500"])  # writes and saves the whole active profile to flash
        self.assertFalse(self.store().mouse_may_differ)


class SavedProfileTrackingTests(unittest.TestCase):
    def test_rename_and_delete(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(os.path.join(d, "profiles.json"))
            s.profiles["Gaming"] = gaming()
            s.rename("Default", "Work")
            self.assertEqual(s.saved_profile, "Work")
            s.active = "Gaming"
            s.delete("Work")
            self.assertIsNone(s.saved_profile)
            self.assertTrue(s.mouse_may_differ)


if __name__ == "__main__":
    unittest.main()
