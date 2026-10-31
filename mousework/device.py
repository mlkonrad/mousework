"""hidraw transport for the supported mice (spec 1.2, spec 2; models.py)."""

import contextlib
import fcntl
import glob
import os
import select
import threading
import time

from . import models
from . import protocol as p

COMMAND_GAP_S = 0.030  # spec 2.3
# Shared by every mousework process (app, CLI, service): responses carry no
# opcode echo (spec 2.1), so two processes querying at once could read each
# other's answers. Each query holds this lock from request to response.
LOCK_PATH = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "mousework.lock")
QUERY_TIMEOUT_S = 1.0
# Every power write drops the radio link (firmware 1.04, measured 2026-10-23):
# turning high efficiency on drops it at once for about 2.5 s, turning it off
# keeps it about 1.2 s and then drops it for about 5 s.
POWER_DROP_S = 3.0
POWER_RELINK_S = 15.0
LINK_POLL_S = 0.2


class DeviceError(Exception):
    pass


class NotFound(DeviceError):
    pass


class MouseUnreachable(DeviceError):
    """The receiver is present but the mouse is asleep, off or unpaired."""


def _top_level_usage(descriptor):
    """Return (usage_page, usage) of the first top-level collection."""
    page = usage = None
    i = 0
    while i < len(descriptor):
        prefix = descriptor[i]
        if prefix == 0xFE:  # long item
            i += 3 + descriptor[i + 1]
            continue
        size = (0, 1, 2, 4)[prefix & 0x03]
        value = int.from_bytes(descriptor[i + 1:i + 1 + size], "little")
        tag = prefix & 0xFC
        if tag == 0x04 and page is None:
            page = value
        elif tag == 0x08 and usage is None:
            usage = value
        elif tag == 0xA0:  # Collection
            return page, usage
        i += 1 + size
    return page, usage


def find_nodes(model=models.DEFAULT):
    """Map usage -> /dev/hidrawN for the model's receiver.

    Interfaces are picked by HID usage, not interface number (spec 1.2).
    """
    wanted = f"HID_ID=0003:{p.VENDOR_ID:08X}:{model.product_id:08X}"
    nodes = {}
    for sys_path in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            with open(os.path.join(sys_path, "device/uevent")) as f:
                if wanted not in f.read().upper():
                    continue
            with open(os.path.join(sys_path, "device/report_descriptor"), "rb") as f:
                usage = _top_level_usage(f.read())
        except OSError:
            continue
        nodes[usage] = "/dev/" + os.path.basename(sys_path)
    return nodes


def find_receiver():
    """(model, nodes) for the first supported receiver plugged in, or (None, {})."""
    for model in models.MODELS:
        nodes = find_nodes(model)
        if p.COMMAND_USAGE in nodes:
            return model, nodes
    return None, {}


BLUETOOTH_VENDOR_ID = 0x0111  # spec 1.1, survey A.1: the same mouse over Bluetooth
BUS_BLUETOOTH = 0x0005


def bluetooth_model():
    """The model connected over Bluetooth (no settings channel, spec 7.5), or None."""
    wanted = {f"HID_ID={BUS_BLUETOOTH:04X}:{BLUETOOTH_VENDOR_ID:08X}:{m.product_id:08X}": m
              for m in models.MODELS}
    for uevent in glob.glob("/sys/bus/hid/devices/*/uevent"):
        try:
            with open(uevent) as f:
                text = f.read().upper()
        except OSError:
            continue
        for key, model in wanted.items():
            if key in text:
                return model
    return None


def bluetooth_present():
    return bluetooth_model() is not None


def bootloader_present():
    wanted = [f"HID_ID=0003:{p.VENDOR_ID:08X}:{m.bootloader_id:08X}" for m in models.MODELS]
    for uevent in glob.glob("/sys/class/hidraw/hidraw*/device/uevent"):
        try:
            with open(uevent) as f:
                text = f.read().upper()
        except OSError:
            continue
        if any(key in text for key in wanted):
            return True
    return False


