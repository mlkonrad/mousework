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
