"""Grounded edit proposals. Models classify IDs; source times stay local."""
from __future__ import annotations
import difflib
import math
import re
from word_timeline import ALIGNMENT_PADDING, normalized, words_for

EPSILON = .002
EMOTIONAL = re.compile(r'哭|呜呜|哈哈|呵呵|哽咽|抽泣|心疼|难过|自责|伤心|好疼|好痛')
REACTION = re.compile(r'^(?:哈|呵|呜|嘿|啊|唔){2,}$')


def intersects(a, b):
    return min(a['end'], b['end']) - max(a['start'], b['start']) > EPSILON


def emotional(row):
    metadata = row.get('asr', {})
    return (bool(REACTION.fullmatch(normalized(row['text'])))
            or normalized(metadata.get('emotion', '')) in ('sad', 'angry', 'fearful', 'disgusted')
            or normalized(metadata.get('event', '')) in ('cry', 'crying', 'laugh', 'laughter', 'music', 'singing')
            or bool(EMOTIONAL.search(row['text'])))


def reliable_words(row):
    words = words_for(row)
    if not words:
        return []
    cursor = row['start'] - ALIGNMENT_PADDING
    identifiers=set()
    for word in words:
        a, b = word.get('start'), word.get('end')
        if (word.get('timing_method') != 'forced_alignment' or type(word.get('id')) not in (int,str)
                or word['id'] in identifiers
                or type(a) not in (int, float) or type(b) not in (int, float)
                or not math.isfinite(a + b) or b <= a or a < cursor - EPSILON
                or a < row['start'] - ALIGNMENT_PADDING - EPSILON
                or b > row['end'] + ALIGNMENT_PADDING + EPSILON
                or not isinstance(word.get('text'), str) or not normalized(word['text'])):
            return []
        identifiers.add(word['id'])
        cursor = b
    if normalized(''.join(word['text'] for word in words)) != normalized(row['text']):
        return []
    return words


def timing_targets(rows, options):
    """Align only local repeated-token/filler rows, never invent token ends."""
    targets = set()
    for row in rows:
        text = normalized(row['text'])
        if 'retakes' in options['speech'] and re.search(r'(.{1,4})\1', text):
            targets.add(row['id'])
        if 'fillers' in options['speech'] and re.search(r'[嗯呃额唔]', text):
            targets.add(row['id'])
    return targets


def timed_streams(row):
    """A complete local window is usable even when a distant word is unknown."""
    full=reliable_words(row)
    if full:return [(row,full,None)]
    if row.get('user_edited'):return []
    windows=row.get('word_windows',[])
    if not isinstance(windows,list):return []
    streams=[]
    for window in windows:
        if not isinstance(window,dict) or not isinstance(window.get('id'),str) or window.get('alignment_complete') is not True:
            continue
        first,last=window.get('char_start'),window.get('char_end')
        if (type(first) is not int or type(last) is not int or not 0<=first<last<=len(row['text'])
                or window.get('text')!=row['text'][first:last]):continue
        local={**row,**window,'user_edited':False}
        words=reliable_words(local)
        if (not words or words[0]['start']<row['start']-ALIGNMENT_PADDING-EPSILON
                or words[-1]['end']>row['end']+ALIGNMENT_PADDING+EPSILON):continue
        indexed=[];cursor=0
        for word in words:
            position=window['text'].find(word['text'],cursor)
            if position<0:break
            indexed.append(dict(word,char_start=first+position,char_end=first+position+len(word['text'])))
            cursor=position+len(word['text'])
        else:
            # Retain the original row ID and emotion context. Source window
            # edges bound padding; local completion never labels the row full.
            local.update(id=row['id'],text=row['text'])
            streams.append((local,indexed,window['id']))
    return streams


def _candidate(cid, kind, row, start, end, quote, **values):
    return {'id': cid, 'kind': kind, 'start': start, 'end': end, 'text': quote,
            'quote': quote, 'row_ids': [row['id']], 'word_ids': [], 'evidence': [],
            'status': 'suggested', 'reason': '', 'block_reason': '', **values}


