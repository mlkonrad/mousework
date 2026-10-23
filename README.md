# Mousework

Settings for the **SteelSeries Rival 3 Wireless** (USB `1038:1830`) on Linux:
a GTK 4 / libadwaita app, a command-line tool and a small background service.

Mousework is an independent project. It is not made, endorsed or supported by
SteelSeries. SteelSeries, Rival and SteelSeries GG are trademarks of their
owners and are used here only to say which hardware Mousework works with.

## Clean-room provenance

Mousework was written from a behavioral specification of how SteelSeries GG
talks to this mouse, produced in a separate reverse-engineering pass for
interoperability. The people writing Mousework's code never saw GG's files,
decompiled code or reverse-engineering notes. Section references such as
`§3.1` in the code point into that specification, which is not part of this
repository.

## Features

| Feature | Where it lives |
|---|---|
| CPI presets (1–5, 100–18000), active preset | on the mouse |
| Polling rate 125/250/500/1000 Hz | on the mouse |
| High efficiency mode, smart illumination, sleep timer (1–20 min) | on the mouse |
| Wheel lighting: off, steady, colour shift, breathe, reactive | on the mouse |
| Remapping 6 buttons and the wheel: clicks, CPI cycle, keyboard shortcuts, media keys | on the mouse |
| Battery level, firmware versions, connection state | read from the mouse |
| Pairing the mouse with the receiver | receiver |
| Named profiles | host (`~/.config/mousework/profiles.json`) |
| Follows CPI changes made with the on-mouse button | live events |
| Acceleration, deceleration and smoothing (0–10 each) | host, via `mousework-filter` |
| Low-battery notifications at 15 % and 5 % (can be turned off) | host, via `mousework-filter` |

Not implemented:

- Firmware updates (§6.3; deliberately left out because a failed flash can brick the mouse).
- Macros (§3.6).
- Automatic per-application profile switching (§7.4). GNOME on Wayland
  doesn't tell apps which window is focused; anything that does (a Shell
  extension, a compositor script) can call `mousework profile use NAME`.

## Install

Mousework needs Python 3.11+, PyGObject with GTK 4 and libadwaita, and
python-evdev. `install.sh` checks for them and prints the command for your
distribution if something is missing.

```sh
git clone https://github.com/mlkonrad/mousework.git
cd mousework
./install.sh            # or ./install.sh --dev to run from this checkout
```

The script installs everything for your user (`~/.local/share/mousework`,
launchers in `~/.local/bin`, an app-grid entry and the `mousework-filter`
systemd user service). It asks for sudo once, for the udev rule
`/etc/udev/rules.d/70-mousework.rules`, which gives the logged-in user access
to:

- the receiver's hidraw interfaces, to read and change the mouse's settings;
- the mouse's input device (not its keyboard interface), so the motion filter
  can read movement;
- `/dev/uinput`, so the motion filter can create its virtual mouse. Any program
  you run can use uinput to send input events; many systems allow this already.

To remove it: `./uninstall.sh` (add `--purge` to delete your profiles too).

## Use

```sh
mousework-gtk                                  # the app
mousework status
mousework status --json                        # for scripts and widgets, see docs/json.md
mousework cpi 400 800 1600 --active 800
mousework polling 1000
mousework power --high-efficiency off --sleep 10
mousework light breathe --stops ff0000@0 0000ff@50
mousework bind back=key:ctrl+c forward=media:next
mousework profile list                         # * marks the active profile
mousework profile new Gaming && mousework profile use Gaming
mousework profile next                         # or previous; handy for a keyboard shortcut
mousework profile use Gaming --temporary       # for scripts: only differences, no flash save
mousework profile current
mousework events                               # watch CPI button, link and battery events
mousework battery-warnings off                 # or on
```

### Battery level in your panel or scripts

`mousework status --json` prints the battery level, connection state, CPI,
polling rate and active profile in a stable, versioned JSON format.
[docs/json.md](docs/json.md) documents every field and has examples for shell
scripts, Python, Waybar, GNOME Shell, KDE Plasma and Polybar; a JSON Schema is
in [docs/status.schema.json](docs/status.schema.json).

### Top-bar indicator for GNOME Shell

`gnome-shell-extension/` is a small GNOME Shell extension (Shell 49 and 50)
built on `mousework status --json`. While the mouse is connected through its
USB receiver, it shows an icon in the top bar (dimmed while the mouse is
asleep), and its menu lists the battery level, DPI, polling rate and profile.
In its settings you choose the icon (battery level, mouse or none) and what
appears next to it: the battery percentage, DPI, polling rate and profile. It
updates as soon as `mousework-filter` reports a change (the CPI button, the
mouse waking or sleeping, a new battery level, a setting or profile changed in
the app or with the CLI), and otherwise every two minutes and whenever you
open the menu.

```sh
glib-compile-schemas gnome-shell-extension/schemas
ln -s "$PWD/gnome-shell-extension" ~/.local/share/gnome-shell/extensions/mousework@mlkonrad.github.com
# log out and back in, then:
gnome-extensions enable mousework@mlkonrad.github.com
```

On first run, Mousework imports what the mouse can report (CPI, polling, power
settings). Button mappings and lighting have no read-back, so they stay as
they are on the mouse until you change them.

### Temporary switches

`--temporary` (on `profile use`, `next` and `previous`) writes only the
settings that differ from the active profile and doesn't save to the mouse's
flash, so scripts can switch often without wearing it out. After a power
cycle the mouse starts with the last saved profile; Mousework remembers which
one that is and re-applies the active profile when it reconnects. Any normal
switch or setting change saves everything again.

## Motion filter

Acceleration, deceleration and smoothing (GG calls smoothing "angle
snapping", §3.7.2) are computed on the computer, not on the mouse.
`mousework-filter` grabs the mouse's input device and re-emits the filtered
motion as a virtual mouse. When all three levels are 0 it leaves the mouse alone.

```sh
mousework motion --accel 4 --decel 3 --smoothing 2
mousework motion --style gg              # exactly like SteelSeries GG
journalctl --user -u mousework-filter    # what the filter is doing
```

Filter styles:

- `smooth` (default): deceleration fades out over ten steps as speed rises,
  and scaling and smoothing carry leftover fractions forward, so slow
  movement is never dropped.
- `gg`: matches SteelSeries GG on Windows exactly. Deceleration switches off
  abruptly at a speed threshold, and its rounding drops many small movements
  at 1000 Hz, which feels like stutter when deceleration and smoothing are
  combined.

Over Bluetooth the filter does nothing, and the app greys out all settings
(the mouse has no settings channel in that mode, §7.5).

Diagnostics: `MOUSEWORK_DEBUG=1` logs button and settings events, and
`MOUSEWORK_TRACE=/path/trace.csv` records every report (input, output, latency).

GNOME's own pointer acceleration still applies on top of the filter. Set
Settings → Mouse → Acceleration to off (flat) if you only want Mousework's.

## Development

```sh
./install.sh --dev                         # code changes apply on the next start
python3 -m unittest discover -s tests -t .
```

## License

MIT, see [LICENSE](LICENSE).
