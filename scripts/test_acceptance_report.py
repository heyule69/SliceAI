import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from acceptance_report import build_report, main


class AcceptanceReportTest(unittest.TestCase):
    def test_default_run_measures_fixtures_and_leaves_real_cases_unmeasured(self):
        report = build_report()
        self.assertFalse(report['product_acceptance'])
        self.assertFalse(report['ci_models_downloaded'])
        self.assertEqual(report['local_fixtures']['listening_example']['status'], 'measured')
        self.assertEqual(report['local_fixtures']['listening_example']['quality']['hit_rate'], 1)
        self.assertEqual(report['local_fixtures']['annotation_example']['status'], 'measured')
        self.assertGreater(report['not_measured_cases'], 0)
        self.assertEqual(report['measured_cases'], 0)
        self.assertTrue(all(case['status'] == 'not_measured' for case in report['cases']))
        self.assertEqual(report['resources']['status'], 'not_measured')
        long = next(case for case in report['cases'] if case['id'] == 'long-recording')
        self.assertIn('not_measured', long['status'])

    def test_supplied_case_file_and_benchmark_report_become_measured(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            measured = root / 'cases'
            measured.mkdir()
            (measured / 'long-recording.json').write_text(
                json.dumps({'status': 'measured', 'missed_events': 0, 'duplicate_event_outputs': 0}),
                encoding='utf-8')
            benchmark = root / 'report.json'
            benchmark.write_text(json.dumps({'performance': {'wall_seconds': 3.5, 'resources_status': 'sampled',
                                                             'peak_process_tree_rss_mb': 12}}), encoding='utf-8')
            report = build_report(measured, benchmark)
            long = next(case for case in report['cases'] if case['id'] == 'long-recording')
            self.assertEqual(long['status'], 'measured')
            self.assertEqual(long['metrics']['duplicate_event_outputs'], 0)
            self.assertEqual(report['resources']['status'], 'measured')
            self.assertEqual(report['resources']['performance']['wall_seconds'], 3.5)
            untouched = next(case for case in report['cases'] if case['id'] == 'heavy-bgm')
            self.assertEqual(untouched['status'], 'not_measured')
            with contextlib.redirect_stdout(io.StringIO()):
                main(['--measured-dir', str(measured), '--benchmark-report', str(benchmark),
                      '--output', str(root / 'checklist.json')])
            written = json.loads((root / 'checklist.json').read_text(encoding='utf-8'))
            self.assertEqual(written['measured_cases'], 1)


if __name__ == '__main__':
    unittest.main()
