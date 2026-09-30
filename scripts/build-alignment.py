"""Build the isolated CPU aligner from local pinned assets; never fetch weights."""
from __future__ import annotations

import argparse
import importlib.metadata as metadata
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path, PurePosixPath

from model_assets import CATALOG, checked, checksum, read_json, verify

ROOT = Path(__file__).resolve().parents[1]
CATALOG_FILE = CATALOG / 'qwen3-forced-aligner.json'
RUNTIME = {'torch': '2.6.0+cpu', 'qwen-asr': '0.0.6', 'transformers': '4.57.6',
           'accelerate': '1.12.0', 'numpy': '1.26.4', 'safetensors': '0.8.0', 'pyinstaller': '6.22.3'}
EXCLUDES = ('qwen_asr.cli', 'qwen_asr.core.vllm_backend', 'vllm', 'gradio', 'flask',
            'fastapi', 'uvicorn', 'tensorflow', 'jax', 'triton', 'torchvision',
            'torchaudio', 'matplotlib', 'IPython', 'pytest', 'tensorboard')


def utf8_text(path):
    try:
        text = Path(path).read_text(encoding='utf-8', errors='strict')
    except UnicodeDecodeError as exc:
        raise ValueError(f'{path} is not UTF-8; no file was converted.') from exc
    if text.startswith('\ufeff'):
        raise ValueError(f'{path} contains a BOM; expected UTF-8 without BOM.')
    return text


def bundle_path(folder, name):
    relative = PurePosixPath(name)
    if not name or '\\' in name or relative.is_absolute() or '..' in relative.parts:
        raise ValueError(f'Unsafe bundle path: {name!r}')
    path = Path(folder) / relative
    if not path.resolve().is_relative_to(Path(folder).resolve()):
        raise ValueError(f'Bundle path escapes its directory: {name!r}')
    return path


def runtime_versions(root=ROOT):
    expected = (Path(root) / '.alignment-venv').resolve()
    if Path(sys.prefix).resolve() != expected:
        raise ValueError('Run this build with .alignment-venv/Scripts/python.exe; ASR and audio environments are separate.')
    versions = {}
    for name, version in RUNTIME.items():
        installed = metadata.version(name)
        if installed != version:
            raise ValueError(f'Expected {name}=={version}, found {installed}. Install requirements-alignment-lock.txt.')
        versions[name] = installed
    return versions


def pyinstaller_args(root=ROOT, executable=None):
    root = Path(root)
    args = [str(executable or sys.executable), '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
            '--name', 'sliceai-alignment', '--distpath', str(root / 'build/alignment-dist'),
            '--workpath', str(root / 'build/alignment-pyinstaller'), '--specpath', str(root / 'build')]
    # Upstream imports reference nagisa; the worker defers Japanese initialization.
    # Preserve its data and the always-used Korean dictionary for offline loading.
    # Keep librosa/numba CPU dependencies.
    for package in ('qwen_asr', 'nagisa', 'soynlp'):
        args += ['--collect-data', package]
    for module in ('nagisa', 'dynet', 'transformers.models.qwen2.tokenization_qwen2',
                   'transformers.models.qwen2.tokenization_qwen2_fast',
                   'transformers.models.whisper.feature_extraction_whisper'):
        args += ['--hidden-import', module]
    for name in ('qwen-asr', 'transformers', 'torch', 'accelerate', 'numpy', 'nagisa',
                 'dyNET38', 'soynlp', 'soundfile', 'librosa', 'tokenizers', 'safetensors'):
        args += ['--copy-metadata', name]
    for name in EXCLUDES:
        args += ['--exclude-module', name]
    args += [str(root / 'backend/alignment_worker.py')]
    return args


def source_data_args():
    # Transformers inspects custom model source when registering processors.
    # Supply the original .py files as well as compiled modules, without CLI/GPU code.
    distribution = metadata.distribution('qwen-asr')
    args = []
    for entry in distribution.files or ():
        name = str(entry).replace('\\', '/')
        if name.startswith('qwen_asr/') and name.endswith('.py') and '/cli/' not in name and '/vllm_backend/' not in name:
            path = distribution.locate_file(entry)
            utf8_text(path)
            args += ['--add-data', str(path) + os.pathsep + str(PurePosixPath(name).parent)]
    return args


