"""Optional offline forced alignment. CTC anchors never masquerade as spans."""
from __future__ import annotations
import copy
import hashlib
import json
import math
import re
import sys
import unicodedata
from pathlib import Path
from engine import Cancelled, check_cancel, command, resource_dir, tool_path
from word_timeline import ALIGNMENT_PADDING

ENGINE = 'qwen3-forced-aligner-cpu-v1'
REVISION = 'c7cbfc2048c462b0d63a45797104fc9db3ad62b7'
MAX_WINDOW = 32


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', text)
                   if not c.isspace() and not unicodedata.category(c).startswith('P'))


def locations():
    if getattr(sys, 'frozen', False):
        folder = resource_dir() / 'alignment'
        return [str(folder / 'sliceai-alignment.exe')], folder / 'model'
    root = Path(__file__).resolve().parents[1]
    python = root / '.alignment-venv' / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
    return [str(python), str(root / 'backend/alignment_worker.py')], root / 'alignment-model/Qwen3-ForcedAligner-0.6B'


def model_identity(model):
    model = Path(model).resolve()
    raw = (model / 'manifest.json').read_bytes()
    manifest = json.loads(raw.decode('utf-8', errors='strict'))
    if manifest.get('engine') != ENGINE or manifest.get('revision') != REVISION:
        raise ValueError('精对齐模型不是固定的已验证版本。')
    files = manifest.get('files')
    if not isinstance(files, dict) or 'model.safetensors' not in files:
        raise ValueError('精对齐模型清单不完整。')
    stats = []
    for name, info in files.items():
        path = (model / name).resolve()
        if path.parent != model or not path.is_file() or path.stat().st_size != info['bytes']:
            raise ValueError('精对齐模型文件缺失或大小不符。')
        stat = path.stat()
        stats.append([name, stat.st_size, stat.st_mtime_ns])
    return {'engine': ENGINE, 'revision': REVISION,
            'manifest': hashlib.sha256(raw).hexdigest(), 'files': stats,
            'inference': 'cpu-bfloat16-pread-v2', 'safetensors': '0.8.0'}


def ready():
    prefix, model = locations()
    try:
        model_identity(model)
        return Path(prefix[0]).is_file()
    except (OSError, ValueError, KeyError, TypeError):
        return False


def checked_words(row, raw, start, end):
    """Require complete original text and sane model spans, never interpolate."""
    if not isinstance(raw, list) or not raw or len(raw) > 1500:
        raise ValueError('对齐器未返回完整字词时间。')
    words = []
    previous = start
    cursor = 0
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError('对齐字词结构无效。')
        text = item.get('text'); a = item.get('start'); b = item.get('end')
        if (not isinstance(text, str) or not normalized(text)
                or type(a) not in (int, float) or type(b) not in (int, float)
                or not math.isfinite(a + b) or a < start - .001 or b > end + .001
                or b <= a or a < previous - .001):
            raise ValueError('对齐字词边界异常，保留原文。')
        word = {'id': f'{row["id"]}:{i}', 'text': text, 'start': round(a, 6),
                'end': round(b, 6), 'timing_method': 'forced_alignment'}
        # Literal offsets are optional. Punctuation normalization must never
        # imply that a changed display subtitle shares an acoustic boundary.
        position = row['text'].find(text, cursor)
        if position >= 0:
            word.update(char_start=position, char_end=position + len(text))
            cursor = position + len(text)
        words.append(word)
        previous = b
    if normalized(''.join(word['text'] for word in words)) != normalized(row['text']):
        raise ValueError('对齐文字未完整覆盖原转写，保留原文。')
    return words


def source_identity(editor, audio=None):
    source = Path(audio['path'] if audio else editor.task['video']).resolve()
    stat = source.stat()
    return source, {'path': str(source), 'bytes': stat.st_size, 'mtime': stat.st_mtime_ns,
                    'audio_track': 0 if audio else editor.task.get('audio_track', 0),
                    'audio_identity': audio.get('identity') if audio else None}


