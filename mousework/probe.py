"""Read-only identification of SteelSeries mice (mousework probe).

Sends only the queries that the model survey (../spec/SURVEY.md section E)
lists as safe for families F1 to F5, and prints what came back, so the owner
of a mouse Mousework doesn't support yet can report it. Nothing here writes a
setting. The rules from survey E.1, in the order this module applies them:

1. The family and query set come from the USB ID alone; no opcode is tried
   to find out what a device is.
2. The command interface is the hidraw node whose report descriptor has the
   usage page 0xFFC0, usage 0x0001 collection (survey B); interface numbers
   are ignored.
3. Stale input reports are drained, then one query is sent and one reply is
   awaited for at most 0.5 s, with at least 30 ms between queries.
4. A query without a reply is recorded as such and never retried.
5. Every payload is the listed bytes followed by zeros.
6. On a receiver the link status is read first, and queries meant for the
   mouse are sent only while it is linked.

Bootloader identities, Bluetooth identities and SteelSeries devices not in
the table below are listed but never sent anything.
"""

import glob
import os
from dataclasses import dataclass, field

from . import device
from . import protocol as p

REPLY_TIMEOUT_S = 0.5  # survey E.1 rule 3
VENDOR = 0x1038

# Opcodes no probe may send even though bit 7 is set: factory resets on F4
# (0x91 0x05) and F5 (0xFD), and the receiver unique ID (0xE3), which isn't
# needed to identify a model (survey E.2, E.5). tests/test_probe.py checks
# the tables against this list.
NEVER_SEND = {0x91, 0xFD, 0xE3}


# --- decoding helpers; every decoder takes the reply R and returns a dict ---

def _le16(r, offset):
    return int.from_bytes(r[offset:offset + 2], "little")


def _ascii(data):
    text = bytes(data).split(b"\0", 1)[0]
    return text.decode("ascii", "replace").strip()


def _echo(expected, r, offset=0):
    """A note when the reply doesn't start with the echoed opcode."""
    if r[offset] != expected:
        return {"unexpected_echo": f"0x{r[offset]:02x}"}
    return {}


def _f1_radio(r):
    states = {0: "not linked", 1: "not linked", 4: "linked", 5: "bluetooth"}
    return {"radio_status": r[0], "meaning": states.get(r[0], "unknown")}


def _f1_version(r):
    return {"version": f"{r[0]}.{r[1]:02d}"}


def _f1_version_minor_major(r):  # Rival 650 Wireless (survey C.2)
    return {"version": f"{r[1]}.{r[0]:02d}"}


def _f1_battery(r):
    return {"level": _le16(r, 0), "charge_status": r[2]}


def _f1_cpi(r):
    t = p.decode_cpi_table(r)
    return {"presets": t.presets, "active_index": t.active}


def _f1_cpi_xy(r):
    t = p.decode_cpi_table_xy(r)
    return {"presets": t.presets, "active_index": t.active,
            "y_codes_differ": bytes(r[2:7]) != bytes(r[7:12])}


def _f1_polling(r):
    return {"level": r[0], "hz": p.POLLING_LEVELS.get(r[0])}


def _f1_power(r):
    pw = p.decode_power(r)
    return {"high_efficiency": pw.high_efficiency, "movement_saving": pw.movement_saving,
            "idle_lighting_s": pw.idle_lighting_s, "sleep_s": pw.idle_sleep_s}


def _f1_power_sleep(r):  # Gen 2: only R[4..5] is defined (survey C.1)
    return {"sleep_s": _le16(r, 4), "bytes_0_3": bytes(r[0:4]).hex(" ")}


def _f1_wireless_mode(r):
    return {"redundancy": r[0], "bluetooth_boost": r[1]}


def _f1_debounce(r):
    return {"make": r[0], "break": r[1]}


def _f1_link_nonzero(r):
    return {"link_status": r[0], "meaning": "linked" if r[0] else "not linked"}


def _f1_active_preset(r):
    return {"active_preset": r[0]}


def _f2_version(r):
    return {**_echo(0x90, r), "version": _ascii(r[1:])}


def _f2_polling(r):
    hz = {1: 1000, 2: 500, 3: 250, 4: 125}
    return {"level": r[0], "hz": hz.get(r[0])}