def copy_licenses(destination):
    destination = Path(destination)
    licenses = destination / 'licenses'
    licenses.mkdir(parents=True, exist_ok=True)
    qwen_license = None
    # Retain installed wheel notices without depending on a user profile or network.
    for distribution in metadata.distributions():
        name = distribution.metadata.get('Name', '')
        if name.lower().replace('_', '-') in ('gradio', 'flask', 'fastapi', 'uvicorn'):
            continue
        for entry in distribution.files or ():
            parts = PurePosixPath(str(entry).replace('\\', '/')).parts
            if not any(part.endswith('.dist-info') for part in parts):
                continue
            if '__pycache__' in parts or Path(parts[-1]).suffix in ('.pyc', '.pyo'):
                continue
            if not (parts[-1].lower().startswith(('license', 'copying', 'notice')) or 'licenses' in parts):
                continue
            source = distribution.locate_file(entry)
            if not source.is_file():
                continue
            utf8_text(source)  # Report unsupported encodings rather than converting them.
            target = licenses / name / Path(*parts[1:])
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            if name.lower().replace('_', '-') == 'qwen-asr' and parts[-1] == 'LICENSE':
                qwen_license = source
    if qwen_license is None:
        raise ValueError('The installed qwen-asr wheel is missing its LICENSE; no bundle was staged.')
    license_text = utf8_text(qwen_license)
    if 'Apache License' not in license_text or 'Version 2.0' not in license_text:
        raise ValueError('The qwen-asr wheel license is not the expected Apache 2.0 text.')
    shutil.copy2(qwen_license, licenses / 'LICENSE-Apache-2.0.txt')
    shutil.copy2(qwen_license, destination / 'model/LICENSE-Apache-2.0.txt')


def write_bundle_manifest(folder, catalog, versions):
    folder = Path(folder)
    manifest = {'schema': 1, 'engine': catalog['manifest']['engine'],
                'revision': catalog['manifest']['revision'], 'runtime': versions, 'files': {}}
    for path in sorted(folder.rglob('*')):
        if path.is_file() and path.name != 'bundle-manifest.json':
            name = path.relative_to(folder).as_posix()
            bundle_path(folder, name)
            manifest['files'][name] = {'bytes': path.stat().st_size, 'sha256': checksum(path)}
    (folder / 'bundle-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n',
                                               encoding='utf-8', newline='\n')


def verify_bundle(folder, catalog=None):
    folder = Path(folder)
    if not folder.is_dir():
        raise ValueError(f'Alignment worker has not been built: {folder}')
    catalog = catalog or read_json(CATALOG_FILE)
    verify(catalog, folder / 'model')
    required = ('sliceai-alignment.exe', 'THIRD-PARTY-NOTICES.txt', 'licenses/LICENSE-Apache-2.0.txt',
                'model/LICENSE-Apache-2.0.txt', 'model/manifest.json',
                '_internal/qwen_asr/inference/assets/korean_dict_jieba.dict',
                '_internal/qwen_asr-0.0.6.dist-info/METADATA',
                '_internal/transformers-4.57.6.dist-info/METADATA',
                '_internal/safetensors-0.8.0.dist-info/METADATA',
                '_internal/torch-2.6.0+cpu.dist-info/METADATA', 'bundle-manifest.json')
    for name in required:
        if not bundle_path(folder, name).is_file():
            raise ValueError(f'Incomplete alignment bundle: missing {name}')
    for name in ('licenses/LICENSE-Apache-2.0.txt', 'model/LICENSE-Apache-2.0.txt'):
        text = utf8_text(folder / name)
        if 'Apache License' not in text or 'Version 2.0' not in text:
            raise ValueError(f'Unexpected Apache 2.0 license: {folder / name}')
    manifest = read_json(folder / 'bundle-manifest.json')
    if manifest.get('schema') != 1 or any(manifest.get(key) != catalog['manifest'][key] for key in ('engine', 'revision')):
        raise ValueError('Alignment bundle manifest differs from the pinned model.')
    if manifest.get('runtime') != RUNTIME:
        raise ValueError('Alignment bundle runtime differs from the pinned CPU dependencies.')
    files = manifest.get('files')
    if not isinstance(files, dict) or not set(required[:-1]).issubset(files):
        raise ValueError('Alignment bundle inventory is incomplete.')
    actual = {path.relative_to(folder).as_posix() for path in folder.rglob('*')
              if path.is_file() and path != folder / 'bundle-manifest.json'}
    if actual != set(files):
        raise ValueError('Alignment bundle contains missing or unlisted files; rebuild it cleanly.')
    pinned_files = {'model/' + name: info for name, info in catalog['files'].items()}
    for name, info in files.items():
        if not isinstance(name, str) or not isinstance(info, dict) or not isinstance(info.get('bytes'), int) or info['bytes'] < 0 or not isinstance(info.get('sha256'), str) or len(info['sha256']) != 64:
            raise ValueError('Alignment bundle inventory contains invalid file metadata.')
        path = bundle_path(folder, name)
        if name in pinned_files:
            expected = pinned_files[name]
            if info != {'bytes': expected['bytes'], 'sha256': expected['sha256']}:
                raise ValueError(f'Alignment bundle weight inventory differs: {name}')
            # verify() already hashed these large pinned assets above.
        else:
            checked(path, info)
    return {'path': str(folder), 'engine': manifest['engine'], 'files': len(files), 'verified': True}


