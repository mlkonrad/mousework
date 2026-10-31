%global ext_uuid mousework@mlkonrad.github.com
%global app_id io.github.mlkonrad.Mousework

Name:           mousework
Version:        0.1.6
Release:        1%{?dist}
Summary:        Settings for SteelSeries Rival 3 Wireless mice

# The app icon is adapted from Adwaita's input-mouse icon (CC-BY-SA-3.0).
License:        MIT AND CC-BY-SA-3.0
URL:            https://github.com/mlkonrad/mousework
Source0:        %{url}/archive/v%{version}/%{name}-%{version}.tar.gz

BuildArch:      noarch

BuildRequires:  python3-devel
BuildRequires:  desktop-file-utils
BuildRequires:  libappstream-glib
BuildRequires:  systemd-rpm-macros
# For the tests in %%check.
BuildRequires:  python3-gobject-base
BuildRequires:  python3-evdev

Requires:       python3-gobject
# GTK's introspection data needs cairo-1.0.typelib, which only this ships;
# minimal installs don't have it.
Requires:       gobject-introspection
Requires:       gtk4
Requires:       libadwaita
Requires:       python3-evdev
Requires:       hicolor-icon-theme

%description
A GTK 4 / libadwaita app, a command-line tool and a background service for the
SteelSeries Rival 3 Wireless (USB 1038:1830): CPI presets, polling rate, power
settings, wheel lighting, button remapping, named profiles, a host-side motion
filter (acceleration, deceleration, smoothing) and low-battery notifications.
The Rival 3 Wireless Gen 2 (USB 1038:1872, no lighting) is also supported, but
not yet tested on the real mouse.

Mousework is an independent project, not made or supported by SteelSeries.

%package gnome-shell-extension
Summary:        GNOME Shell top-bar indicator for Mousework
Requires:       %{name} = %{version}-%{release}
Requires:       gnome-shell
# Pulled in automatically on systems that have GNOME Shell.
Supplements:    (%{name} and gnome-shell)

%description gnome-shell-extension
Shows the battery level, DPI, polling rate and active profile of a SteelSeries
Rival 3 Wireless or Gen 2 in the GNOME Shell top bar, and switches profiles from its
menu. Mousework offers to turn it on the first time it starts; the switch
is also in its App settings.

%prep
%autosetup -p1

%generate_buildrequires
%pyproject_buildrequires

%build
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files -L mousework

desktop-file-install --dir=%{buildroot}%{_datadir}/applications data/%{app_id}.desktop
install -Dpm0644 data/%{app_id}.metainfo.xml %{buildroot}%{_metainfodir}/%{app_id}.metainfo.xml
for icon in data/icons/hicolor/*/apps/%{app_id}.*; do
    install -Dpm0644 "$icon" "%{buildroot}%{_datadir}/icons/${icon#data/icons/}"
done

install -Dpm0644 data/70-mousework.rules %{buildroot}%{_udevrulesdir}/70-mousework.rules
install -Dpm0644 data/mousework-filter.service %{buildroot}%{_userunitdir}/mousework-filter.service
install -d %{buildroot}%{_userpresetdir}
echo 'enable mousework-filter.service' > %{buildroot}%{_userpresetdir}/80-mousework.preset

# The schema goes to the system schema directory, where glib2's file trigger
# compiles it; Extension.getSettings() falls back to it when the extension
# has no schemas/ directory of its own.
install -d %{buildroot}%{_datadir}/gnome-shell/extensions/%{ext_uuid}
install -pm0644 gnome-shell-extension/*.js gnome-shell-extension/metadata.json \
    gnome-shell-extension/stylesheet.css \
    %{buildroot}%{_datadir}/gnome-shell/extensions/%{ext_uuid}/
install -Dpm0644 gnome-shell-extension/schemas/org.gnome.shell.extensions.mousework.gschema.xml \
    %{buildroot}%{_datadir}/glib-2.0/schemas/org.gnome.shell.extensions.mousework.gschema.xml

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/%{app_id}.desktop
appstream-util validate-relax --nonet %{buildroot}%{_metainfodir}/%{app_id}.metainfo.xml
%{py3_test_envvars} %{python3} -m unittest discover -s tests -t .

%post
%systemd_user_post mousework-filter.service
# Apply the rule to a receiver that is already plugged in. udev's own file
# trigger reloads the rules only at the end of the transaction, too late for
# this trigger, so reload them here first.
udevadm control --reload >/dev/null 2>&1 || :
udevadm trigger --subsystem-match=hidraw --subsystem-match=input --subsystem-match=misc >/dev/null 2>&1 || :

%preun
%systemd_user_preun mousework-filter.service

%postun
%systemd_user_postun_with_restart mousework-filter.service

%files -f %{pyproject_files}
%license LICENSE
%doc README.md docs/
%{_bindir}/mousework
%{_bindir}/mousework-gtk
%{_bindir}/mousework-filter
%{_datadir}/applications/%{app_id}.desktop
%{_metainfodir}/%{app_id}.metainfo.xml
%{_datadir}/icons/hicolor/*/apps/%{app_id}.*
%{_udevrulesdir}/70-mousework.rules
%{_userunitdir}/mousework-filter.service
%{_userpresetdir}/80-mousework.preset

%files gnome-shell-extension
%{_datadir}/gnome-shell/extensions/%{ext_uuid}/
%{_datadir}/glib-2.0/schemas/org.gnome.shell.extensions.mousework.gschema.xml

%changelog
* Sat Oct 31 2026 Marlon Konrad <marlonk@gmail.com> - 0.1.6-1
- Add mousework probe: read-only identification of SteelSeries mice that
  Mousework doesn't support yet, for reporting them
- Report a receiver that disappears while it is opened instead of crashing

* Sat Oct 31 2026 Marlon Konrad <marlonk@gmail.com> - 0.1.5-1
- Support the SteelSeries Rival 3 Wireless Gen 2 (USB 1038:1872). This
  support is untested: it was written from the specification without the
  mouse at hand
- Show the mouse model in mousework status and the app

* Sat Oct 31 2026 Marlon Konrad <marlonk@gmail.com> - 0.1.4-1
- Keep source comments ASCII-only
- Build releases in Copr automatically with Packit

* Sat Oct 31 2026 Marlon Konrad <marlonk@gmail.com> - 0.1.3-1
- Add AppStream metainfo with screenshots, so software centers can show
  Mousework

* Sat Oct 31 2026 Marlon Konrad <marlonk@gmail.com> - 0.1.2-1
- Offer to turn on the GNOME top-bar indicator on first start, and add a
  switch for it to the app

* Sat Oct 31 2026 Marlon Konrad <marlonk@gmail.com> - 0.1.1-1
- First package: the app, CLI, motion filter service and udev rule
- GNOME Shell indicator as a subpackage
