"""Tells desktop widgets that the mouse's state changed (docs/json.md).

The motion filter service broadcasts io.github.mlkonrad.Mousework.Changed on
the session bus, so widgets can re-read `mousework status --json` right away
instead of waiting for their next poll.
"""

PATH = "/io/github/mlkonrad/Mousework"
INTERFACE = "io.github.mlkonrad.Mousework"
SIGNAL = "Changed"

_bus = None


def emit(what):
    """Broadcast Changed(what); what is "cpi", "link", "battery" or "settings"."""
    global _bus
    from gi.repository import Gio, GLib
    if _bus is None:
        _bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    _bus.emit_signal(None, PATH, INTERFACE, SIGNAL, GLib.Variant("(s)", (what,)))


SETTLE_S = 1.0
POLL_S = 120


def watch(callback, poll_s=POLL_S, settle_s=SETTLE_S):
    """Call callback() after each burst of Changed signals, and after poll_s
    seconds without one. Returns when callback() returns False.

    Waiting settle_s after the last signal lets a burst end and lets a saved
    setting reach the mouse before it's read. Without a session bus this
    only polls.
    """
    from gi.repository import Gio, GLib
    loop = GLib.MainLoop()
    timer = None

    def schedule(seconds):
        nonlocal timer
        if timer:
            GLib.source_remove(timer)
        timer = GLib.timeout_add(int(seconds * 1000), fire)

    def fire():
        nonlocal timer
        timer = None
        if callback() is False:
            loop.quit()
        else:
            schedule(poll_s)
        return GLib.SOURCE_REMOVE

    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    except GLib.Error:
        bus = None
    if bus:
        subscription = bus.signal_subscribe(None, INTERFACE, SIGNAL, PATH, None, Gio.DBusSignalFlags.NONE,
                                            lambda *_: schedule(settle_s))
    schedule(poll_s)
    try:
        loop.run()
    finally:
        if bus:
            bus.signal_unsubscribe(subscription)
        if timer:
            GLib.source_remove(timer)
