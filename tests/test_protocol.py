import unittest

from mousework import protocol as p
from mousework.profiles import Profile


class CpiTests(unittest.TestCase):
    def test_decode_device_sample(self):
        # §3.1 device sample
        r = bytes.fromhex("05 03 04 00 09 00 0d 00 12 00 17 00").ljust(64, b"\0")
        table = p.decode_cpi_table(r)
        self.assertEqual(table.presets, [400, 800, 1200, 1600, 2000])
        self.assertEqual(table.active_cpi, 1200)

    def test_encode_sorts_and_dedupes(self):
        table = p.make_cpi_table([1600, 400, 800, 400], 800)
        self.assertEqual(table.presets, [400, 800, 1600])
        self.assertEqual(table.active, 2)
        cmd = p.encode_cpi_table(table)
        self.assertEqual(cmd[:13], bytes.fromhex("20 03 02 0400 0900 1200 0000 0000"))
        self.assertEqual(len(cmd), 64)

    def test_table_edges(self):
        self.assertEqual(p.cpi_to_code(100), 0x00)
        self.assertEqual(p.cpi_to_code(18000), 0xD6)
        self.assertEqual(p.code_to_cpi(0x5F), 8000)
        with self.assertRaises(ValueError):
            p.cpi_to_code(150)

    def test_round_trip_all(self):
        for cpi in range(100, 18001, 100):
            self.assertEqual(p.code_to_cpi(p.cpi_to_code(cpi)), cpi)


class PowerTests(unittest.TestCase):
    def test_device_sample(self):
        # §3.3: 01 64 2c01 b004
        r = bytes.fromhex("01 64 2c 01 b0 04").ljust(64, b"\0")
        power = p.decode_power(r)
        self.assertEqual(power, p.PowerSettings(True, 100, 300, 1200))
        self.assertEqual(p.encode_power(power)[:7], bytes.fromhex("2b 01 64 2c 01 b0 04"))


class BatteryTests(unittest.TestCase):
    def test_device_sample(self):
        bat = p.decode_battery(bytes.fromhex("20 00 00").ljust(64, b"\0"))
        self.assertEqual((bat.level, bat.status, bat.known), (32, 0, True))


class ButtonTests(unittest.TestCase):
    def test_defaults(self):
        cmd = p.encode_buttons({})
        self.assertEqual(cmd[0], 0x19)
        self.assertEqual([cmd[1 + 5 * i] for i in range(7)], [1, 2, 3, 4, 5, 0x30, 0])
        wheel = p.encode_wheel({})
        self.assertEqual(wheel[:11], bytes([0x1A, 0x31, 0, 0, 0, 0, 0x32, 0, 0, 0, 0]))

    def test_actions_round_trip(self):
        for text in ("back", "cpi", "disabled", "media:mute", "key:ctrl+shift+t", "key:f5"):
            self.assertEqual(p.format_action(p.parse_action(text)), text)
        self.assertEqual(p.parse_action("key:ctrl+c").keys, (0xE0, 0x06, 0, 0))

    def test_rejects_two_keys(self):
        with self.assertRaises(ValueError):
            p.parse_action("key:a+b")


class LightingTests(unittest.TestCase):
    def test_default_shift_record(self):
        record = p.encode_effect_record(p.Lighting())
        self.assertEqual(len(record), 92)
        self.assertEqual(int.from_bytes(record[0:4], "little"), 10000)
        self.assertEqual(record[16], p.OVERFLOW_WRAP)
        self.assertEqual(record[24], 4)  # 3 colours + 1
        self.assertEqual(record[25:28], bytes([255, 55, 0]))
        self.assertEqual(record[28:32], bytes([255, 55, 0, 0]))
        self.assertEqual(record[32:36], bytes([0, 0, 0, 127]))  # trunc(50 * 2.55)
        self.assertEqual(record[40:44], bytes([255, 55, 0, 2]))  # trunc(1 * 2.55)

    def test_steady(self):
        record = p.encode_effect_record(p.Lighting(effect=p.EFFECT_STEADY, steady_color=(1, 2, 3)))
        self.assertEqual(record[16], p.OVERFLOW_HOLD)
        self.assertEqual(record[24], 1)
        self.assertEqual(record[28:32], bytes([1, 2, 3, 0]))

    def _sections(self, record):
        return [(tuple(record[28 + 4 * i:31 + 4 * i]), record[31 + 4 * i])
                for i in range(record[24])]

    def test_breathe_spec_examples(self):
        red, blue, black = (255, 0, 0), (0, 0, 255), (0, 0, 0)
        one = p.encode_effect_record(p.Lighting(effect=p.EFFECT_BREATHE,
                                                stops=[p.ColorStop(red, 0)]))
        self.assertEqual(one[25:28], bytes(red))
        self.assertEqual(self._sections(one), [(red, 0), (black, 127), (red, 127)])
        two = p.encode_effect_record(p.Lighting(effect=p.EFFECT_BREATHE, stops=[
            p.ColorStop(red, 0), p.ColorStop(blue, 50)]))
        self.assertEqual(self._sections(two),
                         [(red, 0), (black, 63), (blue, 63), (black, 63), (red, 63)])

    def test_full_gap_truncates(self):
        self.assertEqual(p._section_len(100), 254)

    def test_upload_chunks(self):
        cmds = p.encode_effect_upload(bytes(range(92)))
        self.assertEqual(cmds[0][:6], bytes.fromhex("03 00 0000 3000"))
        self.assertEqual(cmds[1][:6], bytes.fromhex("03 00 3000 2c00"))
        self.assertEqual(cmds[1][6:50], bytes(range(48, 92)))
        self.assertEqual(cmds[2][:10], bytes.fromhex("05 00 10ff 00000000 5c00"))
        self.assertEqual(cmds[3][:7], bytes.fromhex("1c 00 5500 0e01 01"))


class FakeMouse:
    def __init__(self):
        self.calls = []

    def power(self):
        return p.PowerSettings()

    def __getattr__(self, name):
        return lambda *a, **k: self.calls.append(name)


class ProfileTests(unittest.TestCase):
    def test_unmanaged_lighting_and_buttons_not_written(self):
        from mousework.profiles import apply, resend_volatile
        import mousework.profiles as profiles
        profiles.time.sleep = lambda s: None
        m = FakeMouse()
        apply(Profile(), m)
        self.assertNotIn("set_lighting", m.calls)
        self.assertNotIn("set_buttons", m.calls)
        self.assertIn("set_cpi_table", m.calls)
        pr = Profile(managed=["lighting", "buttons"])
        m = FakeMouse()
        resend_volatile(pr, m)
        self.assertEqual(m.calls, ["set_lighting", "set_buttons", "set_wheel"])

    def test_json_round_trip(self):
        pr = Profile()
        pr.buttons["back"] = "key:ctrl+c"
        pr.lighting.effect = p.EFFECT_BREATHE
        again = Profile.from_json(pr.to_json())
        self.assertEqual(again, pr)
        again.validate()


if __name__ == "__main__":
    unittest.main()
