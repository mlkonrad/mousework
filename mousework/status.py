"""Machine-readable status (`mousework status --json`), documented in docs/json.md.

Version 1. Fields may be added in later versions of format 1; existing fields
are never renamed, removed or given a different type without bumping
FORMAT_VERSION.
"""

from . import device, models, sync
from . import protocol as p
from .profiles import Store

FORMAT_VERSION = 1
DEVICE_NAME = models.DEFAULT.name  # until a receiver or Bluetooth mouse says otherwise

CONNECTION_RECEIVER = "receiver"
CONNECTION_BLUETOOTH = "bluetooth"
CONNECTION_ASLEEP = "asleep"
CONNECTION_NO_RECEIVER = "no-receiver"
CONNECTION_NO_ACCESS = "no-access"
CONNECTION_NO_RESPONSE = "no-response"

BATTERY_STATES = {0: "discharging", 1: "charging", 2: "charged"}  # spec 5


def _store(store_factory):
    try:
        return store_factory()
    except (OSError, ValueError, KeyError):  # unreadable or damaged profiles.json
        return None


def _profile(store):
    if store is None:
        return None
    return {"active": store.active, "saved_to_mouse": not store.mouse_may_differ,
            "available": list(store.profiles)}


def _skeleton(profile, syncing, name=DEVICE_NAME):
    return {
        "version": FORMAT_VERSION,
        "device": name,
        "connection": None,
        "error": None,
        "battery": None,
        "firmware": {"mouse": None, "receiver": None},
        "cpi": None,
        "polling_hz": None,
        "power": None,
        "profile": profile,
        "syncing": syncing,
    }


def collect(mouse_factory=device.Mouse, bluetooth_present=device.bluetooth_present,
            store_factory=Store, syncing=sync.current, bluetooth_model=device.bluetooth_model):
    """Return the status dict. Never raises for device states."""
    store = _store(store_factory)
    profile = _profile(store)
    syncing = syncing()
    status = _skeleton(profile, syncing)
    try:
        mouse = mouse_factory()
    except device.NotFound:
        if bluetooth_present():
            status["connection"] = CONNECTION_BLUETOOTH
            status["device"] = (bluetooth_model() or models.DEFAULT).name
        else:
            status["connection"] = CONNECTION_NO_RECEIVER
        return status
    except device.DeviceError as err:  # permission denied, usually no udev rule
        status["connection"] = CONNECTION_NO_ACCESS
        status["error"] = str(err)
        return status
    model = models.of(mouse)
    status["device"] = model.name
    # On the Gen 2 high efficiency mode is a host setting (survey C.1).
    host_hem = (model.host_high_efficiency and store is not None
                and store.current.high_efficiency)
    try:
        _read(mouse, status, bluetooth_present, host_hem)
    except device.DeviceError as err:  # unplugged or reset mid-query
        status = _skeleton(profile, syncing, model.name)
        status["connection"] = CONNECTION_NO_RECEIVER
        status["error"] = str(err)
    finally:
        mouse.close()
    return status


def _read(mouse, status, bluetooth_present, host_hem=False):
    try:
        status["firmware"]["receiver"] = mouse.receiver_version()
        radio = mouse.radio_status()
    except device.MouseUnreachable as err:  # the receiver itself is silent
        if bluetooth_present():  # the mouse works; only the receiver is stuck
            status["connection"] = CONNECTION_BLUETOOTH
        else:
            status["connection"] = CONNECTION_NO_RESPONSE
            status["error"] = str(err)
        return
    if radio != p.RADIO_LINKED:
        status["connection"] = (CONNECTION_BLUETOOTH if bluetooth_present()
                                else CONNECTION_ASLEEP)
        return
    status["connection"] = CONNECTION_RECEIVER
    try:
        battery = mouse.battery()
        if battery.known:
            status["battery"] = {"level": battery.level,
                                 "state": BATTERY_STATES.get(battery.status, "discharging")}
        status["firmware"]["mouse"] = mouse.mouse_version()
        table = mouse.cpi_table()
        status["cpi"] = {"presets": table.presets, "active": table.active_cpi,
                         "active_index": table.active}
        power = mouse.power()
        status["power"] = {"high_efficiency": power.high_efficiency or host_hem,
                           "smart_illumination": power.smart_illumination,
                           "sleep_minutes": power.idle_sleep_s // 60}
        # High efficiency mode fixes the rate at 125 Hz and its readback isn't
        # meaningful (spec 3.2). With the host-side mode the rate is real.
        status["polling_hz"] = 125 if power.high_efficiency else mouse.polling_hz()
    except device.MouseUnreachable:
        # The mouse went to sleep between queries.
        status.update(connection=CONNECTION_ASLEEP, battery=None, cpi=None,
                      polling_hz=None, power=None)
        status["firmware"]["mouse"] = None
    except ValueError as err:  # a response that doesn't decode; keep what was read
        status["error"] = str(err)
