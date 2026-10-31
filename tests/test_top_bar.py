import unittest

from mousework.top_bar import UUID, TopBar


class FakeSettings:
    """The two org.gnome.shell keys TopBar uses."""

    def __init__(self, enabled=(), disabled=(), writable=True):
        self.keys = {"enabled-extensions": list(enabled), "disabled-extensions": list(disabled)}
        self.writable = writable
        self.handlers = []

    def get_strv(self, key):
        return list(self.keys[key])

    def set_strv(self, key, value):
        self.keys[key] = list(value)
        for signal, handler in self.handlers:
            if signal == f"changed::{key}":
                handler(self, key)

    def is_writable(self, key):
        return self.writable

    def connect(self, signal, handler):
        self.handlers.append((signal, handler))


class FakeShell:
    def __init__(self, running=True, knows=True):
        self._running = running
        self.knows = knows

    def running(self):
        return self._running

    def knows_extension(self):
        return self.knows


class TopBarTest(unittest.TestCase):
    def test_not_available_without_gnome_shell(self):
        top_bar = TopBar(shell=FakeShell(running=False), installed=False)
        self.assertFalse(top_bar.available)

    def test_not_available_when_not_installed(self):
        top_bar = TopBar(settings=FakeSettings(), shell=FakeShell(), installed=False)
        self.assertFalse(top_bar.available)

    def test_enable_adds_it_and_keeps_other_extensions(self):
        settings = FakeSettings(enabled=["other@example.com"], disabled=[UUID, "x@example.com"])
        top_bar = TopBar(settings=settings, shell=FakeShell(), installed=True)
        self.assertTrue(top_bar.available)
        self.assertFalse(top_bar.enabled)
        top_bar.set_enabled(True)
        self.assertTrue(top_bar.enabled)
        self.assertEqual(settings.keys["enabled-extensions"], ["other@example.com", UUID])
        self.assertEqual(settings.keys["disabled-extensions"], ["x@example.com"])

    def test_enable_twice_lists_it_once(self):
        settings = FakeSettings(enabled=[UUID])
        top_bar = TopBar(settings=settings, shell=FakeShell(), installed=True)
        top_bar.set_enabled(True)
        self.assertEqual(settings.keys["enabled-extensions"], [UUID])

    def test_disable_removes_only_it(self):
        settings = FakeSettings(enabled=["a@example.com", UUID, "b@example.com"])
        top_bar = TopBar(settings=settings, shell=FakeShell(), installed=True)
        top_bar.set_enabled(False)
        self.assertFalse(top_bar.enabled)
        self.assertEqual(settings.keys["enabled-extensions"], ["a@example.com", "b@example.com"])

    def test_disabled_list_wins(self):
        settings = FakeSettings(enabled=[UUID], disabled=[UUID])
        self.assertFalse(TopBar(settings=settings, shell=FakeShell(), installed=True).enabled)

    def test_needs_login_until_shell_has_loaded_it(self):
        shell = FakeShell(knows=False)
        top_bar = TopBar(settings=FakeSettings(), shell=shell, installed=True)
        self.assertTrue(top_bar.needs_login)
        shell.knows = True
        self.assertFalse(top_bar.needs_login)

    def test_locked_setting(self):
        top_bar = TopBar(settings=FakeSettings(writable=False), shell=FakeShell(), installed=True)
        self.assertFalse(top_bar.can_change)

    def test_changes_are_reported(self):
        settings = FakeSettings()
        top_bar = TopBar(settings=settings, shell=FakeShell(), installed=True)
        calls = []
        top_bar.connect_changed(lambda: calls.append(top_bar.enabled))
        top_bar.set_enabled(True)
        self.assertEqual(calls[-1], True)
        settings.set_strv("enabled-extensions", [])  # turned off in the Extensions app
        self.assertEqual(calls[-1], False)


if __name__ == "__main__":
    unittest.main()
