import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from audio_resources import AdaptiveResources, Policy, Sample, MIB


class ResourcePolicyTest(unittest.TestCase):
    def sample(self, at=0, **values):
        return replace(Sample(at,16,8,16,10,0,12*1024*MIB,16*1024*MIB),**values)

    def test_uses_hardware_and_does_not_count_own_load_as_other_programs(self):
        policy=Policy()
        self.assertEqual(policy.decide(self.sample(),0)[0],8)
        # Eight threads using half the host: no other program has become busier.
        self.assertEqual(policy.decide(self.sample(2,system_cpu=50,own_cpu=800),2)[0],8)
        small=Policy()
        self.assertEqual(small.decide(self.sample(logical=4,physical=4,allowed=4,system_cpu=0),0)[0],3)
        single=Policy()
        self.assertEqual(single.decide(self.sample(logical=1,physical=1,allowed=1),0)[0],1)

    def test_backs_off_immediately_then_recovers_gradually(self):
        policy=Policy();policy.decide(self.sample(),0)
        busy=self.sample(2,system_cpu=95,own_cpu=0)
        threads,reason,delay=policy.decide(busy,2)
        self.assertEqual(threads,1);self.assertGreater(delay,0)
        for at in range(4,22,2):
            self.assertEqual(policy.decide(self.sample(at,system_cpu=0),at)[0],1)
        self.assertEqual(policy.decide(self.sample(22,system_cpu=0),22)[0],2)
        self.assertEqual(policy.decide(self.sample(24,system_cpu=0),24)[0],2)
        # A second foreground load spike wins over the smoothed idle estimate.
        self.assertEqual(policy.decide(self.sample(26,system_cpu=95),26)[0],1)

    def test_memory_pressure_affinity_and_monitor_failure(self):
        policy=Policy();policy.decide(self.sample(),0)
        self.assertEqual(policy.decide(self.sample(2,available=2*1024*MIB),2)[0],2)
        result=policy.decide(self.sample(4,available=300*MIB),4)
        self.assertEqual(result[0],1);self.assertGreater(result[2],0)
        policy=Policy();policy.decide(self.sample(),0)
        self.assertEqual(policy.decide(self.sample(2,allowed=2),2)[0],2)
        policy=Policy();policy.decide(self.sample(),0)
        self.assertEqual(policy.decide(None,2)[0],2)
        self.assertEqual(policy.decide(self.sample(0),30)[0],2)

    def test_repeated_snapshot_cannot_trigger_recovery(self):
        policy=Policy();policy.decide(self.sample(system_cpu=99),0)
        idle=self.sample(20,system_cpu=0)
        for _ in range(10):policy.decide(idle,20)
        self.assertEqual(policy.good_samples,1)
        for at in (22,24):policy.decide(self.sample(at,system_cpu=0),at)
        before=policy.threads;count=policy.good_samples
        for _ in range(20):policy.decide(self.sample(24,system_cpu=0),24)
        self.assertEqual(policy.threads,before);self.assertEqual(policy.good_samples,count)

    def test_sampler_failure_is_safe_and_adjustment_runs_only_at_boundary(self):
        with patch('audio_resources.time.sleep'),patch('audio_resources.time.monotonic',return_value=0):
            control=AdaptiveResources(sampler_factory=Mock(side_effect=RuntimeError('unavailable')))
        self.assertEqual(control.initial_threads,1)
        control.latest=self.sample(2,system_cpu=0)
        setter=Mock()
        with patch('audio_resources.time.monotonic',return_value=2):control.boundary(setter)
        setter.assert_called_once_with(8)
        # Sampling itself never mutates torch's thread pool.
        control.latest=self.sample(4,available=1024*MIB)
        setter.assert_called_once()
        with patch('audio_resources.time.monotonic',return_value=4):control.boundary(setter)
        self.assertEqual(setter.call_args.args,(1,))
        control.close();self.assertTrue(control.stop.is_set())


if __name__=='__main__':unittest.main()
