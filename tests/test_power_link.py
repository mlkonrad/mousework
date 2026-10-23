import unittest
from unittest import mock

from mousework import device


class ScriptedMouse(device.Mouse):
    """A Mouse whose radio status follows a script, one value per check."""

    def __init__(self, links):
        self.links = list(links)
        self.sent = []

    def linked(self):
        return self.links.pop(0) if len(self.links) > 1 else self.links[0]

    def _mouse_send(self, payload):
        self.sent.append(payload)


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


@mock.patch.object(device, "time", new_callable=Clock)
class SetPowerTests(unittest.TestCase):
    def test_waits_for_the_drop_and_the_reconnect(self, clock):
        # turning high efficiency off: linked a while, dropped, back
        mouse = ScriptedMouse([True] * 6 + [False] * 25 + [True])
        mouse.set_power(device.p.PowerSettings())
        self.assertEqual(len(mouse.sent), 1)
        self.assertEqual(mouse.links, [True])  # every scripted check was used

    def test_returns_after_a_while_if_the_link_never_drops(self, clock):
        mouse = ScriptedMouse([True])
        mouse.set_power(device.p.PowerSettings())
        self.assertGreaterEqual(clock.now, device.POWER_DROP_S)

    def test_raises_if_the_mouse_doesnt_come_back(self, clock):
        mouse = ScriptedMouse([False])
        with self.assertRaises(device.MouseUnreachable):
            mouse.set_power(device.p.PowerSettings())
        self.assertLess(clock.now, device.POWER_RELINK_S + 1)


if __name__ == "__main__":
    unittest.main()
