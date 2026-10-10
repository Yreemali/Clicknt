#!/usr/bin/env python3
"""Filter mouse button bounce and reconnect automatically on Linux."""

import argparse
import configparser
import errno
import logging
import math
from pathlib import Path
import select
import signal
import threading

from evdev import InputDevice, UInput, ecodes, list_devices
from evdev.uinput import UInputError

LOG = logging.getLogger("clicknt")
VIRTUAL_NAME = "clicknt Virtual Mouse"
VIRTUAL_PHYS = "clicknt/uinput"
DEFAULT_CONFIG = Path(__file__).resolve().with_name("clicknt.ini")


def load_config(path):
    config = configparser.ConfigParser(interpolation=None)
    with open(path, encoding="utf-8") as stream:
        config.read_file(stream)
    if not config.has_section("device"):
        raise ValueError("Config needs a [device] section")
    selector = dict(config["device"])
    allowed = {"path", "name", "vendor", "product", "uniq", "phys"}
    if set(selector) - allowed:
        raise ValueError("Unknown device selector: " + ", ".join(set(selector) - allowed))
    selector = {key: value.strip() for key, value in selector.items() if value.strip()}
    if not selector:
        raise ValueError("Set at least one device selector")
    for key in ("vendor", "product"):
        if key in selector:
            selector[key] = int(selector[key], 0)
            if not 0 <= selector[key] <= 65535:
                raise ValueError(f"{key} must be between 0 and 65535")
    settings = config["filter"] if config.has_section("filter") else {}
    threshold = float(settings.get("release_to_press_ms", "50"))
    retry = float(settings.get("reconnect_interval_seconds", "1"))
    if not math.isfinite(threshold) or threshold < 0:
        raise ValueError("release_to_press_ms must be finite and nonnegative")
    if not math.isfinite(retry) or retry <= 0:
        raise ValueError("reconnect_interval_seconds must be finite and positive")
    names = settings.get("buttons", "BTN_LEFT").replace(",", " ").split()
    if not names or any(not name.startswith("BTN_") or name not in ecodes.ecodes for name in names):
        raise ValueError("buttons must contain valid BTN_* names, e.g. BTN_LEFT BTN_RIGHT")
    buttons = {ecodes.ecodes[name] for name in names}
    level = settings.get("log_level", "INFO").upper()
    if level not in ("DEBUG", "INFO", "WARNING", "ERROR"):
        raise ValueError("log_level must be DEBUG, INFO, WARNING, or ERROR")
    return selector, threshold, retry, buttons, level


def is_mouse(device):
    caps = device.capabilities()
    return (device.phys != VIRTUAL_PHYS and device.name != VIRTUAL_NAME
            and ecodes.BTN_LEFT in caps.get(ecodes.EV_KEY, [])
            and {ecodes.REL_X, ecodes.REL_Y}.issubset(caps.get(ecodes.EV_REL, [])))


def matches(device, selector):
    for key, value in selector.items():
        if key == "path":
            continue
        actual = getattr(device.info, key) if key in ("vendor", "product") else getattr(device, key)
        if actual != value:
            return False
    return True


def find_device(selector):
    paths = [selector["path"]] if "path" in selector else sorted(list_devices())
    found = []
    try:
        for path in paths:
            try:
                device = InputDevice(path)
            except OSError as exc:
                if exc.errno in (errno.ENOENT, errno.ENODEV):
                    continue
                LOG.warning("Cannot open %s: %s", path, exc)
                continue
            try:
                if is_mouse(device) and matches(device, selector):
                    found.append(device)
                else:
                    device.close()
            except OSError:
                device.close()
        if len(found) > 1:
            raise ValueError("Multiple mice match; use --select-device or a stable path/uniq/phys selector")
        return found.pop() if found else None
    finally:
        for device in found:
            device.close()


def stable_path(device):
    for directory in (Path("/dev/input/by-id"), Path("/dev/input/by-path")):
        for link in sorted(directory.glob("*")):
            if link.resolve() == Path(device.path).resolve():
                return str(link)
    return ""


def enumerate_mice():
    devices = []
    for path in sorted(list_devices()):
        try:
            device = InputDevice(path)
        except OSError as exc:
            LOG.warning("Cannot open %s: %s", path, exc)
            continue
        try:
            if is_mouse(device):
                devices.append({"path": device.path, "stable_path": stable_path(device),
                                "name": device.name, "vendor": f"0x{device.info.vendor:04x}",
                                "product": f"0x{device.info.product:04x}",
                                "uniq": device.uniq, "phys": device.phys})
        except OSError as exc:
            LOG.warning("Cannot inspect %s: %s", path, exc)
        finally:
            device.close()
    return devices


