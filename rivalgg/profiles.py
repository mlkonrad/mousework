"""Named configurations stored on the host and applied to the mouse (§7.4)."""

import json
import os
import time
from dataclasses import asdict, dataclass, field

from . import protocol as p

CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
                          "rivalgg")
CONFIG_FILE = os.path.join(CONFIG_DIR, "profiles.json")
DEFAULT_NAME = "Default"


@dataclass
class Profile:
    """Factory defaults follow §8.3."""
    cpi_presets: list = field(default_factory=lambda: [400, 800, 1200, 1600, 2000])
    active_cpi: int = 400
    polling_hz: int = 1000
    high_efficiency: bool = False
    smart_illumination: bool = True
    sleep_minutes: int = 5
    lighting: p.Lighting = field(default_factory=p.Lighting)
    buttons: dict = field(default_factory=lambda: {
        name: p.format_action(b) for name, b in {**p.DEFAULT_BUTTONS, **p.DEFAULT_WHEEL}.items()
    })
    # Host-side motion filter (§3.7), applied by rivalgg-filter
    accel_level: int = 0
    decel_level: int = 0
    smoothing_level: int = 0
    motion_style: str = "smooth"  # or "gg" to match SteelSeries GG exactly
    # Lighting and buttons can't be read back, so they are only written once
    # the user has set them here; until then the mouse keeps its own.
    managed: list = field(default_factory=list)  # subset of ["lighting", "buttons"]

    def to_json(self):
        return asdict(self)

    @classmethod
    def from_json(cls, data):
        data = dict(data)
        if "decel_style" in data:  # renamed
            data.setdefault("motion_style", data.pop("decel_style"))
        light = dict(data.pop("lighting", {}))
        stops = [p.ColorStop(tuple(s["color"]), s["position"]) for s in light.pop("stops", [])]
        for key in ("steady_color", "reactive_color"):
            if key in light:
                light[key] = tuple(light[key])
        lighting = p.Lighting(**light)
        if stops:
            lighting.stops = stops
        profile = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        profile.lighting = lighting
        defaults = cls().buttons
        profile.buttons = {**defaults, **profile.buttons}
        return profile

    def bindings(self):
        parsed = {name: p.parse_action(action) for name, action in self.buttons.items()}
        buttons = {n: parsed[n] for n in p.BUTTON_NAMES if n in parsed}
        wheel = {n: parsed[n] for n in p.WHEEL_NAMES if n in parsed}
        return buttons, wheel

    def validate(self):
        p.make_cpi_table(self.cpi_presets, self.active_cpi)
        p.encode_polling(self.polling_hz)
        if not 1 <= self.sleep_minutes <= 20:
            raise ValueError("sleep timer must be 1..20 minutes")
        for level in (self.accel_level, self.decel_level, self.smoothing_level):
            if not 0 <= level <= 10:
                raise ValueError("motion levels must be 0..10")
        if self.motion_style not in ("smooth", "gg"):
            raise ValueError("filter style must be smooth or gg")
        self.bindings()
        p.encode_effect_record(self.lighting)


class Store:
    def __init__(self, path=CONFIG_FILE):
        self.path = path
        self.profiles = {DEFAULT_NAME: Profile()}
        self.active = DEFAULT_NAME
        self.battery_warnings = True  # app-wide, not per profile
        # The profile whose settings the mouse holds in flash. It differs from
        # active after a temporary switch; the mouse returns to it on power-up.
        self.saved_profile = DEFAULT_NAME
        self.fresh = True  # no saved configuration yet
        self.load()

    def load(self):
        try:
            with open(self.path) as f:
                data = json.load(f)
        except FileNotFoundError:
            return
        self.fresh = False
        self.profiles = {name: Profile.from_json(d) for name, d in data["profiles"].items()}
        if not self.profiles:
            self.profiles = {DEFAULT_NAME: Profile()}
        self.active = data.get("active", DEFAULT_NAME)
        self.battery_warnings = data.get("battery_warnings", True)
        self.saved_profile = data.get("saved_profile", self.active)
        if self.active not in self.profiles:
            self.active = next(iter(self.profiles))

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"active": self.active,
                       "battery_warnings": self.battery_warnings,
                       "saved_profile": self.saved_profile,
                       "profiles": {n: pr.to_json() for n, pr in self.profiles.items()}},
                      f, indent=2)
        os.replace(tmp, self.path)

    @property
    def current(self):
        return self.profiles[self.active]

    @property
    def mouse_may_differ(self):
        """True when a power-up could bring back the saved profile instead."""
        return self.saved_profile != self.active

    def mark_saved(self):
        """Record that the active profile was just saved to the mouse's flash."""
        self.saved_profile = self.active

    def rename(self, old, new):
        self.profiles = {new if k == old else k: v for k, v in self.profiles.items()}
        if self.active == old:
            self.active = new
        if self.saved_profile == old:
            self.saved_profile = new

    def delete(self, name):
        if len(self.profiles) == 1:
            raise ValueError("cannot delete the last profile")
        del self.profiles[name]
        if self.active == name:
            self.active = next(iter(self.profiles))
        if self.saved_profile == name:
            self.saved_profile = None  # flash holds a deleted profile's settings


