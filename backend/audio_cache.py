"""Bound audio intermediates without deleting source, previews or saved assets."""
from __future__ import annotations
import json
import math
import shutil
import time
import uuid
from pathlib import Path

CACHE_LIMIT_BYTES = 16 * 1024 ** 3
SPACE_RESERVE_BYTES = 256 * 1024 ** 2


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def estimate_bytes(seconds, *, raw_ready=False, stem_ready=False):
    seconds = float(seconds)
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError('无法估算声音处理空间，请检查片段时长。')
    # Float32 mono: 48 kHz raw; 44.1 kHz model input/output; 48 kHz
    # resampling result and immutable speech cache. Model scratch is removed
    # before mixing, so a strength-only update allocates just one 48 kHz WAV.
    peak_per_second = 48000 * 4 if not raw_ready else 0
    peak_per_second += 48000 * 4 if stem_ready else (44100 * 4 * 2 + 48000 * 4 * 2)
    return math.ceil(seconds * peak_per_second * 1.08) + 5 * 4096


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _identities(value):
    if isinstance(value, dict):
        if {'source', 'size', 'mtime', 'start', 'end', 'engine'}.issubset(value):
            yield canonical({k: v for k, v in value.items() if k != 'strength'})
        for item in value.values():
            yield from _identities(item)
    elif isinstance(value, list):
        for item in value:
            yield from _identities(item)


def _linked(path):
    from path_safety import is_link
    path=Path(path)
    return is_link(path)


def _has_link(path, boundary=None):
    """Inspect the lexical path before resolve can hide Windows junctions."""
    path=Path(path).absolute()
    boundary=Path(boundary).absolute() if boundary is not None else path
    try:
        relative=path.relative_to(boundary)
    except ValueError:
        return True
    current=boundary
    if _linked(current):return True
    for component in relative.parts:
        current=current/component
        if _linked(current):return True
    return False


def _safe_file(path, root):
    path = Path(path)
    root = Path(root)
    if _has_link(root) or _has_link(path,root):
        return None
    root = root.resolve()
    # Never follow a cache-manifest path outside its owned tree, or a link.
    try:
        relative = path.resolve().relative_to(root)
    except (OSError, ValueError):
        return None
    if not relative.parts:
        return None
    if path.suffix != '.wav' or not path.name.startswith(('original-', 'speech-', 'processed-')):
        return None
    return path.resolve()


def record_cache(folder, key, identity, files):
    folder = Path(folder)
    if _has_link(folder):raise ValueError('声音缓存目录包含链接，未写入缓存。')
    folder = folder.resolve()
    manifest = folder / f'cache-{key}.json'
    previous = []
    if manifest.is_file():
        try:
            previous = json.loads(manifest.read_text(encoding='utf-8')).get('files', [])
        except (OSError, ValueError, TypeError):
            pass
    paths = {str(p) for value in [*previous, *(str(Path(p).resolve()) for p in files)]
             if (p := _safe_file(value, folder)) and p.is_file()}
    record = {'identity': identity, 'files': sorted(paths), 'used': time.time()}
    temporary = manifest.with_suffix('.partial.json')
    temporary.write_text(canonical(record), encoding='utf-8')
    temporary.replace(manifest)


def checked_folder(editor, folder):
    folder=Path(folder).absolute()
    raw_owner=Path(getattr(editor,'folder',folder)).absolute()
    boundary=raw_owner if folder.is_relative_to(raw_owner) else folder
    store_root=getattr(getattr(editor,'store',None),'root',None)
    if store_root and folder.is_relative_to(Path(store_root).absolute()):
        boundary=Path(store_root).absolute()
    if _has_link(folder,boundary):
        raise ValueError('声音缓存目录包含链接，未清理或创建音频。请更改数据目录后重试。')
    return folder.resolve()


