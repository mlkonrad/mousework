// Generated with AI for personal use.
// Do NOT upload to extensions.gnome.org (EGO) unless you understand JavaScript
// and can maintain this code.

import Adw from 'gi://Adw';
import Gio from 'gi://Gio';
import Gtk from 'gi://Gtk';

import {ExtensionPreferences} from 'resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js';

const ICONS = [
    ['battery', 'Battery level'],
    ['mouse', 'Mouse'],
    ['none', 'None'],
];

const TEXTS = [
    ['show-battery', 'Battery percentage', 'battery-level-70-symbolic'],
    ['show-dpi', 'DPI', 'input-mouse-symbolic'],
    ['show-polling-rate', 'Polling rate', 'power-profile-performance-symbolic'],
    ['show-profile', 'Profile', 'user-bookmarks-symbolic'],
];

export default class MouseworkPreferences extends ExtensionPreferences {
    fillPreferencesWindow(window) {
        const settings = this.getSettings();
        const page = new Adw.PreferencesPage();
        window.add(page);

        const group = new Adw.PreferencesGroup({
            title: 'Top Bar',
            description: 'The indicator appears while the mouse is connected through its USB receiver.',
        });
        page.add(group);

        const iconRow = new Adw.ComboRow({
            title: 'Icon',
            model: Gtk.StringList.new(ICONS.map(([, label]) => label)),
        });
        const syncIcon = () => {
            iconRow.selected = ICONS.findIndex(([nick]) => nick === settings.get_string('panel-icon'));
        };
        syncIcon();
        const changedId = settings.connect('changed::panel-icon', syncIcon);
        window.connect('close-request', () => settings.disconnect(changedId));
        iconRow.connect('notify::selected', () => {
            const [nick] = ICONS[iconRow.selected];
            if (nick !== settings.get_string('panel-icon'))
                settings.set_string('panel-icon', nick);
        });
        group.add(iconRow);

        const textGroup = new Adw.PreferencesGroup({title: 'Show Next to the Icon'});
        page.add(textGroup);
        for (const [key, title, iconName] of TEXTS) {
            const row = new Adw.SwitchRow({title});
            row.add_prefix(new Gtk.Image({icon_name: iconName}));
            settings.bind(key, row, 'active', Gio.SettingsBindFlags.DEFAULT);
            textGroup.add(row);
        }
    }
}
