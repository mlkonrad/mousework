import io
import json
import os
import re
import threading
import unittest
from contextlib import redirect_stdout
from unittest import mock

from mousework import cli, device, status
from mousework import protocol as p

DOCS = os.path.join(os.path.dirname(__file__), "..", "docs")
with open(os.path.join(DOCS, "status.schema.json")) as f:
    SCHEMA = json.load(f)
with open(os.path.join(DOCS, "json.md")) as f:
    GUIDE = f.read()


def validate(value, schema, path="$"):
    """The subset of JSON Schema that status.schema.json uses."""
    types = schema.get("type")
    if types:
        types = [types] if isinstance(types, str) else types
        checks = {"object": dict, "array": list, "string": str, "boolean": bool,
                  "null": type(None)}
        ok = any(isinstance(value, int) and not isinstance(value, bool) if t == "integer"
                 else isinstance(value, checks[t]) for t in types)
        assert ok, f"{path}: {value!r} is not {types}"
    if "const" in schema:
        assert value == schema["const"], f"{path}: {value!r} != {schema['const']!r}"
    if "enum" in schema:
        # type() too, since True == 1 in Python
        assert any(value == e and type(value) is type(e) for e in schema["enum"]), \
            f"{path}: {value!r} not in enum"
    if isinstance(value, dict):
        for key in schema.get("required", []):
            assert key in value, f"{path}: missing {key}"
        for key, sub in schema.get("properties", {}).items():
            if key in value:
                validate(value[key], sub, f"{path}.{key}")
    if isinstance(value, list):
        assert len(value) >= schema.get("minItems", 0), f"{path}: too short"
        assert len(value) <= schema.get("maxItems", len(value)), f"{path}: too long"
        for i, item in enumerate(value):
            validate(item, schema.get("items", {}), f"{path}[{i}]")
    if isinstance(value, int) and not isinstance(value, bool):
        assert value >= schema.get("minimum", value), f"{path}: below minimum"
        assert value <= schema.get("maximum", value), f"{path}: above maximum"
    if isinstance(value, str) and "pattern" in schema:
        assert re.search(schema["pattern"], value), f"{path}: {value!r} doesn't match"


class FakeMouse:
    def __init__(self, radio=p.RADIO_LINKED, battery=p.Battery(62, 0),
                 power=p.PowerSettings(idle_sleep_s=600), sleep_after=None, fail_after=None):
        self.radio = radio
        self._battery = battery
        self._power = power
        self.queries = 0
        self.sleep_after = sleep_after  # raise MouseUnreachable from this query on
        self.fail_after = fail_after  # raise DeviceError (EIO) from this query on
        self.closed = False

    def _q(self, value):
        self.queries += 1
        if self.fail_after is not None and self.queries > self.fail_after:
            raise device.DeviceError("read failed: [Errno 5] Input/output error")
        if self.sleep_after is not None and self.queries > self.sleep_after:
            raise device.MouseUnreachable("no response from device")
        return value

    def receiver_version(self):
        return self._q("1.02")

    def radio_status(self):
        return self._q(self.radio)

    def battery(self):
        return self._q(self._battery)

    def mouse_version(self):
        return self._q("1.04")

    def cpi_table(self):
        return self._q(p.CpiTable([400, 800, 1600], 2))

    def power(self):
        return self._q(self._power)

    def polling_hz(self):
        return self._q(1000)

    def close(self):
        self.closed = True


class FakeStore:
    active = "Gaming"
    mouse_may_differ = False
    profiles = {"Default": None, "Gaming": None}


def collect(mouse=None, error=None, bluetooth=False, store=FakeStore, syncing=lambda: None):
    def factory():
        if error:
            raise error
        return mouse
    return status.collect(factory, lambda: bluetooth, store, syncing)


