import errno
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import clicknt as fix
from evdev import InputEvent, ecodes as e


def event(code, value, ms=0, kind=e.EV_KEY):
    return InputEvent(ms // 1000, (ms % 1000) * 1000, kind, code, value)


class FilterTests(unittest.TestCase):
    def test_drops_complete_bounce_and_keeps_next_click(self):
        bounce = fix.BounceFilter({e.BTN_LEFT}, 50)
        inputs = [(1, 100), (0, 200), (1, 210), (0, 215), (1, 265), (0, 300)]
        self.assertEqual([bounce.accept(event(e.BTN_LEFT, value), ms) for value, ms in inputs],
                         [True, True, False, False, True, True])

    def test_drag_other_buttons_and_motion(self):
        bounce = fix.BounceFilter({e.BTN_LEFT, e.BTN_RIGHT}, 50)
        self.assertTrue(bounce.accept(event(e.BTN_LEFT, 1), 1))
        self.assertTrue(bounce.accept(event(e.REL_X, 5, kind=e.EV_REL), 2))
        self.assertTrue(bounce.accept(event(e.BTN_RIGHT, 1), 3))
        self.assertTrue(bounce.accept(event(e.BTN_LEFT, 0), 10000))
        self.assertTrue(bounce.accept(event(e.BTN_RIGHT, 0), 10001))
        self.assertTrue(bounce.accept(event(e.BTN_SIDE, 1), 10002))

    def test_zero_threshold_and_unmatched_release(self):
        bounce = fix.BounceFilter({e.BTN_LEFT}, 0)
        self.assertFalse(bounce.accept(event(e.BTN_LEFT, 0), 0))
        self.assertTrue(bounce.accept(event(e.BTN_LEFT, 1), 0))
        self.assertFalse(bounce.accept(event(e.BTN_LEFT, 1), 1))
        self.assertTrue(bounce.accept(event(e.BTN_LEFT, 0), 1))
        self.assertTrue(bounce.accept(event(e.BTN_LEFT, 1), 1))


class LifecycleTests(unittest.TestCase):
    def test_waits_at_start_and_reconnects_after_disconnect(self):
        stop = MagicMock()
        stop.is_set.side_effect = [False, False, False, False, True]
        first, second = MagicMock(), MagicMock()
        with patch.object(fix, 'find_device', side_effect=[None, first, None, second]), \
             patch.object(fix, 'forward', side_effect=[OSError(errno.ENODEV, 'unplugged'), None]) as forward:
            fix.run({'name': 'mouse'}, 50, 1, {e.BTN_LEFT}, stop)
        self.assertEqual([call.args[0] for call in forward.call_args_list], [first, second])
        self.assertEqual(stop.wait.call_count, 3)

    def test_preserves_frames_and_releases_held_buttons_on_disconnect(self):
        device, ui, stop = MagicMock(), MagicMock(), MagicMock()
        device.info = SimpleNamespace(vendor=1, product=2, version=1, bustype=3)
        device.active_keys.return_value = []
        press = event(e.BTN_LEFT, 1, 100)
        sync = event(e.SYN_REPORT, 0, 100, e.EV_SYN)
        device.read.side_effect = [[press, sync], OSError(errno.ENODEV, 'unplugged')]
        stop.is_set.return_value = False
        with patch.object(fix.UInput, 'from_device', return_value=ui), \
             patch.object(fix.select, 'select', return_value=([device.fd], [], [])):
            with self.assertRaises(OSError):
                fix.forward(device, stop, {e.BTN_LEFT}, 50)
        self.assertEqual([call.args[0] for call in ui.write_event.call_args_list], [press, sync])
        # Only startup and cleanup add a sync; event frames themselves pass unchanged.
        self.assertEqual(ui.syn.call_count, 2)
        ui.write.assert_called_once_with(e.EV_KEY, e.BTN_LEFT, 0)
        device.ungrab.assert_called_once()
        device.close.assert_called_once()
        ui.close.assert_called_once()

    def test_uinput_failure_closes_device_without_grabbing(self):
        device = MagicMock()
        with patch.object(fix.UInput, 'from_device', side_effect=fix.UInputError('missing')):
            with self.assertRaises(fix.UInputError):
                fix.forward(device, MagicMock(), {e.BTN_LEFT}, 50)
        device.grab.assert_not_called()
        device.close.assert_called_once()

    def test_ambiguous_selection_closes_all_candidates(self):
        first, second = MagicMock(), MagicMock()
        with patch.object(fix, 'list_devices', return_value=['a', 'b']), \
             patch.object(fix, 'InputDevice', side_effect=[first, second]), \
             patch.object(fix, 'is_mouse', return_value=True), \
             patch.object(fix, 'matches', return_value=True):
            with self.assertRaisesRegex(ValueError, 'Multiple mice'):
                fix.find_device({'name': 'same'})
        first.close.assert_called_once()
        second.close.assert_called_once()


class ConfigTests(unittest.TestCase):
    def load(self, text):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.ini'
            path.write_text(text)
            return fix.load_config(path)

    def test_default_config(self):
        selector, threshold, retry, buttons, level = fix.load_config(fix.DEFAULT_CONFIG)
        self.assertIn('name', selector)
        self.assertEqual((threshold, retry, buttons, level), (50, 1, {e.BTN_LEFT}, 'INFO'))

    def test_hex_identifiers_and_literal_percent(self):
        selector, *_ = self.load('[device]\nname=100% mouse\nvendor=0x046d\nproduct=123\n')
        self.assertEqual(selector, {'name': '100% mouse', 'vendor': 0x046d, 'product': 123})

    def test_invalid_configuration(self):
        for text in ('[device]\nname=\n', '[device]\nnaem=mouse\n',
                     '[device]\nname=mouse\n[filter]\nrelease_to_press_ms=nan\n',
                     '[device]\nname=mouse\n[filter]\nreconnect_interval_seconds=0\n',
                     '[device]\nname=mouse\n[filter]\nbuttons=KEY_A\n'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.load(text)


if __name__ == '__main__':
    unittest.main()
