"""Preserve full source captions and apply only local, source-time corrections."""
import uuid
EPSILON = .002


def intersects(row, region):
    return min(row['end'], region['end']) - max(row['start'], region['start']) > EPSILON


def crosses_cut(rows, ranges):
    from word_timeline import words_for,cuts_word
    for row in rows:
        for interval in ranges:
            if not intersects(row,interval):
                continue
            if words_for(row) and not row.get('boundary_uncertain'):
                if cuts_word(row,interval):return True
            elif (row.get('boundary_uncertain') or row['start']<interval['start']-EPSILON
                  or row['end']>interval['end']+EPSILON):
                return True
    return False


def source_rows(cues, ranges):
    """Remember saved user subtitles independently of a rendered version's clock."""
    result = []
    offset = 0
    prefix = uuid.uuid4().hex
    for interval in ranges:
        length = interval['end'] - interval['start']
        for index, cue in enumerate(cues):
            start = max(offset, cue['start'])
            end = min(offset + length, cue['end'])
            if end - start > EPSILON:
                result.append({'id': len(result), 'start': interval['start'] + start - offset,
                               'end': interval['start'] + end - offset, 'text': cue['text'],
                               'user_edited': True, 'edit_group': f'{prefix}:{index}'})
        offset += length
    return sorted(result, key=lambda row: (row['start'], row['end']))


def subtract(region, covered):
    pieces = [{'start': region['start'], 'end': region['end']}]
    for other in covered:
        remaining = []
        for piece in pieces:
            if not intersects(piece, other):
                remaining.append(piece)
                continue
            if other['start'] - piece['start'] > EPSILON:
                remaining.append({'start': piece['start'], 'end': other['start']})
            if piece['end'] - other['end'] > EPSILON:
                remaining.append({'start': other['end'], 'end': piece['end']})
        pieces = remaining
    return pieces


def overlay_rows(rows, replacement, regions):
    """Keep captions outside changed audio, including previously excluded audio."""
    result = []
    for row in rows:
        for piece in subtract(row, regions):
            changed = piece['start'] > row['start'] + EPSILON or piece['end'] < row['end'] - EPSILON
            result.append(dict(row, **piece, boundary_uncertain=row.get('boundary_uncertain', False) or changed))
    result.extend(dict(row) for row in replacement)
    result.sort(key=lambda row: (row['start'], row['end']))
    return [dict(row, id=i) for i, row in enumerate(result)]


def mark_partial_groups(rows, ranges):
    groups = {}
    for row in rows:
        if 'edit_group' in row:
            groups.setdefault(row['edit_group'], []).append(row)
    incomplete = {group for group, members in groups.items()
                  if any(intersects(row, region) for row in members for region in ranges)
                  and any(subtract(row, ranges) for row in members)}
    return [dict(row, boundary_uncertain=True) if row.get('edit_group') in incomplete else row for row in rows]


def row_review_spans(row):
    """Source intervals that still need a listen, not the whole VAD row.

    original_fallback has no fresh words to narrow. Explicit
    caption_review_spans win over a row-level caption_warning so a cut that
    removes only the disagreed words does not keep the retained neighbors flagged.
    """
    if row.get('original_fallback'):
        return [{'start': row['start'], 'end': row['end']}]
    spans = row.get('caption_review_spans')
    if isinstance(spans, list) and spans:
        regions = []
        for span in spans:
            if not isinstance(span, dict):
                continue
            start, end = span.get('start'), span.get('end')
            if type(start) in (int, float) and type(end) in (int, float) and end - start > EPSILON:
                regions.append({'start': start, 'end': end})
        if regions:
            return regions
    if row.get('caption_warning') or row.get('analysis_note'):
        return [{'start': row['start'], 'end': row['end']}]
    return []


def warning_regions(rows):
    regions = []
    for row in rows:
        regions.extend(row_review_spans(row))
    return merged_regions(regions)