class CollectTests(unittest.TestCase):
    def check(self, result, connection):
        validate(result, SCHEMA)
        self.assertEqual(result["connection"], connection)
        json.dumps(result)  # serialisable

    def test_linked(self):
        mouse = FakeMouse()
        result = collect(mouse)
        self.check(result, "receiver")
        self.assertEqual(result, {
            "version": 1,
            "device": "SteelSeries Rival 3 Wireless",
            "connection": "receiver",
            "error": None,
            "battery": {"level": 62, "state": "discharging"},
            "firmware": {"mouse": "1.04", "receiver": "1.02"},
            "cpi": {"presets": [400, 800, 1600], "active": 800, "active_index": 2},
            "polling_hz": 1000,
            "power": {"high_efficiency": False, "smart_illumination": True,
                      "sleep_minutes": 10},
            "profile": {"active": "Gaming", "saved_to_mouse": True, "available": ["Default", "Gaming"]},
        "syncing": None,
        })
        self.assertTrue(mouse.closed)

    def test_high_efficiency_reports_125_hz(self):
        result = collect(FakeMouse(power=p.PowerSettings(high_efficiency=True)))
        self.check(result, "receiver")
        self.assertEqual(result["polling_hz"], 125)

    def test_unknown_battery_is_null(self):
        result = collect(FakeMouse(battery=p.Battery(p.BATTERY_UNKNOWN, 0)))
        self.check(result, "receiver")
        self.assertIsNone(result["battery"])
        self.assertEqual(result["cpi"]["active"], 800)

    def test_battery_states(self):
        for code, name in status.BATTERY_STATES.items():
            result = collect(FakeMouse(battery=p.Battery(100, code)))
            self.assertEqual(result["battery"]["state"], name)

    def test_no_receiver(self):
        self.check(collect(error=device.NotFound("x")), "no-receiver")

    def test_bluetooth_without_receiver(self):
        self.check(collect(error=device.NotFound("x"), bluetooth=True), "bluetooth")

    def test_bluetooth_with_receiver_plugged_in(self):
        result = collect(FakeMouse(radio=1), bluetooth=True)
        self.check(result, "bluetooth")
        self.assertEqual(result["firmware"]["receiver"], "1.02")

    def test_no_access(self):
        result = collect(error=device.DeviceError("no permission to open /dev/hidraw2"))
        self.check(result, "no-access")
        self.assertIn("permission", result["error"])

    def test_asleep(self):
        result = collect(FakeMouse(radio=0))
        self.check(result, "asleep")
        self.assertEqual(result["firmware"], {"mouse": None, "receiver": "1.02"})
        self.assertIsNone(result["battery"])

    def test_receiver_silent(self):
        result = collect(FakeMouse(sleep_after=0))
        self.check(result, "no-response")
        self.assertIsNotNone(result["error"])

    def test_receiver_silent_while_on_bluetooth(self):
        self.check(collect(FakeMouse(sleep_after=0), bluetooth=True), "bluetooth")

    def test_falls_asleep_mid_query(self):
        result = collect(FakeMouse(sleep_after=4))  # after battery and mouse firmware
        self.check(result, "asleep")
        self.assertEqual(result["firmware"], {"mouse": None, "receiver": "1.02"})
        for key in ("battery", "cpi", "polling_hz", "power"):
            self.assertIsNone(result[key], key)

    def test_unplugged_mid_query(self):
        mouse = FakeMouse(fail_after=3)
        result = collect(mouse)
        self.check(result, "no-receiver")
        self.assertIsNone(result["firmware"]["receiver"])
        self.assertIn("Input/output", result["error"])
        self.assertTrue(mouse.closed)

    def test_undecodable_response_keeps_what_was_read(self):
        mouse = FakeMouse()
        mouse.cpi_table = lambda: (_ for _ in ()).throw(ValueError("invalid CPI table response"))
        result = collect(mouse)
        self.check(result, "receiver")
        self.assertEqual(result["battery"]["level"], 62)
        self.assertIsNone(result["cpi"])
        self.assertEqual(result["error"], "invalid CPI table response")

    def test_temporary_profile(self):
        class Temporary(FakeStore):
            mouse_may_differ = True
        result = collect(FakeMouse(), store=Temporary)
        self.assertEqual(result["profile"], {"active": "Gaming", "saved_to_mouse": False,
                                             "available": ["Default", "Gaming"]})

    def test_damaged_store(self):
        def broken():
            raise json.JSONDecodeError("Expecting value", "", 0)
        result = collect(FakeMouse(), store=broken)
        self.check(result, "receiver")
        self.assertIsNone(result["profile"])


