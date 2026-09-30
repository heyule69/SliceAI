"""Event-scoped audio preparation, reused by analysis and every render version."""
import hashlib
import json
import math
from pathlib import Path

from audio_identity import ENGINE_ID
from audio_processing import process_audio
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
    source = Path(editor.task['video']).resolve()
    stat = source.stat()
    return {'source': str(source), 'size': stat.st_size, 'mtime': stat.st_mtime_ns,
            'start': editor.clip['start'], 'end': editor.clip['end'],
            'engine': ENGINE_ID, 'strength': strength}


def prepare(editor, strength=1):
    """The model sees a continuous event, never already-spliced audio."""
    fingerprint = identity(editor, strength)
    key = hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode()).hexdigest()[:24]
    folder = editor.folder / 'event-audio' / key
    folder.mkdir(parents=True, exist_ok=True)
    manifest = folder / 'ready.json'
    check_cancel(editor.store, editor.p['id'])
    if manifest.is_file():
        record = json.loads(manifest.read_text(encoding='utf-8'))
        path = Path(record['path'])
        if record['identity'] == fingerprint and path.is_file():
            stat = path.stat()
            if stat.st_size == record['size'] and stat.st_mtime_ns == record['mtime']:
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
                 '-ar', '48000', '-ac', '1', '-c:a', 'pcm_f32le', str(temp)],
                editor.store, editor.p['id'])
        expected = sum(r['end'] - r['start'] for r in ranges)
        if abs(audio_duration(editor, temp) - expected) > .1:
            raise ValueError('剪辑后音频时长不匹配，未生成成片。')
        temp.replace(target)
    finally:
        temp.unlink(missing_ok=True)
    return target
