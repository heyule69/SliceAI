import contextlib
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from benchmark import evaluate, listening_report, main, probe, source_duration


class EvaluationTest(unittest.TestCase):
    def test_misses_false_positives_duplicates_and_deleted_protection(self):
        reference = {'events': [{'start': 0, 'end': 10}, {'start': 30, 'end': 40}],
                     'protected': [{'start': 1, 'end': 4}]}
        result = {'clips': [{'start': 0, 'end': 10}, {'start': 0, 'end': 10}, {'start': 50, 'end': 60}],
                  'ranges': [{'start': 0, 'end': 2}, {'start': 0, 'end': 2}]}
        metrics = evaluate(reference, result)
        self.assertEqual(metrics['selection']['missed_events'], 1)
        self.assertEqual(metrics['selection']['false_positive_clips'], 1)
        self.assertEqual(metrics['selection']['duplicate_event_outputs'], 1)
        self.assertEqual(metrics['deletions']['incorrectly_deleted_seconds'], 2)
        self.assertEqual(metrics['deletions']['duplicated_source_seconds'], 2)

    def test_subtitle_errors_and_missing_annotation_are_not_invented(self):
        metrics = evaluate({'captions': [{'id': 1, 'start': 1, 'end': 2, 'text': 'hello'}]},
                           {'captions': [{'id': 1, 'start': 1.2, 'end': 2.4, 'text': 'changed'}]})
        self.assertAlmostEqual(metrics['subtitles']['max_boundary_error_seconds'], .4)
        self.assertEqual(metrics['subtitles']['text_mismatches'], 1)
        self.assertEqual(metrics['selection']['status'], 'not_measured')
        self.assertEqual(evaluate({}, {})['subtitles']['status'], 'not_measured')

    def test_listening_gold_scores_hits_false_cuts_and_boundary_error(self):
        gold = {'samples': [
            {'id': 'retake', 'category': '重说',
             'deletable': [{'id': 'syllable', 'start': 1.0, 'end': 1.4}],
             'protected': [{'id': 'rest', 'start': 1.4, 'end': 4.0}]},
            {'id': 'laugh', 'category': '笑哭',
             'deletable': [{'id': 'preface', 'start': 1.0, 'end': 1.3}],
             'protected': [{'id': 'laugh', 'start': 4.0, 'end': 6.0}]},
            {'id': 'music', 'category': 'music', 'deletable': [{'id': 'bed', 'start': 2, 'end': 3}]}]}
        proposals = {'samples': [
            {'id': 'retake', 'cuts': [{'id': 'ok', 'start': 1.04, 'end': 1.36},
                                      {'id': 'extra', 'start': 4.2, 'end': 4.6}]},
            {'id': 'laugh', 'cuts': [{'id': 'into-laugh', 'start': 3.8, 'end': 5.0}]},
            {'id': 'music', 'cuts': []}]}
        report = listening_report(gold, proposals)
        self.assertEqual(report['status'], 'measured')
        retake = next(sample for sample in report['samples'] if sample['id'] == 'retake')
        self.assertEqual(retake['hits'], 1)
        self.assertEqual(retake['false_cuts'], 1)
        self.assertAlmostEqual(retake['max_boundary_error_seconds'], .04)
        self.assertEqual(retake['protected_overlap_cuts'], 0)
        laugh = next(sample for sample in report['samples'] if sample['id'] == 'laugh')
        self.assertEqual(laugh['hits'], 0)
        self.assertEqual(laugh['false_cuts'], 1)
        self.assertEqual(laugh['protected_overlap_cuts'], 1)
        self.assertEqual(report['by_category']['音乐']['missed'], 1)
        self.assertEqual(report['hits'], 1)
        self.assertEqual(report['false_cuts'], 2)
        self.assertEqual(listening_report({}, {})['status'], 'not_measured')
        with self.assertRaises(ValueError):
            listening_report({'samples': [{'id': 'x', 'category': '重说', 'deletable': [{'id': 'a', 'start': 0, 'end': float('nan')}]}]},
                             {'samples': [{'id': 'x', 'cuts': []}]})

    def test_listening_example_fixture_runs_without_media(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            report_path = Path(temp) / 'listen.json'
            with contextlib.redirect_stdout(io.StringIO()):
                main(['listen', '--gold', str(root / 'bench/listening-gold.example.json'),
                      '--proposals', str(root / 'bench/listening-proposals.example.json'),
                      '--report', str(report_path)])
            report = json.loads(report_path.read_text(encoding='utf-8'))
        self.assertEqual(report['quality']['status'], 'measured')
        self.assertEqual(report['quality']['hit_rate'], 1)
        self.assertEqual(report['quality']['false_cuts'], 0)
        self.assertLessEqual(report['quality']['max_boundary_error_seconds'], .15)
        self.assertEqual(report['performance']['status'], 'not_measured')
        self.assertEqual(set(report['quality']['by_category']), {'音乐', '无音乐', '重说', '笑哭', '混语'})

    def test_invalid_intervals_fail_instead_of_corrupting_metrics(self):
        with self.assertRaises(ValueError):
            evaluate({'events': [{'start': 0, 'end': float('nan')}]}, {'clips': []})

    def test_measure_uses_video_span_for_nonzero_pts_and_longer_audio(self):
        metadata = {'format': {'format_name': 'matroska,webm', 'start_time': '5', 'duration': '16'},
                    'streams': [{'codec_type': 'video', 'start_time': '5', 'tags': {'DURATION': '00:00:08.000000000'}},
                                {'codec_type': 'audio', 'start_time': '5', 'tags': {'DURATION': '00:00:16.000000000'}}]}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); command = root / 'command.json'; output = root / 'report'
            command.write_text(json.dumps(['unused-child']), encoding='utf-8')
            with patch('benchmark.probe', return_value=metadata), patch('benchmark.environment', return_value={}), \
                    patch('benchmark.measured_command', return_value={'exit_code': 0, 'wall_seconds': 6}), \
                    contextlib.redirect_stdout(io.StringIO()):
                main(['measure', '--command-json', str(command), '--video', 'nonzero-pts.mkv', '--output-dir', str(output)])
            report = json.loads((output / 'report.json').read_text(encoding='utf-8'))
            self.assertEqual(report['source_duration_seconds'], 3)
            self.assertEqual(report['performance']['wall_seconds_per_source_second'], 2)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg fixture required')
    def test_nonzero_pts_media_fixture_uses_video_zero(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'video-starts-at-five.mkv'
            subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-y', '-f', 'lavfi', '-i',
                            'testsrc2=size=160x90:rate=10:duration=2', '-vf', 'setpts=PTS+5/TB',
                            '-c:v', 'libx264', '-preset', 'ultrafast', '-threads', '1', '-fps_mode', 'passthrough',
                            str(path)], check=True, capture_output=True)
            # Some FFmpeg/Matroska versions tag the final frame's PTS without
            # its duration. Allow one 10-fps frame, but never the five-second origin.
            self.assertGreater(float(probe(path)['format']['duration']), 6)
            self.assertAlmostEqual(source_duration(path), 2, delta=.11)


if __name__ == '__main__':
    unittest.main()
