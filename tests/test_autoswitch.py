import os
import tempfile
import time
import unittest
from unittest import mock

from rivalgg import autoswitch, profiles
from rivalgg import protocol as p
from rivalgg.profiles import Profile, Store, apply_changes


class FakeMouse:
    def __init__(self, linked=True):
        self.calls = []
        self._linked = linked

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def linked(self):
        return self._linked

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


class StoreRuleTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "profiles.json")

    def tearDown(self):
        self.dir.cleanup()

    def store(self):
        s = Store(self.path)
        s.profiles["Gaming"] = gaming()
        s.app_profiles = {"steam.desktop": "Gaming"}
        s.save()
        return Store(self.path)

    def test_rule_and_fallback(self):
        s = self.store()
        self.assertEqual(s.profile_for_app("steam.desktop")[0], "Gaming")
        self.assertEqual(s.profile_for_app("org.gnome.Nautilus.desktop")[0], "Default")
        self.assertEqual(s.profile_for_app(None)[0], "Default")

    def test_rename_and_delete_follow_rules(self):
        s = self.store()
        s.rename("Gaming", "Games")
        self.assertEqual(s.app_profiles, {"steam.desktop": "Games"})
        s.delete("Games")
        self.assertEqual(s.app_profiles, {})
        with self.assertRaises(ValueError):
            s.delete("Default")

    def test_rules_to_missing_profiles_dropped_on_load(self):
        s = self.store()
        del s.profiles["Gaming"]
        s.save()
        self.assertEqual(Store(self.path).app_profiles, {})


class ApplyChangesTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(profiles.time, "sleep")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_writes_only_differences_and_never_flash(self):
        m = FakeMouse()
        apply_changes(gaming(), Profile(), m)
        self.assertIn("set_cpi_table", m.calls)
        self.assertIn("set_lighting", m.calls)
        self.assertNotIn("set_power", m.calls)
        self.assertNotIn("set_polling_hz", m.calls)
        self.assertNotIn("set_buttons", m.calls)  # buttons not managed
        self.assertNotIn("save_to_flash", m.calls)

    def test_identical_profiles_write_nothing(self):
        m = FakeMouse()
        apply_changes(Profile(), Profile(), m)
        self.assertEqual(m.calls, [])

    def test_polling_change_written(self):
        m = FakeMouse()
        apply_changes(Profile(polling_hz=500), Profile(), m)
        self.assertEqual(m.calls, ["set_polling_hz"])


class SwitcherTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)  # runs last: after the switcher has stopped
        path = os.path.join(self.dir.name, "profiles.json")
        s = Store(path)
        s.profiles["Gaming"] = gaming()
        s.app_profiles = {"steam.desktop": "Gaming"}
        s.save()
        self.mouse = FakeMouse()
        for target, value in ((profiles, "CONFIG_FILE"), (autoswitch, "CONFIG_FILE")):
            patcher = mock.patch.object(target, value, path)
            patcher.start()
            self.addCleanup(patcher.stop)
        patches = [
            mock.patch.object(Store.__init__, "__defaults__", (path,)),
            mock.patch.object(autoswitch.device, "Mouse", lambda: self.mouse),
            mock.patch.object(autoswitch, "STATE_FILE", os.path.join(self.dir.name, "state.json")),
            mock.patch.object(autoswitch, "SETTLE_S", 0.2),
            mock.patch.object(profiles.time, "sleep"),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.settings = mock.Mock(effective_name=None)
        self.switcher = autoswitch.AutoSwitcher(self.settings, lambda msg: None).start()
        self.addCleanup(self.switcher.join, 3)
        self.addCleanup(self.switcher.stop)

    def wait_for(self, name, timeout=3.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.switcher.applied_name == name:
                return True
            time.sleep(0.05)
        return False

    def test_switches_after_settling_and_back(self):
        self.switcher.focus_changed("steam.desktop")
        self.assertTrue(self.wait_for("Gaming"))
        self.assertEqual(autoswitch.read_state(), {"profile": "Gaming", "app": "steam.desktop"})
        self.assertEqual(self.settings.effective_name, "Gaming")
        self.switcher.focus_changed("org.gnome.Nautilus.desktop")
        self.assertTrue(self.wait_for("Default"))

    def test_quick_focus_pass_does_not_switch(self):
        self.switcher.focus_changed("steam.desktop")
        time.sleep(0.05)
        self.switcher.focus_changed("org.gnome.Terminal.desktop")
        time.sleep(0.6)
        self.assertEqual(self.switcher.applied_name, "Default")
        self.assertEqual(self.mouse.calls, [])

    def test_own_window_restores_active(self):
        self.switcher.focus_changed("steam.desktop")
        self.assertTrue(self.wait_for("Gaming"))
        self.switcher.focus_changed(autoswitch.OWN_APP_ID)
        self.assertTrue(self.wait_for("Default"))

    def test_waits_for_sleeping_mouse(self):
        self.mouse._linked = False
        self.switcher.focus_changed("steam.desktop")
        time.sleep(0.6)
        self.assertEqual(self.switcher.applied_name, "Default")
        self.mouse._linked = True
        self.assertTrue(self.wait_for("Gaming"))


if __name__ == "__main__":
    unittest.main()
