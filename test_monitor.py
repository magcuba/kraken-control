import subprocess
import unittest
from unittest.mock import patch
from monitor import Monitor, gpu_stats, cpu_usage, byte_rate


class MonitorTests(unittest.TestCase):
    def test_cpu_uses_sample_delta(self):
        self.assertIsNone(cpu_usage(None, (100, 50)))
        self.assertEqual(cpu_usage((100, 50), (200, 125)), 25)
        self.assertIsNone(cpu_usage((200, 125), (100, 50)))

    def test_network_rate_and_reset(self):
        self.assertIsNone(byte_rate(None, 1000, 3))
        self.assertEqual(byte_rate(1000, 7000, 3), 2000)
        self.assertEqual(byte_rate(7000, 1000, 3), 0)
        self.assertIsNone(byte_rate(1000, 7000, 0))

    def test_gpu_fields_and_unavailable_fan(self):
        output = 'NVIDIA GeForce RTX 5080, 32, 2, 210, [N/A], 512, 16384\n'
        with patch('monitor.subprocess.run', return_value=subprocess.CompletedProcess([], 0, output, '')):
            data = gpu_stats()
        self.assertEqual(data['temperature'], 32)
        self.assertEqual(data['load'], 2)
        self.assertEqual(data['vram_total'], 16384)
        self.assertIsNone(data['fan'])

    def test_gpu_invalid_or_denied(self):
        for code, output in [(9, ''), (0, 'invalid')]:
            with patch('monitor.subprocess.run', return_value=subprocess.CompletedProcess([], code, output, '')):
                self.assertEqual(gpu_stats(), {})
        with patch('monitor.subprocess.run', side_effect=subprocess.TimeoutExpired('nvidia-smi', 2)):
            self.assertEqual(gpu_stats(), {})

    def test_network_permissions_do_not_hide_other_metrics(self):
        with patch('monitor.psutil.net_if_stats', side_effect=PermissionError('denied')), patch('monitor.gpu_stats', return_value={}):
            data = Monitor().sample()
        self.assertTrue(data['network']['unavailable'])
        self.assertGreater(data['memory']['total'], 0)
        self.assertTrue(data['storage'])
        self.assertTrue(data['cpu_name'])


if __name__ == '__main__':
    unittest.main()
