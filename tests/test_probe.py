"""mousework probe: read-only queries from SURVEY.md section E."""

import unittest

from mousework import device, models, probe
from mousework import protocol as p

ALL_PLANS = {id(i.plan): i.plan for i in probe.IDENTITIES}.values()


def every_query():
    for plan in ALL_PLANS:
        if plan.link:
            yield plan.link
        yield from plan.always
        yield from plan.mouse


class SafetyTests(unittest.TestCase):
    """The properties that make the probe safe to run on an unknown mouse."""

    def test_every_opcode_is_a_read(self):
        # F1 to F5 all mark queries with bit 7 (survey E.2 to E.5).
        for q in every_query():
            self.assertTrue(q.payload[0] & 0x80, f"{q.name}: {q.payload.hex()}")

    def test_never_send_list(self):
        for q in every_query():
            self.assertNotIn(q.payload[0], probe.NEVER_SEND, q.name)

    def test_payloads_are_short(self):
        for q in every_query():
            self.assertLessEqual(len(q.payload), 2, q.name)

    def test_no_bootloader_identity_is_probed(self):
        bootloaders = {m.bootloader_id for m in models.MODELS}
        bootloaders |= {0x1831, 0x1873, 0x1727, 0x172C, 0xB007}
        for identity in probe.IDENTITIES:
            self.assertNotIn(identity.product_id, bootloaders)

    def test_ids_are_unique(self):
        ids = [i.product_id for i in probe.IDENTITIES]
        self.assertEqual(len(ids), len(set(ids)))

    def test_supported_models_match(self):
        supported = {i.product_id for i in probe.IDENTITIES if i.supported}
        self.assertEqual(supported, {m.product_id for m in models.MODELS})

    def test_model_specific_exclusions(self):
        # survey E.2: these opcodes are not defined on the other F1 models
        def opcodes(pid):
            plan = probe.BY_PRODUCT_ID[pid].plan
            qs = ([plan.link] if plan.link else []) + list(plan.always) + list(plan.mouse)
            return {q.payload[0] for q in qs}
        self.assertFalse({0xAC, 0xAE} & opcodes(0x1830))
        self.assertFalse({0xA0, 0x9E} & opcodes(0x1872))
        self.assertFalse({0xA0, 0x9E, 0x97, 0xAB} & opcodes(0x1726))
        self.assertFalse({0xA0, 0x9E, 0x97, 0xAB} & opcodes(0x172B))


class Replies:
    """Answers queries from a table keyed by the first payload byte."""

    def __init__(self, table):
        self.table = table
        self.sent = []

    def __call__(self, payload):
        self.sent.append(payload)
        self.assert_padded(payload)
        reply = self.table.get(payload[0])
        if reply is None:
            raise device.MouseUnreachable("no response")
        return bytes(reply).ljust(64, b"\0")

    @staticmethod
    def assert_padded(payload):
        assert len(payload) == p.REPORT_LEN, len(payload)


def first_bytes(replies):
    return [s[0] for s in replies.sent]


