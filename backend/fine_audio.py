"""Event-scoped audio preparation, reused by analysis and every render version."""
import hashlib
import json
import math
from pathlib import Path

from audio_identity import ENGINE_ID
from audio_cache import canonical, checked_folder, ensure_space, record_cache
from audio_processing import model_identity, process_audio, source_identity
from engine import check_cancel, command, tool_path


def audio_duration(editor, path):
    raw = command([tool_path(editor.settings, 'ffprobe'), '-v', 'error', '-select_streams', 'a:0',
                   '-show_entries', 'stream=codec_type:format=duration', '-of', 'json', str(path)],
                  editor.store, editor.p['id'], timeout=45)
    info = json.loads(raw)
    duration = float(info.get('format', {}).get('duration', 0))
    if not info.get('streams') or not math.isfinite(duration) or duration <= 0:
        raise ValueError('无法确定处理后音频时长。')
    return duration


def identity(editor, strength):
    return {**source_identity(editor, editor.task['video'], editor.clip['start'],
                              editor.clip['end']-editor.clip['start']),
            'engine': ENGINE_ID, 'model_revision': model_identity(), 'strength': float(strength)}


def prepare(editor, strength=1):
    """The model sees a continuous event, never already-spliced audio."""
    fingerprint = identity(editor, strength)
    key = hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode()).hexdigest()[:24]
    # Strength is a cheap mix of the same immutable stem; keep all strengths
    # together so input extraction and model inference run once per event.
    base = {k:v for k,v in fingerprint.items() if k not in ('strength','engine','model_revision')}
    source_key = hashlib.sha256(json.dumps(base, sort_keys=True).encode()).hexdigest()[:24]
    folder = editor.folder / 'event-audio' / source_key
    folder = checked_folder(editor,folder)
    folder.mkdir(parents=True, exist_ok=True)
    manifest = folder / f'ready-{key}.json'
    check_cancel(editor.store, editor.p['id'])
    if manifest.is_file():
        record = json.loads(manifest.read_text(encoding='utf-8'))
        path = Path(record['path'])
        if record['identity'] == fingerprint and path.is_file():
            stat = path.stat()
            if stat.st_size == record['size'] and stat.st_mtime_ns == record['mtime']:
                cache_identity={k:v for k,v in fingerprint.items() if k!='strength'}
                stem_key=hashlib.sha256(canonical(cache_identity).encode('utf-8')).hexdigest()[:20]
                record_cache(folder,stem_key,cache_identity,[path])
                ensure_space(editor,folder,record['duration'],current_identity=cache_identity,allocate_bytes=0)
                step = next((s for s in editor.p.get('execution', {}).get('steps', [])
                             if s['id'] == 'audio'), None)
                # During auto render this step already finished before ASR.
                if step and step['state'] == 'pending':
                    editor.persist('降低背景音乐 · 复用已处理音频')
                return record
    editor.persist('降低背景音乐 · 处理完整事件音频')
    path = process_audio(editor, editor.task['video'], folder, strength,
                         editor.clip['start'], editor.clip['end'] - editor.clip['start'])
    duration = audio_duration(editor, path)
    if abs(duration - (editor.clip['end'] - editor.clip['start'])) > .1:
        raise ValueError('处理后音频时长不匹配，未用于剪辑。')
    stat = path.stat()
    record = {'identity': fingerprint, 'path': str(path), 'size': stat.st_size,
              'mtime': stat.st_mtime_ns, 'duration': duration}
    temp = manifest.with_suffix('.partial')
    temp.write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
    temp.replace(manifest)
    return record


def cut(editor, record, ranges, folder):
    """Apply the exact video edit list to prepared audio, in playback order."""
    check_cancel(editor.store, editor.p['id'])
    folder = checked_folder(editor,folder)
    ensure_space(editor, folder, sum(r['end']-r['start'] for r in ranges),
                 raw_ready=True, stem_ready=True,
                 current_identity={k:v for k,v in record['identity'].items() if k!='strength'})
    # A script keeps long edit lists out of Windows' command-line length limit.
    filters = []
    offset = record['identity']['start']
    for i, interval in enumerate(ranges):
        a, b = interval['start'] - offset, interval['end'] - offset
        if a < -.001 or b > record['duration'] + .1 or b <= a:
            raise ValueError('音频剪辑区间超出已处理片段。')
        filters.append(f'[0:a]atrim=start={max(0,a):.6f}:end={b:.6f},asetpts=PTS-STARTPTS[a{i}]')
    filters.append(''.join(f'[a{i}]' for i in range(len(ranges))) +
                   f'concat=n={len(ranges)}:v=0:a=1[out]')
    script = folder / 'audio-ranges.txt'
    script.write_text(';\n'.join(filters), encoding='utf-8')
    target = folder / 'edited-audio.wav'
    temp = folder / 'edited-audio.partial.wav'
    try:
        command([tool_path(editor.settings, 'ffmpeg'), '-v', 'error', '-nostdin', '-y',
                 '-i', record['path'], '-filter_complex_script', str(script), '-map', '[out]',
                 '-ar', '48000', '-ac', '1', '-c:a', 'pcm_f32le', '-rf64', 'auto', str(temp)],
                editor.store, editor.p['id'])
        expected = sum(r['end'] - r['start'] for r in ranges)
        if abs(audio_duration(editor, temp) - expected) > .1:
            raise ValueError('剪辑后音频时长不匹配，未生成成片。')
        temp.replace(target)
    finally:
        temp.unlink(missing_ok=True)
    return target
