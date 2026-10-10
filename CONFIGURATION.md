# Configuring clicknt

## First setup

Run these commands from the project directory:

```sh
sudo python3 clicknt.py --list-devices
sudo python3 clicknt.py --select-device
python3 clicknt.py --check-config
sudo sh ./install.sh
```

Choose the number of the physical mouse you want to filter. Selection writes its identity into the local `clicknt.ini` and keeps your existing filter settings. Installation starts the systemd service and enables it at boot.

If Python reports that `evdev` is missing, install it on CachyOS / Arch with `sudo pacman -S python-evdev`.

## Upgrade from the previous name

Run `sudo sh ./install.sh` from this project. If the previous `mouse-fix` service is installed, the installer stops and disables it before starting `clicknt`. If `/etc/clicknt.ini` does not exist, it copies settings from `/etc/mouse-fix.ini` when available. An existing `/etc/clicknt.ini` is preserved. Old installation files remain in place, with the old service disabled.

Use `systemctl status clicknt` and `sudo journalctl -u clicknt -f` afterward. Previous journal entries remain under the old service name.

## Which config to edit

| How you run it | Config used |
| --- | --- |
| `sudo python3 clicknt.py` from this project | `clicknt.ini` beside the script |
| Installed systemd service | `/etc/clicknt.ini` |
| Script with `--config /some/file.ini` | The specified file |

Once installed, change `/etc/clicknt.ini`. Editing the project's copy does not update the running service. Reinstalling preserves an existing `/etc/clicknt.ini`.

Open the installed config:

```sh
sudoedit /etc/clicknt.ini
```

After each change, validate it and restart:

```sh
sudo python3 /usr/local/lib/clicknt/clicknt.py --config /etc/clicknt.ini --check-config
sudo systemctl restart clicknt
systemctl status clicknt --no-pager
```

Only restart if validation succeeds. Validation checks settings and syntax; it does not check whether the mouse is connected or accessible. Settings are read at startup.

## Choose or change the mouse

For an installed service:

```sh
sudo python3 /usr/local/lib/clicknt/clicknt.py --config /etc/clicknt.ini --select-device
sudo systemctl restart clicknt
```

The selector lists physical mice and excludes clicknt's virtual mouse. It prefers a persistent path under `/dev/input/by-id`, followed by `/dev/input/by-path`. Avoid manually selecting `/dev/input/eventN`: its number can change after reconnecting or rebooting.

All nonempty fields in `[device]` must match. Blank fields are ignored.

| Field | Meaning |
| --- | --- |
| `path` | Input device path. A stable `...-event-mouse` symlink is preferred. |
| `name` | Exact device name, including capitalization. |
| `vendor` | Vendor ID, such as `0x046d`; hexadecimal or decimal. |
| `product` | Product ID, such as `0xc09d`; hexadecimal or decimal. |
| `uniq` | Exact unique identifier or serial reported by the device. |
| `phys` | Exact physical connection string, often tied to the USB port. |

Use the selection command to populate these values. A by-id selection usually works across USB ports. A by-path or `phys` selection is tied to the connection location: reconnect to the same port, or select the device again after moving it.

When no path is set, the script searches available input devices. If multiple mice match, it reports an error; add a stable path, `uniq`, or `phys` to distinguish them. When no mouse matches, it keeps waiting.

## Filter settings

These are the default settings:

```ini
[filter]
release_to_press_ms = 50
buttons = BTN_LEFT
reconnect_interval_seconds = 1
log_level = INFO
```

| Setting | Accepted values | Effect |
| --- | --- | --- |
| `release_to_press_ms` | Finite number, zero or greater | Suppress a new press occurring less than this many milliseconds after that button's most recent release. |
| `buttons` | One or more valid `BTN_*` names, separated by spaces or commas | Buttons to filter. |
| `reconnect_interval_seconds` | Finite number greater than zero | Delay between reconnect attempts. |
| `log_level` | `DEBUG`, `INFO`, `WARNING`, `ERROR` | How much detail to log. |

