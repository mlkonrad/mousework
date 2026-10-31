"""Rival 3 Wireless Gen 2 (1038:1872), built from SURVEY.md section C.1."""

import unittest
from unittest import mock

from mousework import device, filterd, models, profiles, status
from mousework import protocol as p
from mousework.profiles import Profile, apply, apply_changes, import_from_device, polling_target

GEN2 = models.RIVAL_3_WIRELESS_GEN_2
R3W = models.RIVAL_3_WIRELESS


class CpiXyTests(unittest.TestCase):
    def test_encode_writes_equal_x_and_y_codes(self):
        table = p.make_cpi_table([400, 800, 1600], 800)
        payload = p.encode_cpi_table_xy(table)
        self.assertEqual(len(payload), p.REPORT_LEN)
        self.assertEqual(payload[:13], bytes([
            0x2C, 3, 2,
            0x04, 0x09, 0x12, 0, 0,  # X
            0x04, 0x09, 0x12, 0, 0,  # Y
        ]))
        self.assertFalse(any(payload[13:]))

    def test_decode_reads_x_codes(self):
        # GG's default: 5 presets, active 3, 400/800/1600/2400/3200 (survey C.1)
        codes = [0x04, 0x09, 0x12, 0x1B, 0x26]
        reply = bytes([5, 3, *codes, *codes]).ljust(64, b"\0")
        table = p.decode_cpi_table_xy(reply)
        self.assertEqual(table, p.CpiTable([400, 800, 1600, 2400, 3200], 3))

    def test_round_trip(self):
        table = p.make_cpi_table([100, 18000], 18000)
        reply = p.encode_cpi_table_xy(table)[1:]  # replies carry no opcode echo
        self.assertEqual(p.decode_cpi_table_xy(reply), table)

    def test_decode_rejects_empty_reply(self):
        with self.assertRaises(ValueError):
            p.decode_cpi_table_xy(bytes(64))


class WireMouse(device.Mouse):
    """A Gen 2 Mouse with canned replies that records what it sends."""

    def __init__(self, replies=None):
        self.model = GEN2
        self.replies = replies or {}
        self.sent = []

    def linked(self):
        return True

    def query(self, payload, timeout=None):
        self.sent.append(payload)
        return self.replies[payload[0]]

    def send(self, payload):
        self.sent.append(payload)


@mock.patch.object(device, "time", mock.Mock(monotonic=lambda: 0.0, sleep=lambda s: None))
class DeviceTests(unittest.TestCase):
    def test_cpi_uses_xy_opcodes(self):
        codes = [0x04, 0x09]
        m = WireMouse({0xAC: bytes([2, 1, *codes, 0, 0, 0, *codes]).ljust(64, b"\0")})
        self.assertEqual(m.cpi_table(), p.CpiTable([400, 800], 1))
        m.set_cpi_table(p.CpiTable([400, 800], 1))
        self.assertEqual([s[0] for s in m.sent], [0xAC, 0x2C])

    def test_power_reads_only_the_sleep_timer(self):
        reply = bytes([1, 50, 0x2C, 0x01, 0x58, 0x02]).ljust(64, b"\0")  # 600 s
        power = WireMouse({0xAB: reply}).power()
        self.assertEqual(power, p.PowerSettings(False, 0, 0, 600))

    def test_power_write_sends_zeros_and_the_sleep_timer(self):
        m = WireMouse()
        m._wait_for_link = lambda linked, timeout: True
        m.set_power(p.PowerSettings(True, 100, 300, 1200))
        self.assertEqual(m.sent[0][:7], bytes([0x2B, 0, 0, 0, 0, 0xB0, 0x04]))

    def test_battery_status_is_not_trusted(self):
        reply = bytes([80, 0, 1]).ljust(64, b"\0")
        battery = WireMouse({0xAA: reply}).battery()
        self.assertEqual((battery.level, battery.status), (80, 0))

    def test_lighting_calls_send_nothing(self):
        m = WireMouse()
        m.set_lighting(p.Lighting())
        m.set_direct_color((1, 2, 3))
        m.restart_lighting()
        self.assertEqual(m.sent, [])

    def test_no_debounce(self):
        with self.assertRaises(ValueError):
            WireMouse().debounce()


class DiscoveryTests(unittest.TestCase):
    def test_finds_the_gen2_receiver(self):
        nodes = {p.COMMAND_USAGE: "/dev/hidraw7", p.EVENT_USAGE: "/dev/hidraw6"}
        with mock.patch.object(device, "find_nodes",
                               lambda model: nodes if model is GEN2 else {}):
            self.assertEqual(device.find_receiver(), (GEN2, nodes))

    def test_nothing_plugged_in(self):
        with mock.patch.object(device, "find_nodes", lambda model: {}):
            self.assertEqual(device.find_receiver(), (None, {}))