def ensure_space(editor, folder, seconds, *, raw_ready=False, stem_ready=False,
                 current_identity=None, limit_bytes=CACHE_LIMIT_BYTES, allocate_bytes=None):
    """Evict only unreferenced generated cache files, then check peak free space."""
    folder = checked_folder(editor,folder)
    store_root=getattr(getattr(editor,'store',None),'root',None)
    folder.mkdir(parents=True, exist_ok=True)
    owner = Path(getattr(editor, 'folder', folder)).resolve()
    try:
        folder.relative_to(owner)
    except ValueError:
        owner = folder
    roots = [owner / 'event-audio', owner / 'audio-samples'] if owner != folder else [folder]
    if not any(folder.is_relative_to(root.resolve()) for root in roots):
        roots.append(folder)
    db = getattr(getattr(editor, 'store', None), 'db', None)
    def payloads():
        yield editor.p
        if db:
            # A persisted reference can be newer than an in-memory operation.
            # Stream records rather than retaining every project's subtitle history.
            for table in ('tasks', 'edits'):
                exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
                if exists:
                    for row in db.execute(f'SELECT payload FROM {table}'):
                        yield json.loads(row[0])
    protected = set()
    identities = set()
    manual_bindings = {}
    for payload in payloads():
        for value in _strings(payload):
            try:
                if Path(value).is_absolute():
                    protected.add(str(Path(value).resolve()))
            except (OSError, ValueError):
                pass
        identities.update(_identities(payload))
        bound_owner = owner if payload is editor.p else None
        if db and payload.get('id'):
            try:
                uuid.UUID(payload['id'])
                tasks_root = editor.store.root/'tasks'
                candidate = editor.store.root/'tasks'/payload['id']
                if not _has_link(candidate,editor.store.root) and candidate.resolve().is_relative_to(tasks_root.resolve()):
                    bound_owner = candidate.resolve()
                    # The budget covers managed audio from all persisted projects.
                    roots.extend((bound_owner/'event-audio',bound_owner/'audio-samples'))
            except (ValueError, TypeError):
                pass
        if bound_owner:
            bindings = manual_bindings.setdefault(str(bound_owner), set())
            for version in payload.get('versions', []):
                if version.get('audio_strength', 0) and version.get('audio_engine'):
                    bindings.add((payload.get('source_start'),payload.get('source_end'),version['audio_engine']))
    if current_identity:
        identities.add(canonical(current_identity))
    entries = []
    all_files = {}
    seen = set()
    for root in roots:
        if not root.exists() or _has_link(root,store_root if store_root and root.is_relative_to(store_root) else root):
            continue
        for manifest in root.rglob('cache-*.json'):
            if manifest in seen or _has_link(manifest,root) or not manifest.resolve().is_relative_to(root.resolve()):
                continue
            seen.add(manifest)
            try:
                value = json.loads(manifest.read_text(encoding='utf-8'))
                files = [p for item in value['files'] if (p := _safe_file(item, root)) and p.is_file()]
                bound = canonical(value['identity']) in identities
                # A manual version binds the current event even without analysis_audio.
                identity = value['identity']
                binding=(identity.get('start'),identity.get('end'),identity.get('engine'))
                if binding in manual_bindings.get(str(root.parent.resolve()),set()):
                    bound=True
                locked = bound or any(str(p) in protected for p in files)
                if locked:
                    protected.update(str(p) for p in files)
                entries.append((float(value.get('used', 0)), manifest, files, locked))
                for path in files:
                    all_files[str(path)] = path.stat().st_size
            except (OSError, ValueError, KeyError, TypeError):
                continue
    total = sum(all_files.values())
    needed = estimate_bytes(seconds, raw_ready=raw_ready, stem_ready=stem_ready) if allocate_bytes is None else max(0, int(allocate_bytes))
    reserve = SPACE_RESERVE_BYTES if needed else 0
    free = shutil.disk_usage(folder).free
    removed = 0
    for _, manifest, files, locked in sorted(entries, key=lambda e: e[0]):
        if total + needed <= limit_bytes and free >= needed + reserve:
            break
        if locked or any(str(p) in protected for p in files):
            continue
        # No recursive removals. Only this manifest's validated WAV assets.
        failed=False
        for path in files:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                failed=True
                continue
            size = all_files.pop(str(path), 0)
            removed += size
            total -= size
        if not failed:
            manifest.unlink(missing_ok=True)
        free = shutil.disk_usage(folder).free
    editor.p['audio_storage'] = {'seconds': seconds, 'estimated_additional_bytes': needed,
                               'free_bytes': free, 'cache_bytes': max(0, total),
                               'cache_limit_bytes': limit_bytes, 'removed_bytes': removed}
    if free < needed + reserve:
        gb = 1024 ** 3
        raise ValueError(f'声音处理空间不足：预计另需 {needed/gb:.2f} GB，当前可用 {free/gb:.2f} GB；'
                         '请释放空间或缩短事件后重试。已保存成片与被引用音频均保留。')
    return editor.p['audio_storage']