class Mouse:
    """Command channel to the receiver and mouse. Thread-safe."""

    model = models.DEFAULT  # replaced in __init__ by the receiver found

    def __init__(self, path=None, model=None):
        if path is None:
            model, nodes = find_receiver()
            path = nodes.get(p.COMMAND_USAGE)
            if path is None:
                raise NotFound("no supported SteelSeries receiver found")
        self.model = model or models.DEFAULT
        self.path = path
        try:
            self.fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
        except PermissionError as e:
            raise DeviceError(f"no permission to open {path}; install the udev rule") from e
        except FileNotFoundError as e:  # unplugged since the scan, or no /dev node
            raise NotFound(f"{path} is gone") from e
        except OSError as e:
            raise DeviceError(f"cannot open {path}: {e}") from e
        self._lock = threading.Lock()
        self._last = 0.0

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # --- raw I/O ---

    def _pace(self):
        wait = self._last + COMMAND_GAP_S - time.monotonic()
        if wait > 0:
            time.sleep(wait)

    def _drain(self):
        while True:
            try:
                os.read(self.fd, p.REPORT_LEN)
            except BlockingIOError:
                return

    def _write(self, payload):
        self._pace()
        try:
            os.write(self.fd, b"\0" + payload)  # leading report-ID placeholder
        except OSError as e:
            raise DeviceError(f"write failed: {e}") from e
        finally:
            self._last = time.monotonic()

    @contextlib.contextmanager
    def _exclusive(self):
        with self._lock, open(LOCK_PATH, "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def send(self, payload):
        with self._exclusive():
            self._write(payload)

    def query(self, payload, timeout=QUERY_TIMEOUT_S):
        with self._exclusive():
            try:
                self._drain()
                self._write(payload)
                ready, _, _ = select.select([self.fd], [], [], timeout)
                if not ready:
                    raise MouseUnreachable("no response from device")
                return os.read(self.fd, p.REPORT_LEN)
            except OSError as e:  # EIO while the receiver resets or is unplugged
                raise DeviceError(f"read failed: {e}") from e

    # --- receiver ---

    def radio_status(self):
        return self.query(p.command(p.READ | p.RECEIVER | p.OP_RADIO_STATUS))[0]

    def linked(self):
        return self.radio_status() == p.RADIO_LINKED

    def receiver_version(self):
        return p.decode_version(self.query(p.command(p.READ | p.RECEIVER | p.OP_VERSION)))

    def pair(self):
        self.send(p.command(p.RECEIVER | p.OP_PAIR, 0))

    def wireless_reset(self):
        self.send(p.command(p.RECEIVER | p.OP_WIRELESS_RESET))

    # --- mouse (require a link, spec 1.4) ---

    def _mouse_query(self, payload):
        if not self.linked():
            raise MouseUnreachable("mouse is asleep, off or not paired")
        return self.query(payload)

    def _mouse_send(self, payload):
        if not self.linked():
            raise MouseUnreachable("mouse is asleep, off or not paired")
        self.send(payload)

    def mouse_version(self):
        return p.decode_version(self._mouse_query(p.command(p.READ | p.OP_VERSION)))

    def battery(self):
        battery = p.decode_battery(self._mouse_query(p.command(p.OP_BATTERY, 0x01)))
        if not self.model.charge_status:
            # survey S2: unknown whether R[2] is a charge status on this
            # model, which runs on replaceable cells, so report discharging.
            battery.status = 0
        return battery

    def cpi_table(self):
        if self.model.xy_cpi:
            return p.decode_cpi_table_xy(
                self._mouse_query(p.command(p.READ | p.OP_CPI_TABLE_XY)))
        return p.decode_cpi_table(self._mouse_query(p.command(p.READ | p.OP_CPI_TABLE)))

    def set_cpi_table(self, table):
        if self.model.xy_cpi:
            self._mouse_send(p.encode_cpi_table_xy(table))
        else:
            self._mouse_send(p.encode_cpi_table(table))

    def polling_hz(self):
        level = self._mouse_query(p.command(p.READ | p.OP_POLLING))[0]
        return p.POLLING_LEVELS.get(level)

    def set_polling_hz(self, hz, settle=True):
        self._mouse_send(p.encode_polling(hz))
        if settle:
            time.sleep(3.0)  # spec 2.3

    def power(self):
        power = p.decode_power(self._mouse_query(p.command(p.READ | p.OP_POWER)))
        if self.model.host_high_efficiency:
            # survey C.1: only the sleep timer is a device setting here.
            power = p.PowerSettings(False, 0, 0, power.idle_sleep_s)
        return power

    def set_power(self, settings):
        """Write power settings and return once the mouse is back on its link.

        Commands sent while the link is down fail, so wait for the drop that
        every power write causes and then for the reconnect. Whether the Gen 2
        drops its link too is unknown; if it doesn't, this costs POWER_DROP_S.
        """
        if self.model.host_high_efficiency:
            # survey C.1: GG sends bytes 1..4 as zero and only the sleep timer.
            settings = p.PowerSettings(False, 0, 0, settings.idle_sleep_s)
        self._mouse_send(p.encode_power(settings))
        self._wait_for_link(False, POWER_DROP_S)
        if not self._wait_for_link(True, POWER_RELINK_S):
            raise MouseUnreachable("mouse didn't reconnect after its power settings changed")

    def _wait_for_link(self, linked, timeout):
        deadline = time.monotonic() + timeout
        while self.linked() != linked:
            if time.monotonic() >= deadline:
                return False
            time.sleep(LINK_POLL_S)
        return True

    def debounce(self):
        if not self.model.debounce:
            raise ValueError(f"the {self.model.name} has no debounce read-back")
        r = self._mouse_query(p.command(p.READ | p.OP_DEBOUNCE))
        return r[0], r[1]

    def set_buttons(self, buttons):
        self._mouse_send(p.encode_buttons(buttons))

    def set_wheel(self, wheel):
        self._mouse_send(p.encode_wheel(wheel))

    # Models without lighting (survey C.1) accept and ignore lighting calls,
    # so a profile made on another mouse still applies everything else.

    def set_lighting(self, lighting):
        if not self.model.lighting:
            return
        if not self.linked():
            raise MouseUnreachable("mouse is asleep, off or not paired")
        for cmd in p.encode_effect_upload(p.encode_effect_record(lighting)):
            self.send(cmd)

    def set_direct_color(self, rgb):
        if not self.model.lighting:
            return
        self._mouse_send(p.encode_direct_color(rgb))

    def restart_lighting(self):
        if not self.model.lighting:
            return
        time.sleep(1.0)  # spec 2.3
        self._mouse_send(p.command(p.OP_RESTART_LIGHTING))

    def save_to_flash(self):
        self._mouse_send(p.command(p.OP_SAVE_FLASH))


class EventListener:
    """Reads unsolicited notifications from the event interface (spec 2.4)."""

    def __init__(self, callback, path=None):
        self.path = path or find_receiver()[1].get(p.EVENT_USAGE)
        if self.path is None:
            raise NotFound("event interface not found")
        self.callback = callback
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()
        return self

    @property
    def alive(self):
        return self._thread.is_alive()

    def stop(self):
        self._stop.set()

    def _run(self):
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            return
        try:
            while not self._stop.is_set():
                ready, _, _ = select.select([fd], [], [], 0.5)
                if not ready:
                    continue
                try:
                    data = os.read(fd, p.REPORT_LEN)
                except OSError:
                    return  # device unplugged
                if len(data) >= 2:
                    self.callback(data[0], data[1], data)
        finally:
            os.close(fd)
