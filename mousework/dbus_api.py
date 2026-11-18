"""Session-bus API of mousework-filter (docs/json.md, "D-Bus API").

The service owns io.github.mlkonrad.Mousework.Service and exports a method to
read the status and one to switch profiles. Desktop widgets such as the GNOME
Shell extension use it instead of running the `mousework` command. It can't
use the app ID itself: the GTK app owns that name to keep to one window.
Changes are still announced by the Changed signal (changes.py).

Calls run on their own threads: reading the mouse or writing a profile takes
from a fraction of a second to several seconds, and the bus must keep
answering meanwhile.
"""

import json
import threading

from . import device, status
from .profiles import Store, switch

BUS_NAME = "io.github.mlkonrad.Mousework.Service"
PATH = "/io/github/mlkonrad/Mousework/Service"
INTERFACE = BUS_NAME
ERROR_FAILED = f"{INTERFACE}.Error.Failed"
ERROR_NO_SUCH_PROFILE = f"{INTERFACE}.Error.NoSuchProfile"

INTROSPECTION = f"""
<node>
  <interface name="{INTERFACE}">
    <method name="GetStatus">
      <arg name="status" type="s" direction="out"/>
    </method>
    <method name="UseProfile">
      <arg name="name" type="s" direction="in"/>
    </method>
  </interface>
</node>
"""


class Api:
    """Owns the bus name and answers method calls until the process exits."""

    def __init__(self, log=print, collect=status.collect, store_factory=Store, switch_profile=switch):
        self._log = log
        self._collect = collect
        self._store_factory = store_factory
        self._switch = switch_profile
        # One profile write at a time: two at once would interleave on the mouse.
        self._switch_lock = threading.Lock()

    def start(self):
        threading.Thread(target=self._run, name="dbus-api", daemon=True).start()

    def _run(self):
        from gi.repository import Gio, GLib
        context = GLib.MainContext.new()
        context.push_thread_default()
        loop = GLib.MainLoop.new(context, False)
        interface = Gio.DBusNodeInfo.new_for_xml(INTROSPECTION).interfaces[0]

        def bus_acquired(connection, _name):
            connection.register_object(PATH, interface, self._method_call, None, None)

        def name_lost(_connection, _name):
            self._log(f"D-Bus name {BUS_NAME} is taken or the session bus is gone; "
                      "widgets can't read the status over D-Bus")

        Gio.bus_own_name(Gio.BusType.SESSION, BUS_NAME, Gio.BusNameOwnerFlags.NONE,
                         bus_acquired, None, name_lost)
        loop.run()

    def _method_call(self, _connection, _sender, _path, _interface, method, params, invocation):
        handler = {"GetStatus": self.get_status, "UseProfile": self.use_profile}[method]
        threading.Thread(target=handler, args=(invocation, *params.unpack()), daemon=True).start()

    def get_status(self, invocation):
        from gi.repository import GLib
        try:
            text = json.dumps(self._collect())
        except Exception as err:  # collect() reports device states itself; this is a bug
            invocation.return_dbus_error(ERROR_FAILED, str(err))
            return
        invocation.return_value(GLib.Variant("(s)", (text,)))

    def use_profile(self, invocation, name):
        with self._switch_lock:
            store = self._store_factory()
            if name not in store.profiles:
                invocation.return_dbus_error(
                    ERROR_NO_SUCH_PROFILE, f"no profile named {name!r}; one of " + ", ".join(store.profiles))
                return
            try:
                self._switch(store, name)
            except (device.DeviceError, ValueError) as err:
                invocation.return_dbus_error(ERROR_FAILED, str(err))
                return
        invocation.return_value(None)
