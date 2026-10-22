"""Per-application profiles (§7.4), driven by the rivalgg-focus Shell extension."""

import copy
import json
import os
import threading
import time

from . import device
from .profiles import CONFIG_FILE, Store, apply_changes

FOCUS_BUS_NAME = "io.github.rivalgg.Focus"
FOCUS_PATH = "/io/github/rivalgg/Focus"
FOCUS_IFACE = "io.github.rivalgg.Focus"
OWN_APP_ID = "io.github.rivalgg.desktop"  # focusing the rivalgg window restores the active profile
SETTLE_S = 1.5  # focus must stay put this long before switching
STATE_FILE = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "rivalgg-state.json")


def read_state():
    """What the service last applied: {"profile": name, "app": app_id}, or None."""
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def focus_extension_running():
    from gi.repository import Gio, GLib
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    reply = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus",
                          "org.freedesktop.DBus", "NameHasOwner",
                          GLib.Variant("(s)", (FOCUS_BUS_NAME,)), None,
                          Gio.DBusCallFlags.NONE, -1, None)
    return reply.unpack()[0]


class FocusWatcher:
    """Calls on_change(app_id or None) from a GLib main loop thread."""

    def __init__(self, on_change):
        self.on_change = on_change

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()
        return self

    def _run(self):
        from gi.repository import Gio, GLib
        context = GLib.MainContext.new()
        context.push_thread_default()
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

        def changed(_conn, _sender, _path, _iface, _signal, params):
            self.on_change(params.unpack()[0])

        def appeared(conn, _name, _owner):
            try:
                reply = conn.call_sync(FOCUS_BUS_NAME, FOCUS_PATH, FOCUS_IFACE, "GetFocusedApp",
                                       None, None, Gio.DBusCallFlags.NONE, 2000, None)
                self.on_change(reply.unpack()[0])
            except GLib.Error:
                pass

        bus.signal_subscribe(FOCUS_BUS_NAME, FOCUS_IFACE, "FocusedAppChanged", FOCUS_PATH,
                             None, Gio.DBusSignalFlags.NONE, changed)
        Gio.bus_watch_name_on_connection(bus, FOCUS_BUS_NAME, Gio.BusNameWatcherFlags.NONE,
                                         appeared, lambda *_: self.on_change(None))
        GLib.MainLoop.new(context, False).run()


class AutoSwitcher:
    """Applies the focused app's profile to the mouse, writing only what differs."""

    def __init__(self, settings, log):
        self.settings = settings
        self.log = log
        self.running = True
        self._wake = threading.Event()
        self._app = None
        self._focused_at = 0.0
        store = Store()
        self.applied_name = store.active  # assume the mouse holds the active profile
        self.applied = copy.deepcopy(store.current)
        self._mtime = self._config_mtime()

    def focus_changed(self, app_id):
        self._app = app_id or None
        self._focused_at = time.monotonic()
        self._wake.set()

    def stop(self):
        self.running = False
        self._wake.set()

    def start(self):
        self._thread = threading.Thread(target=self.run, daemon=True)
        self._thread.start()
        return self

    def join(self, timeout=None):
        self._thread.join(timeout)

    @staticmethod
    def _config_mtime():
        try:
            return os.stat(CONFIG_FILE).st_mtime_ns
        except FileNotFoundError:
            return 0

    def run(self):
        while self.running:
            self._wake.wait(1.0)
            self._wake.clear()
            store = Store()
            mtime = self._config_mtime()
            if mtime != self._mtime:
                self._mtime = mtime
                if self.applied_name == store.active:
                    # The app writes edits of the active profile to the mouse itself.
                    self.applied = copy.deepcopy(store.current)
            wait = SETTLE_S - (time.monotonic() - self._focused_at)
            if wait > 0:
                self._wake.wait(wait)
                continue
            app = None if self._app == OWN_APP_ID else self._app
            name, target = store.profile_for_app(app)
            if name != self.applied_name:
                self._switch(name, target, app)

    def _switch(self, name, target, app):
        try:
            with device.Mouse() as m:
                if not m.linked():
                    return  # retried on the next pass
                apply_changes(target, self.applied, m)
        except device.DeviceError as err:
            self.log(f"profile switch to {name} failed: {err}")
            return
        self.log(f"profile {name}" + (f" for {app}" if app else ""))
        # State first: readers treat applied_name and the state file as one fact.
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"profile": name, "app": app or ""}, f)
        os.replace(tmp, STATE_FILE)
        self.applied_name, self.applied = name, copy.deepcopy(target)
        self.settings.effective_name = name
        self.settings.force_reload()
