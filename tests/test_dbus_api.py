import json
import unittest
from unittest import mock

from mousework import dbus_api, device


class FakeInvocation:
    def __init__(self):
        self.value = None
        self.error = None

    def return_value(self, value):
        self.value = value

    def return_dbus_error(self, name, message):
        self.error = (name, message)


class FakeStore:
    def __init__(self, names=("Default", "Work")):
        self.profiles = dict.fromkeys(names)


class GetStatusTest(unittest.TestCase):
    def test_returns_the_status_as_json(self):
        api = dbus_api.Api(collect=lambda: {"version": 1, "connection": "receiver"})
        invocation = FakeInvocation()
        api.get_status(invocation)
        self.assertEqual(json.loads(invocation.value.unpack()[0]), {"version": 1, "connection": "receiver"})

    def test_unexpected_failure_is_a_dbus_error(self):
        api = dbus_api.Api(collect=mock.Mock(side_effect=RuntimeError("boom")))
        invocation = FakeInvocation()
        api.get_status(invocation)
        self.assertEqual(invocation.error, (dbus_api.ERROR_FAILED, "boom"))


class UseProfileTest(unittest.TestCase):
    def test_switches_to_the_profile(self):
        switch = mock.Mock()
        store = FakeStore()
        api = dbus_api.Api(store_factory=lambda: store, switch_profile=switch)
        invocation = FakeInvocation()
        api.use_profile(invocation, "Work")
        switch.assert_called_once_with(store, "Work")
        self.assertIsNone(invocation.error)

    def test_unknown_profile(self):
        switch = mock.Mock()
        api = dbus_api.Api(store_factory=FakeStore, switch_profile=switch)
        invocation = FakeInvocation()
        api.use_profile(invocation, "Gaming")
        switch.assert_not_called()
        self.assertEqual(invocation.error[0], dbus_api.ERROR_NO_SUCH_PROFILE)
        self.assertIn("Default, Work", invocation.error[1])

    def test_device_error_is_explained(self):
        switch = mock.Mock(side_effect=device.MouseUnreachable("mouse is asleep"))
        api = dbus_api.Api(store_factory=FakeStore, switch_profile=switch)
        invocation = FakeInvocation()
        api.use_profile(invocation, "Work")
        self.assertEqual(invocation.error, (dbus_api.ERROR_FAILED, "mouse is asleep"))

    def test_introspection_parses(self):
        from gi.repository import Gio
        node = Gio.DBusNodeInfo.new_for_xml(dbus_api.INTROSPECTION)
        methods = [m.name for m in node.interfaces[0].methods]
        self.assertEqual(methods, ["GetStatus", "UseProfile"])


if __name__ == "__main__":
    unittest.main()
