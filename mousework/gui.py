"""GTK 4 / libadwaita settings app for the Rival 3 Wireless."""

import copy
import os
import queue
import sys
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from . import device, sync  # noqa: E402
from . import protocol as p  # noqa: E402
from .profiles import (Profile, Store, apply, import_from_device, reconcile, resend_volatile,
                       set_polling_if_needed)  # noqa: E402

APP_ID = "io.github.mlkonrad.Mousework"
APPLY_DELAY_MS = 600
POLL_INTERVAL_S = 5  # §1.4, §5

ACTIONS = [
    ("left", "Left click"), ("right", "Right click"), ("middle", "Middle click"),
    ("back", "Back"), ("forward", "Forward"), ("cpi", "CPI cycle"),
    ("wheel-up", "Scroll up"), ("wheel-down", "Scroll down"), ("disabled", "Disabled"),
    ("media:play-pause", "Play/pause"), ("media:next", "Next track"),
    ("media:previous", "Previous track"), ("media:mute", "Mute"),
    ("media:volume-up", "Volume up"), ("media:volume-down", "Volume down"),
    ("key:", "Keyboard shortcut…"),
]
BUTTON_LABELS = {
    "left": "Left button", "right": "Right button", "middle": "Middle button",
    "back": "Side button (back)", "forward": "Side button (forward)", "cpi": "CPI button",
    "wheel-up": "Scroll wheel up", "wheel-down": "Scroll wheel down",
}
EFFECTS = [(p.EFFECT_OFF, "Off"), (p.EFFECT_STEADY, "Steady"), (p.EFFECT_SHIFT, "Colour shift"),
           (p.EFFECT_BREATHE, "Breathe"), (p.EFFECT_REACTIVE, "Reactive")]
POLLING = [125, 250, 500, 1000]
MOTION_STYLES = [("smooth", "Smooth"), ("gg", "Same as SteelSeries GG")]
# GSK_RENDERER values; "auto" leaves the choice to GTK
RENDERERS = [("auto", "Automatic"), ("vulkan", "Vulkan"), ("opengl", "OpenGL"),
             ("cairo", "Software (Cairo)")]
# A GSK_RENDERER set before launch wins over the saved choice, so a renderer
# that breaks the window can always be escaped with GSK_RENDERER=cairo.
RENDERER_FROM_ENV = os.environ.get("GSK_RENDERER")

# GDK key names -> HID key names in protocol.KEYS
GDK_KEY_NAMES = {
    "return": "enter", "escape": "esc", "bracketleft": "leftbracket",
    "bracketright": "rightbracket", "caps_lock": "capslock", "print": "printscreen",
    "scroll_lock": "scrolllock", "page_up": "pageup", "page_down": "pagedown",
    "kp_enter": "enter",
}
GDK_MODIFIERS = [(Gdk.ModifierType.CONTROL_MASK, "ctrl"), (Gdk.ModifierType.SHIFT_MASK, "shift"),
                 (Gdk.ModifierType.ALT_MASK, "alt"), (Gdk.ModifierType.SUPER_MASK, "super")]


def rgba(rgb):
    color = Gdk.RGBA()
    color.red, color.green, color.blue = (c / 255 for c in rgb)
    color.alpha = 1.0
    return color


def rgb(color):
    return tuple(round(c * 255) for c in (color.red, color.green, color.blue))


def describe_action(action):
    for value, label in ACTIONS:
        if value == action:
            return label
    if action.startswith("key:"):
        return " + ".join(part.capitalize() for part in action[4:].split("+"))
    return action


def string_list(labels):
    return Gtk.StringList.new([label for label in labels])


def call_once(fn, *args):
    """Run fn on the main loop exactly once, whatever it returns."""
    def callback():
        fn(*args)
        return GLib.SOURCE_REMOVE
    GLib.idle_add(callback)


class Worker:
    """Runs device I/O in order on one long-lived background thread."""

    def __init__(self):
        self._queue = queue.Queue()
        self._pending = set()
        threading.Thread(target=self._loop, daemon=True).start()

    def run(self, fn, done=None, error=None, key=None):
        """Queue fn. A job with a key is dropped while one with that key waits."""
        if key is not None:
            if key in self._pending:
                return
            self._pending.add(key)
        self._queue.put((fn, done, error, key))

    def _loop(self):
        while True:
            fn, done, error, key = self._queue.get()
            self._pending.discard(key)
            try:
                result = fn()
            except Exception as e:  # reported to the UI
                if error:
                    call_once(error, e)
                continue
            if done:
                call_once(done, result)


