import contextlib
import copy
import io
import sys
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from fine import mapped_cues, subtitle_lines, Editor
from caption_timeline import crosses_cut, refresh_boundaries
from edit_ledger import restore, refresh
from word_timeline import words_for
import test_fine


def row():
    return {'id': 7, 'start': 10, 'end': 15, 'text': '我我带猫去了', 'alignment_complete': True,
            'words': [dict(id=f'7:{i}', text=char, start=10+i*.6, end=10+i*.6+.3,
                           timing_method='forced_alignment') for i, char in enumerate('我我带猫去了')]}


class WordTimelineTest(unittest.TestCase):
    def test_in_sentence_retake_removes_only_the_cut_words_from_captions(self):
        source = row()
        ranges = [{'start': 10.5, 'end': 15}]
        cues = mapped_cues([source], ranges)
        self.assertEqual(''.join(c['text'] for c in cues), '我带猫去了')
        self.assertAlmostEqual(cues[0]['start'], .1)
        self.assertAlmostEqual(cues[0]['end'], 2.8)
        self.assertFalse(crosses_cut([source], ranges))
        self.assertEqual(subtitle_lines(cues)[0]['end'], cues[0]['end'])

    def test_raw_anchors_partial_alignment_and_mid_word_cuts_cannot_claim_safe_timing(self):
        source = row()
        self.assertTrue(crosses_cut([source], [{'start': 10.1, 'end': 15}]))
        source['words'][1]['end'] = float('nan')
        self.assertEqual(words_for(source), [])
        source = row()
        source['words'].pop()
        self.assertEqual(words_for(source), [])
        source = {'id': 1, 'start': 10, 'end': 15, 'text': '我带猫',
                  'tokens': [{'text': '我', 'anchor': 10.2}]}
        self.assertTrue(crosses_cut([source], [{'start': 10.5, 'end': 15}]))

    def test_clipped_text_preserves_numbers_spaces_and_punctuation_from_source(self):
        text = '嗯付了200元，Hello world'
        words = [dict(text=t, start=i, end=i+.5, timing_method='forced_alignment')
                 for i, t in enumerate(['嗯', '付', '了', '2', '0', '0', '元', 'Hello', 'world'])]
        source = {'id': 2, 'start': 0, 'end': 9, 'text': text, 'words': words}
        cues = mapped_cues([source], [{'start': .8, 'end': 9}])
        self.assertEqual(''.join(c['text'] for c in cues), '付了200元，Hello world')

    def test_partial_restore_keeps_overlapping_deletion_and_recounts_actual_union(self):
        version = {'ranges': [{'start': 0, 'end': 2}, {'start': 5, 'end': 10}],
                   'cut_ledger': [{'id': 'a', 'start': 2, 'end': 4, 'status': 'applied', 'reason': '重说'},
                                  {'id': 'b', 'start': 3, 'end': 5, 'status': 'applied', 'reason': '重复'}]}
        clip = {'start': 0, 'end': 10}
        refresh(version, clip)
        self.assertEqual(version['removed_duration'], 3)
        restore(version, 'a', clip)
        refresh(version, clip)
        self.assertEqual(version['ranges'], [{'start': 0, 'end': 3, 'reason': '保留故事与恢复的原声内容'},
                                            {'start': 5, 'end': 10, 'reason': '保留故事与恢复的原声内容'}])
        self.assertEqual(version['removed_duration'], 2)
        self.assertEqual(version['auto_review']['applied_removals'], 1)
        self.assertEqual(version['cut_ledger'][0]['status'], 'restored')
        with self.assertRaises(ValueError):
            restore(version, 'a', clip)

    def test_manual_redelete_has_an_actual_receipt_and_does_not_claim_restored_audio(self):
        clip={'start':0,'end':10}
        version={'ranges':[{'start':0,'end':10}], 'cut_ledger':[
            {'id':'a','start':2,'end':5,'status':'restored','reason':'先前重说'}]}
        version['ranges']=[{'start':0,'end':3},{'start':4,'end':7},{'start':8,'end':10}]
        refresh(version,clip,manual=True)
        self.assertEqual(version['removed_duration'],2)
        self.assertEqual(version['auto_review']['applied_removals'],2)
        self.assertEqual(version['cut_ledger'][0]['status'],'applied')
        self.assertEqual(version['cut_ledger'][0]['effective_intervals'],[{'start':3,'end':4}])
        self.assertEqual(version['cut_ledger'][0]['decision'],'manual')
        self.assertEqual(version['cut_ledger'][1]['kind'],'manual')