def generate(rows, options, clip):
    candidates = []
    for position,row in enumerate(rows):
        a, b = max(clip['start'], row['start']), min(clip['end'], row['end'])
        if options['cleanup'] and b > a:
            # The candidate is an existing speech segment. Classification does
            # not give the model permission to extend it into adjacent sounds.
            candidate = _candidate(f"row:{row['id']}", 'semantic', row, a, b, row['text'],
                                   allowed_kinds=options['cleanup'],
                                   evidence=[{'type': 'source_segment', 'id': row['id']}])
            if 'repeats' in options['cleanup']:
                nearby=[]
                for other in rows[max(0,position-5):position]+rows[position+1:position+6]:
                    similarity=difflib.SequenceMatcher(None,normalized(row['text']),normalized(other['text'])).ratio()
                    if similarity>=.45:
                        nearby.append({'id':other['id'],'quote':other['text'][:80],'similarity':round(similarity,3)})
                if nearby:candidate['evidence'].append({'type':'lexical_repeat_neighbors',
                    'matches':sorted(nearby,key=lambda item:item['similarity'],reverse=True)[:3]})
            if 'greetings' in options['cleanup'] and re.search(r'谢谢.{0,12}(礼物|关注|舰长)|欢迎.{0,8}(回来|加入)|感谢.{0,8}(礼物|支持)',row['text']):
                candidate['evidence'].append({'type':'routine_greeting_phrase','quote':row['text'][:80]})
            if emotional(row):
                candidate.update(status='blocked', block_reason='保留情绪、笑哭或音乐反应')
            elif b-a > 4 and len(normalized(row['text']))/(b-a) < 1:
                candidate.update(status='blocked', block_reason='转写稀疏，不能证明整个声音区间都可删')
            candidates.append(candidate)
        streams=timed_streams(row)
        if not streams:
            if row['id'] in timing_targets([row], options):
                candidates.append(_candidate(f"timing:{row['id']}", 'retakes' if 'retakes' in options['speech'] else 'fillers',
                    row, None, None, row['text'], status='blocked',
                    block_reason='缺少可靠字词起止；CTC 锚点不能作为切口',
                    evidence=[{'type': 'alignment', 'status': row.get('alignment', {}).get('status', 'unavailable')}]))
            continue
        seen=set()
        for local,words,window_id in streams:
            if 'retakes' in options['speech']:
                for index in range(len(words)-1):
                    for width in range(min(4, (len(words)-index)//2), 0, -1):
                        left, right = words[index:index+width], words[index+width:index+2*width]
                        quote = ''.join(word['text'] for word in left)
                        if normalized(quote) != normalized(''.join(word['text'] for word in right)):continue
                        key=('retakes',left[0].get('char_start'),left[-1].get('char_end')) if window_id else tuple(word['id'] for word in left)
                        if key in seen:continue
                        seen.add(key)
                        candidate = _word_candidate(local, words, index, index+width, 'retakes', quote,window_id)
                        repeat={'word_ids':[word['id'] for word in right],
                                'quote':''.join(word['text'] for word in right),
                                'start':right[0]['start'],'end':right[-1]['end']}
                        if 'char_start' in right[0] and 'char_end' in right[-1]:
                            repeat.update(char_start=right[0]['char_start'],char_end=right[-1]['char_end'])
                        candidate['evidence'].append({'type': 'exact_tandem_repeat',
                            'repeat_word_ids': [word['id'] for word in right], 'quote': quote,
                            'repeat_occurrence':repeat})
                        candidates.append(candidate)
                        break
            if 'fillers' in options['speech']:
                for index, word in enumerate(words):
                    if normalized(word['text']) in ('嗯', '呃', '额', '唔'):
                        key=('fillers',word.get('char_start'),word.get('char_end')) if window_id else ('fillers',word['id'])
                        if key in seen:continue
                        seen.add(key)
                        candidates.append(_word_candidate(local, words, index, index+1, 'fillers', word['text'],window_id))
    for candidate in candidates:
        if (candidate['start'] is not None and (candidate['start'] < clip['start']-EPSILON
                or candidate['end'] > clip['end']+EPSILON)):
            candidate.update(status='blocked',block_reason='字词切口超出选定事件，保留原声')
    return candidates


def _word_candidate(row, words, first, last, kind, quote, window_id=None):
    selected = words[first:last]
    a, b = selected[0]['start'], selected[-1]['end']
    # Keep neighboring syllables intact. Padding comes only from measured
    # word gaps; it is never extrapolated from a token emission.
    left = words[first-1]['end'] if first else row['start']
    right = words[last]['start'] if last < len(words) else row['end']
    a = max(left, a-.025); b = min(right, b+.025)
    result = _candidate(f"word:{row['id']}:{window_id+':' if window_id else ''}{first}:{last}:{kind}", kind, row, a, b, quote,
        word_ids=[word['id'] for word in selected],
        evidence=[{'type': 'forced_alignment', 'word_ids': [word['id'] for word in selected]}])
    if window_id:
        result.update(window_id=window_id,char_start=selected[0]['char_start'],char_end=selected[-1]['char_end'])
        literal=row['text'][result['char_start']:result['char_end']]
        result.update(quote=literal,text=literal)
        result['evidence'].append({'type':'literal_source_window','id':window_id,
                                   'char_start':result['char_start'],'char_end':result['char_end']})
    metadata=row.get('asr',{})
    if metadata.get('emotion') or metadata.get('event'):
        result['evidence'].append({'type':'unverified_asr_hint','emotion':metadata.get('emotion',''),
                                   'event':metadata.get('event','')})
    # A whole-row mention of feeling sad does not prove a nearby neutral
    # stutter carries emotion. Judge that in context; never cut a laugh/cry
    # syllable or model-marked foreground reaction automatically.
    reaction=(bool(re.fullmatch(r'(?:哈|呵|呜|嘿|啊|唔)+',normalized(quote)))
              or bool(EMOTIONAL.search(quote))
              or normalized(metadata.get('event','')) in ('cry','crying','laugh','laughter','music','singing'))
    # A measured syllable can extend beyond a VAD row/window edge. Clamping
    # padding must never turn deletion of that word into deletion of half of it.
    if a > selected[0]['start'] + EPSILON or b < selected[-1]['end'] - EPSILON:
        result.update(status='blocked', block_reason='删点未完整覆盖字词起止，保留完整原声')
    elif kind=='retakes' and re.fullmatch(r'一[个句次步点遍本件条张段字口天回]',normalized(quote)):
        result.update(status='blocked', block_reason='量词重叠可能表达逐一或渐进，保留原意')
    elif b-a < .08 or reaction:
        result.update(status='blocked', block_reason='切口过短或含情绪反应，保留原声')
    return result


def validate_decisions(raw, candidates, rows, options):
    decisions = raw.get('decisions') if isinstance(raw, dict) else None
    if not isinstance(decisions, list):
        raise ValueError('候选判断需要 decisions 列表。')
    source = {row['id']: row for row in rows}
    allowed = {item['id']: item for item in candidates}
    seen = set(); result = []
    for decision in decisions:
        if (not isinstance(decision, dict) or not isinstance(decision.get('id'), str)
                or decision['id'] not in allowed or decision['id'] in seen):
            raise ValueError('候选编号不存在或重复。')
        cid = decision['id']; seen.add(cid); candidate = allowed[cid]
        action = decision.get('action'); reason = decision.get('reason')
        if action not in ('remove', 'keep') or not isinstance(reason, str) or not 3 <= len(reason.strip()) <= 160:
            raise ValueError('候选处理或说明无效。')
        blocked=decision.get('validation_blocked',False)
        if type(blocked) is not bool or blocked and action!='keep':
            raise ValueError('未核验候选只能保留原文，不能执行删除。')
        kind = candidate['kind']
        if action == 'remove':
            kind = decision.get('kind', kind)
            if kind not in candidate.get('allowed_kinds', [candidate['kind']]) or kind not in options['cleanup']+options['speech']:
                raise ValueError('候选删除理由未获用户选择。')
            references = decision.get('reference_ids', [])
            if not isinstance(references, list) or any(type(sid) is not int or sid not in source for sid in references):
                raise ValueError('删除依据引用了不存在的原文。')
            if candidate['kind'] == 'semantic' and kind == 'repeats':
                if not any(sid not in candidate['row_ids'] and difflib.SequenceMatcher(None,
                    normalized(candidate['quote']), normalized(source[sid]['text'])).ratio() >= .45 for sid in references):
                    raise ValueError('重复表达候选缺少可核对的另一处原文。')
        result.append({'id': cid, 'action': action, 'kind': kind, 'reason': reason.strip(),
                       'reference_ids': decision.get('reference_ids', []),
                       **({'validation_blocked':True} if blocked else {})})
    if seen != set(allowed):
        raise ValueError('判断遗漏候选，不能默认为删除。')
    return {'decisions': result}


def merge_removed(candidates, clip):
    """One ledger may overlap; reported removed time is the effective union."""
    result = []
    for item in sorted((c for c in candidates if c['status'] == 'applied'), key=lambda c: c['start']):
        a, b = max(clip['start'], item['start']), min(clip['end'], item['end'])
        if b-a < .04:
            continue
        if result and a <= result[-1]['end'] + EPSILON:
            result[-1]['end'] = max(b, result[-1]['end'])
            result[-1]['candidate_ids'].append(item['id'])
            result[-1]['kinds'] = sorted(set(result[-1]['kinds'] + [item['kind']]))
        else:
            result.append({'start': a, 'end': b, 'kind': item['kind'], 'kinds': [item['kind']],
                           'reason': item['reason'], 'text': item['text'], 'candidate_ids': [item['id']]})
    return result


def execution_summary(clip, ranges, ledger):
    source = clip['end']-clip['start']; duration = sum(row['end']-row['start'] for row in ranges)
    applied = sum(item['status'] == 'applied' for item in ledger)
    blocked = sum(item['status'] == 'blocked' for item in ledger)
    removed = max(0., source-duration)
    if removed < .01:
        return f'本次未产生精简；检查了 {len(ledger)} 个候选，其中 {blocked} 个因声音、定位或故事保护而保留。'
    return f'实际应用 {applied} 个候选，删除 {removed:.2f} 秒；原片 {source:.2f} 秒，成片 {duration:.2f} 秒。保留原顺序、故事与情绪反应。'
