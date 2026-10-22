#!/bin/sh
# Install Mousework for the current user.
#
#   ./install.sh          copy Mousework into ~/.local/share/mousework
#   ./install.sh --dev    link to this checkout instead, so code changes apply directly
#
# Only the udev rule needs root; sudo is asked for once if it isn't installed yet.
set -eu

cd "$(dirname "$0")"
SRC=$(pwd)
DATA_HOME=${XDG_DATA_HOME:-$HOME/.local/share}
CONFIG_HOME=${XDG_CONFIG_HOME:-$HOME/.config}
LIB=$DATA_HOME/mousework/lib
BIN=$HOME/.local/bin
APP_ID=io.github.mlkonrad.Mousework
RULE=/etc/udev/rules.d/70-mousework.rules

DEV=0
case "${1:-}" in
    --dev) DEV=1 ;;
    "") ;;
    *) echo "usage: $0 [--dev]" >&2; exit 2 ;;
esac

say() { printf '\033[1m%s\033[0m\n' "$*"; }

missing_dependencies() {
    python3 - <<'EOF' 2>&1
import sys
missing = []
if sys.version_info < (3, 11):
    missing.append("Python 3.11 or newer")
try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gtk  # noqa: F401
except (ImportError, ValueError):
    missing.append("PyGObject with GTK 4 and libadwaita")
try:
    import evdev  # noqa: F401
except ImportError:
    missing.append("python-evdev")
print("\n".join(missing))
EOF
}

dependency_hint() {
    . /etc/os-release 2>/dev/null || true
    case " ${ID:-} ${ID_LIKE:-} " in
        *" fedora "*) echo "sudo dnf install python3-gobject gtk4 libadwaita python3-evdev" ;;
        *" debian "*|*" ubuntu "*) echo "sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 python3-evdev" ;;
        *" arch "*) echo "sudo pacman -S python-gobject gtk4 libadwaita python-evdev" ;;
        *" suse "*|*" opensuse "*) echo "sudo zypper install python3-gobject-Gdk typelib-1_0-Adw-1 python3-evdev" ;;
        *) echo "install PyGObject, GTK 4, libadwaita and python-evdev with your package manager" ;;
    esac
}

command -v python3 >/dev/null || { echo "Mousework needs python3." >&2; exit 1; }
MISSING=$(missing_dependencies)
if [ -n "$MISSING" ]; then
    echo "Missing:" >&2
    echo "$MISSING" | sed 's/^/  - /' >&2
    echo "Install them with:" >&2
    echo "  $(dependency_hint)" >&2
    exit 1
fi

say "Installing Mousework"
mkdir -p "$LIB" "$BIN" "$DATA_HOME/applications" "$CONFIG_HOME/systemd/user"
rm -rf "$LIB/mousework"
if [ "$DEV" = 1 ]; then
    ln -s "$SRC/mousework" "$LIB/mousework"
else
    cp -r "$SRC/mousework" "$LIB/mousework"
    find "$LIB/mousework" -name __pycache__ -prune -exec rm -rf {} +
fi

launcher() {
    cat > "$BIN/$1" <<EOF
#!/bin/sh
PYTHONPATH="$LIB\${PYTHONPATH:+:\$PYTHONPATH}" exec python3 -m $2 "\$@"
EOF
    chmod 755 "$BIN/$1"
}
launcher mousework mousework.cli
launcher mousework-gtk mousework.gui
launcher mousework-filter mousework.filterd

sed "s|^Exec=.*|Exec=$BIN/mousework-gtk|" data/$APP_ID.desktop > "$DATA_HOME/applications/$APP_ID.desktop"
command -v update-desktop-database >/dev/null && update-desktop-database "$DATA_HOME/applications" 2>/dev/null || true
sed "s|^ExecStart=.*|ExecStart=$BIN/mousework-filter|" data/mousework-filter.service \
    > "$CONFIG_HOME/systemd/user/mousework-filter.service"

if ! cmp -s data/70-mousework.rules "$RULE"; then
    say "Installing the udev rule (needs sudo)"
    sudo install -m644 data/70-mousework.rules "$RULE"
    sudo udevadm control --reload
    sudo udevadm trigger --subsystem-match=hidraw --subsystem-match=input --subsystem-match=misc
fi

systemctl --user daemon-reload
systemctl --user enable --now mousework-filter.service >/dev/null 2>&1
systemctl --user restart mousework-filter.service

say "Done"
echo "Open Mousework from your app grid, or run: mousework-gtk"
case ":$PATH:" in
    *":$BIN:"*) ;;
    *) echo "Note: $BIN is not on your PATH; add it to use the mousework command." ;;
esac
