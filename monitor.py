"""Read-only PC telemetry. CPU and network rates use consecutive samples."""
import csv
import io
import math
import subprocess
import time
from pathlib import Path

import psutil


def number(text):
    try:
        value = float(text.strip())
        return value if math.isfinite(value) and value >= 0 else None
    except (ValueError, TypeError):
        return None


def gpu_stats():
    fields = 'name,temperature.gpu,utilization.gpu,clocks.gr,fan.speed,memory.used,memory.total'
    try:
        result = subprocess.run(['/usr/bin/nvidia-smi', '--id=0', '--query-gpu=' + fields,
                                 '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=2)
        if result.returncode:
            return {}
        row = next(csv.reader(io.StringIO(result.stdout)))
        if len(row) != 7:
            return {}
        return dict(zip(('name', 'temperature', 'load', 'clock', 'fan', 'vram_used', 'vram_total'),
                        [row[0].strip()] + [number(v) for v in row[1:]]))
    except (OSError, subprocess.TimeoutExpired, StopIteration, csv.Error):
        return {}


def cpu_usage(previous, current):
    if previous is None:
        return None
    total = current[0] - previous[0]
    idle = current[1] - previous[1]
    return max(0, min(100, 100 * (total - idle) / total)) if total > 0 else None


def byte_rate(previous, current, elapsed):
    if previous is None or elapsed <= 0:
        return None
    return max(0, current - previous) / elapsed


def storage():
    result, seen = [], set()
    for p in sorted(psutil.disk_partitions(all=False), key=lambda p: p.mountpoint != '/'):
        if p.device in seen or p.fstype in ('squashfs', 'tmpfs', 'overlay'):
            continue
        if p.mountpoint != '/' and not p.mountpoint.startswith(('/media/', '/run/media/', '/mnt/')):
            continue
        try:
            usage = psutil.disk_usage(p.mountpoint)
            result.append(dict(path=p.mountpoint, used=usage.used, total=usage.total, percent=usage.percent))
            seen.add(p.device)
        except OSError:
            pass
    if not result:
        u = psutil.disk_usage('/')
        result.append(dict(path='/', used=u.used, total=u.total, percent=u.percent))
    return result


class Monitor:
    def __init__(self):
        self.last_cpu = None
        self.last_net = None
        self.last_time = None
        self.last_processes = {}
        self.cpu_name = 'Procesador'
        try:
            for line in Path('/proc/cpuinfo').read_text().splitlines():
                if line.startswith('model name'):
                    self.cpu_name = line.split(':', 1)[1].strip()
                    break
        except OSError:
            pass

    def sample(self):
        now = time.monotonic()
        elapsed = now - self.last_time if self.last_time is not None else 0
        times = psutil.cpu_times()
        # Linux guest times are already included in user/nice.
        total = sum(times) - getattr(times, 'guest', 0) - getattr(times, 'guest_nice', 0)
        current = (total, times.idle + getattr(times, 'iowait', 0))
        load = cpu_usage(self.last_cpu, current)
        self.last_cpu = current
        mem = psutil.virtual_memory()
        try:
            freq = psutil.cpu_freq()
            clock = freq.current if freq else None
        except (OSError, NotImplementedError):
            clock = None
        network_error = False
        try:
            up = psutil.net_if_stats()
            pernic = psutil.net_io_counters(pernic=True)
            names = [n for n in pernic if n != 'lo' and n in up and up[n].isup]
        except (OSError, psutil.Error):
            pernic, names = {}, []
            network_error = True
        net = (sum(pernic[n].bytes_recv for n in names), sum(pernic[n].bytes_sent for n in names))
        same_interfaces = self.last_net is not None and self.last_net[0] == names
        old = self.last_net[1] if same_interfaces else (None, None)
        download, upload = byte_rate(old[0], net[0], elapsed), byte_rate(old[1], net[1], elapsed)
        self.last_net = (names, net)
        rows, current_processes = [], {}
        count = psutil.cpu_count() or 1
        for p in psutil.process_iter(['pid', 'name', 'cpu_times', 'memory_info', 'create_time'], ad_value=None):
            try:
                a = p.info
                if a['cpu_times'] is None or a['memory_info'] is None:
                    continue
                key = (a['pid'], a['create_time'])
                cpu = a['cpu_times'].user + a['cpu_times'].system
                prev = self.last_processes.get(key)
                percent = min(100, max(0, (cpu - prev) / elapsed / count * 100)) if prev is not None and elapsed else None
                current_processes[key] = cpu
                rows.append(dict(pid=a['pid'], name=a['name'] or str(a['pid']), cpu=percent, ram=a['memory_info'].rss))
            except (psutil.Error, OSError):
                continue
        self.last_processes = current_processes
        self.last_time = now
        rows.sort(key=lambda p: (p['cpu'] or 0, p['ram']), reverse=True)
        gpu = gpu_stats()
        return dict(cpu_name=self.cpu_name, cpu_load=load, cpu_clock=clock,
                    memory=dict(total=mem.total, used=mem.total - mem.available, percent=100 * (1 - mem.available / mem.total)),
                    network=dict(download=None if network_error else download, upload=None if network_error else upload, interfaces=names, unavailable=network_error),
                    storage=storage(), processes=rows[:8], gpu=gpu)
