"""Measured synthetic render baseline and explicit, annotated real-media evaluation."""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import math
import os
import platform
import statistics
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RANGES = [{'start': 1., 'end': 4.}, {'start': 9., 'end': 12.}, {'start': 18., 'end': 22.}]


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8', errors='strict'))
    except UnicodeDecodeError as exc:
        raise ValueError(f'{path} is not UTF-8; no conversion was performed.') from exc


def write_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n',
                    encoding='utf-8', newline='\n')


def intervals(rows):
    if not isinstance(rows, list):
        raise ValueError('Intervals must be an array.')
    result = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Interval must be an object.')
        a, b = row.get('start'), row.get('end')
        if type(a) not in (int, float) or type(b) not in (int, float) or not math.isfinite(a + b) or a < 0 or b <= a:
            raise ValueError('Invalid interval bounds.')
        result.append((a, b))
    return result


def merged(spans):
    result = []
    for a, b in sorted(spans):
        if result and a <= result[-1][1]:
            result[-1] = (result[-1][0], max(b, result[-1][1]))
        else:
            result.append((a, b))
    return result


def overlap(left, right):
    return max(0, min(left[1], right[1]) - max(left[0], right[0]))


def evaluate(reference, result, threshold=.5):
    """Reference events are exhaustive; captions use the output timeline and stable IDs."""
    report = {'selection': {'status': 'not_measured'}, 'deletions': {'status': 'not_measured'},
              'subtitles': {'status': 'not_measured'}}
    if 'events' in reference and 'clips' in result:
        truth, clips = intervals(reference['events']), intervals(result['clips'])
        matches = [[i for i, expected in enumerate(truth)
                    if overlap(clip, expected) / (max(clip[1], expected[1]) - min(clip[0], expected[0])) >= threshold]
                   for clip in clips]
        hits = {i for match in matches for i in match}
        report['selection'] = {'status': 'measured', 'reference_events': len(truth), 'clips': len(clips),
                               'missed_events': len(truth) - len(hits),
                               'false_positive_clips': sum(not match for match in matches),
                               'duplicate_event_outputs': sum(max(0, sum(i in m for m in matches) - 1) for i in range(len(truth))),
                               'iou_threshold': threshold}
    if 'protected' in reference and 'ranges' in result:
        protected, kept = merged(intervals(reference['protected'])), intervals(result['ranges'])
        unique = merged(kept)
        lost = sum(b - a - sum(overlap((a, b), span) for span in unique) for a, b in protected)
        repeated = sum(b - a for a, b in kept) - sum(b - a for a, b in unique)
        report['deletions'] = {'status': 'measured', 'protected_seconds': sum(b - a for a, b in protected),
                               'incorrectly_deleted_seconds': round(max(0, lost), 6),
                               'duplicated_source_seconds': round(max(0, repeated), 6)}
    if 'captions' in reference and 'captions' in result:
        intervals(reference['captions']); intervals(result['captions'])
        expected = {row['id']: row for row in reference['captions']}
        actual = {row['id']: row for row in result['captions']}
        if len(expected) != len(reference['captions']) or len(actual) != len(result['captions']):
            raise ValueError('Caption IDs must be unique.')
        common = expected.keys() & actual.keys()
        errors = sorted(abs(expected[sid][key] - actual[sid][key]) for sid in common for key in ('start', 'end'))
        report['subtitles'] = {'status': 'measured', 'matched_cues': len(common),
                               'missing_cues': len(expected.keys() - actual.keys()),
                               'unexpected_cues': len(actual.keys() - expected.keys()),
                               'median_boundary_error_seconds': statistics.median(errors) if errors else None,
                               'p95_boundary_error_seconds': errors[max(0, math.ceil(.95 * len(errors)) - 1)] if errors else None,
                               'max_boundary_error_seconds': max(errors) if errors else None,
                               'text_mismatches': sum(expected[sid].get('text') != actual[sid].get('text') for sid in common
                                                      if 'text' in expected[sid]),
                               'note': 'Against manually aligned output-timeline cues; no OCR or acoustic alignment is inferred.'}
    return report


def disk_bytes(folder):
    return sum(path.stat().st_size for path in Path(folder).rglob('*') if path.is_file())