class RestoreEditorTest(unittest.TestCase):
    setUp = test_fine.FineTest.setUp
    tearDown = test_fine.FineTest.tearDown
    # Reuse source/store fixtures without rerunning inherited unrelated tests.
    def test_restore_creates_immutable_new_version_and_correct_subtitles(self):
        editor = Editor(self.store, {'project_id': self.p['id']})
        source = row()
        source['start'] -= 10
        source['end'] -= 10
        for word in source['words']:
            word['start'] -= 10
            word['end'] -= 10
        version = editor.version([{'start': .5, 'end': 12}], '删除首个重说字')
        version.update(subtitle_rows=[source], transcript_rows=[source],
                       cut_ledger=[{'id': 'retake:7:0', 'start': 0, 'end': .5,
                                    'status': 'applied', 'reason': '首个我字重说'}])
        before = copy.deepcopy(version)
        editor.req['restore_candidate_id'] = 'retake:7:0'
        editor.update_version()
        current = editor.current()
        self.assertEqual(editor.p['versions'][0], before)
        self.assertNotEqual(current['id'], before['id'])
        self.assertEqual(current['duration'], 12)
        self.assertEqual(current['removed_duration'], 0)
        self.assertEqual(current['auto_review']['applied_removals'], 0)
        self.assertEqual(''.join(c['text'] for c in current['cues']), '我我带猫去了')
        self.assertFalse(current['confirmed'])
        self.assertEqual(current['preview'], '')

    def test_restore_preserves_warning_on_its_original_source_clock(self):
        editor=Editor(self.store,{'project_id':self.p['id']})
        version=editor.version([{'start':0,'end':2},{'start':5,'end':12}],'已剪')
        version.update(transcript_rows=[{'id':0,'start':8,'end':9,'text':'需核对的原话'}],
            cues=[{'id':1,'start':5,'end':6,'text':'需核对的原话'}],
            caption_review={'method':'old','needs_review':[1]},
            cut_ledger=[{'id':'a','start':2,'end':5,'status':'applied','reason':'重说'}])
        editor.req['restore_candidate_id']='a'
        editor.update_version()
        current=editor.current()
        self.assertEqual(current['caption_review_regions'],[{'start':8,'end':9}])
        self.assertEqual(current['cues'][0]['start'],8)
        self.assertEqual(current['caption_review']['needs_review'],[1])

    def test_restored_word_recovers_source_sentence_without_tiny_fragment_asr(self):
        editor=Editor(self.store,{'project_id':self.p['id']})
        version=editor.version([{'start':0,'end':12}],'恢复重说')
        original={'id':0,'start':0,'end':2,'text':'一句一句反驳'}
        edited={'id':3,'start':5,'end':6,'text':'保留用户修改','user_edited':True}
        version.update(transcript_rows=[original,{'id':1,'start':5,'end':6,'text':'原句'}],
            subtitle_rows=[{'id':0,'start':0,'end':.32,'text':original['text'],
                            'boundary_uncertain':True},
                           {'id':1,'start':.32,'end':2,'text':'一句反驳'},edited],
            cut_ledger=[{'id':'retake','start':0,'end':.32,'status':'restored'}],
            caption_boundary_pending=True)
        with patch('fine_auto.checked_captions',side_effect=AssertionError('不应识别孤立的恢复字')):
            refresh_boundaries(editor,version)
        self.assertEqual([cue['text'] for cue in version['cues']],['一句一句反驳','保留用户修改'])
        self.assertNotIn('caption_boundary_pending',version)
        self.assertEqual(version['subtitle_rows'][-1]['text'],edited['text'])
        self.assertTrue(version['subtitle_rows'][-1]['user_edited'])


if __name__ == '__main__':
    unittest.main()