def set_polling_if_needed(mouse, hz):
    """Write the polling rate only if the mouse isn't already at it.

    Each polling-rate write makes the mouse reconfigure, which briefly
    stalls the pointer. Leaving high efficiency mode may already restore the
    rate (§3.3). The 1.5 s wait avoids stale reads (§2.3).
    """
    time.sleep(1.5)
    try:
        if mouse.polling_hz() == hz:
            return
    except Exception:
        pass  # unreadable; write it to be sure
    mouse.set_polling_hz(hz)


def apply(profile, mouse, progress=lambda message: None, save=True):
    """Write every on-mouse setting of a profile, then save to flash (§4)."""
    profile.validate()
    buttons, wheel = profile.bindings()
    current = mouse.power()

    progress("Power settings")
    mouse.set_power(p.PowerSettings(
        high_efficiency=profile.high_efficiency,
        movement_saving=p.SMART_ILLUMINATION_ON if profile.smart_illumination else 0,
        idle_lighting_s=current.idle_lighting_s,  # GG preserves this field (§3.3)
        idle_sleep_s=profile.sleep_minutes * 60,
    ))
    if not profile.high_efficiency:
        progress("Polling rate")
        set_polling_if_needed(mouse, profile.polling_hz)

    progress("Sensitivity")
    mouse.set_cpi_table(p.make_cpi_table(profile.cpi_presets, profile.active_cpi))
    if "lighting" in profile.managed:
        progress("Lighting")
        mouse.set_lighting(profile.lighting)
    if "buttons" in profile.managed:
        progress("Buttons")
        mouse.set_buttons(buttons)
        mouse.set_wheel(wheel)
    if save:
        progress("Saving to mouse")
        mouse.save_to_flash()
    time.sleep(1.0)  # §2.3 settle after a full configuration
    progress("Done")


def import_from_device(profile, mouse):
    """Adopt the settings the mouse can report (CPI, polling, power)."""
    table = mouse.cpi_table()
    power = mouse.power()
    profile.cpi_presets, profile.active_cpi = table.presets, table.active_cpi
    profile.high_efficiency = power.high_efficiency
    profile.smart_illumination = power.smart_illumination
    profile.sleep_minutes = max(1, min(20, power.idle_sleep_s // 60))
    if not power.high_efficiency:
        profile.polling_hz = mouse.polling_hz() or profile.polling_hz


def apply_changes(target, previous, mouse):
    """Write only the settings that differ from the previous profile, without
    saving to flash, so scripts can switch often without wearing it out."""
    buttons, wheel = target.bindings()
    power_keys = ("high_efficiency", "smart_illumination", "sleep_minutes")
    if any(getattr(target, k) != getattr(previous, k) for k in power_keys):
        current = mouse.power()
        mouse.set_power(p.PowerSettings(
            target.high_efficiency,
            p.SMART_ILLUMINATION_ON if target.smart_illumination else 0,
            current.idle_lighting_s, target.sleep_minutes * 60))
    if not target.high_efficiency and (target.polling_hz != previous.polling_hz
                                       or previous.high_efficiency):
        set_polling_if_needed(mouse, target.polling_hz)
    if (target.cpi_presets, target.active_cpi) != (previous.cpi_presets, previous.active_cpi):
        mouse.set_cpi_table(p.make_cpi_table(target.cpi_presets, target.active_cpi))
    if "lighting" in target.managed and target.lighting != previous.lighting:
        mouse.set_lighting(target.lighting)
    if "buttons" in target.managed and target.buttons != previous.buttons:
        mouse.set_buttons(buttons)
        mouse.set_wheel(wheel)


def resend_volatile(profile, mouse):
    """On-connect re-send of lighting and bindings (§7.2)."""
    buttons, wheel = profile.bindings()
    if "lighting" in profile.managed:
        mouse.set_lighting(profile.lighting)
    if "buttons" in profile.managed:
        mouse.set_buttons(buttons)
        mouse.set_wheel(wheel)
