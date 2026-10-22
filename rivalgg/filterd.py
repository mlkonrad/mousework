"""Motion filter service: grabs the mouse and re-emits filtered motion.

Acceleration, deceleration and smoothing are host-side features (§3.7), so
the mouse's evdev node is grabbed and its events are copied to a uinput
device with REL_X/REL_Y rewritten by motion.MotionFilter. When every level
is 0 the mouse is left alone.
"""

import os
import select
import signal
import sys
import threading
import time

import evdev
from evdev import ecodes as e

from . import autoswitch, battery, device
from . import protocol as p
from .motion import MotionFilter
from .profiles import CONFIG_FILE, Store

DEBUG = os.environ.get("RIVALGG_DEBUG") == "1"
TRACE_PATH = os.environ.get("RIVALGG_TRACE")  # per-report CSV for diagnosis
CONFIG_CHECK_S = 1.0
RETRY_S = 3.0
BATTERY_POLL_S = 300


def log(message):
    try:
        print(f"{time.strftime('%H:%M:%S')} rivalgg-filter: {message}", file=sys.stderr,
              flush=True)
    except OSError:
        # The log reader went away (for example tee after Ctrl+C). Logging must
        # never stop the filter or skip its cleanup, so drop further output.
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stderr.fileno())
        os.close(devnull)


def debug(message):
    if DEBUG:
        log(message)


def find_mouse():
    for path in evdev.list_devices():
        try:
            dev = evdev.InputDevice(path)
        except OSError:
            continue
        caps = dev.capabilities()
        if (dev.info.vendor == p.VENDOR_ID and dev.info.product == p.PRODUCT_ID
                and e.REL_X in caps.get(e.EV_REL, [])):
            return dev
        dev.close()
    return None


class Settings:
    """Motion levels and active CPI from the active profile."""

    def __init__(self):
        self._mtime = None
        self.levels = (0, 0, 0)
        self.battery_warnings = True
        self.effective_name = None  # profile chosen by per-app switching
        self.style = None
        self.presets = [p.CPI_MIN]
        self.cpi = None

    def refresh(self):
        try:
            mtime = os.stat(CONFIG_FILE).st_mtime_ns
        except FileNotFoundError:
            mtime = 0
        if mtime == self._mtime:
            return False
        self._mtime = mtime
        store = Store()
        self.battery_warnings = store.battery_warnings
        profile = store.profiles.get(self.effective_name) or store.current
        self.levels = (profile.accel_level, profile.decel_level, profile.smoothing_level)
        self.style = profile.motion_style
        self.presets = sorted(set(profile.cpi_presets))
        self.cpi = profile.active_cpi
        return True

    def force_reload(self):
        self._mtime = None

    def on_event(self, code, value, _raw):
        # §2.4: the on-mouse CPI button reports the new 1-based preset
        if code == p.EVENT_CPI_CHANGED and 1 <= value <= len(self.presets):
            self.cpi = self.presets[value - 1]


