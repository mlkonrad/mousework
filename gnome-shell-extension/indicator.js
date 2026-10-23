// Generated with AI for personal use.
// Do NOT upload to extensions.gnome.org (EGO) unless you understand JavaScript
// and can maintain this code.

import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GioUnix from 'gi://GioUnix';
import GObject from 'gi://GObject';
import St from 'gi://St';

import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

import {readStatus, batteryIconName} from './mousework.js';

// A fallback: mousework-filter announces changes on D-Bus (docs/json.md).
const REFRESH_INTERVAL_S = 120;
// Lets a burst of changes, and the write to the mouse that follows a saved setting, settle first.
const CHANGE_DELAY_MS = 1000;
const CHANGES_INTERFACE = 'io.github.mlkonrad.Mousework';
const CHANGES_PATH = '/io/github/mlkonrad/Mousework';
const APP_ID = 'io.github.mlkonrad.Mousework.desktop';
const MOUSE_ICON = 'input-mouse-symbolic';
const DIM_OPACITY = 180;

const STATE_TEXT = {
    receiver: 'Connected through the USB receiver',
    asleep: 'Asleep. Move or click the mouse to wake it.',
};

export const MouseworkIndicator = GObject.registerClass(
class MouseworkIndicator extends PanelMenu.Button {
    _init(extension) {
        super._init(0.5, extension.metadata.name);
        this._extension = extension;
        this._settings = extension.getSettings();
        this._status = null;
        this._cancellable = new Gio.Cancellable();

        const box = new St.BoxLayout({style_class: 'panel-status-menu-box'});
        this._icon = new St.Icon({style_class: 'system-status-icon'});
        this._label = new St.Label({y_align: Clutter.ActorAlign.CENTER});
        box.add_child(this._icon);
        box.add_child(this._label);
        this.add_child(box);

        this._buildMenu();
        this.visible = false;

        this._settings.connectObject('changed', () => this._render(), this);
        this.menu.connect('open-state-changed', (_menu, open) => {
            if (open)
                this._refresh();
        });

        this._changedId = Gio.DBus.session.signal_subscribe(null, CHANGES_INTERFACE, 'Changed', CHANGES_PATH,
            null, Gio.DBusSignalFlags.NONE, () => this._scheduleRefresh());

        this._refresh();
        this._timeoutId = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, REFRESH_INTERVAL_S, () => {
            this._refresh();
            return GLib.SOURCE_CONTINUE;
        });
    }

    _buildMenu() {
        this._title = new PopupMenu.PopupMenuItem('', {reactive: false});
        this._title.label.add_style_class_name('mousework-title');
        this.menu.addMenuItem(this._title);
        this._stateItem = new PopupMenu.PopupMenuItem('', {reactive: false});
        this._stateItem.label.opacity = DIM_OPACITY;
        this.menu.addMenuItem(this._stateItem);

        this._details = new PopupMenu.PopupMenuSection();
        this._details.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        this._rows = {
            battery: this._addRow('battery-level-100-symbolic', 'Battery'),
            dpi: this._addRow(MOUSE_ICON, 'DPI'),
            polling: this._addRow('power-profile-performance-symbolic', 'Polling rate'),
            profile: this._addRow('user-bookmarks-symbolic', 'Profile'),
        };
        this.menu.addMenuItem(this._details);

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        this.menu.addAction('Mousework Settings', () => {
            GioUnix.DesktopAppInfo.new(APP_ID)?.launch([], global.create_app_launch_context(0, -1));
        });
        this.menu.addAction('Indicator Settings', () => this._extension.openPreferences());
    }

    _addRow(iconName, title) {
        const item = new PopupMenu.PopupBaseMenuItem({reactive: false});
        const icon = new St.Icon({icon_name: iconName, style_class: 'popup-menu-icon'});
        const value = new St.Label({
            x_expand: true,
            x_align: Clutter.ActorAlign.END,
            y_align: Clutter.ActorAlign.CENTER,
            style_class: 'mousework-value',
        });
        item.add_child(icon);
        item.add_child(new St.Label({text: title, y_align: Clutter.ActorAlign.CENTER}));
        item.add_child(value);
        this._details.addMenuItem(item);
        return {item, icon, value};
    }

    _scheduleRefresh() {
        if (this._changeTimeoutId)
            GLib.Source.remove(this._changeTimeoutId);
        this._changeTimeoutId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, CHANGE_DELAY_MS, () => {
            this._changeTimeoutId = null;
            this._refresh();
            return GLib.SOURCE_REMOVE;
        });
    }

    async _refresh() {
        if (this._refreshing) {
            this._refreshAgain = true;
            return;
        }
        this._refreshing = true;
        const cancellable = this._cancellable;
        let status;
        try {
            status = await readStatus(cancellable);
        } catch {
            return;
        } finally {
            this._refreshing = false;
        }
        if (cancellable.is_cancelled())
            return;
        this._status = status;
        this._render();
        if (this._refreshAgain) {
            this._refreshAgain = false;
            this._refresh();
        }
    }

    _render() {
        const status = this._status;
        const connected = status?.connection === 'receiver';
        this.visible = connected || status?.connection === 'asleep';
        if (!this.visible) {
            this.menu.close();
            return;
        }

        this._renderPanel(status, connected);
        this._title.label.text = status.device;
        this._stateItem.label.text = status.error ?? STATE_TEXT[status.connection];
        this._details.actor.visible = connected;
        if (connected)
            this._renderDetails(status);
    }

    _renderPanel(status, connected) {
        const iconMode = this._settings.get_string('panel-icon');
        const parts = [];
        if (connected) {
            if (this._settings.get_boolean('show-battery') && status.battery)
                parts.push(`${status.battery.level} %`);
            if (this._settings.get_boolean('show-dpi') && status.cpi)
                parts.push(`${status.cpi.active} DPI`);
            if (this._settings.get_boolean('show-polling-rate') && status.polling_hz)
                parts.push(`${status.polling_hz} Hz`);
            if (this._settings.get_boolean('show-profile') && status.profile)
                parts.push(status.profile.active);
        } else if (iconMode === 'none') {
            parts.push('Asleep');
        }

        if (iconMode === 'battery' && connected && status.battery)
            this._icon.icon_name = batteryIconName(status.battery);
        else
            this._icon.icon_name = MOUSE_ICON;
        this._icon.visible = iconMode !== 'none' || parts.length === 0;
        this._icon.opacity = connected ? 255 : DIM_OPACITY;
        this._label.text = parts.join('  ');
        this._label.visible = parts.length > 0;
    }

    _renderDetails(status) {
        const {battery, dpi, polling, profile} = this._rows;

        battery.item.visible = status.battery !== null;
        if (status.battery) {
            battery.icon.icon_name = batteryIconName(status.battery);
            battery.value.text = `${status.battery.level} %`;
        }

        dpi.item.visible = status.cpi !== null;
        if (status.cpi) {
            const {presets, active, active_index: index} = status.cpi;
            dpi.value.text = presets.length > 1 ? `${active}  (preset ${index} of ${presets.length})` : `${active}`;
        }

        polling.item.visible = status.polling_hz !== null;
        if (status.polling_hz) {
            const efficiency = status.power?.high_efficiency ? '  (high efficiency)' : '';
            polling.value.text = `${status.polling_hz} Hz${efficiency}`;
        }

        profile.item.visible = status.profile !== null;
        if (status.profile)
            profile.value.text = status.profile.active + (status.profile.saved_to_mouse ? '' : '  (temporary)');
    }

    destroy() {
        if (this._timeoutId) {
            GLib.Source.remove(this._timeoutId);
            this._timeoutId = null;
        }
        if (this._changeTimeoutId) {
            GLib.Source.remove(this._changeTimeoutId);
            this._changeTimeoutId = null;
        }
        Gio.DBus.session.signal_unsubscribe(this._changedId);
        this._cancellable.cancel();
        this._settings.disconnectObject(this);
        this._settings = null;
        this._extension = null;
        super.destroy();
    }
});