def stage_worker(root, catalog, versions):
    root = Path(root).resolve()
    source = root / 'build/alignment-dist/sliceai-alignment'
    destination = root / 'src-tauri/resources/worker/alignment'
    if not source.is_dir() or not (source / 'sliceai-alignment.exe').is_file():
        raise ValueError(f'Alignment executable has not been built: {source / "sliceai-alignment.exe"}')
    for path in (source, destination):
        if not path.resolve().is_relative_to(root):
            raise ValueError(f'Unsafe alignment staging path: {path}')
    model = root / catalog['destination']
    verify(catalog, model)
    staging = root / 'build/alignment-staging'
    staging.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='worker-', dir=staging) as temporary:
        stage = Path(temporary) / 'alignment'
        shutil.copytree(source, stage)
        target = stage / 'model'
        target.mkdir()
        for name in ('manifest.json', *catalog['files']):
            shutil.copy2(model / name, target / name)
        copy_licenses(stage)
        (stage / 'THIRD-PARTY-NOTICES.txt').write_text(
            'Qwen3-ForcedAligner-0.6B model and qwen-asr software: Apache-2.0.\n'
            'Copyright 2026 The Alibaba Qwen team.\n'
            'https://github.com/QwenLM/Qwen3-ASR\n'
            'https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B\n'
            'The model card declares Apache-2.0; model/LICENSE-Apache-2.0.txt reproduces the software wheel license text.\n'
            'Pinned model source, revision and SHA256: model/manifest.json.\n'
            'PyTorch CPU, Transformers, NumPy, SoundFile, librosa, nagisa and other wheel licenses are retained in licenses/ and _internal/.\n'
            'Qwen source files are unchanged. SliceAI supplies the separate alignment_worker adapter.\n'
            'This worker loads only bundled local weights. Runtime downloads are disabled.\n',
            encoding='utf-8', newline='\n')
        write_bundle_manifest(stage, catalog, versions)
        verify_bundle(stage, catalog)
        destination.parent.mkdir(parents=True, exist_ok=True)
        backup = root / 'build' / ('alignment-previous-' + uuid.uuid4().hex[:8])
        if destination.exists():
            destination.rename(backup)
        try:
            stage.rename(destination)
        except OSError:
            if backup.exists() and not destination.exists():
                backup.rename(destination)
            raise
    return verify_bundle(destination, catalog)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true', help='Show paths and command; do not read weights or write files.')
    mode.add_argument('--verify-only', action='store_true', help='Validate an existing frozen worker without building or staging it.')
    mode.add_argument('--stage-only', action='store_true', help='Stage an already-built worker after validating the isolated environment.')
    args = parser.parse_args(argv)
    try:
        if args.dry_run:
            result = {'environment': str(ROOT / '.alignment-venv'), 'model': str(ROOT / 'alignment-model/Qwen3-ForcedAligner-0.6B'),
                      'destination': str(ROOT / 'src-tauri/resources/worker/alignment'),
                      'command': pyinstaller_args(executable=ROOT / '.alignment-venv/Scripts/python.exe'),
                      'downloads': False, 'verified': False, 'dry_run': True}
        elif args.verify_only:
            result = verify_bundle(ROOT / 'src-tauri/resources/worker/alignment')
        else:
            versions = runtime_versions()
            catalog = read_json(CATALOG_FILE)
            verify(catalog, ROOT / catalog['destination'])
            if not args.stage_only:
                command = pyinstaller_args()
                command[-1:-1] = source_data_args()
                subprocess.run(command, cwd=ROOT, check=True)
            result = stage_worker(ROOT, catalog, versions)
    except (OSError, ValueError, metadata.PackageNotFoundError, subprocess.CalledProcessError) as exc:
        parser.exit(1, str(exc) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
