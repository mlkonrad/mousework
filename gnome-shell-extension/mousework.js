import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

Gio._promisify(Gio.DBusConnection.prototype, 'call');

// The D-Bus API of the mousework-filter service (docs/json.md in the
// Mousework repo). The bus starts the service on the first call if needed.
const BUS_NAME = 'io.github.mlkonrad.Mousework.Service';
const OBJECT_PATH = '/io/github/mlkonrad/Mousework/Service';
const INTERFACE = 'io.github.mlkonrad.Mousework.Service';

const STATUS_TIMEOUT_MS = 10000;
// Writing a profile makes the mouse reconnect, which can take a while.
const SWITCH_TIMEOUT_MS = 60000;

/**
 * Thrown when nothing on the session bus provides the Mousework API: the app
 * isn't installed, or is a version from before the API.
 */
export class NotInstalledError extends Error {}

/**
 * @param {string} method the method to call
 * @param {GLib.Variant|null} parameters its arguments
 * @param {string} replyType the reply's signature
 * @param {number} timeoutMs how long to wait
 * @param {Gio.Cancellable} cancellable cancels the call; it then throws CANCELLED
 * @returns {Promise<GLib.Variant>} the reply
 */
async function call(method, parameters, replyType, timeoutMs, cancellable) {
    try {
        return await Gio.DBus.session.call(BUS_NAME, OBJECT_PATH, INTERFACE, method, parameters,
            new GLib.VariantType(replyType), Gio.DBusCallFlags.NONE, timeoutMs, cancellable);
    } catch (e) {
        if (e.matches(Gio.DBusError, Gio.DBusError.SERVICE_UNKNOWN) ||
            e.matches(Gio.DBusError, Gio.DBusError.NAME_HAS_NO_OWNER))
            throw new NotInstalledError('Mousework is not installed');
        if (Gio.DBusError.is_remote_error(e))
            Gio.DBusError.strip_remote_error(e);
        throw e;
    }
}

/**
 * Read the mouse's state (format: docs/json.md in the Mousework repo).
 *
 * @param {Gio.Cancellable} cancellable cancels the call; it then throws CANCELLED
 * @returns {Promise<object|null>} the status object, or null if it couldn't be read
 * @throws {NotInstalledError} if Mousework isn't installed
 */
export async function readStatus(cancellable) {
    let reply;
    try {
        reply = await call('GetStatus', null, '(s)', STATUS_TIMEOUT_MS, cancellable);
    } catch (e) {
        if (e instanceof NotInstalledError || e.matches(Gio.IOErrorEnum, Gio.IOErrorEnum.CANCELLED))
            throw e;
        return null;
    }
    const [text] = reply.deepUnpack();
    const status = JSON.parse(text);
    return status.version === 1 ? status : null;
}

/**
 * Make a profile the active one. Mousework writes it to the mouse and saves
 * it there, which takes a few seconds. Cancelling stops waiting but lets the
 * write finish, so the mouse is never left half configured.
 *
 * @param {string} name a name from the status's `profile.available`
 * @param {Gio.Cancellable} cancellable stops waiting; it then throws CANCELLED
 * @throws {Error} with Mousework's explanation if the switch failed
 */
export async function switchProfile(name, cancellable) {
    await call('UseProfile', new GLib.Variant('(s)', [name]), '()', SWITCH_TIMEOUT_MS, cancellable);
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