def local_windows(row):
    """Use exact text/CTC correspondence to select audio, never to cut it.

    A small forced-alignment window can resolve a repeated character that the
    full-window model assigned zero duration. Its context characters remain
    separate from the candidate and have no authority to delete surrounding
    sounds. Numeric ITN or unknown characters break the mapping safely.
    """
    plain = normalized(row['text']); positions = []; anchors = []; emitted = ''
    previous = row['start']-.001
    for index, char in enumerate(row['text']):
        positions.extend([index] * len(normalized(char)))
    for token in row.get('tokens', []):
        text = normalized(token.get('text', ''))
        anchor = token.get('anchor')
        if (type(anchor) not in (int, float) or not math.isfinite(anchor)
                or anchor < previous-.001 or anchor > row['end']+.001):
            return []
        previous = anchor
        emitted += text; anchors.extend([float(anchor)] * len(text))
    if not plain or plain != emitted or len(positions) != len(anchors):
        return []
    windows = []; seen = set()
    matches = list(re.finditer(r'(.{1,4})\1', plain)) + list(re.finditer(r'[嗯呃额唔]', plain))
    for match in matches:
        left = max(0, match.start()-1); right = min(len(plain), match.end()+1)
        a = positions[left]; b = positions[right-1]+1
        if (a,b) in seen:
            continue
        seen.add((a,b))
        start = max(row['start'], anchors[left]-.08)
        end = min(row['end'], anchors[right-1]+.7)
        if not .15 <= end-start <= 8 or anchors[left] > anchors[right-1]:
            continue
        windows.append({'id': f'{row["id"]}:local:{a}:{b}', 'text': row['text'][a:b],
                        'char_start': a, 'char_end': b, 'start': start, 'end': end,
                        'window_selection': 'exact_text_ctc_context',
                        'words': [], 'alignment_complete': False,
                        'alignment': {'status': 'pending', 'method': 'forced_alignment', 'engine': ENGINE}})
        if len(windows) >= 12:
            break
    return windows


