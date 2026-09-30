"""Source-referenced word timing; emission anchors never become cut boundaries."""
import math
import re
import unicodedata

EPSILON = .002
ALIGNMENT_PADDING = .12  # Context extracted around an ASR/VAD speech row.


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', text)
                   if not c.isspace() and not unicodedata.category(c).startswith('P')).casefold()


def words_for(row):
    words = row.get('words')
    if (row.get('user_edited') or not isinstance(words, list) or not words
            or row.get('alignment_complete') is False):
        return []
    previous = None
    for word in words:
        if not isinstance(word, dict) or word.get('timing_method') != 'forced_alignment':
            return []
        a, b = word.get('start'), word.get('end')
        if (type(a) not in (int, float) or type(b) not in (int, float)
                or not math.isfinite(a + b) or a < 0 or b <= a
                or not isinstance(word.get('text'), str) or not word['text'].strip()
                or previous is not None and a < previous - EPSILON):
            return []
        previous = b
    # An aligner can omit unknown text. Partial coverage cannot justify captions
    # or cuts from the apparently valid remaining words.
    if normalized(''.join(w['text'] for w in words)) != normalized(row['text']):
        return []
    return words


def cuts_word(row, interval):
    words = words_for(row)
    if not words:
        return True
    return any(w['start'] + EPSILON < boundary < w['end'] - EPSILON
               for w in words for boundary in (interval['start'], interval['end']))


def join_words(words):
    text = ''
    for word in words:
        part = word['text']
        if (text and re.search(r'[A-Za-z]$', text)
                and re.match(r'[A-Za-z]', part) and len(part) > 1):
            text += ' '
        text += part
    return text


def source_text(row, words):
    """Retain the user's original spelling, punctuation and numeral formatting."""
    original = row['text']
    a, b = words[0].get('char_start'), words[-1].get('char_end')
    if (type(a) is int and type(b) is int and 0 <= a < b <= len(original)
            and normalized(original[a:b]) == normalized(''.join(word['text'] for word in words))):
        while b < len(original) and not normalized(original[b]):
            b += 1
        return original[a:b].strip()
    # Older aligned rows may lack literal character positions. Reconstruct
    # those positions from complete text coverage, without guessing times.
    positions = []
    plain = ''
    for index, char in enumerate(original):
        fragment = normalized(char)
        plain += fragment
        positions.extend([index] * len(fragment))
    all_words = words_for(row)
    cursor = 0
    offsets = {}
    for word in all_words:
        length = len(normalized(word['text']))
        offsets[id(word)] = (cursor, cursor + length)
        cursor += length
    if cursor == len(plain) and positions and id(words[0]) in offsets and id(words[-1]) in offsets:
        start, end = offsets[id(words[0])][0], offsets[id(words[-1])][1]
        if end > start:
            b = positions[end - 1] + 1
            while b < len(original) and not normalized(original[b]):
                b += 1
            return original[positions[start]:b].strip()
    return join_words(words)


def clipped_word_cues(row, interval, offset):
    """Group retained aligned words without repeating cut-away source text."""
    words = words_for(row)
    output_origin = interval['start']
    if not words or row.get('boundary_uncertain') or cuts_word(row, interval):
        return None
    retained = [w for w in words if w['start'] >= interval['start'] - EPSILON
                and w['end'] <= interval['end'] + EPSILON]
    if not retained:
        return []
    cues = []
    group = []
    for word in retained:
        if group and (len(join_words(group + [word])) > 36
                      or word['end'] - group[0]['start'] > 6
                      or word['start'] - group[-1]['end'] > .8):
            cues.append(group)
            group = []
        group.append(word)
    if group:
        cues.append(group)
    result = []
    whole = len(retained) == len(words) and len(cues) == 1
    for group in cues:
        mapped = [dict(w, start=max(0, w['start'] - output_origin) + offset,
                       end=w['end'] - output_origin + offset) for w in group]
        result.append({'start': mapped[0]['start'], 'end': mapped[-1]['end'],
                       'text': row['text'] if whole else source_text(row, group),
                       'words': mapped})
    return result