To filter both primary buttons:

```ini
buttons = BTN_LEFT BTN_RIGHT
```

Other common names are `BTN_MIDDLE`, `BTN_SIDE`, and `BTN_EXTRA`. Filtering applies independently to each selected button. Movement, scrolling, and unselected buttons pass through.

### Tune the debounce threshold

Start at `50` ms and test ordinary clicks, deliberate fast double-clicks, and dragging.

- If accidental second clicks still get through, increase the threshold a little, restart, and test again.
- If intentional fast double-clicks get suppressed, lower the threshold, restart, and test again.
- Set `0` to disable suppression based on the time threshold. This still forwards events through the virtual mouse and suppresses duplicate presses and unmatched releases for selected buttons.

The interval is measured from the previous release to the next press. A rejected press and its release are both suppressed. Each release updates the reference time, including releases belonging to rejected clicks.

## Log detected bounce

Set this in the existing `[filter]` section, keeping your other settings:

```ini
log_level = DEBUG
```

Validate and restart, then watch:

```sh
sudo python3 /usr/local/lib/clicknt/clicknt.py --config /etc/clicknt.ini --check-config
sudo systemctl restart clicknt
sudo journalctl -u clicknt -f
```

A suppressed press produces a message such as:

```text
DEBUG: Filtered button 272 bounce (12.00 ms)
```

`272` is `BTN_LEFT`; `273` is `BTN_RIGHT`; `274` is `BTN_MIDDLE`. The time is the interval since that button's latest release. These messages show clicks rejected by the configured threshold; they do not independently diagnose a hardware fault. Accepted clicks and the paired suppressed releases are not logged.

`INFO` logs connection, waiting, and shutdown messages. Disconnects and device access failures produce warnings. Return to `INFO` when you no longer need individual detection messages.

Useful log commands:

```sh
# Most recent entries:
sudo journalctl -u clicknt -n 100 --no-pager

# Entries from this boot:
sudo journalctl -u clicknt -b

# Recent detection messages:
sudo journalctl -u clicknt --since '10 minutes ago' --no-pager | rg 'Filtered button'
```

Journal retention is controlled by your system's journald configuration; clicknt does not create a separate log file.

## Check reconnection

With the service running, watch `sudo journalctl -u clicknt -f`, unplug the selected mouse, and reconnect it. You should see a disconnect warning, a waiting message, then `Using ...` after reconnection. The process also waits if the mouse is absent at boot. The device scan interval defaults to one second.

If it keeps waiting after reconnection, list devices and select the mouse again. Check whether a by-path or `phys` selector refers to the previous USB port.

## Troubleshooting and service controls

| Symptom | Action |
| --- | --- |
| `No readable mice found` | Run selection with `sudo`; confirm the mouse is connected and `/dev/input/event*` exists. |
| `Multiple mice match` | Select a specific mouse, or add its stable path or unique identifier. |
| `/dev/uinput` missing | Run `sudo modprobe uinput`. The installer configures module loading at boot. |
| Cannot grab the mouse / device busy | Stop other copies of clicknt or programs exclusively grabbing the same mouse. |
| Changes have no effect | Edit `/etc/clicknt.ini`, validate, and restart the installed service. |
| Mouse behaves incorrectly | Stop the service; the physical mouse is released. Lower the threshold or adjust the selected buttons before restarting. |

```sh
# Stop temporarily; boot enablement stays in place:
sudo systemctl stop clicknt

# Start again:
sudo systemctl start clicknt

# Stop and disable startup at boot:
sudo systemctl disable --now clicknt

# Enable startup at boot and start now:
sudo systemctl enable --now clicknt
```

For a foreground test using the installed config, stop the service first:

```sh
sudo systemctl stop clicknt
sudo python3 /usr/local/lib/clicknt/clicknt.py --config /etc/clicknt.ini
```

Press Ctrl+C to release the mouse and exit. Then run `sudo systemctl start clicknt` to resume background operation. Run one filtering instance at a time.
