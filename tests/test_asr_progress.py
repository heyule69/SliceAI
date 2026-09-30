import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from pipeline import asr_progress_label


class ProgressTest(unittest.TestCase):
    def test_recording_position_is_separate_from_wall_clock_elapsed(self):
        self.assertEqual(asr_progress_label(3456.9,19786.944,80.2),
            '已转写录播 00:57:36 / 05:29:46 · 耗时 00:01:20')

    def test_rounding_does_not_report_past_end_and_hours_do_not_wrap(self):
        self.assertEqual(asr_progress_label(3700,3600,90061),
            '已转写录播 01:00:00 / 01:00:00 · 耗时 25:01:01')


if __name__=='__main__':unittest.main()
