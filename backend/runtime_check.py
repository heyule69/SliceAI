"""Name the missing dev environment or frozen worker before a subprocess starts."""
from __future__ import annotations
import sys
from pathlib import Path


def venv_python(root, name):
    root = Path(root)
    if sys.platform == 'win32':
        return root / name / 'Scripts' / 'python.exe'
    return root / name / 'bin' / 'python'


def repo_root():
    return Path(__file__).resolve().parents[1]


def component_gap(prefix, model, title):
    """Return a user-facing sentence, or '' when the executable and manifest exist."""
    missing = []
    prefix = list(prefix or [])
    if not prefix or not Path(prefix[0]).is_file():
        missing.append(str(prefix[0]) if prefix else f'{title}工作进程')
    if len(prefix) > 1 and not Path(prefix[1]).is_file():
        missing.append(str(prefix[1]))
    if model is not None:
        manifest = Path(model) / 'manifest.json'
        if not manifest.is_file():
            missing.append(str(manifest))
    if not missing:
        return ''
    shown = '、'.join(missing[:4])
    extra = f' 等 {len(missing)} 个路径' if len(missing) > 4 else ''
    return f'缺少{title}环境：未找到 {shown}{extra}。'


def audio_locations(root=None):
    if getattr(sys, 'frozen', False):
        from engine import resource_dir
        folder = resource_dir() / 'audio'
        return [str(folder / 'sliceai-audio.exe')], folder / 'model'
    root = Path(root) if root else repo_root()
    return [str(venv_python(root, '.audio-venv')), str(root / 'backend' / 'audio_worker.py')], root / 'audio-model' / 'BandItPlus'


def alignment_locations(root=None):
    if getattr(sys, 'frozen', False):
        from engine import resource_dir
        folder = resource_dir() / 'alignment'
        return [str(folder / 'sliceai-alignment.exe')], folder / 'model'
    root = Path(root) if root else repo_root()
    python = venv_python(root, '.alignment-venv')
    return [str(python), str(root / 'backend' / 'alignment_worker.py')], root / 'alignment-model' / 'Qwen3-ForcedAligner-0.6B'