class KeyCaptureDialog(Adw.Dialog):
    def __init__(self, on_done):
        super().__init__(title="Keyboard Shortcut", content_width=360)
        self.on_done = on_done
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        status = Adw.StatusPage(icon_name="input-keyboard-symbolic",
                                title="Press a Key Combination",
                                description="Up to three modifiers and one key")
        toolbar.set_content(status)
        self.set_child(toolbar)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._pressed)
        self.add_controller(keys)

    def _pressed(self, controller, keyval, keycode, state):
        display = self.get_display()
        ok, base, *_ = display.translate_key(keycode, 0, 0)
        name = (Gdk.keyval_name(base if ok else keyval) or "").lower()
        if name.endswith(("_l", "_r")) and name[:-2] in ("control", "shift", "alt", "super", "meta"):
            return True  # wait for the non-modifier key
        key = GDK_KEY_NAMES.get(name, name)
        if key not in p.KEYS:
            return True
        mods = [label for mask, label in GDK_MODIFIERS if state & mask]
        self.on_done("key:" + "+".join(mods + [key]))
        self.close()
        return True


class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Mousework", default_width=560,
                         default_height=760, icon_name=APP_ID)
        self.store = Store()
        self.worker = Worker()
        self.mouse = None
        self.linked = False
        self.bluetooth = False
        self._reconciled = False  # restored the active profile after a reconnect
        self._loading = False
        self._dirty = set()
        self._apply_source = None
        self._listener = None

        self.toasts = Adw.ToastOverlay()
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        toolbar.add_top_bar(header)

        self.profile_dropdown = Gtk.DropDown(tooltip_text="Profile")
        self.profile_dropdown.connect("notify::selected", self._on_profile_selected)
        header.pack_start(self.profile_dropdown)
        menu = Gio.Menu()
        menu.append("New Profile", "win.new-profile")
        menu.append("Rename Profile", "win.rename-profile")
        menu.append("Delete Profile", "win.delete-profile")
        menu.append("Reset Profile to Defaults", "win.reset-profile")
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu,
                                       tooltip_text="Main Menu"))
        for name, cb in (("new-profile", self._new_profile), ("rename-profile", self._rename_profile),
                         ("delete-profile", self._delete_profile),
                         ("reset-profile", self._reset_profile)):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", cb)
            self.add_action(action)

        self.banner = Adw.Banner(button_label="Retry")
        self.banner.connect("button-clicked", lambda *_: self._connect())
        toolbar.add_top_bar(self.banner)

        page = Adw.PreferencesPage()
        page.add(self._build_device())
        self.settings_groups = [self._build_cpi(), self._build_performance(),
                                self._build_lighting()]
        for group in self.settings_groups:
            page.add(group)
        self.stops_group = Adw.PreferencesGroup(title="Colours")
        page.add(self.stops_group)
        self.settings_groups += [self.stops_group, self._build_buttons(), self._build_motion()]
        for group in self.settings_groups[-2:]:
            page.add(group)
        page.add(self._build_app())
        self.page = page
        toolbar.set_content(page)
        self.toasts.set_child(toolbar)
        self.set_content(self.toasts)

        self._reload_profiles()
        self._load_profile()
        self._connect()
        GLib.timeout_add_seconds(POLL_INTERVAL_S, self._poll)
        self.connect("close-request", self._on_close)

    # --- construction ---

    def _build_device(self):
        group = Adw.PreferencesGroup(title="Device")
        self.row_link = Adw.ActionRow(title="Connection", subtitle="Searching…")
        self.row_battery = Adw.ActionRow(title="Battery", subtitle="—")
        self.battery_bar = Gtk.LevelBar(min_value=0, max_value=100, valign=Gtk.Align.CENTER,
                                        width_request=120)
        self.row_battery.add_suffix(self.battery_bar)
        self.row_firmware = Adw.ActionRow(title="Firmware", subtitle="—")
        self.pair_button = Gtk.Button(label="Pair", valign=Gtk.Align.CENTER)
        self.pair_button.connect("clicked", self._pair)
        self.row_link.add_suffix(self.pair_button)
        self.battery_warnings = Adw.SwitchRow(
            title="Low battery warnings",
            subtitle="Notify at 15 % and 5 %, even when this window is closed")
        self.battery_warnings.set_active(self.store.battery_warnings)
        self.battery_warnings.connect("notify::active", self._on_battery_warnings)
        for row in (self.row_link, self.row_battery, self.battery_warnings, self.row_firmware):
            group.add(row)
        return group

    def _on_battery_warnings(self, row, _pspec):
        self.store.battery_warnings = row.get_active()
        self.store.save()

    def _build_cpi(self):
        group = Adw.PreferencesGroup(title="Sensitivity",
                                     description="The CPI button cycles through these presets")
        self.cpi_count = Adw.SpinRow.new_with_range(1, p.CPI_MAX_PRESETS, 1)
        self.cpi_count.set_title("Presets")
        self.cpi_count.connect("notify::value", self._on_cpi_count)
        group.add(self.cpi_count)
        self.cpi_rows = []
        for i in range(p.CPI_MAX_PRESETS):
            row = Adw.SpinRow.new_with_range(p.CPI_MIN, p.CPI_MAX, p.CPI_STEP)
            row.set_title(f"Preset {i + 1}")
            row.set_subtitle("CPI")
            row.connect("notify::value", lambda *_: self._changed("cpi"))
            self.cpi_rows.append(row)
            group.add(row)
        self.cpi_active = Adw.ComboRow(title="Active preset")
        self.cpi_active.connect("notify::selected", lambda *_: self._changed("cpi"))
        group.add(self.cpi_active)
        return group

    def _build_performance(self):
        group = Adw.PreferencesGroup(title="Performance and Battery")
        self.polling = Adw.ComboRow(title="Polling rate",
                                    model=string_list(f"{hz} Hz" for hz in POLLING))
        self.polling.connect("notify::selected", lambda *_: self._changed("polling"))
        self.hem = Adw.SwitchRow(title="High efficiency mode",
                                 subtitle="Longer battery life; polling fixed at 125 Hz")
        self.hem.connect("notify::active", self._on_hem)
        self.smart = Adw.SwitchRow(title="Smart illumination",
                                   subtitle="Saves battery by managing the wheel light")
        self.smart.connect("notify::active", self._on_smart)
        self.sleep = Adw.SpinRow.new_with_range(1, 20, 1)
        self.sleep.set_title("Sleep after")
        self.sleep.set_subtitle("Minutes of inactivity")
        self.sleep.connect("notify::value", lambda *_: self._changed("power"))
        for row in (self.polling, self.hem, self.smart, self.sleep):
            group.add(row)
        return group

    def _build_lighting(self):
        group = Adw.PreferencesGroup(title="Wheel Lighting")
        self.effect = Adw.ComboRow(title="Effect", model=string_list(l for _, l in EFFECTS))
        self.effect.connect("notify::selected", self._on_effect)
        self.steady_row, self.steady_color = self._color_row("Colour")
        self.reactive_row, self.reactive_color = self._color_row("Colour on click")
        self.reactive_time = Adw.SpinRow.new_with_range(0, 2000, 50)
        self.reactive_time.set_title("Fade time")
        self.reactive_time.set_subtitle("Milliseconds")
        self.reactive_time.connect("notify::value", lambda *_: self._changed("lighting"))
        self.speed = Adw.SpinRow.new_with_range(100, 10000, 100)
        self.speed.set_title("Cycle length")
        self.speed.set_subtitle("Milliseconds")
        self.speed.connect("notify::value", lambda *_: self._changed("lighting"))
        for row in (self.effect, self.steady_row, self.reactive_row, self.reactive_time,
                    self.speed):
            group.add(row)
        self.lighting_group = group
        return group

    def _color_row(self, title):
        row = Adw.ActionRow(title=title)
        button = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False),
                                       valign=Gtk.Align.CENTER)
        button.connect("notify::rgba", lambda *_: self._changed("lighting"))
        row.add_suffix(button)
        return row, button

    def _build_buttons(self):
        group = Adw.PreferencesGroup(title="Buttons")
        self.button_rows = {}
        model = string_list(label for _, label in ACTIONS)
        for name in p.BUTTON_NAMES + p.WHEEL_NAMES:
            row = Adw.ComboRow(title=BUTTON_LABELS[name], model=model)
            row.connect("notify::selected", self._on_button, name)
            self.button_rows[name] = row
            group.add(row)
        return group

    def _build_motion(self):
        group = Adw.PreferencesGroup(
            title="Motion",
            description="Applied on this computer by the mousework-filter service")
        self.motion_rows = {}
        for key, title, subtitle in (
                ("accel_level", "Acceleration", "Faster hand movement moves the pointer further"),
                ("decel_level", "Deceleration", "Slow movements become finer for precise aim"),
                ("smoothing_level", "Smoothing", "Steadies slow movements")):
            row = Adw.SpinRow.new_with_range(0, 10, 1)
            row.set_title(title)
            row.set_subtitle(subtitle)
            row.connect("notify::value", lambda *_: self._changed("motion"))
            self.motion_rows[key] = row
            group.add(row)
        self.motion_style = Adw.ComboRow(
            title="Filter style",
            subtitle="Smooth never drops slow movement; GG matches SteelSeries GG exactly",
            model=string_list(label for _, label in MOTION_STYLES))
        self.motion_style.connect("notify::selected", lambda *_: self._changed("motion"))
        group.add(self.motion_style)
        return group

    def _build_app(self):
        group = Adw.PreferencesGroup(title="App")
        self.renderer = Adw.ComboRow(
            title="Renderer",
            subtitle="How this window is drawn. Software uses about half the memory; "
                     "switch if the window looks wrong",
            model=string_list(label for _, label in RENDERERS))
        keys = [key for key, _ in RENDERERS]
        if RENDERER_FROM_ENV:
            self.renderer.set_subtitle(f"Set by GSK_RENDERER={RENDERER_FROM_ENV}")
            self.renderer.set_sensitive(False)
        if self.store.renderer in keys:
            self.renderer.set_selected(keys.index(self.store.renderer))
        self.renderer.connect("notify::selected", self._on_renderer)
        group.add(self.renderer)
        return group

    def _on_renderer(self, row, _pspec):
        self.store.renderer = RENDERERS[row.get_selected()][0]
        self.store.save()
        toast = Adw.Toast(title="Restart Mousework to use the new renderer",
                          button_label="Restart")
        toast.connect("button-clicked", self._restart)
        self.toasts.add_toast(toast)

    def _restart(self, *_):
        self.get_application().restart = True
        self.close()

    def _update_motion_rows(self):
        pr = self.profile
        self.motion_style.set_sensitive(pr.decel_level > 0 or pr.smoothing_level > 0)

    # --- profile <-> widgets ---

    @property
    def profile(self):
        return self.store.current

    def _reload_profiles(self):
        self._loading = True
        names = list(self.store.profiles)
        self.profile_dropdown.set_model(string_list(names))
        self.profile_dropdown.set_selected(names.index(self.store.active))
        self._loading = False

    def _load_profile(self):
        self._loading = True
        pr = self.profile
        presets = pr.cpi_presets[:p.CPI_MAX_PRESETS]
        self.cpi_count.set_value(len(presets))
        for i, row in enumerate(self.cpi_rows):
            row.set_value(presets[i] if i < len(presets) else (i + 1) * 400)
        self._update_cpi_rows()
        if pr.active_cpi in presets:
            self.cpi_active.set_selected(presets.index(pr.active_cpi))
        self.polling.set_selected(POLLING.index(pr.polling_hz))
        self.hem.set_active(pr.high_efficiency)
        self.polling.set_sensitive(not pr.high_efficiency)
        self.smart.set_active(pr.smart_illumination)
        self.sleep.set_value(pr.sleep_minutes)

        light = pr.lighting
        self.effect.set_selected([e for e, _ in EFFECTS].index(light.effect))
        self.steady_color.set_rgba(rgba(light.steady_color))
        self.reactive_color.set_rgba(rgba(light.reactive_color))
        self.reactive_time.set_value(light.reactive_time)
        self.speed.set_value(light.speed)
        self._rebuild_stops()
        self._update_lighting_rows()

        for name, row in self.button_rows.items():
            self._show_action(row, pr.buttons[name])
        for key, row in self.motion_rows.items():
            row.set_value(getattr(pr, key))
        self.motion_style.set_selected([v for v, _ in MOTION_STYLES].index(pr.motion_style))
        self._update_motion_rows()
        self._loading = False

    def _show_action(self, row, action):
        values = [v for v, _ in ACTIONS]
        if action.startswith("key:"):
            row.set_selected(values.index("key:"))
            row.set_subtitle(describe_action(action))
        else:
            row.set_selected(values.index(action) if action in values else 0)
            row.set_subtitle("")

    def _update_cpi_rows(self):
        count = int(self.cpi_count.get_value())
        for i, row in enumerate(self.cpi_rows):
            row.set_visible(i < count)
        selected = self.cpi_active.get_selected()
        self.cpi_active.set_model(string_list(f"Preset {i + 1}" for i in range(count)))
        self.cpi_active.set_selected(min(selected if selected != Gtk.INVALID_LIST_POSITION
                                         else 0, count - 1))

    def _rebuild_stops(self):
        group = self.stops_group
        for row in list(getattr(self, "_stop_rows", [])):
            group.remove(row)
        self._stop_rows = []
        stops = self.profile.lighting.stops
        limit = 7 if self.profile.lighting.effect == p.EFFECT_BREATHE else p.MAX_COLOR_STOPS
        for index, stop in enumerate(stops):
            row = Adw.ActionRow(title=f"Colour {index + 1}")
            button = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False),
                                           valign=Gtk.Align.CENTER, rgba=rgba(stop.color))
            spin = Gtk.SpinButton.new_with_range(0, 100, 1)
            spin.set_value(stop.position)
            spin.set_valign(Gtk.Align.CENTER)
            spin.set_tooltip_text("Position in the cycle (%)")
            remove = Gtk.Button(icon_name="list-remove-symbolic", valign=Gtk.Align.CENTER,
                                tooltip_text="Remove Colour", css_classes=["flat"])
            remove.set_sensitive(len(stops) > 1)
            button.connect("notify::rgba", self._on_stop_changed)
            spin.connect("value-changed", self._on_stop_changed)
            remove.connect("clicked", self._remove_stop, index)
            row.add_suffix(spin)
            row.add_suffix(button)
            row.add_suffix(remove)
            row.stop_widgets = (button, spin)
            group.add(row)
            self._stop_rows.append(row)
        add = Adw.ButtonRow(title="Add Colour", start_icon_name="list-add-symbolic")
        add.set_sensitive(len(stops) < limit)
        add.connect("activated", self._add_stop)
        group.add(add)
        self._stop_rows.append(add)

    def _update_lighting_rows(self):
        effect = self.profile.lighting.effect
        self.steady_row.set_visible(effect in (p.EFFECT_STEADY, p.EFFECT_REACTIVE))
        self.steady_row.set_title("Resting colour" if effect == p.EFFECT_REACTIVE else "Colour")
        self.reactive_row.set_visible(effect == p.EFFECT_REACTIVE)
        self.reactive_time.set_visible(effect == p.EFFECT_REACTIVE)
        self.speed.set_visible(effect in (p.EFFECT_SHIFT, p.EFFECT_BREATHE))
        self.stops_group.set_visible(effect in (p.EFFECT_SHIFT, p.EFFECT_BREATHE))
        # §8.1: lighting is unavailable in High Efficiency Mode
        hem = self.profile.high_efficiency
        self.lighting_group.set_sensitive(not hem and not self.bluetooth)
        self.stops_group.set_sensitive(not hem and not self.bluetooth)
        if hem:
            note = "Unavailable in high efficiency mode"
        elif effect == p.EFFECT_REACTIVE and self.profile.smart_illumination:
            # Verified on device: smart illumination suppresses click flashes (§3.4.3)
            note = "Click flashes only appear with smart illumination turned off"
        else:
            note = None
        self.lighting_group.set_description(note)

    def _read_widgets(self):
        pr = self.profile
        count = int(self.cpi_count.get_value())
        presets = [int(row.get_value()) for row in self.cpi_rows[:count]]
        pr.cpi_presets = presets
        pr.active_cpi = presets[min(self.cpi_active.get_selected(), count - 1)]
        pr.polling_hz = POLLING[self.polling.get_selected()]
        pr.high_efficiency = self.hem.get_active()
        pr.smart_illumination = self.smart.get_active()
        pr.sleep_minutes = int(self.sleep.get_value())
        for key, row in self.motion_rows.items():
            setattr(pr, key, int(row.get_value()))
        pr.motion_style = MOTION_STYLES[self.motion_style.get_selected()][0]
        self._update_motion_rows()
        light = pr.lighting
        light.effect = EFFECTS[self.effect.get_selected()][0]
        light.steady_color = rgb(self.steady_color.get_rgba())
        light.reactive_color = rgb(self.reactive_color.get_rgba())
        light.reactive_time = int(self.reactive_time.get_value())
        light.speed = int(self.speed.get_value())
        light.stops = [p.ColorStop(rgb(row.stop_widgets[0].get_rgba()),
                                   int(row.stop_widgets[1].get_value()))
                       for row in self._stop_rows if hasattr(row, "stop_widgets")]

    # --- change handling ---

    def _changed(self, category):
        if self._loading:
            return
        self._read_widgets()
        if category in ("lighting", "buttons") and category not in self.profile.managed:
            self.profile.managed.append(category)
        self._dirty.add(category)
        self.store.save()
        if self._apply_source:
            GLib.source_remove(self._apply_source)
        self._apply_source = GLib.timeout_add(APPLY_DELAY_MS, self._apply_dirty)

    def _on_cpi_count(self, *_):
        if self._loading:
            return
        self._update_cpi_rows()
        self._changed("cpi")

    def _on_hem(self, *_):
        if self._loading:
            return
        on = self.hem.get_active()
        self.polling.set_sensitive(not on)
        self._changed("power")
        if not on:
            self._dirty.add("polling")  # restore the chosen rate (§3.3)
        self._update_lighting_rows()

    def _on_smart(self, *_):
        if self._loading:
            return
        self._changed("power")
        self._update_lighting_rows()

    def _on_effect(self, *_):
        if self._loading:
            return
        self._read_widgets()
        self._rebuild_stops()
        self._update_lighting_rows()
        self._changed("lighting")

    def _on_stop_changed(self, *_):
        self._changed("lighting")

    def _add_stop(self, *_):
        stops = self.profile.lighting.stops
        last = stops[-1].position if stops else 0
        stops.append(p.ColorStop((255, 255, 255), min(100, last + 10)))
        self._rebuild_stops()
        self._changed("lighting")

    def _remove_stop(self, _button, index):
        del self.profile.lighting.stops[index]
        self._rebuild_stops()
        self._changed("lighting")

    def _on_button(self, row, _pspec, name):
        if self._loading:
            return
        value = ACTIONS[row.get_selected()][0]
        if value == "key:":
            def done(action):
                self.profile.buttons[name] = action
                row.set_subtitle(describe_action(action))
                self._changed("buttons")
            KeyCaptureDialog(done).present(self)
            return
        row.set_subtitle("")
        self.profile.buttons[name] = value
        self._changed("buttons")

    def _apply_dirty(self):
        self._apply_source = None
        if not self.mouse or not self.linked:
            return False  # kept in _dirty; applied when the mouse reconnects
        dirty, self._dirty = self._dirty - {"motion"}, set()
        if not dirty:
            return False  # motion settings are host-side; the service reloads them
        profile = copy.deepcopy(self.profile)
        name = self.store.active

        def work():
            with sync.syncing(name):
                write()

        def write():
            m = self.mouse
            profile.validate()
            if "power" in dirty:
                current = m.power()
                m.set_power(p.PowerSettings(
                    profile.high_efficiency,
                    p.SMART_ILLUMINATION_ON if profile.smart_illumination else 0,
                    current.idle_lighting_s, profile.sleep_minutes * 60))
            if "polling" in dirty and not profile.high_efficiency:
                set_polling_if_needed(m, profile.polling_hz)
            if "cpi" in dirty:
                m.set_cpi_table(p.make_cpi_table(profile.cpi_presets, profile.active_cpi))
            if "lighting" in dirty:
                m.set_lighting(profile.lighting)
            if "buttons" in dirty:
                buttons, wheel = profile.bindings()
                m.set_buttons(buttons)
                m.set_wheel(wheel)
            m.save_to_flash()

        self.worker.run(work, done=self._saved_to_flash, error=self._device_error)
        return False

    # --- profiles ---

    def _on_profile_selected(self, *_):
        if self._loading:
            return
        names = list(self.store.profiles)
        self.store.active = names[self.profile_dropdown.get_selected()]
        self.store.save()
        self._load_profile()
        self._apply_full()

    def _saved_to_flash(self, _result=None):
        self.store.mark_saved()
        self.store.save()

    def _apply_full(self):
        if not self.mouse or not self.linked:
            return
        profile = copy.deepcopy(self.profile)
        name = self.store.active
        def done(_):
            self._saved_to_flash()
            self._toast("Profile applied")

        def work():
            with sync.syncing(name):
                apply(profile, self.mouse)
        self.worker.run(work, done=done, error=self._device_error)

    def _ask_name(self, heading, initial, on_ok):
        dialog = Adw.AlertDialog(heading=heading)
        entry = Gtk.Entry(text=initial, activates_default=True)
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("ok", "OK")
        dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("ok")

        def response(_d, result):
            name = entry.get_text().strip()
            if result == "ok" and name:
                if name in self.store.profiles and name != initial:
                    self._toast(f"A profile named “{name}” already exists")
                    return
                on_ok(name)
        dialog.connect("response", response)
        dialog.present(self)

    def _new_profile(self, *_):
        def create(name):
            self.store.profiles[name] = copy.deepcopy(self.profile)
            self.store.active = name
            self.store.save()
            self._reload_profiles()
        self._ask_name("New Profile", "", create)

    def _rename_profile(self, *_):
        old = self.store.active

        def rename(name):
            self.store.rename(old, name)
            self.store.save()
            self._reload_profiles()
        self._ask_name("Rename Profile", old, rename)

    def _delete_profile(self, *_):
        if len(self.store.profiles) == 1:
            self._toast("The last profile cannot be deleted")
            return
        self.store.delete(self.store.active)
        self.store.save()
        self._reload_profiles()
        self._load_profile()
        self._apply_full()

    def _reset_profile(self, *_):
        self.store.profiles[self.store.active] = Profile()
        self.store.save()
        self._load_profile()
        self._apply_full()
        self._toast("Profile reset to defaults")

    # --- device state ---

    def _connect(self):
        self.worker.run(lambda: self._read_state(on_connect=True), done=self._show_state,
                        error=self._device_error, key="poll")

    def _read_state(self, on_connect=False):
        if self.mouse is None:
            try:
                self.mouse = device.Mouse()
            except device.NotFound:
                if device.bluetooth_present():
                    return {"bluetooth": True}
                raise
        m = self.mouse
        state = {"radio": m.radio_status(), "receiver": m.receiver_version()}
        if state["radio"] != p.RADIO_LINKED and device.bluetooth_present():
            state["bluetooth"] = True
            return state
        if state["radio"] == p.RADIO_LINKED:
            state["battery"] = m.battery()
            state["mouse"] = m.mouse_version()
            state["cpi"] = m.cpi_table()
            if self.store.fresh:
                # First run: adopt what the mouse can report instead of
                # overwriting it; buttons and lighting have no read-back.
                import_from_device(self.profile, m)
                state["imported"] = True
            elif ((on_connect or not self.linked) and self.store.mouse_may_differ
                  and not self._reconciled):
                # After a temporary switch a power-up brings back the saved
                # profile; restore the active one instead of adopting its CPI.
                # Only once: if a write drops the link, the next reconnect
                # must not write again, or the mouse never stays connected.
                self._reconciled = True
                with sync.syncing(self.store.active):
                    reconcile(copy.deepcopy(self.profile), m)
                state["cpi"] = m.cpi_table()
            elif on_connect or not self.linked:
                resend_volatile(self.profile, m)  # §7.2
        return state

    def _set_bluetooth(self, on):
        """§7.5: over Bluetooth nothing can be configured, as in GG."""
        if on == self.bluetooth:
            return
        self.bluetooth = on
        for group in self.settings_groups:
            group.set_sensitive(not on)
        self.profile_dropdown.set_sensitive(not on)
        self.pair_button.set_sensitive(not on)
        self._update_lighting_rows()

    def _show_state(self, state):
        if state.get("bluetooth"):
            self.linked = False
            self._set_bluetooth(True)
            self.banner.set_title("Connected over Bluetooth. Connect the USB receiver "
                                  "to change settings.")
            self.banner.set_button_label(None)
            self.banner.set_revealed(True)
            self.row_link.set_subtitle("Bluetooth")
            self.row_battery.set_subtitle("Unknown")
            self.battery_bar.set_value(0)
            receiver = state.get("receiver")
            self.row_firmware.set_subtitle(f"Receiver {receiver}" if receiver else "—")
            return False
        self._set_bluetooth(False)
        self.banner.set_revealed(False)
        was_linked = self.linked
        self.linked = state["radio"] == p.RADIO_LINKED
        if not self.linked:
            self.row_link.set_subtitle("Mouse asleep, off or not paired")
            self.row_battery.set_subtitle("—")
            self.battery_bar.set_value(0)
            self.row_firmware.set_subtitle(f"Receiver {state['receiver']}")
        else:
            self.row_link.set_subtitle("Connected (2.4 GHz)")
            bat = state["battery"]
            self.row_battery.set_subtitle(f"{bat.level} %" if bat.known else "Unknown")
            self.battery_bar.set_value(bat.level if bat.known else 0)
            self.row_firmware.set_subtitle(f"Mouse {state['mouse']} · Receiver {state['receiver']}")
            if state.get("imported"):
                self.store.fresh = False
                self.store.save()
                self._load_profile()
            self._adopt_cpi(state["cpi"])
        if self._listener is None:
            try:
                self._listener = device.EventListener(self._on_event).start()
            except device.DeviceError:
                pass
        if self.linked and not was_linked and self._dirty:
            self._apply_dirty()
        return False

    def _adopt_cpi(self, table):
        """The device is the source of truth for CPI (§7.3)."""
        pr = self.profile
        if table.presets != sorted(set(pr.cpi_presets)) or table.active_cpi != pr.active_cpi:
            pr.cpi_presets = table.presets
            pr.active_cpi = table.active_cpi
            self.store.save()
            self._load_profile()

    def _on_event(self, code, value, _raw):
        if code == p.EVENT_CPI_CHANGED:
            self.worker.run(lambda: self.mouse.cpi_table(), done=self._adopt_cpi)
        elif code in (p.EVENT_LINK, p.EVENT_BATTERY):
            call_once(self._poll)

    def _poll(self):
        # GG polls only while focused (§1.4); we poll whenever the window is
        # open so switching to Bluetooth or back shows up without a click.
        if self.get_mapped():
            self.worker.run(self._read_state, done=self._show_state, error=self._device_error,
                            key="poll")
        return GLib.SOURCE_CONTINUE  # also the 5 s timer callback

    def _device_error(self, error):
        if isinstance(error, device.MouseUnreachable):
            self.linked = False
            self.row_link.set_subtitle("Mouse asleep, off or not paired")
        elif isinstance(error, device.NotFound):
            self._set_bluetooth(False)
            self.banner.set_title("Receiver not found. Plug in the USB receiver.")
            self.banner.set_button_label("Retry")
            self.banner.set_revealed(True)
        elif isinstance(error, device.DeviceError):
            if self.mouse:
                self.mouse.close()
            self.mouse = None
            self.banner.set_title(str(error))
            self.banner.set_button_label("Retry")
            self.banner.set_revealed(True)
        else:
            self._toast(str(error))
        return False

    def _pair(self, *_):
        if self.mouse is None:
            return
        self._toast("Put the mouse in pairing mode")

        def work():
            import time
            m = self.mouse
            if m.radio_status() not in p.RADIO_UNLINKED:
                return "Mouse is already paired"
            m.pair()
            hits, deadline = 0, time.monotonic() + 20  # §7.1
            while time.monotonic() < deadline:
                time.sleep(2)
                hits = hits + 1 if m.radio_status() == p.RADIO_LINKED else 0
                if hits >= 2:
                    return "Paired"
            m.wireless_reset()
            return "Pairing timed out"
        self.worker.run(work, done=lambda msg: (self._toast(msg), self._poll()))

    def _toast(self, message):
        self.toasts.add_toast(Adw.Toast(title=message))
        return False

    def _on_close(self, *_):
        if self._listener:
            self._listener.stop()
        if self._apply_source:
            GLib.source_remove(self._apply_source)
            self._apply_dirty()
        return False


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.restart = False

    def do_activate(self):
        window = self.get_active_window() or Window(self)
        window.present()


def main():
    renderer = Store().renderer
    if not RENDERER_FROM_ENV and renderer != "auto":
        os.environ["GSK_RENDERER"] = renderer  # GTK reads it when the first window is drawn
    app = App()
    status = app.run(sys.argv)
    if app.restart:
        if not RENDERER_FROM_ENV:
            os.environ.pop("GSK_RENDERER", None)
        os.execv(sys.executable, [sys.executable, "-m", "mousework.gui", *sys.argv[1:]])
    return status


if __name__ == "__main__":
    sys.exit(main())