def review_regions(version):
    regions = list(version.get('caption_review_regions', []))
    for row in version.get('subtitle_rows', version.get('transcript_rows', [])):
        regions.extend(row_review_spans(row))
    uncertain = set(version.get('caption_review', {}).get('needs_review', []))
    if uncertain:
        regions.extend(source_rows([cue for cue in version['cues'] if cue['id'] in uncertain], version['ranges']))
    return merged_regions(regions)


def merged_regions(regions):
    result=[]
    for row in sorted(regions,key=lambda row:row['start']):
        if result and row['start']<=result[-1]['end']+EPSILON:
            result[-1]['end']=max(result[-1]['end'],row['end'])
        else:result.append({'start':row['start'],'end':row['end']})
    return result


def update_review(version, regions, method):
    from fine import mapped_cues
    regions=merged_regions(regions)
    mapped = mapped_cues([dict(row, text='需核对') for row in regions], version['ranges'])
    version['caption_review_regions'] = regions
    version['caption_review'] = {'method': method, 'needs_review': [cue['id'] for cue in version['cues']
        if any(intersects(cue, region) for region in mapped)]}


def refresh_boundaries(editor, version):
    """Re-listen to cut sentences, keeping full user edits and unrelated warnings."""
    from fine import mapped_cues
    from fine_auto import checked_captions
    base = version.get('subtitle_rows', version.get('transcript_rows', editor.sentences))
    restored=[item for item in version.get('cut_ledger',[]) if item.get('status')=='restored'
              and type(item.get('start')) in (int,float) and type(item.get('end')) in (int,float)]
    # Retained-only ASR leaves hidden source fragments inside deleted words.
    # Restoring a word must recover its original sentence, rather than ask VAD
    # to recognize a 200–300 ms fragment without speech context.
    originals=[row for row in version.get('transcript_rows',[]) if any(intersects(row,cut) for cut in restored)
               and not any(edited.get('user_edited') and intersects(row,edited) for edited in base)]
    if originals:
        base=overlay_rows(base, originals, merged_regions(originals))
        version['subtitle_rows']=base
    rows = mark_partial_groups(base, version['ranges'])
    warnings = review_regions(version)
    targets = []
    preserved = []
    for interval in version['ranges']:
        edits = [row for row in rows if row.get('user_edited') and not row.get('boundary_uncertain')
                 and row['start'] >= interval['start'] - EPSILON and row['end'] <= interval['end'] + EPSILON]
        preserved.extend(edits)
        for row in rows:
            if crosses_cut([row], [interval]):
                region = {'start': max(row['start'], interval['start']), 'end': min(row['end'], interval['end'])}
                targets.extend(subtract(region, edits))
    merged = []
    for target in sorted(targets, key=lambda row: row['start']):
        if merged and target['start'] <= merged[-1]['end'] + EPSILON:
            merged[-1]['end'] = max(target['end'], merged[-1]['end'])
        else:
            merged.append(dict(target))
    audio = None
    if merged and version.get('audio_strength'):
        from fine_audio import prepare
        audio = prepare(editor, version['audio_strength'])
    replacement = []
    for target in merged:
        editor.persist('重新核对剪切点字幕')
        fresh = checked_captions(editor, audio, clip=target)
        for row in rows:
            for span in row_review_spans(row):
                if not intersects(span, target):
                    continue
                piece = {'start': max(span['start'], target['start']), 'end': min(span['end'], target['end'])}
                if piece['end'] - piece['start'] > EPSILON:
                    warnings.append(piece)
        replacement.extend(fresh)
    if merged:
        version['subtitle_rows'] = overlay_rows(rows, replacement + preserved, merged + preserved)
    version['cues'] = mapped_cues(version.get('subtitle_rows', base), version['ranges'])
    version.pop('caption_boundary_pending', None)
    update_review(version, warnings, 'retained_audio_retranscription')
