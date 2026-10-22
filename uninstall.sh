#!/bin/sh
# Remove Mousework installed by install.sh.
#
#   ./uninstall.sh           keep your profiles (~/.config/mousework)
#   ./uninstall.sh --purge   delete them too
set -eu

DATA_HOME=${XDG_DATA_HOME:-$HOME/.local/share}
CONFIG_HOME=${XDG_CONFIG_HOME:-$HOME/.config}
BIN=$HOME/.local/bin
APP_ID=io.github.mlkonrad.Mousework
RULE=/etc/udev/rules.d/70-mousework.rules

PURGE=0
case "${1:-}" in
    --purge) PURGE=1 ;;
    "") ;;
    *) echo "usage: $0 [--purge]" >&2; exit 2 ;;
esac

systemctl --user disable --now mousework-filter.service 2>/dev/null || true
rm -f "$CONFIG_HOME/systemd/user/mousework-filter.service"
systemctl --user daemon-reload

rm -f "$BIN/mousework" "$BIN/mousework-gtk" "$BIN/mousework-filter"
rm -f "$DATA_HOME/applications/$APP_ID.desktop"
rm -rf "$DATA_HOME/mousework"

if [ -e "$RULE" ]; then
    echo "Removing the udev rule (needs sudo)"
    sudo rm -f "$RULE"
    sudo udevadm control --reload
fi

if [ "$PURGE" = 1 ]; then
    rm -rf "$CONFIG_HOME/mousework"
    echo "Mousework and your profiles have been removed."
else
    echo "Mousework has been removed. Your profiles are still in $CONFIG_HOME/mousework."
fi
