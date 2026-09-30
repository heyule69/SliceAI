"""Retained story anchors must survive neighboring aligned semantic cuts."""
import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from fine import valid_ranges
from fine_auto import run
from fine_candidates import generate
from word_timeline import cuts_word


class FixtureEditor:
    def __init__(self, rows):
        self.context = rows
        self.clip = {'start': 0., 'end': rows[-1]['end'] + 1}
        self.req = {'options': {'cleanup': ['offtopic'], 'speech': [], 'subtitles': 'none',
                                'music': 'original', 'normalize': False}}
        self.p = {'id': 'overlap-fixture'}
        self.store = None

    def persist(self, *args):
        pass

    def version(self, ranges, summary, **options):
        self.result = {'ranges': valid_ranges(ranges, self.clip),
                       'duration': sum(row['end'] - row['start'] for row in ranges),
                       'summary': summary}
        return self.result

    def render(self):
        pass


class FineOverlapSafetyTest(unittest.TestCase):
    def aligned_row(self, index, text):
        start = index * 2.
        # Adjacent VAD rows do not overlap, but an aligner may start the next
        # word 100 ms earlier within the supported extraction margin.
        a = start - .1 if index else start
        words = [dict(id=f'{index}:0', text=text[0], start=a, end=start+.8,
                      timing_method='forced_alignment'),
                 dict(id=f'{index}:1', text=text[1], start=start+1.1, end=start+1.95,
                      timing_method='forced_alignment')]
        return {'id': index, 'start': start, 'end': start+2, 'text': text,
                'alignment_complete': True, 'words': words}

    def execute(self, rows, *, anchor=True, restore_ids=()):
        editor = FixtureEditor(rows)
        story = {'outline': {'summary': '保留结局'},
                 'nodes': [{'id': 0, 'quote': rows[0]['text'], 'role': 'ending'}] if anchor else []}
        def decisions(editor, candidates, *args):
            return [{'id': candidate['id'], 'action': 'remove', 'kind': 'offtopic',
                     'reason': '模型提议删除无关内容', 'reference_ids': []} for candidate in candidates]
        # Exercise the production run/grounding/receipt path without any model,
        # API, video, Torch import, or rendering. Final review proposes no rescue.
        with patch('fine_auto.checked_captions', return_value=copy.deepcopy(rows)), \
                patch('fine_story.build_story', return_value=story), \
                patch('fine_story.decide', side_effect=decisions), \
                patch('fine_story.final_review', return_value={'restore_ids': list(restore_ids), 'reason': '最终复核保留故事表达'}), \
                patch('fine_auto.check_cancel'):
            run(editor)
        return editor.result

    def test_anchor_restoration_blocks_neighbor_cut_from_truncating_its_tail(self):
        rows = [self.aligned_row(0, '结局'), self.aligned_row(1, '闲聊')]
        version = self.execute(rows)
        by_id = {candidate['id']: candidate for candidate in version['cut_ledger']}
        self.assertEqual(by_id['row:0']['status'], 'blocked')
        self.assertIn('关键故事节点', by_id['row:0']['block_reason'])
        self.assertEqual(by_id['row:1']['status'], 'blocked')
        self.assertIn('保留的语音时间重叠', by_id['row:1']['block_reason'])
        self.assertEqual(version['removed'], [])
        self.assertEqual(version['removed_duration'], 0)
        self.assertEqual(version['duration'], 5)

    def test_neighbor_protection_propagates_until_all_retained_speech_is_safe(self):
        rows = [self.aligned_row(0, '结局'), self.aligned_row(1, '闲聊'), self.aligned_row(2, '谢礼')]
        version = self.execute(rows)
        self.assertTrue(all(candidate['status'] == 'blocked' for candidate in version['cut_ledger']))
        self.assertEqual(version['auto_review']['applied_removals'], 0)
        self.assertEqual(version['removed'], [])
        self.assertEqual(version['duration'], 7)

    def test_final_story_restoration_rechecks_neighbor_cuts_again(self):
        rows = [self.aligned_row(0, '结局'), self.aligned_row(1, '闲聊')]
        version = self.execute(rows, anchor=False, restore_ids=['row:0'])
        by_id = {candidate['id']: candidate for candidate in version['cut_ledger']}
        self.assertIn('全事件复核恢复', by_id['row:0']['block_reason'])
        self.assertEqual(by_id['row:1']['status'], 'blocked')
        self.assertIn('保留的语音时间重叠', by_id['row:1']['block_reason'])
        self.assertEqual(version['removed'], [])
        self.assertEqual(version['auto_review']['applied_removals'], 0)
        self.assertEqual(version['duration'], 5)


class WordCandidateBoundsTest(unittest.TestCase):
    def candidate(self, text, spans, speech):
        row = {'id': 0, 'start': 2., 'end': 4., 'text': text,
               'alignment_complete': True,
               'words': [dict(id=f'0:{index}', text=character, start=a, end=b,
                              timing_method='forced_alignment')
                         for index, (character, (a, b)) in enumerate(zip(text, spans))]}
        candidates = generate([row], {'cleanup': [], 'speech': [speech]}, {'start': 0., 'end': 5.})
        self.assertEqual(len(candidates), 1)
        return row, candidates[0]

    def test_first_retake_word_crossing_row_start_is_blocked(self):
        row, candidate = self.candidate('就就是', [(1.9, 2.1), (2.25, 2.45), (3., 3.2)], 'retakes')
        self.assertTrue(cuts_word(row, candidate))
        self.assertEqual(candidate['status'], 'blocked')
        self.assertIn('未完整覆盖字词起止', candidate['block_reason'])

    def test_last_filler_word_crossing_row_end_is_blocked(self):
        row, candidate = self.candidate('好呃', [(2.1, 2.3), (3.9, 4.08)], 'fillers')
        self.assertTrue(cuts_word(row, candidate))
        self.assertEqual(candidate['status'], 'blocked')
        self.assertIn('未完整覆盖字词起止', candidate['block_reason'])

    def test_complete_retake_and_filler_words_stay_eligible(self):
        cases = [('就就是', [(2.1, 2.3), (2.5, 2.7), (3.1, 3.3)], 'retakes'),
                 ('好呃', [(2.1, 2.3), (3.5, 3.7)], 'fillers')]
        for text, spans, speech in cases:
            with self.subTest(speech=speech):
                row, candidate = self.candidate(text, spans, speech)
                self.assertFalse(cuts_word(row, candidate))
                self.assertEqual(candidate['status'], 'suggested')
                self.assertEqual(candidate['block_reason'], '')


if __name__ == '__main__':
    unittest.main()