def _f3_connection(r):
    return {**_echo(0xBC, r), "linked": r[1] == 1}


def _f3_version(r):
    if r[0] == 0x40:
        return {"mouse_unreachable": True}
    return {"version": _ascii(r)}


def _f3_battery(r):
    if r[0] == 0x40:
        return {"mouse_unreachable": True}
    raw = r[1] & 0x7F
    return {"charging": bool(r[1] & 0x80), "raw": raw,
            "level": 5 * (raw - 1) if 1 <= raw <= 21 else None}


def _f4_connection(r):
    return {**_echo(0xBC, r), "linked": r[1] == 1}


def _f4_version(r):
    strings = [_ascii(r[1 + 12 * i:13 + 12 * i]) for i in range(3)]
    return {**_echo(0x90, r), "versions": [s for s in strings if s]}


def _f4_battery(r):
    return {**_echo(0x92, r), "charge_status": r[1],
            "level": None if r[2] == 0xFF else r[2]}


def _f4_cpi(r):
    entries = []
    for i in range(min(r[1], 5)):
        o = 3 + 5 * i
        entries.append({"x": _le16(r, o), "y": _le16(r, o + 2), "lift_off": r[o + 4]})
    return {**_echo(0xAD, r), "count": r[1], "active_index_0": r[2], "presets": entries}


def _f4_polling(r):
    # The level-to-Hz mapping is unknown (survey S10), so report levels only.
    return {**_echo(0xAB, r), "wireless_level": r[1], "wired_level": r[2]}


def _f4_high_efficiency(r):
    return {**_echo(0xA8, r), "mode": r[1], "rate": r[2],
            "timeout": int.from_bytes(r[3:7], "little"), "auto": r[7], "battery_limit": r[8]}


def _f5_connection(r):
    return {**_echo(0xBC, r), "status": r[1], "linked": r[2] == 1}


def _f5_version(r):
    return {**_echo(0x90, r), "status": r[1],
            "receiver": _ascii(r[2:32]), "mouse": _ascii(r[32:62])}


def _f5_battery(r):
    return {**_echo(0x92, r), "status": r[1], "mouse_level": r[2], "charging": r[3],
            "charger_level": r[4]}


def _f5_model(r):
    return {**_echo(0xC4, r), "status": r[1],
            "model": None if r[2] == 0xFF else r[2]}


def _f5_cpi(r):
    entries = []
    for i in range(min(r[2], 5)):
        o = 4 + 6 * i
        entries.append({"x": _le16(r, o), "y": _le16(r, o + 2),
                        "lift_off": r[o + 4], "landing": r[o + 5]})
    return {**_echo(0xB4, r), "status": r[1], "count": r[2], "active_index_0": r[3],
            "presets": entries}


def _f5_polling_profiles(r):
    entries = [{"report_rate": r[4 + 2 * i], "polling_rate": r[5 + 2 * i]}
               for i in range(min(r[2], 5))]
    return {**_echo(0xAD, r), "status": r[1], "count": r[2], "active_index_0": r[3],
            "profiles": entries}


# --- the probe sets (survey E.2 to E.5) ---

@dataclass(frozen=True)
class Query:
    name: str
    payload: bytes  # the listed bytes; zero padding is added when sent
    decode: object  # callable(reply) -> dict


@dataclass(frozen=True)
class Plan:
    """Queries for one USB identity, in the order they are sent."""
    link: Query = None  # read first; None for a wired mouse
    linked: object = None  # callable(decoded link reply) -> bool
    always: tuple = ()  # receiver queries, sent whatever the link
    mouse: tuple = ()  # sent only when there is no link query or it says linked


def Q(name, data, decode):
    return Query(name, bytes(data), decode)


# F1, Rival 3 Wireless and Gen 2 (survey E.2)
_R3W = Plan(
    link=Q("radio status", [0xE8], _f1_radio), linked=lambda d: d["radio_status"] == 4,
    always=(Q("receiver version", [0xD0], _f1_version),),
    mouse=(Q("mouse version", [0x90], _f1_version),
           Q("battery", [0xAA, 0x01], _f1_battery),
           Q("cpi table", [0xA0], _f1_cpi),
           Q("active preset", [0x96], _f1_active_preset),
           Q("polling", [0x97], _f1_polling),
           Q("power", [0xAB], _f1_power),
           Q("debounce", [0x9E], _f1_debounce)))
