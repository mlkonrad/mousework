"""Low-battery notifications (our addition; GG has none for this mouse, §7.4)."""

LOW = 15
CRITICAL = 5
REARM_MARGIN = 5  # the level must rise this far above a threshold to warn again


class BatteryMonitor:
    """Decides when to warn. Feed it levels; it returns a warning or None."""

    def __init__(self):
        self.warned = set()  # thresholds already warned about

    def update(self, level):
        if level is None or not 0 <= level <= 100:
            return None  # unknown (101 = Bluetooth, §5)
        for threshold in (LOW, CRITICAL):
            if level >= threshold + REARM_MARGIN:
                self.warned.discard(threshold)  # battery replaced
        for threshold in (CRITICAL, LOW):
            if level <= threshold:
                if threshold in self.warned:
                    return None
                self.warned.update(t for t in (LOW, CRITICAL) if t >= threshold)
                return Warning(level, critical=threshold == CRITICAL)
        return None


class Warning:
    def __init__(self, level, critical):
        self.level = level
        self.critical = critical

    @property
    def summary(self):
        return "Mouse battery critically low" if self.critical else "Mouse battery low"

    @property
    def body(self):
        return (f"Your Rival 3 Wireless is at {self.level} %. "
                + ("Replace the battery now." if self.critical
                   else "Replace the battery soon."))


def notify(warning):
    """Show a desktop notification through the freedesktop notification service."""
    from gi.repository import Gio, GLib
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    hints = {"urgency": GLib.Variant("y", 2 if warning.critical else 1),
             "desktop-entry": GLib.Variant("s", "io.github.mlkonrad.Mousework")}
    bus.call_sync(
        "org.freedesktop.Notifications", "/org/freedesktop/Notifications",
        "org.freedesktop.Notifications", "Notify",
        GLib.Variant("(susssasa{sv}i)", ("Mousework", 0, "battery-caution-symbolic",
                                          warning.summary, warning.body, [], hints, -1)),
        None, Gio.DBusCallFlags.NONE, -1, None)
