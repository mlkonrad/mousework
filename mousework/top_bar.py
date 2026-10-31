"""Turn the GNOME Shell top-bar indicator on or off for the current user.

Which extensions run is a per-user GNOME setting, so a distribution package
can install the indicator but can't turn it on. The app does it for the user
who asks, by changing the same setting the Extensions app changes.
"""

import os

from gi.repository import Gio, GLib

UUID = "mousework@mlkonrad.github.com"
SHELL_SCHEMA = "org.gnome.shell"
DBUS_TIMEOUT_MS = 3000


def _installed_on_disk():
    dirs = [GLib.get_user_data_dir(), *GLib.get_system_data_dirs()]
    return any(os.path.isfile(os.path.join(d, "gnome-shell", "extensions", UUID, "metadata.json"))
               for d in dirs)


class _Shell:
    """GNOME Shell's extension service on the session bus."""

    def __init__(self):
        try:
            self.proxy = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SESSION, Gio.DBusProxyFlags.DO_NOT_AUTO_START, None,
                "org.gnome.Shell", "/org/gnome/Shell", "org.gnome.Shell.Extensions", None)
        except GLib.Error:
            self.proxy = None

    def running(self):
        return self.proxy is not None and self.proxy.get_name_owner() is not None

    def knows_extension(self):
        """Whether Shell has loaded the extension; it only looks at login."""
        try:
            info = self.proxy.call_sync("GetExtensionInfo", GLib.Variant("(s)", (UUID,)),
                                        Gio.DBusCallFlags.NONE, DBUS_TIMEOUT_MS, None)
        except GLib.Error:
            return False
        return bool(info.unpack()[0])


class TopBar:
    """The indicator's state for this user.

    available is False unless GNOME Shell is running, its settings are there
    and the extension is installed (by a package or install.sh).
    """

    def __init__(self, settings=None, shell=None, installed=None):
        self.shell = shell or _Shell()
        if settings is None and self.shell.running():
            source = Gio.SettingsSchemaSource.get_default()
            if source and source.lookup(SHELL_SCHEMA, True):
                settings = Gio.Settings(schema_id=SHELL_SCHEMA)
        self.settings = settings
        if installed is None:
            installed = self.shell.running() and (_installed_on_disk() or self.shell.knows_extension())
        self.available = settings is not None and installed

    @property
    def enabled(self):
        return (UUID in self.settings.get_strv("enabled-extensions")
                and UUID not in self.settings.get_strv("disabled-extensions"))

    @property
    def can_change(self):
        return self.settings.is_writable("enabled-extensions")

    @property
    def needs_login(self):
        """True if Shell hasn't loaded the extension yet (installed during this session)."""
        return not self.shell.knows_extension()

    def set_enabled(self, on):
        # Shell watches these keys: an extension it has loaded starts or stops
        # at once, one installed during this session starts at the next login.
        enabled = [u for u in self.settings.get_strv("enabled-extensions") if u != UUID]
        if on:
            enabled.append(UUID)
            disabled = [u for u in self.settings.get_strv("disabled-extensions") if u != UUID]
            self.settings.set_strv("disabled-extensions", disabled)
        self.settings.set_strv("enabled-extensions", enabled)

    def connect_changed(self, callback):
        """Call callback() when the indicator is turned on or off anywhere."""
        for key in ("enabled-extensions", "disabled-extensions"):
            self.settings.connect(f"changed::{key}", lambda *_: callback())
