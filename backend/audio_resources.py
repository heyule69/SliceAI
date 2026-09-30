"""Low-cost host sampling; change torch parallelism only between audio blocks."""
from dataclasses import dataclass
import math
import os
import threading
import time

MIB = 1024 ** 2


@dataclass(frozen=True)
class Sample:
    at: float
    logical: int
    physical: int
    allowed: int
    system_cpu: float  # Whole-machine percentage, 0..100.
    own_cpu: float     # Process percentage, may exceed 100 on multiple cores.
    available: int
    total: int


class HostSampler:
    def __init__(self):
        # A static import lets PyInstaller include the Windows extension.
        import psutil
        self.psutil = psutil
        self.process = psutil.Process()
        self.logical = psutil.cpu_count() or os.cpu_count() or 1
        self.physical = psutil.cpu_count(logical=False) or max(1, self.logical // 2)
        self.psutil.cpu_percent(None)
        self.process.cpu_percent(None)

    def read(self):
        memory = self.psutil.virtual_memory()
        try:
            allowed = len(self.process.cpu_affinity())
        except (AttributeError, self.psutil.Error):
            allowed = self.logical
        return Sample(time.monotonic(), self.logical, self.physical, max(1, allowed),
                      self.psutil.cpu_percent(None), self.process.cpu_percent(None),
                      memory.available, memory.total)


class Policy:
    """Fast backoff, slow recovery, and leave headroom for interactive programs.

    This controls concurrency, not a hard CPU/RAM quota. Memory pressure cannot
    release model weights; it reduces parallel scratch work at the next boundary.
    """
    def __init__(self):
        self.threads = 1
        self.initialized = False
        self.last_change = 0.
        self.last_sample = None
        self.external = 0.
        self.good_samples = 0

    def decide(self, sample, now):
        if sample is None or now - sample.at > 10:
            self.good_samples = 0
            self.threads = min(self.threads, 2)
            self.last_change = now
            return self.threads, '监测暂不可用，保守运行', 0.
        logical = max(1, sample.logical)
        external = max(0., min(100., sample.system_cpu - sample.own_cpu / logical))
        fresh = sample.at != self.last_sample
        if fresh:
            self.external = external if not self.initialized else .65 * self.external + .35 * external
            self.last_sample = sample.at
        # Use physical cores rather than treating SMT as equivalent performance.
        # Limit very large CPUs until a throughput benchmark justifies more.
        ceiling = max(1, min(sample.physical, sample.allowed, 16))
        budget = math.floor(logical * max(0., .80 - max(external, self.external) / 100))
        target = max(1, min(ceiling, budget))
        reason = '根据其他程序负载分配 CPU'
        reserve = max(1024 * MIB, min(4096 * MIB, sample.total * .10))
        delay = 0.
        if sample.available < reserve:
            target = 1
            reason = '可用内存较少，降低并行度'
            delay = .5 if sample.available < 512 * MIB else 0.
        elif sample.available < reserve * 2:
            target = min(target, 2)
            reason = '为其他程序保留内存'
        if external > 90:
            target = 1
            delay = max(delay, .25)
            reason = '其他程序繁忙，优先让出 CPU'
        if not self.initialized or target < self.threads:
            self.threads = target
            self.last_change = now
            self.good_samples = 0
        elif target > self.threads:
            if fresh:
                self.good_samples += 1
            if self.good_samples >= 3 and now - self.last_change >= 20:
                self.threads += 1
                self.last_change = now
                self.good_samples = 0
        else:
            self.good_samples = 0
        self.initialized = True
        return self.threads, reason, delay


class AdaptiveResources:
    def __init__(self, report=lambda data: None, sampler_factory=HostSampler):
        self.policy = Policy()
        self.report = report
        self.stop = threading.Event()
        self.latest = None
        self.sampler = None
        self.thread = None
        self.last_report = None
        try:
            self.sampler = sampler_factory()
            # Prime both system and process counters over the same small window.
            time.sleep(.15)
            self.latest = self.sampler.read()
        except Exception:
            pass  # Monitoring failure must not lose the user's audio job.
        self.initial_threads = self.policy.decide(self.latest, time.monotonic())[0]

    def start(self):
        if self.sampler is not None:
            self.thread = threading.Thread(target=self._watch, name='audio-resources', daemon=True)
            self.thread.start()

    def _watch(self):
        while not self.stop.wait(2):
            try:
                self.latest = self.sampler.read()
            except Exception:
                self.latest = None

    def boundary(self, set_threads):
        """Called on the inference thread, never while a model call is running."""
        sample = self.latest
        before = self.policy.threads
        threads, reason, delay = self.policy.decide(sample, time.monotonic())
        if threads != before:
            set_threads(threads)
        state = (threads, reason)
        if state != self.last_report:
            self.report({'threads': threads, 'reason': reason,
                         'available_memory_mb': round(sample.available / MIB) if sample else None})
            self.last_report = state
        if delay:
            self.stop.wait(delay)

    def close(self):
        self.stop.set()
        if self.thread is not None:
            self.thread.join(timeout=3)