class PlanTests(unittest.TestCase):
    def test_unlinked_receiver_gets_no_mouse_queries(self):
        replies = Replies({0xE8: [1], 0xD0: [1, 4]})
        results = probe.run_plan(probe.BY_PRODUCT_ID[0x1830].plan, replies)
        self.assertEqual(first_bytes(replies), [0xE8, 0xD0])
        self.assertIn("skipped", results[-1])

    def test_no_link_reply_gets_no_mouse_queries(self):
        replies = Replies({})
        probe.run_plan(probe.BY_PRODUCT_ID[0x1838].plan, replies)
        self.assertEqual(first_bytes(replies), [0xBC, 0x90])

    def test_linked_rival_3_wireless(self):
        cpi = bytes([5, 4]) + b"".join(p.u16(c) for c in (0x04, 0x09, 0x0D, 0x12, 0x17))
        replies = Replies({0xE8: [4], 0xD0: [1, 4], 0x90: [1, 4], 0xAA: [90, 0, 0],
                           0xA0: cpi, 0x96: [4], 0x97: [3], 0xAB: [1, 0, 0x2C, 1, 0xB0, 4],
                           0x9E: [6, 20]})
        results = probe.run_plan(probe.BY_PRODUCT_ID[0x1830].plan, replies)
        decoded = {r["query"]: r.get("decoded") for r in results}
        self.assertEqual(decoded["mouse version"], {"version": "1.04"})
        self.assertEqual(decoded["battery"]["level"], 90)
        self.assertEqual(decoded["cpi table"]["presets"], [400, 800, 1200, 1600, 2000])
        self.assertEqual(decoded["polling"]["hz"], 125)
        self.assertEqual(decoded["power"]["sleep_s"], 1200)

    def test_a_missing_reply_is_not_retried(self):
        replies = Replies({0xE8: [4], 0xD0: [1, 4]})
        results = probe.run_plan(probe.BY_PRODUCT_ID[0x1830].plan, replies)
        self.assertEqual(len(replies.sent), len(set(first_bytes(replies))))
        self.assertIsNone(next(r for r in results if r.get("query") == "battery")["reply"])

    def test_wired_f2_has_no_link_query(self):
        replies = Replies({0x90: [0x90, *b"1.2.3"], 0xAB: [1]})
        results = probe.run_plan(probe.BY_PRODUCT_ID[0x1836].plan, replies)
        self.assertEqual(first_bytes(replies), [0x90, 0xAB])
        self.assertEqual(results[0]["decoded"]["version"], "1.2.3")
        self.assertEqual(results[1]["decoded"]["hz"], 1000)

    def test_f3_receiver_tunnels_mouse_queries(self):
        replies = Replies({0xBC: [0xBC, 1], 0x90: b"0.4.1", 0xD0: b"0.9.2",
                           0xD2: [0xD2, 0x80 | 15]})
        results = probe.run_plan(probe.BY_PRODUCT_ID[0x1838].plan, replies)
        self.assertEqual(first_bytes(replies), [0xBC, 0x90, 0xD0, 0xD2])
        battery = results[-1]["decoded"]
        self.assertEqual((battery["charging"], battery["level"]), (True, 70))

    def test_f3_mouse_unreachable_marker(self):
        replies = Replies({0xBC: [0xBC, 1], 0x90: b"0.4.1", 0xD0: [0x40], 0xD2: [0x40]})
        results = probe.run_plan(probe.BY_PRODUCT_ID[0x1838].plan, replies)
        self.assertEqual(results[-1]["decoded"], {"mouse_unreachable": True})

    def test_f4_cpi_entries(self):
        entry = p.u16(800) + p.u16(800) + bytes([2])
        replies = Replies({0xBC: [0xBC, 1], 0x90: [0x90], 0x92: [0x92, 0, 0xFF],
                           0xAD: bytes([0xAD, 1, 0]) + entry, 0xAB: [0xAB, 1, 2],
                           0xA8: [0xA8]})
        results = probe.run_plan(probe.BY_PRODUCT_ID[0x1890].plan, replies)
        decoded = {r["query"]: r.get("decoded") for r in results}
        self.assertEqual(decoded["cpi table"]["presets"], [{"x": 800, "y": 800, "lift_off": 2}])
        self.assertIsNone(decoded["battery"]["level"])

    def test_wrong_echo_is_flagged(self):
        replies = Replies({0xBC: [0x00, 1]})
        results = probe.run_plan(probe.BY_PRODUCT_ID[0x1890].plan, replies)
        self.assertEqual(results[0]["decoded"]["unexpected_echo"], "0x00")


class DiscoveryTests(unittest.TestCase):
    class Channel:
        def __init__(self, replies):
            self.replies = replies

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            pass

        def query(self, payload, timeout):
            return self.replies(payload)

    def test_only_the_command_node_of_a_known_id_is_queried(self):
        opened = []
        replies = Replies({0xE8: [1], 0xD0: [1, 4]})

        def open_channel(path):
            opened.append(path)
            return self.Channel(replies)

        devices = [
            (3, 0x1038, 0x1830, "/dev/hidraw2", (0xFF00, 1)),
            (3, 0x1038, 0x1830, "/dev/hidraw3", (0xFFC0, 1)),
            (3, 0x1038, 0x1831, "/dev/hidraw4", (0xFFC0, 1)),  # bootloader
            (3, 0x1038, 0x1600, "/dev/hidraw5", (0xFFC0, 1)),  # not in the table
            (5, 0x0111, 0x1872, "/dev/hidraw6", (0x0001, 2)),  # Bluetooth
            (3, 0x046D, 0xC52B, "/dev/hidraw7", (0xFF00, 1)),  # another vendor
        ]
        reports = probe.probe(devices, open_channel)
        self.assertEqual(opened, ["/dev/hidraw3"])
        notes = [r.get("note", "") for r in reports]
        self.assertEqual(sum("nothing sent" in n for n in notes), 3)

    def test_identity_without_a_command_node(self):
        devices = [(3, 0x1038, 0x1836, "/dev/hidraw2", (0x0001, 2))]
        reports = probe.probe(devices, lambda path: self.fail("opened"))
        self.assertIn("no command interface", reports[0]["error"])

    def test_text_report(self):
        devices = [(3, 0x1038, 0x1830, "/dev/hidraw3", (0xFFC0, 1))]
        replies = Replies({0xE8: [1], 0xD0: [1, 4]})
        text = probe.format_text(probe.probe(devices, lambda path: self.Channel(replies)))
        self.assertIn("1038:1830 Rival 3 Wireless", text)
        self.assertIn("receiver version: sent [d0] reply [01 04]", text)


if __name__ == "__main__":
    unittest.main()
