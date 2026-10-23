// Generated with AI for personal use.
// Do NOT upload to extensions.gnome.org (EGO) unless you understand JavaScript
// and can maintain this code.

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

Gio._promisify(Gio.Subprocess.prototype, 'communicate_utf8_async');

// GNOME Shell's PATH usually doesn't include ~/.local/bin.
const COMMAND = [
    GLib.build_filenamev([GLib.get_home_dir(), '.local', 'bin', 'mousework']),
    'status', '--json',
];

const TIMEOUT_S = 10;

/**
 * Run `mousework status --json` (format: docs/json.md in the Mousework repo).
 *
 * @param {Gio.Cancellable} cancellable cancels the call; it then throws CANCELLED
 * @returns {Promise<object|null>} the status object, or null if it couldn't be read
 */
export async function readStatus(cancellable) {
    const proc = Gio.Subprocess.new(COMMAND,
        Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE);
    let timeoutId = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, TIMEOUT_S, () => {
        timeoutId = 0;
        proc.force_exit();
        return GLib.SOURCE_REMOVE;
    });
    try {
        const [stdout] = await proc.communicate_utf8_async(null, cancellable);
        if (!proc.get_successful())
            return null;
        const status = JSON.parse(stdout);
        return status.version === 1 ? status : null;
    } catch (e) {
        if (e instanceof GLib.Error && e.matches(Gio.IOErrorEnum, Gio.IOErrorEnum.CANCELLED)) {
            proc.force_exit();
            throw e;
        }
        return null;
    } finally {
        if (timeoutId)
            GLib.Source.remove(timeoutId);
    }
}

/**
 * @param {object} battery the status's `battery` object
 * @returns {string} the Adwaita icon for that charge
 */
export function batteryIconName(battery) {
    const level = Math.min(100, Math.max(0, Math.round(battery.level / 10) * 10));
    if (battery.state === 'charged')
        return 'battery-level-100-charged-symbolic';
    if (battery.state === 'charging')
        return `battery-level-${level}-charging-symbolic`;
    return `battery-level-${level}-symbolic`;
}
