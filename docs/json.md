# Mousework JSON status

`mousework status --json` prints the state of the mouse as one JSON object.
It is meant for anything that wants to show the battery level or other mouse
state: GNOME Shell extensions, KDE Plasma widgets, Waybar, Polybar, conky,
shell scripts, or your own programs.

- The output always describes the situation, whether or not the mouse can be
  reached. A missing receiver, a sleeping mouse or missing permissions are
  reported as states, not as errors (see [Connection states](#connection-states)).
- The format is versioned and only grows. Code written for version 1 keeps
  working (see [Compatibility](#compatibility)).
- A machine-readable [JSON Schema](https://json-schema.org/) is in
  [`status.schema.json`](status.schema.json). The test suite checks the real
  output against it, so the schema and this page stay in step with the code.

Contents:

1. [Quick start](#quick-start)
2. [How it works](#how-it-works)
3. [Example output](#example-output)
4. [Fields](#fields)
5. [Connection states](#connection-states)
6. [Exit status](#exit-status)
7. [How often to call it](#how-often-to-call-it)
8. [Change notifications](#change-notifications)
9. [Compatibility](#compatibility)
10. [Writing your own integration](#writing-your-own-integration)
11. [Examples](#examples): shell, Python, Waybar (Omarchy, Hyprland, Sway), GNOME Shell,
    KDE Plasma, Xfce, Polybar, i3blocks and others

## Quick start

```sh
mousework status --json                              # the whole object
mousework status --json | jq '.battery.level'        # 62, or null if unknown
```

Where the `mousework` command lives depends on how you installed it:

| Installed with | Command |
|---|---|
| `install.sh` | `~/.local/bin/mousework` |
| a distribution package (RPM, AUR, ...) | `/usr/bin/mousework` |

Desktop shells don't always have `~/.local/bin` in their `PATH` (GNOME Shell
on Fedora doesn't), so from an extension or widget call it by its full path.
The examples below use `~/.local/bin/mousework`; with a package, use
`/usr/bin/mousework` or just `mousework` instead. The Python and GJS examples
find it either way.

## How it works

Three pieces are involved. Your integration only ever talks to the first two.

```text
 mouse ))) USB receiver ──── hidraw ───┬──> mousework status --json ──> JSON on stdout
                                       │       (reads the receiver and
 ~/.config/mousework/profiles.json ────┤        profiles.json, then exits)
                                       │
                                       └──> mousework-filter (systemd user service)
                                              watches hardware events and profiles.json
                                              └──> D-Bus signal "Changed" on the session bus
```

1. **`mousework status --json`** answers the question "what is the state right
   now?". Each call opens the receiver, asks the receiver and the mouse a few
   short questions, reads the active profile from
   `~/.config/mousework/profiles.json`, prints one JSON object and exits. It
   only reads: it never changes a setting.
2. **The `Changed` signal** answers "when should I ask again?". The
   `mousework-filter` service, which `install.sh` sets up and starts at login,
   is always running anyway (it applies the motion filter and sends low-battery
   notifications). It hears the mouse's own events (the CPI button, the mouse
   waking up or going to sleep, battery reports) and notices when
   `profiles.json` changes, which is what happens whenever the app or the
   command line changes a setting or switches profiles. For each of these it
   broadcasts `io.github.mlkonrad.Mousework.Changed` on the session bus. The
   signal carries no state, only a hint about what happened: always read the
   state with `mousework status --json`.
3. **`--follow` and `--wait`** combine the two, for tools that can't use D-Bus:
   they listen for the signal themselves and print a fresh status after each
   change.

So an integration is always: read the status once at start, then read it again
whenever a change is announced, with a slow poll in case the service isn't
running. The JSON format and the signal are the stable interface; everything
else (the receiver protocol, the profile file's layout, the service's
internals) can change between releases.

## Example output

The mouse connected through its USB receiver:

```json
{
  "version": 1,
  "device": "SteelSeries Rival 3 Wireless",
  "connection": "receiver",
  "error": null,
  "battery": {
    "level": 62,
    "state": "discharging"
  },
  "firmware": {
    "mouse": "1.04",
    "receiver": "1.02"
  },
  "cpi": {
    "presets": [400, 800, 1600],
    "active": 800,
    "active_index": 2
  },
  "polling_hz": 1000,
  "power": {
    "high_efficiency": false,
    "smart_illumination": true,
    "sleep_minutes": 10
  },
  "profile": {
    "active": "Gaming",
    "saved_to_mouse": true,
    "available": ["Default", "Gaming"]
  },
  "syncing": null
}
```

The receiver is plugged in, but the mouse is asleep:

```json
{
  "version": 1,
  "device": "SteelSeries Rival 3 Wireless",
  "connection": "asleep",
  "error": null,
  "battery": null,
  "firmware": {
    "mouse": null,
    "receiver": "1.02"
  },
  "cpi": null,
  "polling_hz": null,
  "power": null,
  "profile": {
    "active": "Gaming",
    "saved_to_mouse": true,
    "available": ["Default", "Gaming"]
  },
  "syncing": null
}
```

Every field is always present. When a value isn't known, it is `null`; it is
never left out. (Real output is indented the same way, but arrays are spread
over several lines.)

## Fields

| Field | Type | Meaning |
|---|---|---|
| `version` | integer | Format version, currently `1`. See [Compatibility](#compatibility). |
| `device` | string | `"SteelSeries Rival 3 Wireless"`, the only supported mouse. Meant for display. |
| `connection` | string | How the mouse is reachable right now. One of the [connection states](#connection-states). This is the field to look at first. |
| `error` | string or null | A human-readable explanation when something went wrong, for example `"no permission to open /dev/hidraw2; install the udev rule"`. Show it in a tooltip or log it, but don't parse it: the wording can change in any release. |
| `battery` | object or null | The battery, or `null` when the level isn't known. |
| `battery.level` | integer, 0–100 | Charge in percent. |
| `battery.state` | string | `discharging`, `charging` or `charged`. The Rival 3 Wireless runs on replaceable batteries, so in practice it reports `discharging`. The other two values exist in the mouse's protocol and are listed so your code handles them. |
| `firmware` | object | Firmware versions. The object is always present; its fields can be `null`. |
| `firmware.mouse` | string or null | Mouse firmware, for example `"1.04"`. Only known while the mouse is reachable. |
| `firmware.receiver` | string or null | Receiver firmware, for example `"1.02"`. Known whenever the receiver answers, also while the mouse sleeps. |
| `cpi` | object or null | Sensitivity settings (CPI is often called DPI). |
| `cpi.presets` | array of integers | 1 to 5 presets in ascending order, each 100–18000. The CPI button on the mouse cycles through them. |
| `cpi.active` | integer | The CPI value in use, one of `cpi.presets`. |
| `cpi.active_index` | integer, 1–5 | Position of the active preset in `cpi.presets`, **counting from 1** (so `cpi.presets[cpi.active_index - 1]` equals `cpi.active`). |
| `polling_hz` | integer or null | Polling rate: `125`, `250`, `500` or `1000`. Always `125` while `power.high_efficiency` is on. |
| `power` | object or null | Power-saving settings. |
| `power.high_efficiency` | boolean | High efficiency mode, for longer battery life. The polling rate is fixed at 125 Hz while it's on. |
| `power.smart_illumination` | boolean | Smart illumination, the power-saving option for the wheel lighting. |
| `power.sleep_minutes` | integer, 1–20 | Minutes without use before the mouse goes to sleep. |
| `profile` | object or null | The active Mousework profile. Read from `~/.config/mousework/profiles.json`, so it is available whatever the connection. `null` only if that file can't be read. |
| `profile.active` | string | Name of the active profile, as shown by `mousework profile current`. Before the first profile is created it is `"Default"`. |
| `profile.available` | array of strings | Names of all profiles, including the active one, in the order the app lists them and `mousework profile next` cycles through them. Switch with `mousework profile use NAME`. |
| `syncing` | object or null | Not `null` while Mousework writes settings to the mouse: a profile switch, a setting changed in the app or with the command line. See [Syncing](#syncing). |
| `syncing.profile` | string or null | The profile being written, or `null` if Mousework doesn't say. |
| `profile.saved_to_mouse` | boolean | `false` after a temporary switch (`mousework profile use NAME --temporary`): the mouse has the profile's settings now, but it will start with a different, saved profile after it's switched off and on. `true` otherwise. |

Rules that hold for every state:

- `battery`, `cpi`, `polling_hz` and `power` are only filled in when
  `connection` is `receiver`. In every other state they are `null`.
- `profile` and `syncing` don't depend on the connection.
- Even with `connection` set to `receiver`, `battery` is `null` if the mouse
  didn't report a level, and `polling_hz` is `null` if it reported a rate
  Mousework doesn't know.
- Rarely, the mouse sends an answer Mousework can't decode. `connection` is
  then still `receiver`, `error` says what failed, and the fields that couldn't
  be read are `null`.

## Connection states

| `connection` | What it means | What to show | Other fields |
|---|---|---|---|
| `receiver` | The mouse is awake and connected through its USB receiver. | The battery level. | Filled in (see above). |
| `asleep` | The receiver is plugged in, but the mouse doesn't answer: it is asleep, switched off, out of range or not paired. Moving or clicking it wakes it up. | "Asleep" or a dimmed icon. Keep showing the last known battery level if you like; Mousework doesn't remember it for you. | `firmware.receiver` is known. |
| `bluetooth` | The mouse is connected over Bluetooth. In this mode it has no settings channel, so Mousework can't read anything from it, including the battery. | "Bluetooth". For a battery level, use the desktop's own Bluetooth battery display (UPower), if it shows one. | `firmware.receiver` is known if the receiver is also plugged in and answering. |
| `no-receiver` | The USB receiver isn't plugged in, and the mouse isn't connected over Bluetooth either. Also reported when the receiver was unplugged while Mousework was reading it. | Nothing, or "Disconnected". Many widgets simply hide themselves. | All `null`, `error` may explain. |
| `no-access` | The receiver is there, but your user isn't allowed to open it. Usually the udev rule is missing: run `./install.sh` again. | "No permission", with `error` in a tooltip. | All `null`, `error` explains. |
| `no-response` | The receiver is plugged in but doesn't answer, while the mouse isn't on Bluetooth either. The receiver is stuck; unplugging it and plugging it back in resets it. | "Not responding", or treat it like `asleep`. | All `null`, `error` explains. |

Handle unknown values: if `connection` is something your code doesn't know, a
newer Mousework added a state. Treat it like `no-receiver` and show nothing,
rather than failing.

### Syncing

Changing the mouse's power settings (high efficiency, smart illumination,
sleep timer) makes it drop its link to the receiver for a few seconds and then
reconnect by itself. Turning high efficiency on drops it at once for about
2.5 s; turning it off keeps it about 1.2 s and then drops it for about 5 s.
Profile switches often change power settings, so they cause this too.

While Mousework writes settings, `syncing` is set, and the writing process
sends the [`Changed` signal](#change-notifications) with `what` = `syncing`
when it starts and when it ends. During the drop, `connection` reads `asleep`,
truthfully, but `syncing` tells you why, so show "syncing" (GNOME's extension
spins a sync icon) instead of "asleep":

```json
{
  "connection": "asleep",
  "syncing": {"profile": "Gaming"}
}
```

A switch takes about 3 to 10 seconds. `syncing` is reported only while the
writing process is alive, so a crash can't leave it stuck.

## Exit status

| Exit status | Meaning |
|---|---|
| `0` | Valid JSON was printed on standard output. **This includes every connection state**, even `no-receiver`. |
| `2` | The command line was wrong, for example an old Mousework that doesn't know `--json` yet, or `--follow` without `--json`. Nothing was printed on standard output. |
| anything else | An unexpected failure (a bug, or a broken installation). Standard output may be empty or incomplete; a message is on standard error. |

So the rule for your code is: if the exit status isn't `0`, or the output
doesn't parse, show "unknown" and try again later. Warnings and errors only
ever go to standard error, never to standard output.

## How often to call it

Each call starts Python and sends about a dozen short queries to the receiver and mouse. It
usually takes well under a second, but plan for more:

- **Never block a user interface while it runs.** In a desktop shell this
  matters most: a blocked GNOME Shell freezes the whole desktop. Use the
  asynchronous APIs shown in the examples.
- **Use a timeout of about 10 seconds.** A receiver that doesn't answer costs
  one second per call; Mousework's own app and background service share the
  receiver with you, and a call waits for them to finish their current query.
- **Poll every 1 to 5 minutes for the battery.** The level changes slowly.
  Mousework's own background service checks it every 5 minutes. Polling more
  often than every 10 seconds gains nothing.
- **Or don't poll at all**: `--follow` and `--wait` print when something
  changes (see [Change notifications](#change-notifications)).
- **Calling it while the Mousework app or service is running is safe.** All
  Mousework processes take turns on the receiver, so they never read each
  other's answers.

`mousework status --json` only reads. It never changes settings and never
writes to the mouse's memory.

## Change notifications

Your widget can update as soon as something changes (the CPI button, the mouse
waking up or going to sleep, a new battery level, a setting or profile changed
in the app or with the command line) instead of on its next poll.

The easiest way is to let Mousework do the waiting:

- **`mousework status --json --follow`** prints the status right away as one
  line of JSON, then another line after every change, and at least every two
  minutes. It runs until you stop it or stop reading its output. Use it with
  anything that reads a command's output line by line: Waybar, Polybar,
  i3blocks, a `while read` loop, a pipe in your own program.
- **`mousework status --json --wait`** waits for the next change (at most two
  minutes), prints the status once, formatted like plain `--json`, and exits.
  Use it with tools that run a command and wait for it to finish, such as a
  KDE Plasma widget: start it again each time it returns.

Changes are announced by the `mousework-filter` service. If it isn't running,
both options still print every two minutes.

To listen yourself, subscribe to this signal on the session bus:

| | |
|---|---|
| Interface | `io.github.mlkonrad.Mousework` |
| Signal | `Changed (s what)` |
| Object path | `/io/github/mlkonrad/Mousework` |

When the signal arrives, call `mousework status --json` again. `what` says
what happened, as a hint only (more values may be added):

| `what` | Sent when |
|---|---|
| `cpi` | The CPI button on the mouse switched presets. |
| `link` | The mouse woke up, went to sleep or lost its link to the receiver. |
| `battery` | The mouse reported a new battery level. |
| `syncing` | Mousework started or finished writing settings to the mouse; see `syncing` in the status. |
| `settings` | Profiles or settings changed, from the app, the command line or by editing `~/.config/mousework/profiles.json`. Also sent once when the service starts. |

Wait about a second after the last signal before you read the status. A
setting is saved before it is written to the mouse, and changes often come in
bursts, so this reads the new values once instead of several times.

The signal comes from the `mousework-filter` service. It is a broadcast, so
the sender has no well-known bus name; match on interface, member and path.
If the service isn't running, no signals arrive, so keep polling as well, at
the slower end of the range above.

```sh
dbus-monitor --session "type='signal',interface='io.github.mlkonrad.Mousework'"
```

In GJS:

```js
const id = Gio.DBus.session.signal_subscribe(null, 'io.github.mlkonrad.Mousework', 'Changed',
    '/io/github/mlkonrad/Mousework', null, Gio.DBusSignalFlags.NONE, () => scheduleRefresh());
// later: Gio.DBus.session.signal_unsubscribe(id);
```

## Compatibility

The format is versioned by the `version` field. Within version 1:

- **Fields are only ever added.** A later release may add new fields at the top
  level or inside the objects. Ignore fields you don't know.
- **Existing fields keep their name, type and meaning.** A field that is
  "integer or null" stays exactly that.
- **New values may appear** in `connection` and `battery.state`. Handle values
  you don't know as described above.
- `error` is free text and may change in any release.
- **The `Changed` signal** keeps its interface, object path and `(s)`
  argument, and `--follow` and `--wait` keep their behaviour. New values of
  `what` may appear; ignore them or treat them as "something changed".

If a change ever has to break one of these rules, `version` becomes `2`.
Check it before you use the rest:

```js
if (status.version !== 1) { /* show "unknown": written for version 1 */ }
```

`mousework status` without `--json` prints text for people. Its layout may
change at any time, so don't parse it.

## Writing your own integration

The examples below cover the common desktops. For anything else, this is what
a good integration does:

1. **Pick how to learn about changes**, from best to simplest:
   - Your program can use D-Bus (a GNOME Shell extension, a Qt or GTK app,
     Python with Gio or dbus-next): read the status once, then subscribe to
     the [`Changed` signal](#change-notifications) and read it again about a
     second after the last signal.
   - Your tool reads a command's output line by line (Waybar, Polybar,
     i3blocks, a pipe): run `mousework status --json --follow` and handle each
     line as a complete status.
   - Your tool runs a command and waits for it to end (KDE Plasma's executable
     data engine, many applet frameworks): run `mousework status --json` once,
     then `mousework status --json --wait` again each time it returns.
   - None of these: poll `mousework status --json` every one to five minutes.
2. **Run it by its full path**: `~/.local/bin/mousework` after `install.sh`,
   because desktop shells often don't have `~/.local/bin` in their `PATH`,
   or `/usr/bin/mousework` from a distribution package. To support both,
   try `~/.local/bin/mousework` first and fall back to `PATH`.
3. **Never block the user interface.** Run the command asynchronously, with a
   timeout of about 10 seconds. A frozen desktop shell freezes the whole
   desktop.
4. **Trust only exit status `0` and `version` `1`.** Anything else means
   "unknown": show nothing or a question mark, and try again later. With
   `--follow`, each line is one complete JSON object.
5. **Start from `syncing`, then `connection`.** While `syncing` isn't `null`,
   show that the mouse is syncing, whatever `connection` says. Otherwise show
   the details only for `receiver`, show a dimmed or "asleep" state for
   `asleep`, and hide for `no-receiver`. Treat a
   value you don't know like `no-receiver`. Show `error` in a tooltip, but
   don't parse it.
6. **Expect `null`.** Even while connected, `battery`, `polling_hz` and the
   other objects can be `null` when the mouse didn't answer.
7. **Keep a slow poll as a safety net** (every two minutes or so) if you listen
   to the signal yourself, for when `mousework-filter` isn't running.
   `--follow` and `--wait` already do this.
8. **To change settings, run the command-line tool** (`mousework cpi`,
   `mousework profile use NAME`, and so on; see the README). Prefer
   `--temporary` for profile switches that happen often, such as on scroll:
   it doesn't write the mouse's flash memory. Avoid writing power settings
   (high efficiency, sleep timer) repeatedly: each write makes the mouse drop
   its link to the receiver for several seconds. Your integration then gets
   the `Changed` signal like everyone else, so it doesn't need to update its
   own display after a change.

To test an integration without touching the mouse:

```sh
# Pretend something changed: your integration should read the status again.
gdbus emit --session --object-path /io/github/mlkonrad/Mousework \
    --signal io.github.mlkonrad.Mousework.Changed cpi

# Watch the real signals while you press the CPI button or move a sleeping mouse.
dbus-monitor --session "type='signal',interface='io.github.mlkonrad.Mousework'"

# Check that the service that sends them is running.
systemctl --user status mousework-filter
```

For the other states, put your own command in place of `mousework`: a script
that prints one of the [example outputs](#example-output), for example with
`connection` set to `asleep` or `no-receiver`.

## Examples

The examples show the battery level, and some also the CPI, polling rate and
profile. They are written for clarity; adapt the labels and icons to taste.
The examples that update live use [`--follow` or `--wait`](#change-notifications).

Tested: the shell, Python and GNOME Shell examples, and the `jq` filters of all
the others. **Not tested** inside the bar or desktop itself, because none was
available: Waybar, KDE Plasma, Xfce, Polybar, i3blocks and conky. Corrections
are welcome.

### Shell with jq

```sh
#!/bin/sh
# Print "Mouse: 62 %", or the connection state when there's no battery level.
status=$(timeout 10 mousework status --json) || { echo "Mouse: unknown"; exit 0; }
echo "$status" | jq -r '
  if .battery then "Mouse: \(.battery.level) %"
  else "Mouse: \(.connection)" end'
```

Other one-liners:

```sh
mousework status --json | jq -e '.connection == "receiver"' >/dev/null && echo awake
mousework status --json | jq -r '.cpi.active // empty'                    # 800
mousework status --json | jq -r '.profile.active'                        # Gaming
```

Live, one line per change:

```sh
mousework status --json --follow | jq --unbuffered -r '.battery.level // "-"'
```

`--unbuffered` makes jq pass each line on at once instead of collecting them.

### Python

Standard library only, Python 3.8 or later:

```python
import json
import os
import shutil
import subprocess

# install.sh puts it in ~/.local/bin, distribution packages in /usr/bin.
USER_MOUSEWORK = os.path.expanduser("~/.local/bin/mousework")
if os.access(USER_MOUSEWORK, os.X_OK):
    MOUSEWORK = USER_MOUSEWORK
else:
    MOUSEWORK = shutil.which("mousework") or "/usr/bin/mousework"


def mouse_status():
    """Return the status dict, or None if it couldn't be read."""
    try:
        result = subprocess.run([MOUSEWORK, "status", "--json"],
                                capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        status = json.loads(result.stdout)
    except ValueError:
        return None
    return status if status.get("version") == 1 else None


status = mouse_status()
if status is None:
    print("Mouse: unknown")
elif status["battery"]:
    print(f"Mouse: {status['battery']['level']} %")
else:
    print(f"Mouse: {status['connection']}")
```

Live, one status per change:

```python
with subprocess.Popen([MOUSEWORK, "status", "--json", "--follow"],
                      stdout=subprocess.PIPE, text=True) as proc:
    for line in proc.stdout:
        status = json.loads(line)
        print(status["battery"]["level"] if status["battery"] else status["connection"])
```

### Waybar (Omarchy, Hyprland, Sway, niri)

Waybar is the top bar of [Omarchy](https://omarchy.org) and of most Hyprland
and Sway setups. This module shows the battery level, has the CPI, polling rate
and profile in its tooltip, updates live with `--follow`, and hides itself
when the receiver is unplugged.

Save this script as `~/.local/bin/mousework-waybar` and make it executable
(`chmod +x`). It turns each status line into Waybar's own JSON format:

```sh
#!/bin/sh
# Waybar custom module for Mousework: one line per change.
~/.local/bin/mousework status --json --follow 2>/dev/null | jq --unbuffered -c '
  if .connection == "receiver" and .battery then {
    text: "\(.battery.level)%",
    percentage: .battery.level,
    tooltip: ([.device,
               "Battery \(.battery.level) %",
               (if .cpi then "DPI \(.cpi.active) (preset \(.cpi.active_index) of \(.cpi.presets | length))" else empty end),
               (if .polling_hz then "Polling rate \(.polling_hz) Hz" else empty end),
               (if .profile then "Profile \(.profile.active)" else empty end)] | join("\n")),
    class: (if .battery.level <= 5 then "critical" elif .battery.level <= 15 then "low" else "normal" end)
  } elif .connection == "asleep" then {
    text: "zz",
    tooltip: "\(.device): asleep, move it to wake it up",
    class: "asleep"
  } else {
    text: "",
    tooltip: "\(.device): \(.connection)" + (if .error then "\n\(.error)" else "" end),
    class: .connection
  } end'
```

To show the CPI in the bar as well, change `text` to
`"\(.battery.level)% \(.cpi.active // "") DPI"`.

In Waybar's config (Omarchy: `~/.config/waybar/config.jsonc`), add
`"custom/mouse"` to `modules-right` and define the module:

```jsonc
"custom/mouse": {
  "exec": "~/.local/bin/mousework-waybar",
  "return-type": "json",
  "restart-interval": 10,
  "format": "󰍽 {}",
  "on-click": "~/.local/bin/mousework-gtk",
  "on-scroll-up": "~/.local/bin/mousework profile next --temporary",
  "on-scroll-down": "~/.local/bin/mousework profile previous --temporary"
}
```

There is no `interval`: the script keeps running and Waybar redraws the module
for every line. `restart-interval` restarts it if it ever exits. `󰍽` is the
mouse icon of the Nerd Fonts that Omarchy uses; replace it with text if your
font doesn't have it. Scrolling switches profiles with `--temporary` (see the
README), so it doesn't wear out the mouse's flash memory.

Style it in `style.css` next to the config, for example:

```css
#custom-mouse.low      { color: #e5a50a; }
#custom-mouse.critical { color: #e01b24; }
#custom-mouse.asleep   { opacity: 0.5; }
```

`killall -SIGUSR2 waybar` reloads the configuration and style.

Mousework's motion filter adds acceleration on top of the compositor's own.
For Mousework's only, make the compositor's flat: on Hyprland,
`input { accel_profile = flat }` (Omarchy: `~/.config/hypr/input.conf`); on
Sway, `input type:pointer accel_profile flat`.

### GNOME Shell extension

A complete extension, with an icon, a menu with all the details, settings for
what the top bar shows, and live updates, is in
[`gnome-shell-extension/`](../gnome-shell-extension/) of this repository; the
README says how to install it. The minimal version below is a starting point
for your own. For live updates, subscribe to the signal as shown in
[Change notifications](#change-notifications).

For GNOME 45 and later. It adds the battery level to the top bar and updates it
every two minutes. The command runs asynchronously, so the Shell never waits
for it.

The parts that talk to Mousework are kept in their own module,
`mousework.js`, so you can reuse them in other GJS programs:

```js
// mousework.js
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

Gio._promisify(Gio.Subprocess.prototype, 'communicate_utf8_async');

// install.sh puts it in ~/.local/bin, which GNOME Shell's PATH usually
// doesn't include; distribution packages put it in /usr/bin.
const USER_MOUSEWORK = GLib.build_filenamev([GLib.get_home_dir(), '.local', 'bin', 'mousework']);
const MOUSEWORK = GLib.file_test(USER_MOUSEWORK, GLib.FileTest.IS_EXECUTABLE)
    ? USER_MOUSEWORK
    : GLib.find_program_in_path('mousework') ?? '/usr/bin/mousework';

export const COMMAND = [MOUSEWORK, 'status', '--json'];

/** Resolve to the status object, or null if it couldn't be read. */
export async function readStatus(cancellable = null, command = COMMAND) {
    try {
        const proc = Gio.Subprocess.new(command,
            Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE);
        const [stdout] = await proc.communicate_utf8_async(null, cancellable);
        if (!proc.get_successful())
            return null;
        const status = JSON.parse(stdout);
        return status.version === 1 ? status : null;
    } catch (e) {
        if (e instanceof GLib.Error && e.matches(Gio.IOErrorEnum, Gio.IOErrorEnum.CANCELLED))
            throw e;
        return null; // not installed, invalid output, ...
    }
}

/** A short text for a panel label. */
export function describe(status) {
    if (!status)
        return '?';
    if (status.battery)
        return `${status.battery.level} %`;
    switch (status.connection) {
    case 'asleep': return 'Asleep';
    case 'bluetooth': return 'Bluetooth';
    case 'no-access': return 'No permission';
    case 'no-response': return 'Not responding';
    default: return '';
    }
}
```

```js
// extension.js
import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import St from 'gi://St';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';

import {readStatus, describe} from './mousework.js';

const INTERVAL_S = 120;

export default class MouseBatteryExtension extends Extension {
    enable() {
        this._cancellable = new Gio.Cancellable();
        this._indicator = new PanelMenu.Button(0.0, this.metadata.name, true);
        this._label = new St.Label({text: '…', y_align: Clutter.ActorAlign.CENTER});
        this._indicator.add_child(this._label);
        Main.panel.addToStatusArea(this.uuid, this._indicator);

        this._refresh();
        this._timeoutId = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, INTERVAL_S, () => {
            this._refresh();
            return GLib.SOURCE_CONTINUE;
        });
    }

    disable() {
        GLib.source_remove(this._timeoutId);
        this._timeoutId = null;
        this._cancellable.cancel();
        this._cancellable = null;
        this._indicator.destroy();
        this._indicator = null;
        this._label = null;
    }

    async _refresh() {
        let status;
        try {
            status = await readStatus(this._cancellable);
        } catch {
            return; // cancelled because the extension was disabled
        }
        if (!this._label)
            return; // disabled while the command ran
        const text = describe(status);
        this._label.text = text;
        this._indicator.visible = text !== '';
    }
}
```

Add a `metadata.json` with your own `uuid`, a `name` and `"shell-version":
["45", "46", "47", "48", "49", "50"]`, as for any extension.

### KDE Plasma 6 widget (untested)

**This example hasn't been run.** It follows the Plasma 6 widget API, but no
Plasma desktop was available to test it. Corrections are welcome.

The quickest route needs no code: install a "Command Output" widget from
*Get New Widgets* and give it this command:

```sh
~/.local/bin/mousework status --json | jq -r 'if .battery then "\(.battery.level) %" else .connection end'
```

As your own widget, it updates live with `--wait`: every time the command
returns, the widget shows the result and starts it again. Make a folder
`mousework-plasmoid` with two files. `metadata.json`:

```json
{
  "KPackageStructure": "Plasma/Applet",
  "X-Plasma-API-Minimum-Version": "6.0",
  "KPlugin": {
    "Id": "io.github.mlkonrad.mousework",
    "Name": "Mousework",
    "Description": "Battery and CPI of the SteelSeries Rival 3 Wireless",
    "Icon": "input-mouse",
    "Version": "1.0"
  }
}
```

`contents/ui/main.qml`:

```qml
import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.plasmoid
import org.kde.plasma.components as PlasmaComponents
import org.kde.plasma.plasma5support as P5Support

PlasmoidItem {
    id: root

    property var mouse: null
    readonly property string command: "$HOME/.local/bin/mousework status --json"
    readonly property bool connected: mouse !== null && mouse.connection === "receiver" && mouse.battery !== null

    Plasmoid.status: mouse && (mouse.connection === "receiver" || mouse.connection === "asleep")
        ? PlasmaCore.Types.ActiveStatus : PlasmaCore.Types.HiddenStatus

    P5Support.DataSource {
        id: executable
        engine: "executable"
        connectedSources: []
        onNewData: (source, data) => {
            disconnectSource(source)
            let status = null
            if (data["exit code"] === 0) {
                try {
                    status = JSON.parse(data["stdout"])
                } catch (e) {}
            }
            root.mouse = status && status.version === 1 ? status : null
            if (root.mouse)
                connectSource(root.command + " --wait")  // returns at the next change
            else
                retry.start()  // not installed or broken: don't spin
        }
    }

    Timer {
        id: retry
        interval: 60 * 1000
        onTriggered: executable.connectSource(root.command)
    }

    Component.onCompleted: executable.connectSource(root.command)

    compactRepresentation: RowLayout {
        Kirigami.Icon {
            source: "input-mouse"
            opacity: root.connected ? 1 : 0.5
            Layout.preferredWidth: Kirigami.Units.iconSizes.small
            Layout.preferredHeight: Kirigami.Units.iconSizes.small
        }
        PlasmaComponents.Label {
            text: root.connected ? root.mouse.battery.level + " %" : ""
            visible: root.connected
        }
    }

    toolTipMainText: mouse ? mouse.device : "Mouse"
    toolTipSubText: !connected ? (mouse ? mouse.connection : "")
        : "Battery " + mouse.battery.level + " %"
          + (mouse.cpi ? "\nCPI " + mouse.cpi.active : "")
          + (mouse.polling_hz ? "\nPolling rate " + mouse.polling_hz + " Hz" : "")
          + (mouse.profile ? "\nProfile " + mouse.profile.active : "")
}
```

Install it with `kpackagetool6 -t Plasma/Applet -i mousework-plasmoid` (after
changes, `-u` instead of `-i`), then add "Mousework" to a panel with *Add
Widgets*.

For Mousework's acceleration only, set System Settings → Mouse & Touchpad →
Pointer acceleration to *None* (flat).

### Xfce panel (untested)

**This example hasn't been run** inside Xfce; its output was checked with the
example statuses. It uses the Generic Monitor (genmon) panel plugin, which runs
a command and shows its output.

Save as `~/.local/bin/mousework-genmon` and make it executable:

```sh
#!/bin/sh
# Xfce Generic Monitor plugin for Mousework.
~/.local/bin/mousework status --json 2>/dev/null | jq -r '
  if .connection == "receiver" and .battery then
    "<icon>input-mouse-symbolic</icon><txt> \(.battery.level) %</txt>",
    "<tool>\(.device)\nBattery \(.battery.level) %\nCPI \(.cpi.active // "?")\nPolling rate \(.polling_hz // "?") Hz\nProfile \(.profile.active // "?")</tool>"
  else "<txt></txt>" end'
```

Add a Generic Monitor to the panel, set its command to the full path of the
script (genmon doesn't expand `~`), and its period to 120 seconds.

For live updates, have the panel refresh the plugin after every change. Hover
over the plugin in Panel Preferences → Items to see its id, for example
`genmon-7`, and start this at login (Session and Startup → Application
Autostart):

```sh
~/.local/bin/mousework status --json --follow | while read -r _; do
    xfce4-panel --plugin-event=genmon-7:refresh:bool:true
done
```

### Polybar, i3blocks, conky and others

**Not tested** in these tools; the commands and their output were.

Polybar, live with `tail = true`:

```ini
[module/mouse]
type = custom/script
exec = ~/.local/bin/mousework status --json --follow | jq --unbuffered -r 'if .battery then "\(.battery.level)% \(.cpi.active) DPI" else "" end'
tail = true
click-left = ~/.local/bin/mousework-gtk &
```

i3blocks (i3, Sway), live with `interval=persist`:

```ini
[mouse]
command=~/.local/bin/mousework status --json --follow | jq --unbuffered -r 'if .battery then "\(.battery.level)%" else "" end'
interval=persist
```

conky can't follow a command, so it polls, inside `conky.text`:

```lua
${execi 120 ~/.local/bin/mousework status --json | jq -r '.battery.level // "-"'} %
```

Anything else that shows a command's output works the same way: if it reads
lines as they come, use `--follow`; if it runs a command and waits for it to
end, poll every one to five minutes or use `--wait` in a loop.
