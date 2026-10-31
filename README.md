# Mousework

Settings for the **SteelSeries Rival 3 Wireless** (USB `1038:1830`) on Linux:
a GTK 4 / libadwaita app, a command-line tool and a small background service.

The **Rival 3 Wireless Gen 2** (USB `1038:1872`) is supported too, but that
support is **untested**: it was written from the specification alone, without
the mouse at hand. If you have one, please report how it works, together with
the output of `mousework status`. See [Rival 3 Wireless Gen 2](#rival-3-wireless-gen-2).

Mousework is an independent project. It is not made, endorsed or supported by
SteelSeries. SteelSeries, Rival and SteelSeries GG are trademarks of their
owners and are used here only to say which hardware Mousework works with.

## Clean-room provenance

Mousework was written from a behavioral specification of how SteelSeries GG
talks to this mouse, produced in a separate reverse-engineering pass for
interoperability. The people writing Mousework's code never saw GG's files,
decompiled code or reverse-engineering notes. Section references such as
`spec 3.1` in the code point into that specification, and `survey C.1` into a
later survey of other SteelSeries models made the same way. Neither is part of
this repository.

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

## Compared with other tools

Two other Linux tools configure SteelSeries mice. As of October 2026:

- [Piper](https://github.com/libratbag/piper), the GUI for
  [libratbag](https://github.com/libratbag/libratbag), doesn't support the
  Rival 3 Wireless: libratbag has no device file for `1038:1830`.
- [rivalcfg](https://github.com/flozz/rivalcfg) (command line, WTFPL license)
  supports it: CPI presets, polling rate, mapping buttons 1 to 6, battery
  level and firmware version.

What Mousework adds for this mouse:

- a GTK 4 / libadwaita app, next to the command line;
- wheel lighting, power settings (high efficiency mode, smart illumination,
  sleep timer), remapping the scroll wheel, and pairing;
- named profiles, the motion filter (acceleration, deceleration, smoothing)
  and low-battery notifications;
- live updates from the mouse, `mousework status --json` for panels and the
  GNOME Shell indicator.

Where rivalcfg is ahead: it supports dozens of SteelSeries mice, while
Mousework supports the Rival 3 Wireless and, untested so far, the Rival 3
Wireless Gen 2. If you need another model, use rivalcfg.

Mousework doesn't use code from either project.

## Rival 3 Wireless Gen 2

The Gen 2 is a different mouse with its own receiver (`1038:1872`), so it
needs no extra setup: Mousework finds whichever receiver is plugged in. Its
differences, as far as Mousework is concerned:

- No lighting and no smart illumination. The app hides them, and
  `mousework light` refuses. Profiles keep their lighting settings for a
  Rival 3 Wireless.
- High efficiency mode isn't a setting of the mouse itself. Mousework keeps
  the switch in the profile and sets the polling rate to 125 Hz while it's
  on, which is what SteelSeries GG does for this mouse.
- The mouse can set X and Y sensitivity separately. Mousework always sets
  both to the same value; a preset with different values is shown with its
  X value.
- Low-battery notifications ignore the first 10 seconds after the mouse
  connects, when fresh alkaline cells read low.
- Not implemented: the mouse's wireless power settings (link redundancy and
  Bluetooth boost). Mousework leaves them as they are.

None of this has been tried on the real mouse yet. If you have one, please
[report how it works](#other-steelseries-mice).

## Other SteelSeries mice

Mousework can't configure other SteelSeries mice yet, but it can identify
many of them so their owners can help add support:

```sh
mousework probe            # or: sudo mousework probe
```

The probe only reads: it asks for the firmware version, the link and battery
state, and where the format is known, the CPI and polling settings. It never
sends a command that changes a setting, and it sends nothing to a device it
doesn't recognise, to a mouse in its bootloader, or over Bluetooth. It knows
the Rival 3 Wireless family, the Aerox 3/5/9 (wired and wireless), Rival 5,
Prime Mini, Prime Wireless, Rival 3 Gen 2 and the Sensei Pro / Rival Pro
series. The udev rule only gives access to the supported mice, so for the
others run it with `sudo`.

Please paste the output into a
[mouse report](https://github.com/mlkonrad/mousework/issues/new?template=other-mouse.yml).

## Install

### Fedora

Mousework is packaged for Fedora 43 and newer (x86_64 and aarch64) in the
[mlkonrad/mousework](https://copr.fedorainfracloud.org/coprs/mlkonrad/mousework/)
Copr repository:

```sh
sudo dnf copr enable mlkonrad/mousework
sudo dnf install mousework
```

New versions then arrive with your normal system updates (`dnf upgrade`,
GNOME Software). The package installs the app, the `mousework` command, the
udev rule (see [below](#device-access)) and the `mousework-filter` user
service, which starts at your next login: log out and back in once after
installing. On GNOME it also installs the
[top-bar indicator](#top-bar-indicator-for-gnome-shell), and Mousework offers
to turn it on the first time you open it.

To remove it: `sudo dnf remove mousework`. Your profiles in
`~/.config/mousework` stay. To keep the app but drop the indicator:
`sudo dnf remove mousework-gnome-shell-extension`.

If you used `install.sh` before, run `./uninstall.sh` first: a copy in
`~/.local` takes precedence over the package.

### Other distributions

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
systemd user service). On GNOME it also offers the
[top-bar indicator](#top-bar-indicator-for-gnome-shell). It asks for sudo once,
for the udev rule `/etc/udev/rules.d/70-mousework.rules`. To update, run
`git pull` and `./install.sh` again.

To remove it: `./uninstall.sh` (add `--purge` to delete your profiles too).

### Device access

The udev rule (`70-mousework.rules`) gives the logged-in user access to:

- the receiver's hidraw interfaces, to read and change the mouse's settings;
- the mouse's input device (not its keyboard interface), so the motion filter
  can read movement;
- `/dev/uinput`, so the motion filter can create its virtual mouse. Any program
  you run can use uinput to send input events; many systems allow this already.

## Use

```sh
mousework-gtk                                  # the app
mousework status
mousework status --json                        # for scripts and widgets, see docs/json.md
mousework status --json --follow               # one line now and after every change
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
mousework probe                                # identify a SteelSeries mouse (read-only)
mousework battery-warnings off                 # or on
```

The app's **Renderer** setting (at the bottom of the window) picks how GTK
draws it: Automatic, Vulkan, OpenGL or Software (Cairo). Software uses about
half the memory (~38 MB instead of ~73 MB). If a choice leaves the window
unusable, start it once with another renderer, which overrides the saved one:
`GSK_RENDERER=cairo mousework-gtk`.

### Battery level in your panel or scripts

`mousework status --json` prints the battery level, connection state, CPI,
polling rate and active profile in a stable, versioned JSON format.
`--follow` prints a new line whenever something changes, so panels update
live without polling. [docs/json.md](docs/json.md) documents every field and
has examples for shell scripts, Python, Waybar (Omarchy, Hyprland, Sway), GNOME
Shell, KDE Plasma, Xfce, Polybar and i3blocks; a JSON Schema is in
[docs/status.schema.json](docs/status.schema.json).

### Top-bar indicator for GNOME Shell

`gnome-shell-extension/` is a small GNOME Shell extension (Shell 49 and 50)
built on `mousework status --json`. While the mouse is connected through its
USB receiver, it shows an icon in the top bar (dimmed while the mouse is
asleep, and spinning a sync icon while settings are written to the mouse),
and its menu lists the battery level, DPI and polling rate, and switches
between your profiles with a click.
In its settings you choose the icon (battery level, mouse or none) and what
appears next to it: the battery percentage, DPI, polling rate and profile. It
updates as soon as `mousework-filter` reports a change (the CPI button, the
mouse waking or sleeping, a new battery level, a setting or profile changed in
the app or with the CLI), and otherwise every two minutes and whenever you
open the menu.

Switching to a profile with different power settings makes the mouse drop its
link to the receiver for a few seconds while it syncs. The indicator shows a
sync icon during that time instead of an asleep mouse. The icon follows
GNOME's animation setting: it spins normally, and stands still when Settings →
Accessibility → Reduce Animation is on (or when another extension, such as Just
Perfection, turns animations off).

On GNOME, `install.sh` checks that your GNOME Shell version can run it and
asks whether to install it (with `--dev` it links to the checkout, like the
rest). Log out and back in afterwards: GNOME loads new extensions at login.
`uninstall.sh` removes it again.

The **Top bar indicator** switch in the app's App section turns the
indicator on or off for your user; it appears whenever the extension is
installed and you're on GNOME. A distribution package can install the
extension but not turn it on, so the first time you open Mousework with the
indicator installed but off, it offers to turn it on. Right after installing
the extension, it starts at your next login; after that, the switch takes
effect at once.

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

MIT, see [LICENSE](LICENSE). The app icon is an exception: it is adapted
from GNOME's Adwaita `input-mouse` icon and licensed under
[CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/).