_R3W_GEN2 = Plan(
    link=Q("radio status", [0xE8], _f1_radio), linked=lambda d: d["radio_status"] == 4,
    always=(Q("receiver version", [0xD0], _f1_version),),
    mouse=(Q("mouse version", [0x90], _f1_version),
           Q("battery", [0xAA, 0x01], _f1_battery),
           Q("cpi table", [0xAC], _f1_cpi_xy),
           Q("polling", [0x97], _f1_polling),
           Q("power", [0xAB], _f1_power_sleep),
           Q("wireless power mode", [0xAE], _f1_wireless_mode)))
_R650_MOUSE_QUERIES = (Q("mouse version", [0x90], _f1_version_minor_major),
                       Q("battery", [0xAA, 0x01], _f1_battery),
                       Q("active preset", [0x96], _f1_active_preset))
_R650_RECEIVER = Plan(
    link=Q("link status", [0xDD], _f1_link_nonzero), linked=lambda d: d["link_status"] != 0,
    mouse=_R650_MOUSE_QUERIES)
_R650_WIRED = Plan(mouse=_R650_MOUSE_QUERIES)  # GG assumes the cabled mouse is linked

# F2, wired (survey E.3)
_F2 = Plan(mouse=(Q("version", [0x90], _f2_version),
                  Q("polling", [0xAB], _f2_polling)))

# F3 (survey E.4): through the receiver the mouse queries carry the 0x40 bit
_F3_RECEIVER = Plan(
    link=Q("connection", [0xBC], _f3_connection), linked=lambda d: d["linked"],
    always=(Q("receiver version", [0x90, 0x00], _f3_version),),
    mouse=(Q("mouse version", [0xD0, 0x00], _f3_version),
           Q("battery", [0xD2], _f3_battery)))
_F3_WIRED = Plan(mouse=(Q("version", [0x90, 0x00], _f3_version),
                        Q("battery", [0x92], _f3_battery),
                        Q("connection", [0xBC], _f3_connection)))

# F4 and F5 (survey E.5). The survey lists these bytes without a tunnel bit;
# they are sent exactly as listed.
_F4_MOUSE_QUERIES = (Q("battery", [0x92], _f4_battery),
                     Q("cpi table", [0xAD], _f4_cpi),
                     Q("polling", [0xAB], _f4_polling),
                     Q("high efficiency mode", [0xA8], _f4_high_efficiency))
_F4_RECEIVER = Plan(
    link=Q("connection", [0xBC], _f4_connection), linked=lambda d: d["linked"],
    always=(Q("version", [0x90, 0x00], _f4_version),),
    mouse=_F4_MOUSE_QUERIES)
_F4_WIRED = Plan(mouse=(Q("connection", [0xBC], _f4_connection),
                        Q("version", [0x90, 0x00], _f4_version)) + _F4_MOUSE_QUERIES)
_F5 = Plan(
    link=Q("connection", [0xBC], _f5_connection), linked=lambda d: d["linked"],
    always=(Q("version", [0x90, 0x00], _f5_version),),
    mouse=(Q("device model", [0xC4], _f5_model),
           Q("battery", [0x92], _f5_battery),
           Q("cpi table", [0xB4], _f5_cpi),
           Q("polling profiles", [0xAD], _f5_polling_profiles)))


@dataclass(frozen=True)
class Identity:
    product_id: int
    name: str
    family: str
    kind: str  # "receiver", "wired mouse" or "base station"
    plan: Plan = field(repr=False)
    supported: bool = False  # Mousework can configure it


def _pair(rx, mouse, name, family, rx_plan, wired_plan):
    return [Identity(rx, name, family, "receiver", rx_plan),
            Identity(mouse, name, family, "wired mouse", wired_plan)]


