"""mousework command-line interface."""

import argparse
import os
import sys
import time

from . import device
from . import protocol as p
from .profiles import (Store, apply, apply_changes, import_from_device, set_polling_if_needed,
                       set_power_if_needed)


def _rgb(text):
    text = text.lstrip("#")
    if len(text) != 6:
        raise argparse.ArgumentTypeError("colour must be RRGGBB")
    return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))


def _stop(text):
    """'ff0000@0' -> ColorStop"""
    color, _, pos = text.partition("@")
    return p.ColorStop(_rgb(color), int(pos or 0))


def cmd_status(args):
    if args.json:
        _status_json(args)
        return
    if args.follow or args.wait:
        print("mousework: --follow and --wait need --json", file=sys.stderr)
        sys.exit(2)
    with device.Mouse() as m:
        radio = m.radio_status()
        print(f"Receiver firmware: {m.receiver_version()}")
        if radio != p.RADIO_LINKED:
            print(f"Mouse: not reachable (radio status {radio}); wake it or pair it")
            return
        bat = m.battery()
        table = m.cpi_table()
        power = m.power()
        hz = 125 if power.high_efficiency else m.polling_hz()
        print(f"Mouse firmware:    {m.mouse_version()}")
        print(f"Battery:           {bat.level}%" if bat.known else "Battery: unknown")
        print("CPI presets:       " + "  ".join(
            f"[{c}]" if i + 1 == table.active else str(c) for i, c in enumerate(table.presets)))
        print(f"Polling rate:      {hz} Hz")
        print(f"High efficiency:   {'on' if power.high_efficiency else 'off'}")
        print(f"Smart illumination:{' on' if power.smart_illumination else ' off'}")
        print(f"Sleep timer:       {power.idle_sleep_s // 60} min")


def _status_json(args):
    import json
    from . import changes, status

    def show(indent):
        try:
            print(json.dumps(status.collect(), indent=indent), flush=True)
        except BrokenPipeError:  # the reader went away; don't fail again at exit
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
            return False
        return True

    def show_once():
        show(2)
        return False

    try:
        if args.follow:
            if show(None):
                changes.watch(lambda: show(None))
        elif args.wait:
            changes.watch(show_once)
        else:
            show(2)
    except KeyboardInterrupt:
        pass


def _write_buttons(m, pr):
    buttons, wheel = pr.bindings()
    m.set_buttons(buttons)
    m.set_wheel(wheel)


def _edit_profile(args, change, write):
    """Change the profile, save it, and write only the affected setting."""
    store = Store()
    profile = store.profiles[args.profile or store.active]
    if store.fresh:
        with device.Mouse() as m:
            import_from_device(profile, m)
    change(profile)
    profile.validate()
    store.save()
    if args.no_apply or (args.profile and args.profile != store.active):
        return
    with device.Mouse() as m:
        write(m, profile)
        m.save_to_flash()
    if profile is store.current:
        store.mark_saved()  # the mouse now holds the whole active profile in flash
        store.save()


def cmd_cpi(args):
    def change(pr):
        pr.cpi_presets = args.presets
        pr.active_cpi = args.active or args.presets[0]
    _edit_profile(args, change, lambda m, pr: m.set_cpi_table(
        p.make_cpi_table(pr.cpi_presets, pr.active_cpi)))


def cmd_polling(args):
    def change(pr):
        pr.polling_hz = args.hz
        if pr.high_efficiency:
            print("note: high efficiency mode is on, so the mouse stays at 125 Hz")

    def write(m, pr):
        if not pr.high_efficiency:
            m.set_polling_hz(pr.polling_hz)
    _edit_profile(args, change, write)


def cmd_power(args):
    def change(pr):
        if args.high_efficiency is not None:
            pr.high_efficiency = args.high_efficiency == "on"
        if args.smart_illumination is not None:
            pr.smart_illumination = args.smart_illumination == "on"
        if args.sleep is not None:
            pr.sleep_minutes = args.sleep

    def write(m, pr):
        set_power_if_needed(m, pr)
        if not pr.high_efficiency and args.high_efficiency == "off":
            set_polling_if_needed(m, pr.polling_hz)  # restore the chosen rate (§3.3)
    _edit_profile(args, change, write)


def cmd_light(args):
    def change(pr):
        light = pr.lighting
        if "lighting" not in pr.managed:
            pr.managed.append("lighting")
        light.effect = args.effect
        if args.effect in (p.EFFECT_STEADY, p.EFFECT_REACTIVE) and args.color:
            light.steady_color = args.color
        if args.effect == p.EFFECT_REACTIVE and args.reactive_color:
            light.reactive_color = args.reactive_color
        if args.stops:
            light.stops = args.stops
        if args.speed:
            light.speed = args.speed
    _edit_profile(args, change, lambda m, pr: m.set_lighting(pr.lighting))


