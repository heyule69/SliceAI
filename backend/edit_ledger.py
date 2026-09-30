"""Derive edit receipts from source intervals, including partial restoration."""
import math

EPSILON = .002


def union(intervals):
    result = []
    for row in sorted(intervals, key=lambda row: row['start']):
        if row['end'] - row['start'] <= EPSILON:
            continue
        if result and row['start'] <= result[-1]['end'] + EPSILON:
            result[-1]['end'] = max(result[-1]['end'], row['end'])
        else:
            result.append({'start': row['start'], 'end': row['end']})
    return result


def deleted_intervals(ranges, clip):
    result = []
    cursor = clip['start']
    for row in union(ranges):
        if row['start'] - cursor > EPSILON:
            result.append({'start': cursor, 'end': row['start']})
        cursor = max(cursor, row['end'])
    if clip['end'] - cursor > EPSILON:
        result.append({'start': cursor, 'end': clip['end']})
    return result


def intersections(row, regions):
    return [{'start': max(row['start'], region['start']), 'end': min(row['end'], region['end'])}
            for region in regions
            if min(row['end'], region['end']) - max(row['start'], region['start']) > EPSILON]


def positioned(candidate, clip):
    a, b = candidate.get('start'), candidate.get('end')
    return (type(a) in (int, float) and type(b) in (int, float) and math.isfinite(a + b)
            and clip['start'] - EPSILON <= a < b <= clip['end'] + EPSILON)


def ledger_for(version):
    ledger=version.get('cut_ledger',version.get('candidate_ledger',{}).get('candidates',[]))
    version['cut_ledger']=ledger
    # Migrate the temporary nested format to one canonical source of receipts.
    version.pop('candidate_ledger',None)
    return ledger


def restore(version, candidate_id, clip):
    if not isinstance(candidate_id, str) or version.get('reordered'):
        raise ValueError('此删点无法直接恢复，请通过保留区间调整。')
    ledger = ledger_for(version)
    matches = [item for item in ledger if item.get('id') == candidate_id]
    if len(matches) != 1 or matches[0].get('status') != 'applied' or not positioned(matches[0], clip):
        raise ValueError('此删点未应用或已恢复，请刷新后重试。')
    candidate = matches[0]
    # Restore this candidate while honoring any overlapping applied candidate.
    from caption_timeline import subtract
    others = [item for item in ledger if item is not candidate and item.get('status') == 'applied'
              and positioned(item, clip)]
    restored = subtract(candidate, others)
    version['ranges'] = [dict(row, reason='保留故事与恢复的原声内容')
                         for row in union(version['ranges'] + restored)]
    candidate['status'] = 'restored'
    candidate['effective_intervals'] = []
    candidate['effective_duration'] = 0


def refresh(version, clip, manual=False):
    deleted = deleted_intervals(version['ranges'], clip)
    ledger = ledger_for(version)
    for item in ledger:
        if (manual and item.get('status') == 'restored' and positioned(item, clip)
                and intersections(item, deleted)):
            item.update(status='applied', decision='manual',
                        reason='手动区间调整重新删除此处；'+item.get('reason',''))
        if item.get('status') != 'applied' or not positioned(item, clip):
            continue
        effective = intersections(item, deleted)
        item['effective_intervals'] = effective
        item['effective_duration'] = round(sum(r['end'] - r['start'] for r in effective), 3)
        if not effective:
            item['status'] = 'restored'
    if manual:
        from caption_timeline import subtract
        explained=[piece for item in ledger if item.get('status')=='applied'
                   for piece in item.get('effective_intervals',[])]
        for region in deleted:
            for piece in subtract(region,explained):
                ledger.append(dict(piece,id=f"manual:{piece['start']:.6f}:{piece['end']:.6f}",
                    kind='manual',status='applied',decision='manual',reason='手动调整保留区间',
                    text='',quote='',row_ids=[],word_ids=[],evidence=[{'type':'user_ranges'}],
                    effective_intervals=[piece],effective_duration=round(piece['end']-piece['start'],3)))
        version['cut_ledger']=ledger
    removed = []
    for region in deleted:
        contributors = [item for item in ledger if item.get('status') == 'applied'
                        and positioned(item, clip) and intersections(item, [region])]
        removed.append(dict(region,
            reason='；'.join(dict.fromkeys(str(item.get('reason', '')) for item in contributors))
                   or '手动调整保留区间',
            candidate_ids=[item['id'] for item in contributors]))
    version['removed'] = removed
    version['source_duration'] = round(clip['end'] - clip['start'], 3)
    version['duration'] = sum(row['end'] - row['start'] for row in version['ranges'])
    version['removed_duration'] = round(sum(row['end'] - row['start'] for row in deleted), 3)
    review = version.setdefault('auto_review', {})
    review.update(suggested_removals=len(ledger),
                  blocked_removals=sum(item.get('status') == 'blocked' for item in ledger),
                  applied_removals=sum(item.get('status') == 'applied' for item in ledger),
                  source_duration=version['source_duration'], output_duration=version['duration'],
                  removed_duration=version['removed_duration'])
    if manual:
        review['final_story_review']={'status':'user_adjusted',
                                     'reason':'保留区间已经手动修改，请检查当前故事与字幕后确认。'}
    version['summary'] = (f"原片 {version['source_duration']:.2f} 秒，当前 {version['duration']:.2f} 秒，"
                          f"实际精简 {version['removed_duration']:.2f} 秒；请重新确认。")