def choose_device(path, interactive):
    devices = enumerate_mice()
    if not devices:
        raise ValueError("No readable mice found. Try sudo and check /dev/input/event*.")
    for index, item in enumerate(devices, 1):
        print(f"{index}. {item['name']} ({item['path']})")
        for key in ("stable_path", "vendor", "product", "uniq", "phys"):
            if item[key]:
                print(f"   {key}: {item[key]}")
    if not interactive:
        return
    choice = int(input("Select mouse number: "))
    if not 1 <= choice <= len(devices):
        raise ValueError("Invalid mouse number")
    selected = devices[choice - 1]
    config = configparser.ConfigParser(interpolation=None)
    if path.exists():
        with path.open(encoding="utf-8") as stream:
            config.read_file(stream)
    config["device"] = {key: selected[key] for key in ("name", "vendor", "product", "uniq") if selected[key]}
    if selected["stable_path"]:
        config["device"]["path"] = selected["stable_path"]
    elif not selected["uniq"] and selected["phys"]:
        config["device"]["phys"] = selected["phys"]
    if not config.has_section("filter"):
        config["filter"] = {"release_to_press_ms": "50", "buttons": "BTN_LEFT",
                            "reconnect_interval_seconds": "1", "log_level": "INFO"}
    with path.open("w", encoding="utf-8") as stream:
        config.write(stream)
    print(f"Saved selected mouse to {path}")


class BounceFilter:
    """Drop the entire bounced click, preserving accepted press/release pairs."""

    def __init__(self, buttons, threshold_ms):
        self.buttons = buttons
        self.threshold_ms = threshold_ms
        self.last_release = {}
        self.pressed = set()

    def accept(self, event, now_ms):
        if event.type != ecodes.EV_KEY or event.code not in self.buttons:
            return True
        code = event.code
        if event.value == 1:
            if code in self.pressed:
                return False
            released = self.last_release.get(code)
            if released is not None and now_ms - released < self.threshold_ms:
                LOG.debug("Filtered button %s bounce (%.2f ms)", code, now_ms - released)
                return False
            self.pressed.add(code)
            return True
        if event.value == 0:
            self.last_release[code] = now_ms
            if code not in self.pressed:
                return False
            self.pressed.remove(code)
            return True
        return code in self.pressed


def forward(device, stop, buttons, threshold):
    ui = None
    grabbed = False
    held = set()
    try:
        ui = UInput.from_device(device, name=VIRTUAL_NAME, phys=VIRTUAL_PHYS,
                               vendor=device.info.vendor, product=device.info.product,
                               version=device.info.version, bustype=device.info.bustype,
                               input_props=device.input_props())
        device.grab()
        grabbed = True
        LOG.info("Using %s: %s", device.path, device.name)
        bounce = BounceFilter(buttons, threshold)
        # Buttons already held at startup must have a matching virtual press.
        for code in device.active_keys():
            ui.write(ecodes.EV_KEY, code, 1)
            held.add(code)
            if code in buttons:
                bounce.pressed.add(code)
        ui.syn()
        while not stop.is_set():
            if not select.select([device.fd], [], [], 0.5)[0]:
                continue
            try:
                events = device.read()
                for event in events:
                    if event.type == ecodes.EV_SYN and event.code == ecodes.SYN_DROPPED:
                        raise OSError(errno.EOVERFLOW, "Input queue overflow; reconnecting to resynchronize")
                    # Use kernel event timestamps so queued events retain their spacing.
                    now_ms = event.sec * 1000 + event.usec / 1000
                    if bounce.accept(event, now_ms):
                        ui.write_event(event)
                        if event.type == ecodes.EV_KEY:
                            if event.value == 1:
                                held.add(event.code)
                            elif event.value == 0:
                                held.discard(event.code)
                    # Original EV_SYN events delimit frames; do not synthesize one per event.
            except BlockingIOError:
                continue
    finally:
        if ui is not None:
            try:
                for code in held:
                    ui.write(ecodes.EV_KEY, code, 0)
                ui.syn()
            except OSError:
                pass
        if grabbed:
            try:
                device.ungrab()
            except OSError:
                pass
        try:
            if ui is not None:
                ui.close()
        finally:
            device.close()


def run(selector, threshold, retry, buttons, stop):
    waiting = False
    while not stop.is_set():
        device = find_device(selector)
        if device is None:
            if not waiting:
                LOG.info("Waiting for selected mouse: %s", selector)
                waiting = True
            stop.wait(retry)
            continue
        waiting = False
        try:
            forward(device, stop, buttons, threshold)
        except (OSError, UInputError) as exc:
            LOG.warning("Mouse disconnected or unavailable: %s; retrying in %s seconds", exc, retry)
            stop.wait(retry)
    LOG.info("Stopped")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--list-devices", action="store_true", help="List readable physical mice")
    modes.add_argument("--select-device", action="store_true", help="Interactively select a mouse and save config")
    modes.add_argument("--check-config", action="store_true", help="Validate configuration without grabbing a mouse")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        if args.list_devices or args.select_device:
            choose_device(args.config, args.select_device)
            return 0
        selector, threshold, retry, buttons, level = load_config(args.config)
        LOG.setLevel(level)
        if args.check_config:
            print(f"Config valid: {args.config}")
            return 0
        stop = threading.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda _signum, _frame: stop.set())
        run(selector, threshold, retry, buttons, stop)
        return 0
    except (OSError, ValueError, configparser.Error, EOFError) as exc:
        LOG.error("%s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
