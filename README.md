# clicknt

Linux mouse button debounce filter using python-evdev. It exclusively grabs your selected physical mouse and forwards its events through a virtual mouse. It waits when the mouse is absent at startup and reconnects after unplugging, including when the event number changes. SIGINT/SIGTERM releases the mouse cleanly.

## Setup on CachyOS / Arch

```sh
sudo pacman -S python-evdev
sudo python3 clicknt.py --list-devices
sudo python3 clicknt.py --select-device
python3 clicknt.py --check-config
sudo sh ./install.sh
```

The selection command saves your choice in `clicknt.ini`. It prefers a persistent `/dev/input/by-id` path, then `/dev/input/by-path`, and saves identifying fields. If no persistent path or serial exists, physical port matching is used: keep the mouse on that port. Identical mice without a serial need a stable path or `phys` selector. Multiple matches produce an error instead of grabbing an arbitrary mouse. Disconnecting a mouse and reconnecting to the same port should preserve a by-path selection; a by-id path generally permits moving ports.

The installer copies the script into `/usr/local/lib/clicknt`, the config into `/etc/clicknt.ini`, and the systemd unit into `/etc/systemd/system`. It loads `uinput`, arranges loading it at boot, and enables and starts the service. Existing installed config is preserved on reinstall. The installer also stops and disables an installed service under the previous name and migrates its config if the new config does not exist. The system service runs as root for access to input devices and uinput; no input group membership or broadly writable device permissions are required.

## Configuration

See the [configuration guide](CONFIGURATION.md) for device selection, debounce tuning, detection logs, and troubleshooting.

Edit `/etc/clicknt.ini` after installation. All nonempty device fields must match. `vendor` and `product` accept hexadecimal values like `0x046d` or decimal numbers. Avoid `/dev/input/eventN` for long-term use because numbering can change.

- `release_to_press_ms = 50`: ignore presses less than 50 ms after that button's latest release. Lower it if intentional fast double-clicks get suppressed; zero disables the time threshold.
- `buttons = BTN_LEFT`: space- or comma-separated buttons; for example `BTN_LEFT BTN_RIGHT`.
- `reconnect_interval_seconds = 1`: how often to retry a missing device.
- `log_level = INFO`: use `DEBUG` to log filtered clicks.

Ignored presses and their releases are suppressed together. Other buttons, motion, wheel events, and original event frame boundaries are preserved. Queue overflow triggers a new connection to resynchronize state. Force-feedback output is not proxied.

```sh
# Edit settings / choose another device after installation:
sudo python3 /usr/local/lib/clicknt/clicknt.py --config /etc/clicknt.ini --select-device
sudo systemctl restart clicknt

# Status and logs:
systemctl status clicknt
journalctl -u clicknt -f

# Stop and disable:
sudo systemctl disable --now clicknt
```

For a foreground trial, stop the service first, then run `sudo python3 clicknt.py`; press Ctrl+C to exit. Run one instance at a time. Selection only takes effect at the next process/service start.

Verify on your desktop: test ordinary clicks, dragging, double-clicking, wheel and side buttons; then unplug and reconnect the mouse while watching the journal. Logs should show waiting followed by `Using ...`. Stop the service and confirm the physical mouse works normally.

## Remove

```sh
sudo systemctl disable --now clicknt
sudo rm /etc/systemd/system/clicknt.service
sudo systemctl daemon-reload
sudo rm -r /usr/local/lib/clicknt
sudo rm /etc/clicknt.ini /etc/modules-load.d/clicknt.conf
```

## Checks

```sh
python3 -B -m unittest discover -s tests -v
sh -n install.sh
systemd-analyze verify clicknt.service
```

API references: [python-evdev](https://python-evdev.readthedocs.io/en/stable/tutorial.html), [systemd service units](https://github.com/systemd/systemd/blob/main/man/systemd.service.xml).
