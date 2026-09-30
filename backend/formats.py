from __future__ import annotations
import json
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

def read_utf8(path: Path, max_bytes=32 * 1024 * 1024):
    if path.stat().st_size > max_bytes:
        raise ValueError(f'{path.name} 超过 {max_bytes // 1024 // 1024} MB，无法直接导入。')
    try:
        return path.read_text(encoding='utf-8', errors='strict').lstrip('\ufeff')
    except UnicodeDecodeError as exc:
        raise ValueError(f'{path.name} 不是 UTF-8 编码，请先确认并转换为 UTF-8；程序未修改原文件。') from exc

def timestamp(text):
    fields = text.replace(',', '.').split(':')
    if len(fields) == 2:
        fields.insert(0, '0')
    if len(fields) != 3:
        raise ValueError('字幕时间戳格式错误。')
    h, m, s = map(float, fields)
    if not all(math.isfinite(x) and x >= 0 for x in (h, m, s)) or m >= 60 or s >= 60:
        raise ValueError('字幕时间戳超出范围。')
    return h * 3600 + m * 60 + s

def parse_subtitles(path: Path, duration: float):
    content = read_utf8(path).replace('\r\n', '\n').replace('\r', '\n')
    result = []
    pattern = re.compile(r'(?m)^\s*((?:\d+:)?\d{2}:\d{2}[.,]\d{1,3})\s*-->\s*((?:\d+:)?\d{2}:\d{2}[.,]\d{1,3})[^\n]*\n((?:(?!\n\s*\n).)*(?:\n(?!\s*\n).*)*)')
    # Blank-line-delimited cues cover SRT and WebVTT, including cue identifiers.
    for block in re.split(r'\n\s*\n', content):
        lines = block.strip().splitlines()
        for index, line in enumerate(lines):
            match = re.match(r'\s*((?:\d+:)?\d{2}:\d{2}[.,]\d{1,3})\s*-->\s*((?:\d+:)?\d{2}:\d{2}[.,]\d{1,3})', line)
            if not match:
                continue
            start, end = timestamp(match[1]), timestamp(match[2])
            text = re.sub(r'<[^>]+>', '', ' '.join(lines[index + 1:])).strip()
            if start > duration + 2:
                raise ValueError('字幕时间超出了视频时长，请确认字幕与录播属于同一个文件。')
            if text and end > start and start < duration:
                result.append({'start': start, 'end': min(end, duration), 'text': text[:3000]})
            break
    if not result:
        raise ValueError('字幕中没有可用的带时间戳文本。支持 UTF-8 SRT / VTT。')
    result.sort(key=lambda x: (x['start'], x['end']))
    for i, row in enumerate(result):
        row['id'] = i
    return result

def parse_chat(path: Path | None, duration: float, offset=0.0):
    if not path:
        return []
    result = []
    def append(t, text):
        try:
            sec = float(t) + offset
        except (ValueError, TypeError):
            return
        if math.isfinite(sec) and 0 <= sec <= duration and str(text).strip():
            result.append({'time': sec, 'text': str(text).strip()[:160]})
    if path.suffix.lower() == '.xml':
        # Validate encoding incrementally, without loading the XML or recording into RAM.
        try:
            with path.open(encoding='utf-8', errors='strict') as stream:
                while stream.read(65536):
                    pass
        except UnicodeDecodeError as exc:
            raise ValueError('弹幕 XML 不是 UTF-8 编码；请确认后转换，程序未修改原文件。') from exc
        with path.open('rb') as stream:
            for _, element in ET.iterparse(stream, events=('end',)):
                if element.tag == 'd':
                    append(element.attrib.get('p', '').split(',')[0], element.text or '')
                    if len(result) >= 300000:
                        raise ValueError('弹幕超过 30 万条，请先拆分录播，避免过高内存占用。')
                element.clear()
    elif path.suffix.lower() == '.json':
        raw = json.loads(read_utf8(path))
        rows = raw if isinstance(raw, list) else raw.get('danmaku', raw.get('comments', []))
        if not isinstance(rows, list):
            raise ValueError('弹幕 JSON 应为数组，或含 danmaku / comments 数组。')
        for row in rows:
            if isinstance(row, dict):
                t = row.get('time', row.get('start', row.get('offset', None)))
                if t is None and 'progress' in row:
                    t = float(row['progress']) / 1000
                append(t, row.get('text', row.get('content', '')))
    else:
        raise ValueError('弹幕仅支持 XML / JSON。')
    if not result:
        raise ValueError('弹幕中没有与视频时间匹配的数据。JSON 需使用相对视频的秒数 time，或毫秒 progress。')
    return sorted(result, key=lambda row: row['time'])

