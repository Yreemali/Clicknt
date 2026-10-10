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
/usr/bin/python3 "$project_dir/mouse_fix.py" --config "$project_dir/mouse_fix.ini" --check-config
modprobe uinput
install -d -m 755 /usr/local/lib/mouse-fix /etc/modules-load.d
install -m 644 "$project_dir/mouse_fix.py" /usr/local/lib/mouse-fix/mouse_fix.py
if [ ! -e /etc/mouse-fix.ini ]; then
    install -m 644 "$project_dir/mouse_fix.ini" /etc/mouse-fix.ini
else
    echo "Keeping existing /etc/mouse-fix.ini"
fi
/usr/bin/python3 /usr/local/lib/mouse-fix/mouse_fix.py --config /etc/mouse-fix.ini --check-config
printf 'uinput\n' > /etc/modules-load.d/mouse-fix.conf
install -m 644 "$project_dir/mouse-fix.service" /etc/systemd/system/mouse-fix.service
systemctl daemon-reload
systemctl enable --now mouse-fix.service
systemctl --no-pager status mouse-fix.service
