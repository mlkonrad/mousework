import unittest
from unittest import mock

from mousework import filterd
from mousework import protocol as p


class ChangeSignalTest(unittest.TestCase):
    def setUp(self):
        self.service = filterd.Service()
        self.service.settings.battery_warnings = False
        patcher = mock.patch("mousework.changes.emit")
        self.emit = patcher.start()
        self.addCleanup(patcher.stop)

    def test_mouse_events_are_announced(self):
        self.service.on_event(p.EVENT_CPI_CHANGED, 2, b"")
        self.service.on_event(p.EVENT_LINK, 1, b"")
        self.service.on_event(p.EVENT_BATTERY, 40, b"")
        self.assertEqual([c.args[0] for c in self.emit.call_args_list], ["cpi", "link", "battery"])

    def test_unknown_events_are_not_announced(self):
        self.service.on_event(0x99, 0, b"")
        self.emit.assert_not_called()

    def test_settings_announced_only_when_changed(self):
        with mock.patch.object(self.service.settings, "refresh", side_effect=[True, False]):
            self.assertTrue(self.service.refresh_settings())
            self.assertFalse(self.service.refresh_settings())
        self.emit.assert_called_once_with("settings")

    def test_bus_errors_dont_stop_the_service(self):
        self.emit.side_effect = RuntimeError("no session bus")
        self.service.on_event(p.EVENT_LINK, 1, b"")


if __name__ == "__main__":
    unittest.main()
