#!/bin/sh
# Run after selecting your mouse in the local config.
set -eu
if [ "$(id -u)" -ne 0 ]; then
    echo "Run: sudo sh ./install.sh" >&2
    exit 1
fi
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
/usr/bin/python3 -c 'import evdev' || {
    echo "Install evdev first: sudo pacman -S python-evdev" >&2
    exit 1
}
/usr/bin/python3 "$project_dir/clicknt.py" --config "$project_dir/clicknt.ini" --check-config
modprobe uinput
# Upgrade an installation that used the previous service name.
# Stop it before starting clicknt so only one process grabs the mouse.
if [ -f /etc/systemd/system/mouse-fix.service ]; then
    systemctl disable --now mouse-fix.service
fi
install -d -m 755 /usr/local/lib/clicknt /etc/modules-load.d
install -m 644 "$project_dir/clicknt.py" /usr/local/lib/clicknt/clicknt.py
if [ ! -e /etc/clicknt.ini ]; then
    if [ -f /etc/mouse-fix.ini ]; then
        install -m 644 /etc/mouse-fix.ini /etc/clicknt.ini
        echo "Migrated existing settings to /etc/clicknt.ini"
    else
        install -m 644 "$project_dir/clicknt.ini" /etc/clicknt.ini
    fi
else
    echo "Keeping existing /etc/clicknt.ini"
fi
/usr/bin/python3 /usr/local/lib/clicknt/clicknt.py --config /etc/clicknt.ini --check-config
printf 'uinput\n' > /etc/modules-load.d/clicknt.conf
install -m 644 "$project_dir/clicknt.service" /etc/systemd/system/clicknt.service
systemctl daemon-reload
systemctl enable --now clicknt.service
systemctl --no-pager status clicknt.service