def prepare(editor, rows, row_ids=None, audio=None):
    """Align selected short VAD windows in one independently cancellable worker.

    Returned coordinates are on the original video clock. Missing assets, bad
    text or failed spans explicitly leave words empty, never approximate ends.
    """
    result = copy.deepcopy(rows)
    chosen = set(row_ids) if row_ids is not None else {r['id'] for r in result}
    selected = [r for r in result if r['id'] in chosen]
    for row in selected:
        row.update(words=[], alignment_complete=False,
                   word_windows=[],
                   alignment={'status': 'pending', 'method': 'forced_alignment', 'engine': ENGINE})
    if not selected:
        return result
    prefix, model = locations()
    try:
        model_key = model_identity(model)
        if not Path(prefix[0]).is_file():
            raise ValueError('未安装独立精对齐运行组件。')
    except (OSError, ValueError, KeyError, TypeError):
        for row in selected:
            row['alignment'].update(status='unavailable', warning='精对齐组件未准备，句内删除保持待确认。')
        return result
    source, source_key = source_identity(editor, audio)
    origin = float(audio.get('identity', {}).get('start', editor.clip['start'])) if audio else 0
    folder = (editor.folder / 'alignment-cache').resolve()
    if not folder.is_relative_to(editor.folder.resolve()):
        raise ValueError('精对齐缓存目录无效。')
    folder.mkdir(parents=True, exist_ok=True)
    jobs = []; wavs = []; targets = {}
    try:
        from media_audio import aligned_audio_args
        def queue_window(row, a, b, local=False):
            identity = {'schema': 2, 'source': source_key, 'model': model_key,
                        'start': a, 'end': b, 'text': row['text'], 'language': 'Chinese',
                        'local_context': local}
            key = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()
            path = folder / (key + '.json')
            if path.is_file():
                try:
                    cached = json.loads(path.read_text(encoding='utf-8', errors='strict'))
                    if cached.get('identity') != identity:
                        raise ValueError('cache identity')
                    row['words'] = checked_words(row, cached['words'], a, b)
                    row.update(alignment_complete=True)
                    row['alignment'].update(status='complete', cached=True, window_start=a, window_end=b)
                    return True
                except (OSError, ValueError, KeyError, TypeError):
                    pass
            wav = folder / (key + '.partial.wav'); wavs.append(wav)
            args = aligned_audio_args(tool_path(editor.settings, 'ffmpeg'), source, wav,
                                      track=source_key['audio_track'], start=a-origin,
                                      duration=b-a, rate=16000, pcm='pcm_s16le',
                                      ffprobe=tool_path(editor.settings, 'ffprobe'))
            command(args, editor.store, editor.p['id'], timeout=90)
            job_id = str(len(jobs)); targets[job_id] = (row, path, identity, a, b)
            jobs.append({'id': job_id, 'wav': str(wav), 'start': a, 'end': b,
                         'text': row['text'], 'language': 'Chinese'})
            return False
        for row in selected:
            check_cancel(editor.store, editor.p['id'])
            a = max(editor.clip['start'], row['start'] - ALIGNMENT_PADDING)
            b = min(editor.clip['end'], row['end'] + ALIGNMENT_PADDING)
            if b <= a or b - a > MAX_WINDOW or not normalized(row.get('text', '')):
                row['alignment'].update(status='unsupported', warning='此转写窗口无法安全进行局部精对齐。')
                continue
            if queue_window(row, a, b):
                continue
            row['word_windows'] = local_windows(row)
            for window in row['word_windows']:
                queue_window(window, window['start'], window['end'], local=True)
        if not jobs:
            return result
        request = folder / 'requests.partial.jsonl'
        request.write_text(''.join(json.dumps(job, ensure_ascii=False) + '\n' for job in jobs),
                           encoding='utf-8', newline='\n')
        def report(line):
            try:
                event = json.loads(line)
            except ValueError:
                return
            if event.get('event') == 'ready':
                editor.persist(f'局部字词精对齐 · 0/{len(jobs)}')
            if event.get('event') != 'alignment' or event.get('id') not in targets:
                return
            row, path, identity, a, b = targets[event['id']]
            try:
                if event.get('error'):
                    raise ValueError(str(event['error'])[:160])
                row['words'] = checked_words(row, event['words'], a, b)
                row.update(alignment_complete=True)
                row['alignment'].update(status='complete', cached=False, window_start=a, window_end=b)
                temp = path.with_suffix('.partial')
                try:
                    temp.write_text(json.dumps({'identity': identity, 'words': row['words']}, ensure_ascii=False), encoding='utf-8')
                    temp.replace(path)
                finally:
                    temp.unlink(missing_ok=True)
            except (ValueError, KeyError, TypeError) as exc:
                row.update(words=[], alignment_complete=False)
                row['alignment'].update(status='invalid', warning='字词对齐不完整或边界异常，保留对应内容。',
                                        detail=str(exc)[:160])
            done = sum(target[0]['alignment']['status'] != 'pending' for target in targets.values())
            editor.persist(f'局部字词精对齐 · {done}/{len(jobs)}')
        try:
            command(prefix + ['--model', str(model), '--requests', str(request), '--threads',
                              str(max(1, min(4, int(editor.settings.get('asr_threads', 2)))))],
                    editor.store, editor.p['id'], on_line=report, timeout=max(300, len(jobs)*120))
        except Cancelled:
            raise
        except ValueError as exc:
            memory_shortage = any(marker in str(exc) for marker in ('1450', '1455', 'MemoryError', 'bad allocation'))
            for row in [target[0] for target in targets.values()]:
                if row['alignment']['status'] == 'pending':
                    warning = ('当前可用内存不足，句内删除保持待确认，可稍后重试。' if memory_shortage
                               else '独立精对齐运行失败，句内删除保持待确认。')
                    row['alignment'].update(status='failed', warning=warning)
        finally:
            request.unlink(missing_ok=True)
        for row in [target[0] for target in targets.values()]:
            if row['alignment']['status'] == 'pending':
                row['alignment'].update(status='failed', warning='对齐器未返回此窗口，句内删除保持待确认。')
        return result
    finally:
        for wav in wavs:
            wav.unlink(missing_ok=True)