def measured_command(argv, folder, cwd=ROOT):
    if not isinstance(argv, list) or not argv or any(not isinstance(arg, str) for arg in argv):
        raise ValueError('command JSON must be a nonempty argument array; shell strings are not accepted.')
    try:
        import psutil
    except ImportError:
        psutil = None
    folder = Path(folder)
    before = disk_bytes(folder); peak_disk = before; peak_rss = 0; samples = 0; counters = {}
    started = time.monotonic()
    # Output is captured as raw bytes, so an external tool's unknown encoding is
    # not silently converted into a text log.
    with (folder / 'process-output.bin').open('wb') as log:
        process = subprocess.Popen(argv, cwd=cwd, stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                                   env={**os.environ, 'PYTHONUTF8': '1'})
        while True:
            if psutil:
                try:
                    parent = psutil.Process(process.pid); total = 0
                    for child in [parent, *parent.children(recursive=True)]:
                        try:
                            key = (child.pid, child.create_time()); cpu = child.cpu_times(); memory = child.memory_info()
                            previous = counters.get(key, {})
                            current = {**previous, 'cpu_seconds': cpu.user + cpu.system}
                            try:
                                io_counts = child.io_counters()
                                current.update(read_bytes=io_counts.read_bytes, write_bytes=io_counts.write_bytes)
                            except (psutil.Error, AttributeError):
                                pass
                            counters[key] = current; total += memory.rss
                        except psutil.Error:
                            pass
                    peak_rss = max(peak_rss, total); samples += 1
                except psutil.Error:
                    pass
            peak_disk = max(peak_disk, disk_bytes(folder))
            if process.poll() is not None:
                break
            time.sleep(.1)
    elapsed = time.monotonic() - started
    cpu = sum(row['cpu_seconds'] for row in counters.values()) if samples else None
    return {'exit_code': process.returncode, 'wall_seconds': round(elapsed, 4),
            'sample_interval_seconds': .1, 'process_tree_samples': samples,
            'peak_process_tree_rss_mb': round(peak_rss / 1024 ** 2, 3) if samples else None,
            'sampled_process_tree_cpu_seconds': round(cpu, 4) if cpu is not None else None,
            'average_cpu_percent_one_core_basis': round(cpu / elapsed * 100, 2) if cpu is not None else None,
            'sampled_process_tree_read_bytes': sum(row.get('read_bytes', 0) for row in counters.values()) if any('read_bytes' in row for row in counters.values()) else None,
            'sampled_process_tree_write_bytes': sum(row.get('write_bytes', 0) for row in counters.values()) if any('write_bytes' in row for row in counters.values()) else None,
            'peak_output_directory_growth_bytes': max(0, peak_disk - before),
            'final_output_directory_growth_bytes': disk_bytes(folder) - before,
            'measurement_note': 'Sampled counters may miss short-lived processes; RSS is working set, not a memory cap. Disk scope is this output directory.',
            'resources_status': 'sampled' if samples else 'not_measured: psutil unavailable or process exited before sampling'}


def environment():
    result = {'platform': platform.platform(), 'python': platform.python_version(), 'logical_cpus': os.cpu_count()}
    for tool in ('ffmpeg', 'ffprobe'):
        try:
            result[tool] = subprocess.check_output([tool, '-version']).decode('utf-8', errors='strict').splitlines()[0]
        except (OSError, subprocess.CalledProcessError):
            result[tool] = None
    try:
        result['git_commit'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode('utf-8', errors='strict').strip()
        result['git_worktree_dirty'] = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT))
    except (OSError, subprocess.CalledProcessError):
        result.update(git_commit=None, git_worktree_dirty=None)
    return result


def probe(path):
    return json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries',
                                               'format=format_name,start_time,duration:stream=codec_type,width,height,start_time,duration:stream_tags=DURATION',
                                               '-of', 'json', str(path)]))


def source_duration(path):
    backend = str(ROOT / 'backend')
    if backend not in sys.path:
        sys.path.insert(0, backend)
    from media_audio import video_duration
    duration = video_duration(probe(path))
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('Cannot determine the source video timeline duration.')
    return duration


def fresh_folder(path):
    folder = Path(path).resolve()
    if folder.exists() and any(folder.iterdir()):
        raise ValueError('Use an empty output directory; benchmark results are never deleted or overwritten.')
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def synthetic(folder):
    folder = fresh_folder(folder); video = folder / 'source.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-y', '-f', 'lavfi', '-i',
                    'testsrc2=size=320x180:rate=25', '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000',
                    '-t', '24', '-c:v', 'libx264', '-preset', 'ultrafast', '-threads', '2', '-c:a', 'aac', str(video)], check=True)
    metrics = measured_command([sys.executable, '-X', 'utf8', str(Path(__file__).resolve()), '_render',
                                '--video', str(video), '--output-dir', str(folder)], folder)
    report = {'schema_version': 1, 'kind': 'synthetic-render', 'artifacts_dir': str(folder), 'environment': environment(), 'performance': metrics,
              'fixture': {'duration_seconds': 24, 'width': 320, 'height': 180, 'fps': 25, 'ranges': RANGES},
              'semantic_quality': {'status': 'not_measured', 'reason': 'Fixed edit list and tone/test pattern; no model or real speech ran.'},
              'acoustic_subtitle_sync': {'status': 'not_measured', 'reason': 'Subtitle metadata checked; no speech alignment or burned-text OCR.'}}
    if metrics['exit_code'] == 0:
        result = read_json(folder / 'render-result.json'); media = probe(result['path'])
        expected = [{'id': i + 1, 'start': start, 'end': end, 'text': text}
                    for i, (start, end, text) in enumerate([(0., 3., 'First retained interval'), (3., 6., 'Second retained interval'), (6., 10., 'Third retained interval')])]
        report['quality'] = evaluate({'captions': expected}, {'captions': result['captions']})
        report['quality']['duration_error_seconds'] = abs(float(media['format']['duration']) - 10)
        report['passed'] = report['quality']['duration_error_seconds'] <= .3 and report['quality']['subtitles']['max_boundary_error_seconds'] == 0
    else:
        report['passed'] = False
    write_json(folder / 'report.json', report)
    return report


