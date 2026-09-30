"""Stage a complete test client without creating or replacing an installer."""
from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('package_release', Path(__file__).with_name('package-release.py'))
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def within(root, path):
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f'Test client path escapes the workspace: {path}')


def stage(root=ROOT):
    root = Path(root).resolve()
    executable = root / 'src-tauri/target/release/sliceai.exe'
    source = root / 'src-tauri/resources/worker'
    target = executable.parent / 'worker'
    temporary_parent = root / 'build/portable-staging'
    backup = root / 'build' / ('portable-worker-previous-' + uuid.uuid4().hex[:8])
    for path in (executable, source, target, temporary_parent, backup):
        within(root, path)
    release.required_file(executable)
    components = release.verify_workers(source, require_alignment=True)
    if not all(components.values()):
        raise ValueError('Build the ASR, audio and alignment workers before staging a complete test client.')
    temporary_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='worker-', dir=temporary_parent) as temporary:
        copied = Path(temporary) / 'worker'
        within(root, copied)
        shutil.copytree(source, copied)
        release.verify_workers(copied, require_alignment=True)
        # Replace the entire worker tree so removed runtime files cannot linger.
        # Preserve the previous tree; an in-use file fails without killing the app.
        for path in (copied, target, backup):
            within(root, path)
        if target.exists():
            target.rename(backup)
        try:
            copied.rename(target)
        except OSError:
            if backup.exists() and not target.exists():
                backup.rename(target)
            raise
    return {'test_client': str(executable), 'worker': str(target), 'components': components,
            'installer_changed': False, 'previous_worker': str(backup) if backup.exists() else None}


def main():
    try:
        print(json.dumps(stage(), ensure_ascii=False, indent=2))
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == '__main__':
    main()