def chat_context(chat, start, end, limit=70):
    import bisect
    left = bisect.bisect_left(chat, start, key=lambda c: c['time'])
    right = bisect.bisect_right(chat, end + 8, key=lambda c: c['time'])
    buckets, unique = {}, {}
    for item in chat[left:right]:
        bin_id = int(item['time'] // 15)
        buckets[bin_id] = buckets.get(bin_id, 0) + 1
        key = (bin_id, item['text'])
        if key not in unique:
            unique[key] = {'time': round(item['time'], 1), 'text': item['text'], 'repeats': 1}
        else:
            unique[key]['repeats'] += 1
    candidates = list(unique.values())
    # Preserve a chronological, evenly distributed sample and the most repeated reactions.
    frequent = sorted(candidates, key=lambda c: c['repeats'], reverse=True)[:limit // 3]
    step = max(1, len(candidates) // max(1, limit - len(frequent)))
    samples = {(c['time'], c['text']): c for c in frequent + candidates[::step][:limit - len(frequent)]}
    return {'activity_15s': [{'time': b*15, 'count': count} for b,count in sorted(buckets.items())],
            'samples': sorted(samples.values(), key=lambda c: c['time'])}

def transcript_windows(sentences, max_chars=10500, max_seconds=480, overlap_seconds=45):
    windows, start = [], 0
    while start < len(sentences):
        end, chars = start, 0
        while end < len(sentences):
            row = sentences[end]
            size = len(row['text']) + 50
            if end > start and (chars + size > max_chars or row['end'] - sentences[start]['start'] > max_seconds):
                break
            chars += size
            end += 1
        windows.append(sentences[start:end])
        if end == len(sentences):
            break
        next_start = end
        while next_start > start + 1 and sentences[end-1]['end'] - sentences[next_start-1]['start'] < overlap_seconds:
            next_start -= 1
        start = max(start + 1, next_start)
    return windows

def validate_candidates(raw, context, duration, minimum, maximum):
    by_id = {s['id']: s for s in context}
    accepted = []
    if not isinstance(raw, list):
        raise ValueError('API 返回的 clips 不是数组。')
    for item in raw:
        if not isinstance(item, dict):
            continue
        a, b = item.get('start_id'), item.get('end_id')
        if type(a) is not int or type(b) is not int or a not in by_id or b not in by_id or a > b:
            continue
        start, end = max(0, by_id[a]['start'] - .15), min(duration, by_id[b]['end'] + .2)
        if not minimum <= end-start <= maximum or end <= start:
            continue
        try:
            score = float(item.get('score', 60))
        except (ValueError, TypeError):
            continue
        if not math.isfinite(score):
            continue
        accepted.append({'start':round(start,3),'end':round(end,3),'start_id':a,'end_id':b,
                         'title':str(item.get('title', '精彩片段'))[:80],
                         'reason':str(item.get('reason', ''))[:500],
                         'category':str(item.get('category', '精彩内容'))[:20],
                         'score':max(0,min(score,100)),
                         'excerpt':' '.join(s['text'] for s in context if a<=s['id']<=b)[:1500]})
    return accepted

def deduplicate(candidates, limit):
    chosen=[]
    for item in sorted(candidates, key=lambda c:c['score'], reverse=True):
        duplicate=False
        for other in chosen:
            intersection=max(0,min(item['end'],other['end'])-max(item['start'],other['start']))
            if intersection / min(item['end']-item['start'],other['end']-other['start']) > .35:
                duplicate=True
                break
        if not duplicate:
            chosen.append(item)
        if len(chosen)>=limit:
            break
    return sorted(chosen,key=lambda c:c['start'])

def srt_time(seconds):
    ms=max(0,round(seconds*1000))
    return f'{ms//3600000:02d}:{ms//60000%60:02d}:{ms//1000%60:02d},{ms%1000:03d}'

def clip_cues(sentences,start,end,offset=0):
    return [{'start':max(0,s['start']-start)+offset,'end':min(end,s['end'])-start+offset,'text':s['text']}
            for s in sentences if s['end']>start and s['start']<end]

def write_srt(path,cues):
    text='\n\n'.join(f'{i+1}\n{srt_time(c["start"])} --> {srt_time(c["end"])}\n{c["text"]}' for i,c in enumerate(cues))
    Path(path).write_text(text+'\n',encoding='utf-8')