def cmd_bind(args):
    def change(pr):
        if "buttons" not in pr.managed:
            pr.managed.append("buttons")
        for item in args.bindings:
            name, _, action = item.partition("=")
            if name not in p.BUTTON_NAMES + p.WHEEL_NAMES:
                raise SystemExit(f"unknown button {name!r}; one of "
                                 + ", ".join(p.BUTTON_NAMES + p.WHEEL_NAMES))
            pr.buttons[name] = p.format_action(p.parse_action(action))
    _edit_profile(args, change, _write_buttons)


def cmd_motion(args):
    def change(pr):
        for key in ("accel", "decel", "smoothing"):
            value = getattr(args, key)
            if value is not None:
                setattr(pr, f"{key}_level", value)
        if args.style:
            pr.motion_style = args.style
    # Host-side only: mousework-filter picks the change up from the profile.
    _edit_profile(args, change, lambda m, pr: None)
    store = Store()
    pr = store.current
    print(f"acceleration {pr.accel_level}, deceleration {pr.decel_level}, "
          f"smoothing {pr.smoothing_level}, style {pr.motion_style}")


def _switch_to(store, name, temporary=False):
    """Write the profile to the mouse first, then record it as active, so a
    failed write (mouse asleep) leaves the store unchanged."""
    target = store.profiles[name]
    with device.Mouse() as m:
        if temporary:
            apply_changes(target, store.current, m)
        else:
            apply(target, m)
    store.active = name
    if not temporary:
        store.mark_saved()
    store.save()
    print(f"profile {name}" + (" (temporary)" if temporary else ""))


def cmd_profile(args):
    store = Store()
    action = args.profile_action
    names = list(store.profiles)

    def existing(name):
        if name not in store.profiles:
            raise SystemExit(f"mousework: no profile named {name!r}; one of " + ", ".join(names))
        return name

    def free(name):
        if name in store.profiles:
            raise SystemExit(f"mousework: a profile named {name!r} already exists")
        return name

    if action == "list":
        for name in names:
            print(("* " if name == store.active else "  ") + name)
    elif action == "current":
        print(store.active)
    elif action == "show":
        import json
        print(json.dumps(store.profiles[existing(args.name or store.active)].to_json(), indent=2))
    elif action == "use":
        _switch_to(store, existing(args.name), args.temporary)
    elif action in ("next", "previous"):
        step = 1 if action == "next" else -1
        _switch_to(store, names[(names.index(store.active) + step) % len(names)], args.temporary)
    elif action == "new":
        from copy import deepcopy
        store.profiles[free(args.name)] = deepcopy(store.current)
        store.save()
    elif action == "rename":
        store.rename(existing(args.old), free(args.new))
        store.save()
    elif action == "delete":
        store.delete(existing(args.name))
        store.save()


def cmd_battery_warnings(args):
    store = Store()
    if args.state:
        store.battery_warnings = args.state == "on"
        store.save()
    print(f"low battery warnings: {'on' if store.battery_warnings else 'off'}")


def cmd_pair(args):
    with device.Mouse() as m:
        if m.radio_status() not in p.RADIO_UNLINKED:
            print("Mouse is already paired.")
            return
        print("Put the mouse in pairing mode now…")
        m.pair()
        hits, deadline = 0, time.monotonic() + 20  # §7.1
        while time.monotonic() < deadline:
            time.sleep(2)
            hits = hits + 1 if m.radio_status() == p.RADIO_LINKED else 0
            if hits >= 2:
                print("Paired.")
                return
        m.wireless_reset()
        raise SystemExit("Pairing timed out.")


