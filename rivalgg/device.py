"""hidraw transport for the Rival 3 Wireless (§1.2, §2)."""

import glob
import os
import select
import threading
import time

from . import protocol as p

COMMAND_GAP_S = 0.030  # §2.3
QUERY_TIMEOUT_S = 1.0


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


def find_nodes():
    """Map usage -> /dev/hidrawN for the 1038:1830 receiver.

    Interfaces are picked by HID usage, not interface number (§1.2).
    """
    wanted = f"HID_ID=0003:{p.VENDOR_ID:08X}:{p.PRODUCT_ID:08X}"
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


BLUETOOTH_VENDOR_ID = 0x0111  # §1.1: the same mouse over Bluetooth
BUS_BLUETOOTH = 0x0005


def bluetooth_present():
    """True if the mouse is connected over Bluetooth (no settings channel, §7.5)."""
    wanted = f"HID_ID={BUS_BLUETOOTH:04X}:{BLUETOOTH_VENDOR_ID:08X}:{p.PRODUCT_ID:08X}"
    for uevent in glob.glob("/sys/bus/hid/devices/*/uevent"):
        try:
            with open(uevent) as f:
                if wanted in f.read().upper():
                    return True
        except OSError:
            pass
    return False


def bootloader_present():
    wanted = f"HID_ID=0003:{p.VENDOR_ID:08X}:{p.BOOTLOADER_PRODUCT_ID:08X}"
    for uevent in glob.glob("/sys/class/hidraw/hidraw*/device/uevent"):
        try:
            with open(uevent) as f:
                if wanted in f.read().upper():
                    return True
        except OSError:
            pass
    return False


class Mouse:
    """Command channel to the receiver and mouse. Thread-safe."""

    def __init__(self, path=None):
        if path is None:
            path = find_nodes().get(p.COMMAND_USAGE)
            if path is None:
                raise NotFound("Rival 3 Wireless receiver not found")
        self.path = path
        try:
            self.fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
        except PermissionError as e:
            raise DeviceError(f"no permission to open {path}; install the udev rule") from e
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

    def send(self, payload):
        with self._lock:
            self._write(payload)

    def query(self, payload, timeout=QUERY_TIMEOUT_S):
        with self._lock:
            self._drain()
            self._write(payload)
            ready, _, _ = select.select([self.fd], [], [], timeout)
            if not ready:
                raise MouseUnreachable("no response from device")
            return os.read(self.fd, p.REPORT_LEN)

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

    # --- mouse (require a link, §1.4) ---

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
        return p.decode_battery(self._mouse_query(p.command(p.OP_BATTERY, 0x01)))

    def cpi_table(self):
        return p.decode_cpi_table(self._mouse_query(p.command(p.READ | p.OP_CPI_TABLE)))

    def set_cpi_table(self, table):
        self._mouse_send(p.encode_cpi_table(table))

    def polling_hz(self):
        level = self._mouse_query(p.command(p.READ | p.OP_POLLING))[0]
        return p.POLLING_LEVELS.get(level)

    def set_polling_hz(self, hz, settle=True):
        self._mouse_send(p.encode_polling(hz))
        if settle:
            time.sleep(3.0)  # §2.3

    def power(self):
        return p.decode_power(self._mouse_query(p.command(p.READ | p.OP_POWER)))

    def set_power(self, settings):
        self._mouse_send(p.encode_power(settings))

    def debounce(self):
        r = self._mouse_query(p.command(p.READ | p.OP_DEBOUNCE))
        return r[0], r[1]

    def set_buttons(self, buttons):
        self._mouse_send(p.encode_buttons(buttons))

    def set_wheel(self, wheel):
        self._mouse_send(p.encode_wheel(wheel))

    def set_lighting(self, lighting):
        if not self.linked():
            raise MouseUnreachable("mouse is asleep, off or not paired")
        for cmd in p.encode_effect_upload(p.encode_effect_record(lighting)):
            self.send(cmd)

    def set_direct_color(self, rgb):
        self._mouse_send(p.encode_direct_color(rgb))

    def restart_lighting(self):
        time.sleep(1.0)  # §2.3
        self._mouse_send(p.command(p.OP_RESTART_LIGHTING))

    def save_to_flash(self):
        self._mouse_send(p.command(p.OP_SAVE_FLASH))


class EventListener:
    """Reads unsolicited notifications from the event interface (§2.4)."""

    def __init__(self, callback, path=None):
        self.path = path or find_nodes().get(p.EVENT_USAGE)
        if self.path is None:
            raise NotFound("event interface not found")
        self.callback = callback
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()
        return self

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
