import io
import json
import time
import unittest
from contextlib import redirect_stdout
from unittest import mock

from gi.repository import GLib

from mousework import changes, cli, filterd, status
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


class WatchTest(unittest.TestCase):
    def test_polls_without_signals_until_callback_says_stop(self):
        calls = []

        def callback():
            calls.append(time.monotonic())
            return len(calls) < 3

        changes.watch(callback, poll_s=0.05)
        self.assertEqual(len(calls), 3)

    def test_works_without_a_session_bus(self):
        error = GLib.Error("no bus")
        with mock.patch("gi.repository.Gio.bus_get_sync", side_effect=error):
            changes.watch(lambda: False, poll_s=0.01)


class FollowCliTest(unittest.TestCase):
    def run_cli(self, *flags, rounds=2):
        def watch(callback):
            for _ in range(rounds):
                if callback() is False:
                    return

        out = io.StringIO()
        with mock.patch.object(status, "collect", return_value={"version": 1}), \
                mock.patch.object(changes, "watch", side_effect=watch), redirect_stdout(out):
            cli.main(["status", "--json", *flags])
        return out.getvalue()

    def test_follow_prints_one_line_per_update(self):
        lines = self.run_cli("--follow").splitlines()
        self.assertEqual(len(lines), 3)  # now, then two changes
        self.assertTrue(all(json.loads(line) == {"version": 1} for line in lines))

    def test_wait_prints_once(self):
        self.assertEqual(json.loads(self.run_cli("--wait")), {"version": 1})

    def test_follow_needs_json(self):
        with self.assertRaises(SystemExit) as exit, redirect_stdout(io.StringIO()), \
                mock.patch("sys.stderr", io.StringIO()):
            cli.main(["status", "--follow"])
        self.assertEqual(exit.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