# survey A.1, families F1 to F5
IDENTITIES = [
    Identity(0x1830, "Rival 3 Wireless", "F1", "receiver", _R3W, supported=True),
    Identity(0x1872, "Rival 3 Wireless Gen 2", "F1", "receiver", _R3W_GEN2, supported=True),
    Identity(0x1726, "Rival 650 Wireless", "F1", "receiver", _R650_RECEIVER),
    Identity(0x172B, "Rival 650 Wireless", "F1", "wired mouse", _R650_WIRED),
    Identity(0x1836, "Aerox 3 (2020)", "F2", "wired mouse", _F2),
    Identity(0x1850, "Aerox 5", "F2", "wired mouse", _F2),
    Identity(0x183C, "Rival 5", "F2", "wired mouse", _F2),
    Identity(0x183E, "Rival 5 Destiny 2 Edition", "F2", "wired mouse", _F2),
    Identity(0x184D, "Prime Mini", "F2", "wired mouse", _F2),
    Identity(0x1870, "Rival 3 Gen 2 (wired)", "F2", "wired mouse", _F2),
    *_pair(0x1838, 0x183A, "Aerox 3 Wireless", "F3", _F3_RECEIVER, _F3_WIRED),
    *_pair(0x1878, 0x187A, "CS2 Dragon Lore Edition", "F3", _F3_RECEIVER, _F3_WIRED),
    *_pair(0x1852, 0x1854, "Aerox 5 Wireless", "F3", _F3_RECEIVER, _F3_WIRED),
    *_pair(0x185C, 0x185E, "Aerox 5 Wireless Destiny 2 Edition", "F3",
           _F3_RECEIVER, _F3_WIRED),
    *_pair(0x1860, 0x1862, "Aerox 5 Wireless Diablo IV Edition", "F3",
           _F3_RECEIVER, _F3_WIRED),
    *_pair(0x1858, 0x185A, "Aerox 9 Wireless", "F3", _F3_RECEIVER, _F3_WIRED),
    *_pair(0x1874, 0x1876, "Aerox 9 Wireless WOW Edition", "F3", _F3_RECEIVER, _F3_WIRED),
    *_pair(0x1840, 0x1842, "Prime Wireless", "F3", _F3_RECEIVER, _F3_WIRED),
    *_pair(0x1848, 0x184A, "Prime Mini Wireless", "F3", _F3_RECEIVER, _F3_WIRED),
    *_pair(0x1890, 0x1892, "Aerox 3 Wireless Gen 2", "F4", _F4_RECEIVER, _F4_WIRED),
    Identity(0x1880, "Sensei Pro / Rival Pro series", "F5", "base station", _F5),
    Identity(0x1882, "Sensei Pro / Rival Pro series", "F5", "receiver", _F5),
]
BY_PRODUCT_ID = {i.product_id: i for i in IDENTITIES}


# --- running ---

def _hid_devices():
    """(bus, vendor, product, hidraw path or None, usage) for every HID device."""
    found = []
    for sys_path in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            with open(os.path.join(sys_path, "device/uevent")) as f:
                hid_id = next((line.split("=", 1)[1].strip() for line in f
                               if line.startswith("HID_ID=")), None)
            with open(os.path.join(sys_path, "device/report_descriptor"), "rb") as f:
                usage = device._top_level_usage(f.read())
        except (OSError, StopIteration):
            continue
        if not hid_id:
            continue
        bus, vendor, product = (int(x, 16) for x in hid_id.split(":"))
        found.append((bus, vendor, product, "/dev/" + os.path.basename(sys_path), usage))
    return found


def run_plan(plan, query):
    """Send a plan's queries through query(payload) -> reply; return result dicts.

    query raises device.MouseUnreachable when nothing comes back in time.
    """
    results = []

    def send(q):
        result = {"query": q.name, "sent": q.payload.hex(" ")}
        try:
            reply = bytes(query(p.command(*q.payload)))
        except device.MouseUnreachable:
            result["reply"] = None  # survey E.1 rule 4: no retry
            results.append(result)
            return None
        result["reply"] = reply.rstrip(b"\0").hex(" ") or "00"
        try:
            result["decoded"] = q.decode(reply.ljust(p.REPORT_LEN, b"\0"))
        except (ValueError, IndexError) as err:
            result["decode_error"] = str(err)
        results.append(result)
        return result.get("decoded")

    linked = True
    if plan.link is not None:
        decoded = send(plan.link)
        linked = bool(decoded) and bool(plan.linked(decoded))
    for q in plan.always:
        send(q)
    if linked:
        for q in plan.mouse:
            send(q)
    elif plan.mouse:
        results.append({"skipped": [q.name for q in plan.mouse],
                        "reason": "mouse not linked (survey E.1 rule 6)"})
    return results


