"""Pre-release checklist. Local fixtures are scored; real recordings stay not_measured.

No model weights, AI calls, or private media are required. Drop a measured JSON
at test-results/acceptance/<case-id>.json to move that case from not_measured
to measured. The default run exits 0 even when real cases are still unmeasured.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / 'scripts') not in sys.path:
    sys.path.insert(0, str(ROOT / 'scripts'))

from benchmark import evaluate, listening_report, read_json, write_json


CASES = ROOT / 'bench' / 'acceptance-cases.json'
ANNOTATIONS = ROOT / 'bench' / 'annotations.example.json'
RESULTS = ROOT / 'bench' / 'results.example.json'
GOLD = ROOT / 'bench' / 'listening-gold.example.json'
PROPOSALS = ROOT / 'bench' / 'listening-proposals.example.json'


def _case_file(folder, case_id):
    if folder is None:
        return None
    path = Path(folder) / f'{case_id}.json'
    return path if path.is_file() else None


def _load_measured(path):
    payload = read_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f'{path} must be a JSON object.')
    status = payload.get('status', 'measured')
    if status not in ('measured', 'not_measured'):
        raise ValueError(f'{path} status must be measured or not_measured.')
    return {'status': status, 'source': str(path), 'metrics': payload}


def _resources(report_path):
    if report_path is None:
        return {'status': 'not_measured',
                'reason': 'Pass --benchmark-report from scripts/benchmark.py synthetic or measure. CI does not download models to fill this in.'}
    payload = read_json(report_path)
    if not isinstance(payload, dict):
        raise ValueError('Benchmark report must be a JSON object.')
    performance = payload.get('performance')
    if not isinstance(performance, dict):
        return {'status': 'not_measured', 'source': str(report_path),
                'reason': 'Report has no performance object.'}
    sampled = performance.get('wall_seconds') is not None or performance.get('resources_status') == 'sampled'
    if not sampled and performance.get('status') == 'not_measured':
        return {'status': 'not_measured', 'source': str(report_path), 'performance': performance}
    return {'status': 'measured', 'source': str(report_path), 'performance': performance}


def build_report(measured_dir=None, benchmark_report=None):
    catalog = read_json(CASES)
    if not isinstance(catalog, dict) or not isinstance(catalog.get('cases'), list):
        raise ValueError('Acceptance catalog is missing cases.')
    fixtures = {
        'annotation_example': {
            'status': 'measured',
            'data_kind': 'example_fixture',
            'quality': evaluate(read_json(ANNOTATIONS), read_json(RESULTS)),
            'note': 'Committed example intervals, not an accepted recording.',
        },
        'listening_example': {
            'status': 'measured',
            'data_kind': 'example_fixture',
            'quality': listening_report(read_json(GOLD), read_json(PROPOSALS)),
            'note': 'Synthetic listening gold. Subjective fine-cut acceptance is still open.',
        },
    }
    cases = []
    for case in catalog['cases']:
        if not isinstance(case, dict) or not isinstance(case.get('id'), str):
            raise ValueError('Acceptance case needs a string id.')
        found = _case_file(measured_dir, case['id'])
        if found is None:
            cases.append({**case, 'status': 'not_measured',
                          'reason': 'No local result file. Real media and any AI stay outside the default run.'})
        else:
            loaded = _load_measured(found)
            cases.append({**case, **loaded})
    return {'schema': 'sliceai.acceptance-report.v1',
            'product_acceptance': False,
            'ci_models_downloaded': False,
            'local_fixtures': fixtures,
            'resources': _resources(benchmark_report),
            'cases': cases,
            'measured_cases': sum(case['status'] == 'measured' for case in cases),
            'not_measured_cases': sum(case['status'] == 'not_measured' for case in cases)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--measured-dir', type=Path,
                        help='Directory of <case-id>.json files. Missing files stay not_measured.')
    parser.add_argument('--benchmark-report', type=Path,
                        help='Optional synthetic or measure report.json to attach resource metrics.')
    parser.add_argument('--output', type=Path, help='Write the checklist JSON here.')
    args = parser.parse_args(argv)
    report = build_report(args.measured_dir, args.benchmark_report)
    if args.output:
        write_json(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    return report


if __name__ == '__main__':
    main()
