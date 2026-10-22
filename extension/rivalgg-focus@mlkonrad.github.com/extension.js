// This extension was generated with an AI assistant for personal use with rivalgg.
// It is not intended for upload to extensions.gnome.org unless its author can maintain it.

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Shell from 'gi://Shell';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const BUS_NAME = 'io.github.rivalgg.Focus';
const OBJECT_PATH = '/io/github/rivalgg/Focus';
const INTERFACE_XML = `
<node>
  <interface name="io.github.rivalgg.Focus">
    <method name="GetFocusedApp">
      <arg type="s" direction="out" name="app_id"/>
    </method>
    <signal name="FocusedAppChanged">
      <arg type="s" name="app_id"/>
    </signal>
  </interface>
</node>`;

export default class RivalggFocusExtension extends Extension {
    enable() {
        this._tracker = Shell.WindowTracker.get_default();
        this._dbus = Gio.DBusExportedObject.wrapJSObject(INTERFACE_XML, this);
        this._dbus.export(Gio.DBus.session, OBJECT_PATH);
        this._nameId = Gio.bus_own_name_on_connection(Gio.DBus.session, BUS_NAME,
            Gio.BusNameOwnerFlags.NONE, null, null);
        this._focusId = this._tracker.connect('notify::focus-app', () => {
            this._dbus.emit_signal('FocusedAppChanged',
                new GLib.Variant('(s)', [this.GetFocusedApp()]));
        });
    }

    disable() {
        this._tracker.disconnect(this._focusId);
        Gio.bus_unown_name(this._nameId);
        this._dbus.unexport();
        this._dbus = null;
        this._tracker = null;
    }

    GetFocusedApp() {
        return this._tracker.focus_app?.get_id() ?? '';
    }
}