def render_fixture(video, folder):
    sys.path.insert(0, str(ROOT / 'backend'))
    from storage import Store
    from pipeline import now
    from fine import create, Editor
    folder = Path(folder); store = Store(folder / 'profile'); task_id = str(uuid.uuid4())
    rows = [{'id': i, **r, 'text': text} for i, (r, text) in enumerate(zip(RANGES,
            ['First retained interval', 'Second retained interval', 'Third retained interval']))]
    task = {'id': task_id, 'created': now(), 'title': 'synthetic baseline', 'video': str(video), 'duration': 24,
            'prefs': {'exclude_playback': False}, 'output_root': str(folder / 'exports'), 'exports': [],
            'clips': [{'id': 1, 'title': 'synthetic baseline', 'start': 0, 'end': 24}]}
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            store.put(task); write_json(store.task_dir(task_id) / 'transcript.json', rows)
            project = create(store, task_id, 1); editor = Editor(store, {'project_id': project['id']})
            version = editor.version(RANGES, 'Fixed synthetic intervals'); version['confirmed'] = True
            editor.render(); editor.render(export=True)
        write_json(folder / 'render-result.json', {'path': editor.p['exports'][-1]['path'], 'ranges': version['ranges'], 'captions': version['cues']})
    finally:
        store.db.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__); commands = parser.add_subparsers(dest='mode', required=True)
    synth = commands.add_parser('synthetic'); synth.add_argument('--output-dir', type=Path, default=ROOT / 'test-results/bench' / uuid.uuid4().hex[:8])
    scoring = commands.add_parser('evaluate'); scoring.add_argument('--annotations', type=Path, required=True); scoring.add_argument('--results', type=Path, required=True)
    scoring.add_argument('--report', type=Path, required=True); scoring.add_argument('--iou-threshold', type=float, default=.5)
    measure = commands.add_parser('measure'); measure.add_argument('--command-json', type=Path, required=True); measure.add_argument('--output-dir', type=Path, required=True)
    measure.add_argument('--video', type=Path, help='Optional explicit long recording, only probed for media duration.')
    measure.add_argument('--cwd', type=Path, default=ROOT)
    worker = commands.add_parser('_render', help=argparse.SUPPRESS); worker.add_argument('--video', type=Path, required=True); worker.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.mode == '_render':
        render_fixture(args.video, args.output_dir); return
    if args.mode == 'synthetic':
        report = synthetic(args.output_dir)
    elif args.mode == 'evaluate':
        if not 0 < args.iou_threshold <= 1:
            parser.error('IoU threshold must be within (0,1].')
        reference, result = read_json(args.annotations), read_json(args.results)
        report = {'schema_version': 1, 'kind': 'annotated-evaluation',
                  'data_kind': 'example_fixture' if reference.get('example_fixture') or result.get('example_fixture') else 'supplied_annotations_and_results',
                  'quality': evaluate(reference, result, args.iou_threshold),
                  'performance': {'status': 'not_measured', 'reason': 'Evaluation scores supplied results; no pipeline was run.'}}
        write_json(args.report, report)
    else:
        folder = fresh_folder(args.output_dir); report = {'schema_version': 1, 'kind': 'explicit-command', 'artifacts_dir': str(folder), 'environment': environment(),
                    'performance': measured_command(read_json(args.command_json), folder, args.cwd),
                    'semantic_quality': {'status': 'not_measured', 'reason': 'Supply independent annotations and results to evaluate quality.'}}
        if args.video:
            duration = source_duration(args.video); report['source_duration_seconds'] = duration
            report['performance']['wall_seconds_per_source_second'] = report['performance']['wall_seconds'] / duration
        write_json(folder / 'report.json', report)
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    if report.get('passed') is False or report.get('performance', {}).get('exit_code', 0) != 0:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