class DocumentationTests(unittest.TestCase):
    """Keep docs/json.md and the schema in step with the code."""

    def test_schema_lists_exactly_the_emitted_fields(self):
        result = collect(FakeMouse())
        self.assertEqual(set(result), set(SCHEMA["properties"]))
        self.assertEqual(set(result), set(SCHEMA["required"]))
        for key in ("battery", "firmware", "cpi", "power", "profile"):
            self.assertEqual(set(result[key]), set(SCHEMA["properties"][key]["properties"]), key)

    def test_connection_states_match(self):
        states = {v for k, v in vars(status).items() if k.startswith("CONNECTION_")}
        self.assertEqual(states, set(SCHEMA["properties"]["connection"]["enum"]))
        for state in states:
            self.assertIn(f"`{state}`", GUIDE)

    def test_guide_documents_every_field(self):
        result = collect(FakeMouse())
        for key, value in result.items():
            self.assertIn(f"`{key}`", GUIDE)
            if isinstance(value, dict):
                for sub in value:
                    self.assertIn(f"`{key}.{sub}`", GUIDE)
        for state in status.BATTERY_STATES.values():
            self.assertIn(f"`{state}`", GUIDE)

    def test_version_matches(self):
        self.assertEqual(SCHEMA["properties"]["version"]["const"], status.FORMAT_VERSION)

    def test_validator_rejects_bad_output(self):
        good = collect(FakeMouse())
        for change in ({"connection": "usb"}, {"battery": {"level": 101, "state": "charging"}},
                       {"polling_hz": 300}, {"version": 2}, {"cpi": {"presets": []}},
                       {"power": {"high_efficiency": 1, "smart_illumination": True,
                                  "sleep_minutes": 5}}):
            with self.subTest(change=change), self.assertRaises(AssertionError):
                validate({**good, **change}, SCHEMA)


class CliTests(unittest.TestCase):
    def run_cli(self, result):
        out = io.StringIO()
        with mock.patch.object(status, "collect", return_value=result), redirect_stdout(out):
            cli.main(["status", "--json"])
        return json.loads(out.getvalue())

    def test_prints_json(self):
        result = collect(FakeMouse())
        self.assertEqual(self.run_cli(result), result)

    def test_no_receiver_still_succeeds(self):
        result = collect(error=device.NotFound("x"))
        self.assertEqual(self.run_cli(result)["connection"], "no-receiver")  # no SystemExit


class QueryErrorTests(unittest.TestCase):
    """A hidraw read error (EIO while the receiver resets) is a DeviceError."""

    def test_read_error(self):
        r, w = os.pipe()
        mouse = device.Mouse.__new__(device.Mouse)
        mouse.fd, mouse._last = w, 0.0
        mouse._lock = threading.Lock()
        with mock.patch.object(device, "LOCK_PATH", os.devnull), \
                mock.patch.object(device.select, "select", return_value=([w], [], [])), \
                mock.patch.object(device.os, "read", side_effect=[BlockingIOError(), OSError(5, "Input/output error")]):
            with self.assertRaises(device.DeviceError):
                mouse.query(p.command(p.READ | p.RECEIVER | p.OP_RADIO_STATUS))
        os.close(r)
        os.close(w)


if __name__ == "__main__":
    unittest.main()
