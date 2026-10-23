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
2. [Example output](#example-output)
3. [Fields](#fields)
4. [Connection states](#connection-states)
5. [Exit status](#exit-status)
6. [How often to call it](#how-often-to-call-it)
7. [Compatibility](#compatibility)
8. [Examples](#examples): shell, Python, Waybar, GNOME Shell, KDE Plasma, Polybar and others

## Quick start

```sh
mousework status --json                              # the whole object
mousework status --json | jq '.battery.level'        # 62, or null if unknown
```

Mousework installs its commands in `~/.local/bin`. Desktop shells don't always
have that directory in their `PATH` (GNOME Shell on Fedora doesn't), so from
an extension or widget call it by its full path: `~/.local/bin/mousework`.

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
    "saved_to_mouse": true
  }
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
    "saved_to_mouse": true
  }
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
| `profile.saved_to_mouse` | boolean | `false` after a temporary switch (`mousework profile use NAME --temporary`): the mouse has the profile's settings now, but it will start with a different, saved profile after it's switched off and on. `true` otherwise. |

Rules that hold for every state:

- `battery`, `cpi`, `polling_hz` and `power` are only filled in when
  `connection` is `receiver`. In every other state they are `null`.
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

## Exit status

| Exit status | Meaning |
|---|---|
| `0` | Valid JSON was printed on standard output. **This includes every connection state**, even `no-receiver`. |
| `2` | The command line was wrong, for example an old Mousework that doesn't know `--json` yet. Nothing was printed on standard output. |
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
- **Calling it while the Mousework app or service is running is safe.** All
  Mousework processes take turns on the receiver, so they never read each
  other's answers.

`mousework status --json` only reads. It never changes settings and never
writes to the mouse's memory.

## Compatibility

The format is versioned by the `version` field. Within version 1:

- **Fields are only ever added.** A later release may add new fields at the top
  level or inside the objects. Ignore fields you don't know.
- **Existing fields keep their name, type and meaning.** A field that is
  "integer or null" stays exactly that.
- **New values may appear** in `connection` and `battery.state`. Handle values
  you don't know as described above.
- `error` is free text and may change in any release.

If a change ever has to break one of these rules, `version` becomes `2`.
Check it before you use the rest:

```js
if (status.version !== 1) { /* show "unknown": written for version 1 */ }
```

`mousework status` without `--json` prints text for people. Its layout may
change at any time, so don't parse it.

## Examples

All examples show the battery level. They are written for clarity; adapt the
labels, icons and polling interval to taste. The shell, Python, Waybar and GNOME
Shell examples are tested. The KDE Plasma example is **untested**.

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

### Python

Standard library only, Python 3.8 or later:

```python
import json
import os
import subprocess

MOUSEWORK = os.path.expanduser("~/.local/bin/mousework")


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

### Waybar

Save this script as `~/.local/bin/mousework-waybar` and make it executable
(`chmod +x`). It turns the status into Waybar's own JSON format:

```sh
#!/bin/sh
# Waybar custom module for Mousework.
~/.local/bin/mousework status --json 2>/dev/null | jq -c '
  if .battery then {
    text: "\(.battery.level)%",
    percentage: .battery.level,
    tooltip: "\(.device)\nBattery \(.battery.level) %\nProfile \(.profile.active // "?")",
    class: (if .battery.level <= 5 then "critical"
            elif .battery.level <= 15 then "low" else "normal" end)
  } else {
    text: (if .connection == "asleep" then "zz" else "" end),
    tooltip: "\(.device): \(.connection)" + (if .error then "\n\(.error)" else "" end),
    class: .connection
  } end'
```

In `~/.config/waybar/config`:

```json
"modules-right": ["custom/mouse"],
"custom/mouse": {
  "exec": "~/.local/bin/mousework-waybar",
  "return-type": "json",
  "interval": 120,
  "format": "🖱 {}"
}
```

Style it in `~/.config/waybar/style.css`, for example:

```css
#custom-mouse.low      { color: #e5a50a; }
#custom-mouse.critical { color: #e01b24; }
#custom-mouse.no-receiver { opacity: 0; }
```

### GNOME Shell extension

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

// GNOME Shell's PATH usually doesn't include ~/.local/bin.
export const COMMAND = [
    GLib.build_filenamev([GLib.get_home_dir(), '.local', 'bin', 'mousework']),
    'status', '--json',
];

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

As your own widget, `contents/ui/main.qml`:

```qml
import QtQuick
import org.kde.plasma.plasmoid
import org.kde.plasma.components as PlasmaComponents
import org.kde.plasma.plasma5support as P5Support

PlasmoidItem {
    id: root

    property var mouse: null
    readonly property string command: "$HOME/.local/bin/mousework status --json"

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
        }
    }

    Timer {
        interval: 120 * 1000
        running: true
        repeat: true
        triggeredOnStart: true
        onTriggered: executable.connectSource(root.command)
    }

    compactRepresentation: PlasmaComponents.Label {
        text: !root.mouse ? "?"
            : root.mouse.battery ? root.mouse.battery.level + " %"
            : root.mouse.connection
    }

    toolTipMainText: root.mouse ? root.mouse.device : "Mouse"
    toolTipSubText: root.mouse && root.mouse.error ? root.mouse.error : ""
}
```

### Polybar, i3blocks, conky and others

Any tool that can show a command's output works with a jq one-liner.

Polybar:

```ini
[module/mouse]
type = custom/script
exec = ~/.local/bin/mousework status --json | jq -r 'if .battery then "\(.battery.level)%" else "" end'
interval = 120
```

conky, inside `conky.text`:

```lua
${execi 120 ~/.local/bin/mousework status --json | jq -r '.battery.level // "-"'} %
```