def probe(devices=None, open_channel=None):
    """Probe every SteelSeries device found. Returns a list of report dicts."""
    devices = _hid_devices() if devices is None else devices
    open_channel = open_channel or (lambda path: device.Mouse(path))
    reports, seen, without_command = [], set(), {}
    for bus, vendor, product, path, usage in devices:
        if vendor == device.BLUETOOTH_VENDOR_ID and bus == device.BUS_BLUETOOTH:
            key = ("bt", product)
            if key not in seen:
                seen.add(key)
                reports.append({"usb_id": f"{vendor:04x}:{product:04x}", "bus": "bluetooth",
                                "note": "Bluetooth identity; listed only, nothing sent"})
            continue
        if vendor != VENDOR or bus != 0x0003:
            continue
        identity = BY_PRODUCT_ID.get(product)
        if identity is None:
            if product not in seen:
                seen.add(product)
                reports.append({"usb_id": f"{vendor:04x}:{product:04x}", "bus": "usb",
                                "note": "not in the probe table (other family, bootloader "
                                        "or not a mouse); listed only, nothing sent"})
            continue
        if usage != p.COMMAND_USAGE or product in seen:
            without_command.setdefault(product, identity)
            continue  # survey E.1 rule 2: only the 0xFFC0/0x0001 collection
        seen.add(product)
        report = {"usb_id": f"{vendor:04x}:{product:04x}", "bus": "usb",
                  "name": identity.name, "family": identity.family, "kind": identity.kind,
                  "supported": identity.supported, "node": path}
        try:
            with open_channel(path) as channel:
                report["results"] = run_plan(
                    identity.plan, lambda payload: channel.query(payload, REPLY_TIMEOUT_S))
        except device.DeviceError as err:
            report["error"] = str(err)
            if "permission" in str(err):
                report["error"] += " (try: sudo mousework probe)"
        reports.append(report)
    for product, identity in without_command.items():
        if product not in seen:
            reports.append({"usb_id": f"{VENDOR:04x}:{product:04x}", "bus": "usb",
                            "name": identity.name, "family": identity.family,
                            "kind": identity.kind, "supported": identity.supported,
                            "node": None, "error": "no command interface (usage page "
                            "0xFFC0) found; nothing sent"})
    return reports


def _version():
    """This copy's version: a source checkout's pyproject.toml, else the package's."""
    pyproject = os.path.join(os.path.dirname(__file__), "..", "pyproject.toml")
    try:
        with open(pyproject) as f:
            for line in f:
                if line.startswith("version = "):
                    return line.split("=", 1)[1].strip().strip('"') + " (source)"
    except OSError:
        pass
    try:
        from importlib.metadata import version
        return version("mousework")
    except Exception:
        return "unknown"


def format_text(reports):
    lines = [f"mousework probe, Mousework {_version()}, kernel {os.uname().release}"]
    if not reports:
        lines.append("No SteelSeries device found.")
    for r in reports:
        lines.append("")
        if "name" not in r:
            lines.append(f"{r['usb_id']} ({r['bus']}): {r['note']}")
            continue
        status = "supported" if r["supported"] else "not supported yet"
        lines.append(f"{r['usb_id']} {r['name']}, {r['kind']}, family {r['family']}, "
                     f"{status} ({r['node']})")
        if "error" in r:
            lines.append(f"  error: {r['error']}")
            continue
        for res in r["results"]:
            if "skipped" in res:
                lines.append(f"  skipped: {', '.join(res['skipped'])}: {res['reason']}")
                continue
            reply = res["reply"] if res["reply"] is not None else "no reply"
            lines.append(f"  {res['query']}: sent [{res['sent']}] reply [{reply}]")
            if "decoded" in res:
                lines.append("    " + ", ".join(f"{k}={v}" for k, v in res["decoded"].items()))
            if "decode_error" in res:
                lines.append(f"    could not decode: {res['decode_error']}")
    lines.append("")
    lines.append("Decoded values follow the specification and are unverified for every "
                 "model not marked supported.")
    return "\n".join(lines)
