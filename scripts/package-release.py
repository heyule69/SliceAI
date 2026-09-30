"""Collect a verified local portable build and installer after `npm run bundle`."""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import tempfile
import uuid
from pathlib import Path

from model_assets import CATALOG, checksum, read_json, verify

ROOT = Path(__file__).resolve().parents[1]
VERSION = '0.2.0'


def alignment_builder():
    spec = importlib.util.spec_from_file_location('build_alignment', Path(__file__).with_name('build-alignment.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def required_file(path):
    if not Path(path).is_file():
        raise ValueError(f'Release resource is missing: {path}')


def verify_workers(worker, require_alignment=False):
    worker = Path(worker)
    for name in ('sliceai-worker.exe', 'bin/ffmpeg.exe', 'bin/ffprobe.exe', 'THIRD-PARTY-NOTICES.txt'):
        required_file(worker / name)
    verify(read_json(CATALOG / 'sensevoice.json'), worker / 'models/sensevoice-int8')
    components = {'asr': True, 'audio': False, 'alignment': False}
    audio = worker / 'audio'
    if audio.exists():
        for name in ('sliceai-audio.exe', 'THIRD-PARTY-NOTICES.txt', 'licenses/LICENSE-MIT.txt',
                     'licenses/LICENSE-Apache-2.0.txt', 'licenses/NOTICE.txt'):
            required_file(audio / name)
        verify(read_json(CATALOG / 'bandit-plus.json'), audio / 'model')
        components['audio'] = True
    alignment = worker / 'alignment'
    if alignment.exists():
        alignment_builder().verify_bundle(alignment)
        components['alignment'] = True
    elif require_alignment:
        raise ValueError('Alignment worker has not been built. Build/stage it before npm run bundle; no release was changed.')
    return components


def verify_build(root=ROOT, require_alignment=False):
    build = Path(root) / 'src-tauri/target/release'
    installer = build / f'bundle/nsis/SliceAI_{VERSION}_x64-setup.exe'
    required_file(build / 'sliceai.exe')
    required_file(installer)
    required_file(Path(root) / 'README.md')
    components = verify_workers(build / 'worker', require_alignment)
    return build, installer, components


def package(root=ROOT, require_alignment=False):
    root = Path(root).resolve()
    build, installer, components = verify_build(root, require_alignment)
    release = root / 'release'
    if not release.resolve().is_relative_to(root):
        raise ValueError('Unsafe release destination.')
    stage_parent = root / 'build/release-staging'
    stage_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='release-', dir=stage_parent) as temporary:
        stage = Path(temporary) / 'release'
        portable = stage / f'SliceAI-{VERSION}'
        portable.mkdir(parents=True)
        shutil.copy2(build / 'sliceai.exe', portable / 'SliceAI.exe')
        shutil.copytree(build / 'worker', portable / 'worker')
        shutil.copy2(root / 'README.md', stage / 'README.md')
        shutil.copy2(installer, stage / installer.name)
        # Verify the copied payload, including models/licenses, before replacing a release.
        verify_workers(portable / 'worker', require_alignment)
        checksums = {path.relative_to(stage).as_posix(): checksum(path)
                     for path in sorted(stage.rglob('*')) if path.is_file()}
        (stage / 'SHA256.json').write_text(json.dumps(checksums, ensure_ascii=False, indent=2) + '\n',
                                          encoding='utf-8', newline='\n')
        backup = root / 'build' / ('release-previous-' + uuid.uuid4().hex[:8])
        if release.exists():
            release.rename(backup)
        try:
            stage.rename(release)
        except OSError:
            if backup.exists() and not release.exists():
                backup.rename(release)
            raise
    return {'installer': str(release / installer.name), 'portable': str(release / f'SliceAI-{VERSION}/SliceAI.exe'),
            'installer_mb': round(installer.stat().st_size / 1024**2, 2), 'components': components,
            'previous_release': str(backup) if backup.exists() else None}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true', help='Show paths only; do not verify assets or write a release.')
    mode.add_argument('--verify-only', action='store_true', help='Verify source build assets; do not change release/.')
    parser.add_argument('--require-alignment', action='store_true', help='Reject builds without the independent fine-edit alignment worker.')
    args = parser.parse_args(argv)
    try:
        if args.dry_run:
            result = {'build': str(ROOT / 'src-tauri/target/release'), 'release': str(ROOT / 'release'),
                      'require_alignment': args.require_alignment, 'dry_run': True, 'verified': False, 'downloads': False}
        elif args.verify_only:
            build, installer, components = verify_build(require_alignment=args.require_alignment)
            result = {'build': str(build), 'installer': str(installer), 'components': components, 'verified': True}
        else:
            result = package(require_alignment=args.require_alignment)
    except (OSError, ValueError) as exc:
        parser.exit(1, str(exc) + '\n')
    if 'components' in result and not result['components']['alignment']:
        result['fine_edit_warning'] = 'No bundled aligner: ASR remains available; word-level fine-edit candidates lack verified boundaries.'
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