def cmd_events(args):
    names = {p.EVENT_CPI_CHANGED: "cpi-preset", p.EVENT_LINK: "link", p.EVENT_BATTERY: "battery"}

    def show(code, value, raw):
        label = names.get(code, f"0x{code:02x}")
        print(f"{label}: {value}" + ("" if code in names else f"  raw={raw[:8].hex(' ')}"),
              flush=True)

    device.EventListener(show).start()
    print("Listening for mouse events (Ctrl+C to stop)…")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mousework",
                                 description="Settings for the SteelSeries Rival 3 Wireless (unofficial)")
    sub = ap.add_subparsers(dest="command", required=True)

    def editing(name, **kw):
        sp = sub.add_parser(name, **kw)
        sp.add_argument("--profile", help="profile to change (default: active)")
        sp.add_argument("--no-apply", action="store_true", help="only save the profile")
        return sp

    sp = sub.add_parser("status", help="show device state")
    sp.add_argument("--json", action="store_true",
                    help="machine-readable output for scripts and desktop widgets "
                         "(format: docs/json.md)")
    mode = sp.add_mutually_exclusive_group()
    mode.add_argument("--follow", action="store_true",
                      help="with --json: print one line now and another after every change")
    mode.add_argument("--wait", action="store_true",
                      help="with --json: wait for the next change (at most 2 minutes), then print")
    sp.set_defaults(func=cmd_status)

    sp = editing("cpi", help="set CPI presets")
    sp.add_argument("presets", type=int, nargs="+", help="1-5 values, 100-18000")
    sp.add_argument("--active", type=int, help="active preset value")
    sp.set_defaults(func=cmd_cpi)

    sp = editing("polling", help="set polling rate")
    sp.add_argument("hz", type=int, choices=sorted(p.POLLING_HZ))
    sp.set_defaults(func=cmd_polling)

    sp = editing("power", help="battery settings")
    sp.add_argument("--high-efficiency", choices=["on", "off"])
    sp.add_argument("--smart-illumination", choices=["on", "off"])
    sp.add_argument("--sleep", type=int, metavar="MIN", help="1-20 minutes")
    sp.set_defaults(func=cmd_power)

    sp = editing("light", help="wheel lighting")
    sp.add_argument("effect", choices=[p.EFFECT_OFF, p.EFFECT_STEADY, p.EFFECT_SHIFT,
                                       p.EFFECT_BREATHE, p.EFFECT_REACTIVE])
    sp.add_argument("--color", type=_rgb, help="steady colour RRGGBB")
    sp.add_argument("--reactive-color", type=_rgb)
    sp.add_argument("--stops", type=_stop, nargs="+", metavar="RRGGBB@POS",
                    help="colour stops for shift/breathe, e.g. ff0000@0 0000ff@50")
    sp.add_argument("--speed", type=int)
    sp.set_defaults(func=cmd_light)

    sp = editing("bind", help="remap buttons, e.g. back=key:ctrl+c forward=media:next")
    sp.add_argument("bindings", nargs="+", metavar="BUTTON=ACTION")
    sp.set_defaults(func=cmd_bind)

    sp = editing("motion", help="host-side acceleration, deceleration and smoothing")
    sp.add_argument("--accel", type=int, choices=range(11), metavar="0-10")
    sp.add_argument("--decel", type=int, choices=range(11), metavar="0-10")
    sp.add_argument("--smoothing", type=int, choices=range(11), metavar="0-10")
    sp.add_argument("--style", "--decel-style", dest="style", choices=["smooth", "gg"],
                    help="smooth (default, never drops slow movement) or gg (exactly like "
                         "SteelSeries GG)")
    sp.set_defaults(func=cmd_motion, no_apply=True)

    sp = sub.add_parser("profile", help="list, switch and manage profiles")
    psub = sp.add_subparsers(dest="profile_action", required=True)
    psub.add_parser("list", help="all profiles; * marks the active one")
    psub.add_parser("current", help="print the active profile")
    psub.add_parser("show", help="print a profile as JSON").add_argument("name", nargs="?")
    temporary = argparse.ArgumentParser(add_help=False)
    temporary.add_argument(
        "--temporary", action="store_true",
        help="write only what differs and don't save to the mouse's flash; for scripts "
             "that switch often (after a power cycle the mouse starts with the last "
             "saved profile)")
    psub.add_parser("use", help="switch to a profile", parents=[temporary]).add_argument("name")
    psub.add_parser("next", help="switch to the next profile", parents=[temporary])
    psub.add_parser("previous", help="switch to the previous profile", parents=[temporary])
    psub.add_parser("new", help="copy the active profile").add_argument("name")
    rp = psub.add_parser("rename", help="rename a profile")
    rp.add_argument("old")
    rp.add_argument("new")
    psub.add_parser("delete", help="delete a profile").add_argument("name")
    sp.set_defaults(func=cmd_profile)

    sp = sub.add_parser("battery-warnings", help="low-battery notifications on or off")
    sp.add_argument("state", choices=["on", "off"], nargs="?")
    sp.set_defaults(func=cmd_battery_warnings)

    sub.add_parser("pair", help="pair the mouse with the receiver").set_defaults(func=cmd_pair)
    sub.add_parser("events", help="print live mouse events").set_defaults(func=cmd_events)

    args = ap.parse_args(argv)
    try:
        args.func(args)
    except (device.DeviceError, ValueError) as e:
        sys.exit(f"mousework: {e}")


if __name__ == "__main__":
    main()
