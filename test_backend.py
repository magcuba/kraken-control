import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import subprocess
import backend
from app import DEFAULT, sensors


class BackendTests(unittest.TestCase):
    def config(self):
        return copy.deepcopy(DEFAULT)

    def test_only_selected_channels_are_written(self):
        c = self.config()
        self.assertEqual(backend.cooling(c), [])
        c['fan_enabled'] = True
        self.assertEqual(backend.cooling(c), [backend.LIQ + ['set', 'fan', 'speed', '60']])
        c['fan_mode'] = 'curve'
        self.assertEqual(backend.cooling(c)[0][-8:], ['30', '40', '35', '60', '40', '80', '45', '100'])

    def test_invalid_pump_and_curve_rejected(self):
        for key, value in [('pump', 0), ('brightness', 101), ('curve', [[35, 40], [30, 80]])]:
            c = self.config()
            c[key] = value
            with self.assertRaises(ValueError):
                backend.validate(c)

    def test_persisted_cpu_keeps_original_updater(self):
        text = backend.unit_text(self.config())
        self.assertIn('Type=simple', text)
        self.assertIn('/usr/local/lib/kraken-control/cpu_display.py', text)
        self.assertNotIn('"fan" "speed"', text)
        self.assertIn('"orientation" "180"', text)

    def test_liquid_mode_is_oneshot(self):
        c = self.config()
        c['screen'] = 'liquid'
        text = backend.unit_text(c)
        self.assertIn('Type=oneshot', text)
        self.assertIn('RemainAfterExit=yes', text)
        self.assertNotIn('/usr/local/lib/kraken-control/cpu_display.py', text)

    def test_unit_escaping(self):
        text = backend.unit_command(['/usr/bin/tool', 'a b%$"c'])
        self.assertIn('%%', text)
        self.assertIn('$$', text)
        self.assertIn('\\"', text)

    def test_writer_is_resumed_after_usb_error(self):
        calls = []
        def run(args, **kw):
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, '987654321\n' if 'show' in args else '', '')
        with patch.object(backend, 'run', run):
            with self.assertRaises(RuntimeError):
                with backend.pause_writer():
                    raise RuntimeError('USB failed')
        self.assertTrue(any('--signal=SIGCONT' in args for args in calls))

    def test_failed_save_restores_previous_dropin(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'config.conf'
            path.write_text('previous')
            failed = False
            def run(args, **kw):
                nonlocal failed
                if 'restart' in args and not failed:
                    failed = True
                    raise RuntimeError('failed')
                return subprocess.CompletedProcess(args, 0, '', '')
            with patch.object(backend, 'DROPIN', path), patch.object(backend, 'run', run):
                with self.assertRaises(RuntimeError):
                    backend.perform('save', self.config())
            self.assertEqual(path.read_text(), 'previous')

    def test_sensors_can_be_read_without_root(self):
        self.assertIsInstance(sensors(), dict)

    def test_pump_curve_and_minimum(self):
        c = self.config()
        c.update(pump_enabled=True, pump_mode='curve')
        backend.validate(c)
        self.assertEqual(backend.cooling(c)[0][-8:], ['30', '60', '35', '70', '40', '85', '45', '100'])
        c['pump_curve'][0][1] = 0
        with self.assertRaises(ValueError):
            backend.validate(c)

    def test_old_preferences_gain_pump_defaults(self):
        c = self.config()
        del c['pump_mode']
        del c['pump_curve']
        self.assertEqual(backend.validate(c)['pump_mode'], 'fixed')


if __name__ == '__main__':
    unittest.main()
