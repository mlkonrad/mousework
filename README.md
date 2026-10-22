# rivalgg

Settings for the **SteelSeries Rival 3 Wireless** (USB `1038:1830`) on Linux:
a GTK 4 / libadwaita app and a command-line tool.

## Clean-room provenance

This code was written only from the behavioral specification in
`../spec/SPEC.md`. The implementer never saw SteelSeries GG's files,
decompiled code or reverse-engineering notes (`../re-work/`). Section
references such as `§3.1` in the code point into that spec.

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
| Named profiles | host (`~/.config/rivalgg/profiles.json`) |
| Follows CPI changes made with the on-mouse button | live events |
| Acceleration, deceleration and smoothing (0–10 each) | host, via `rivalgg-filter` |
| Low-battery notifications at 15 % and 5 % (can be turned off) | host, via `rivalgg-filter` |

Not implemented:

- Firmware updates (§6.3; deliberately left out because a failed flash can brick the mouse).
- Macros (§3.6).
- Automatic per-application profile switching (§7.4). GNOME on Wayland
  doesn't tell apps which window is focused; anything that does (a Shell
  extension, a compositor script) can call `rivalgg profile use NAME`.

## Install

```sh
sudo install -m644 data/70-rivalgg.rules /etc/udev/rules.d/   # access without root
sudo udevadm control --reload && sudo udevadm trigger
python3 -m pip install --user --no-deps --editable .         # uses system python3-gobject, python3-evdev
install -Dm644 data/io.github.rivalgg.desktop ~/.local/share/applications/io.github.rivalgg.desktop
install -Dm644 data/rivalgg-filter.service ~/.config/systemd/user/rivalgg-filter.service
systemctl --user enable --now rivalgg-filter                  # idle until a motion level is above 0
```

## Use

```sh
rivalgg-gtk                                  # the app
rivalgg status
rivalgg cpi 400 800 1600 --active 800
rivalgg polling 1000
rivalgg power --high-efficiency off --sleep 10
rivalgg light breathe --stops ff0000@0 0000ff@50
rivalgg bind back=key:ctrl+c forward=media:next
rivalgg profile list                         # * marks the active profile
rivalgg profile new Gaming && rivalgg profile use Gaming
rivalgg profile next                         # or previous; handy for a keyboard shortcut
rivalgg profile current
rivalgg events                               # watch CPI button, link and battery events
rivalgg battery-warnings off                 # or on
```

On first run, rivalgg imports what the mouse can report (CPI, polling, power
settings). Button mappings and lighting have no read-back, so they stay as
they are on the mouse until you change them.

## Motion filter

Acceleration, deceleration and smoothing (GG calls smoothing "angle
snapping", §3.7.2) are computed on the computer, not on the mouse.
`rivalgg-filter` grabs the mouse's input device and re-emits the filtered
motion as a virtual mouse. When all three levels are 0 it leaves the mouse alone.

```sh
rivalgg motion --accel 4 --decel 3 --smoothing 2
rivalgg motion --style gg              # exactly like SteelSeries GG
journalctl --user -u rivalgg-filter    # what the filter is doing
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

Diagnostics: `RIVALGG_DEBUG=1` logs button and settings events, and
`RIVALGG_TRACE=/path/trace.csv` records every report (input, output, latency).

GNOME's own pointer acceleration still applies on top of the filter. Set
Settings → Mouse → Acceleration to off (flat) if you only want rivalgg's.

## Tests

```sh
python3 -m unittest discover -s tests -t .
```