class RecordingMouse:
    """Holds what a Gen 2 holds and records the writes, in order."""

    model = GEN2

    def __init__(self, sleep_s=300, hz=1000, table=None):
        self._power = p.PowerSettings(False, 0, 0, sleep_s)
        self._hz = hz
        self._table = table or p.make_cpi_table([400, 800], 400)
        self.writes = []

    def power(self):
        return self._power

    def set_power(self, settings):
        self.writes.append(("power", settings))
        self._power = settings

    def polling_hz(self):
        return self._hz

    def set_polling_hz(self, hz, settle=True):
        self.writes.append(("polling", hz))
        self._hz = hz

    def cpi_table(self):
        return self._table

    def set_cpi_table(self, table):
        self.writes.append(("cpi", table))
        self._table = table

    def __getattr__(self, name):  # buttons, wheel, flash
        return lambda *a, **k: self.writes.append((name,))


def kinds(mouse):
    return [w[0] for w in mouse.writes]


@mock.patch.object(profiles.time, "sleep", lambda s: None)
class ProfileTests(unittest.TestCase):
    def test_polling_target(self):
        on = Profile(high_efficiency=True, polling_hz=500)
        off = Profile(high_efficiency=False, polling_hz=500)
        self.assertEqual(polling_target(on, GEN2), 125)
        self.assertIsNone(polling_target(on, R3W))
        self.assertEqual(polling_target(off, GEN2), 500)
        self.assertEqual(polling_target(off, R3W), 500)

    def test_high_efficiency_writes_125_hz_and_no_power(self):
        mouse = RecordingMouse(sleep_s=300)
        pr = Profile(cpi_presets=[400, 800], active_cpi=400, high_efficiency=True,
                     sleep_minutes=5)
        apply(pr, mouse)
        self.assertNotIn("power", kinds(mouse))
        self.assertIn(("polling", 125), mouse.writes)

    def test_sleep_change_writes_power(self):
        mouse = RecordingMouse(sleep_s=300)
        pr = Profile(cpi_presets=[400, 800], active_cpi=400, sleep_minutes=10)
        apply(pr, mouse)
        self.assertEqual(mouse.writes[0], ("power", p.PowerSettings(False, 0, 0, 600)))

    def test_smart_illumination_alone_writes_nothing(self):
        mouse = RecordingMouse(sleep_s=300)
        before = Profile(cpi_presets=[400, 800], active_cpi=400, smart_illumination=True)
        after = Profile(cpi_presets=[400, 800], active_cpi=400, smart_illumination=False)
        apply_changes(after, before, mouse)
        self.assertEqual(mouse.writes, [])

    def test_leaving_high_efficiency_restores_the_rate(self):
        mouse = RecordingMouse(hz=125)
        before = Profile(cpi_presets=[400, 800], active_cpi=400, high_efficiency=True,
                         polling_hz=500)
        after = Profile(cpi_presets=[400, 800], active_cpi=400, high_efficiency=False,
                        polling_hz=500)
        apply_changes(after, before, mouse)
        self.assertEqual(mouse.writes, [("polling", 500)])

    def test_import_keeps_the_host_side_switch(self):
        mouse = RecordingMouse(sleep_s=1200, hz=500, table=p.make_cpi_table([800], 800))
        pr = Profile(high_efficiency=False, smart_illumination=True)
        import_from_device(pr, mouse)
        self.assertEqual((pr.cpi_presets, pr.active_cpi), ([800], 800))
        self.assertEqual((pr.sleep_minutes, pr.polling_hz), (20, 500))
        self.assertTrue(pr.smart_illumination)  # untouched


class StatusMouse:
    model = GEN2

    def receiver_version(self):
        return "1.05"

    def radio_status(self):
        return p.RADIO_LINKED

    def battery(self):
        return p.Battery(70, 0)

    def mouse_version(self):
        return "1.05"

    def cpi_table(self):
        return p.CpiTable([400, 800], 1)

    def power(self):
        return p.PowerSettings(False, 0, 0, 300)

    def polling_hz(self):
        return 125

    def close(self):
        pass


class StatusTests(unittest.TestCase):
    def collect(self, hem):
        class Store:
            active = "Default"
            mouse_may_differ = False
            profiles = {"Default": None}
            current = Profile(high_efficiency=hem)
        return status.collect(StatusMouse, lambda: False, Store, lambda: None)

    def test_name_and_host_side_high_efficiency(self):
        result = self.collect(hem=True)
        self.assertEqual(result["device"], "SteelSeries Rival 3 Wireless Gen 2")
        self.assertEqual(result["power"], {"high_efficiency": True,
                                           "smart_illumination": False, "sleep_minutes": 5})
        self.assertEqual(result["polling_hz"], 125)

    def test_high_efficiency_off(self):
        self.assertFalse(self.collect(hem=False)["power"]["high_efficiency"])


class BatterySettleTests(unittest.TestCase):
    def test_levels_right_after_link_up_are_ignored(self):
        service = filterd.Service()
        service._settle_s = GEN2.battery_settle_s
        service._linked_at = 100.0
        self.assertTrue(service.battery_settling(now=105.0))
        self.assertFalse(service.battery_settling(now=110.5))

    def test_rival_3_wireless_never_settles(self):
        service = filterd.Service()
        service._settle_s = R3W.battery_settle_s
        service._linked_at = 100.0
        self.assertFalse(service.battery_settling(now=100.5))


if __name__ == "__main__":
    unittest.main()