class Service:
    def __init__(self):
        self.settings = Settings()
        self.running = True
        self.battery = battery.BatteryMonitor()
        self._battery_lock = threading.Lock()
        self._listener = None

    def stop(self, *_):
        self.running = False

    def on_event(self, code, value, raw):
        self.settings.on_event(code, value, raw)
        if code == p.EVENT_BATTERY:  # §2.4
            self.battery_level(value)

    def battery_level(self, level):
        if not self.settings.battery_warnings:
            return
        with self._battery_lock:
            warning = self.battery.update(level)
        if warning:
            log(f"battery {level} %: notifying")
            try:
                battery.notify(warning)
            except Exception as err:  # no notification service; keep running
                log(f"notification failed: {err}")

    def _watch_device(self):
        """Keep the event listener alive and poll the battery (§5)."""
        next_poll = 0.0
        while self.running:
            if self._listener is None or not self._listener.alive:
                try:
                    self._listener = device.EventListener(self.on_event).start()
                except device.DeviceError:
                    self._listener = None
            if time.monotonic() >= next_poll:
                next_poll = time.monotonic() + BATTERY_POLL_S
                try:
                    with device.Mouse() as m:
                        if m.linked():  # don't query a sleeping or Bluetooth mouse
                            self.battery_level(m.battery().level)
                except device.DeviceError:
                    pass
            time.sleep(RETRY_S)

    def run(self):
        threading.Thread(target=self._watch_device, daemon=True).start()
        switcher = autoswitch.AutoSwitcher(self.settings, log).start()
        autoswitch.FocusWatcher(switcher.focus_changed).start()
        while self.running:
            self.settings.refresh()
            if not any(self.settings.levels):
                time.sleep(CONFIG_CHECK_S)
                continue
            dev = find_mouse()
            if dev is None:
                time.sleep(RETRY_S)
                continue
            try:
                self._filter(dev)
            except OSError as err:  # unplugged or permission lost
                log(f"device error: {err}")
                time.sleep(RETRY_S)
            finally:
                dev.close()

    def _make_motion(self):
        accel, decel, smoothing = self.settings.levels
        log(f"filtering (accel {accel}, decel {decel}, smoothing {smoothing}, "
            f"style {self.settings.style})")
        return MotionFilter(accel, decel, smoothing, self.settings.cpi, self.settings.style)

    def _filter(self, dev):
        """Hold one grab and one virtual mouse for as long as filtering is on.

        Settings changes only swap the MotionFilter. Releasing the grab or the
        virtual device while a button is down would leave the desktop with a
        press that never gets its release.
        """
        held = set()
        with evdev.UInput.from_device(dev, name="rivalgg filtered mouse") as out:
            dev.grab()
            log(f"grabbed {dev.path}")
            try:
                self._loop(dev, out, held)
            finally:
                for code in sorted(held):
                    out.write(e.EV_KEY, code, 0)
                    debug(f"release on exit: {code}")
                if held:
                    out.syn()
                try:
                    dev.ungrab()
                except OSError:
                    pass
                log(f"released {dev.path}")

    def _loop(self, dev, out, held):
        motion = self._make_motion()
        frame, dx, dy, dropped = [], 0, 0, False
        trace = open(TRACE_PATH, "a", buffering=1 << 16) if TRACE_PATH else None
        if trace:
            trace.write("event_time,dt,dx,dy,out_dx,out_dy,latency_us\n")
        last_check = time.monotonic()
        while self.running:
            if time.monotonic() - last_check >= CONFIG_CHECK_S:
                last_check = time.monotonic()
                if self.settings.refresh():
                    debug("settings changed")
                    if any(self.settings.levels):
                        motion = self._make_motion()
            if not any(self.settings.levels) and not held:
                return  # filtering turned off; hand the mouse back
            motion.cpi = self.settings.cpi or motion.cpi
            ready, _, _ = select.select([dev.fd], [], [], CONFIG_CHECK_S)
            if not ready:
                continue
            for event in dev.read():
                if event.type == e.EV_SYN and event.code == e.SYN_DROPPED:
                    debug("SYN_DROPPED")
                    frame, dx, dy, dropped = [], 0, 0, True
                elif dropped:
                    if event.type == e.EV_SYN and event.code == e.SYN_REPORT:
                        dropped = False
                        self._resync_buttons(dev, out, held)
                elif event.type == e.EV_REL and event.code == e.REL_X:
                    dx += event.value
                elif event.type == e.EV_REL and event.code == e.REL_Y:
                    dy += event.value
                elif event.type == e.EV_SYN and event.code == e.SYN_REPORT:
                    dt = motion.interval(event.timestamp())
                    fx, fy = motion.process(dx, dy, dt)
                    if trace:
                        latency = (time.time() - event.timestamp()) * 1e6
                        trace.write(f"{event.timestamp():.6f},{dt},{dx},{dy},{fx},{fy},"
                                    f"{latency:.0f}\n")
                    for queued in frame:
                        out.write_event(queued)
                    if fx:
                        out.write(e.EV_REL, e.REL_X, fx)
                    if fy:
                        out.write(e.EV_REL, e.REL_Y, fy)
                    out.syn()
                    frame, dx, dy = [], 0, 0
                else:
                    if event.type == e.EV_KEY:
                        (held.add if event.value else held.discard)(event.code)
                        debug(f"button {event.code} {'down' if event.value else 'up'}")
                    frame.append(event)

    @staticmethod
    def _resync_buttons(dev, out, held):
        """After dropped events, match the virtual mouse to the real buttons."""
        active = set(dev.active_keys())
        for code in held - active:
            out.write(e.EV_KEY, code, 0)
        for code in active - held:
            out.write(e.EV_KEY, code, 1)
        out.syn()
        debug(f"resynced buttons {sorted(held)} -> {sorted(active)}")
        held.clear()
        held.update(active)


def main():
    service = Service()
    signal.signal(signal.SIGTERM, service.stop)
    signal.signal(signal.SIGINT, service.stop)
    service.run()


if __name__ == "__main__":
    main()
