"""Contract and cache checks without inference downloads or user-profile data."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from asr import result_row, shift_row_timing
from engine import Cancelled
from fine_alignment import checked_words, local_windows, prepare
from fine_candidates import generate, reliable_words
from word_timeline import ALIGNMENT_PADDING, cuts_word


class TimingTest(unittest.TestCase):
    def padded_row(self):
        spans = [('前',10-ALIGNMENT_PADDING,10.1),('就',10.5,10.74),
                 ('就',11.1,11.58),('是',11.65,12),('后',14.95,15+ALIGNMENT_PADDING)]
        return {'id':7,'start':10,'end':15,'text':'前就就是后','alignment_complete':True,
                'words':[{'id':f'7:{i}','text':text,'start':a,'end':b,
                          'timing_method':'forced_alignment'} for i,(text,a,b) in enumerate(spans)]}

    def test_extracted_padding_at_both_edges_keeps_internal_retakes_usable(self):
        row = self.padded_row()
        self.assertEqual(reliable_words(row),row['words'])
        items = generate([row],{'cleanup':[],'speech':['retakes']},{'start':9.7,'end':15.3})
        self.assertEqual(len(items),1)
        candidate = items[0]
        self.assertEqual(candidate['quote'],'就')
        self.assertEqual(candidate['status'],'suggested')
        self.assertLessEqual(candidate['start'],row['words'][1]['start'])
        self.assertGreaterEqual(candidate['end'],row['words'][1]['end'])
        self.assertFalse(cuts_word(row,candidate))

    def test_alignment_beyond_padding_and_rounding_tolerance_is_rejected(self):
        for edge in ('start','end'):
            row = self.padded_row()
            word = row['words'][0 if edge=='start' else -1]
            word[edge] += -.003 if edge=='start' else .003
            with self.subTest(edge=edge):
                self.assertEqual(reliable_words(row),[])
        rounded = self.padded_row()
        rounded['words'][0]['start'] -= .0000001
        rounded['words'][-1]['end'] += .0000001
        self.assertEqual(reliable_words(rounded),rounded['words'])

    def test_padding_never_permits_a_partial_first_word_deletion(self):
        row = self.padded_row()
        row['text']='就就是后'
        row['words']=[dict(word,id=f'7:{i}',text=text) for i,(word,text) in enumerate(
            zip([row['words'][0],row['words'][1],row['words'][3],row['words'][4]],'就就是后'))]
        self.assertEqual(len(reliable_words(row)),4)
        items = generate([row],{'cleanup':[],'speech':['retakes']},{'start':9.7,'end':15.3})
        self.assertEqual(len(items),1)
        self.assertEqual(items[0]['status'],'blocked')
        self.assertIn('完整覆盖字词',items[0]['block_reason'])

    def test_local_window_uses_exact_ctc_source_characters_without_cut_ends(self):
        row = {'id': 7, 'start': 10, 'end': 14, 'text': '候，就就是非常',
               'tokens': [{'text': t, 'anchor': a} for t,a in
                          [('候',10.476),('，',10.596),('就',10.716),('就',11.736),
                           ('是',11.916),('非',12.816),('常',12.996)]]}
        windows = local_windows(row)
        self.assertEqual(len(windows),1)
        window = windows[0]
        self.assertEqual(window['text'],'候，就就是')
        self.assertEqual(row['text'][window['char_start']:window['char_end']],window['text'])
        self.assertAlmostEqual(window['start'],10.396)
        self.assertAlmostEqual(window['end'],12.616)
        self.assertEqual(window['words'],[])
        self.assertFalse(window['alignment_complete'])
        changed = copy.deepcopy(row); changed['text'] = '候，就是非常'
        self.assertEqual(local_windows(changed),[])
        changed = copy.deepcopy(row); changed['tokens'][2]['anchor'] = 9
        self.assertEqual(local_windows(changed),[])

    def test_emission_anchors_have_no_invented_ends(self):
        result = SimpleNamespace(text='<|zh|>就就是！', tokens=['就', '就', '是'],
                                 timestamps=[.2, .5, .8], lang='<|zh|>', emotion='<|HAPPY|>', event='<|BGM|>')
        row = result_row(result, 10, 11, 7)
        self.assertEqual([t['anchor'] for t in row['tokens']], [10.2, 10.5, 10.8])
        self.assertTrue(all('end' not in t for t in row['tokens']))
        shift_row_timing(row, 100)
        self.assertEqual(row['vad'], {'start': 110, 'end': 111, 'method': 'silero_vad', 'sample_rate': 16000})
        self.assertEqual(row['tokens'][0]['anchor'], 110.2)
        self.assertEqual(row['timing_metadata']['event_labels'], 'model_hints_not_verified')

    def test_invalid_emission_anchors_are_not_cut_spans(self):
        row = result_row(SimpleNamespace(text='原话', tokens=['原', '话', '嗯'],
                         timestamps=[float('nan'), -1, 99]), 0, 2, 0)
        self.assertEqual(row['tokens'], [])
        self.assertEqual(row['timing_method'], 'vad_segment')

    def test_complete_words_keep_literal_offsets(self):
        row = {'id': 5, 'text': '就，就是。'}
        words = checked_words(row, [{'text': '就', 'start': 10, 'end': 10.2},
                             {'text': '就', 'start': 10.4, 'end': 10.6},
                             {'text': '是', 'start': 10.6, 'end': 10.8}], 10, 11)
        self.assertEqual([(w['char_start'], w['char_end']) for w in words], [(0, 1), (2, 3), (3, 4)])
        self.assertEqual(words[0]['id'], '5:0')
        self.assertTrue(all(w['timing_method'] == 'forced_alignment' for w in words))

    def test_missing_unsupported_zero_overlap_and_nonfinite_are_rejected(self):
        row = {'id': 5, 'text': '原话'}
        cases = [[], [{'text': '原', 'start': 10, 'end': 10.5}],
                 [{'text': '原话', 'start': 10, 'end': 10}],
                 [{'text': '原话', 'start': float('nan'), 'end': 10.5}],
                 [{'text': '原话', 'start': 9, 'end': 10.5}],
                 [{'text': '原', 'start': 10, 'end': 10.5}, {'text': '话', 'start': 10.2, 'end': 10.8}]]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError):
                checked_words(row, case, 10, 11)
        with self.assertRaises(ValueError):
            checked_words({'id': 1, 'text': '原话🎵'}, [{'text': '原话', 'start': 10, 'end': 10.5}], 10, 11)


class PrepareTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.source = self.root/'source.mp4'; self.source.write_bytes(b'test source')
        self.python = self.root/'python'; self.python.write_bytes(b'worker')
        self.editor = SimpleNamespace(folder=self.root, task={'video': str(self.source), 'audio_track': 1},
            clip={'start': 100, 'end': 110}, store=None, p={'id': 'edit'}, settings={'asr_threads': 2}, persist=lambda *args: None)
        self.rows = [{'id': 1, 'start': 101, 'end': 103, 'text': '原话。'}]
        self.extracts = []; self.runs = 0

    def tearDown(self):
        self.temp.cleanup()

    def extract(self, ffmpeg, source, wav, **kwargs):
        self.extracts.append(kwargs); Path(wav).write_bytes(b'audio'); return ['extract']

    def command(self, args, *unused, **kwargs):
        if args == ['extract']:
            return ''
        self.runs += 1
        request = Path(args[args.index('--requests')+1])
        jobs = [json.loads(line) for line in request.read_text(encoding='utf-8').splitlines()]
        for job in jobs:
            kwargs['on_line'](json.dumps({'event': 'alignment', 'id': job['id'], 'words': [
                {'text': '原', 'start': job['start']+.2, 'end': job['start']+.5},
                {'text': '话', 'start': job['start']+.6, 'end': job['start']+.9}]}))

    def patches(self):
        import contextlib
        stack = contextlib.ExitStack()
        stack.enter_context(patch('fine_alignment.locations', return_value=([str(self.python)], self.root/'model')))
        stack.enter_context(patch('fine_alignment.model_identity', return_value={'engine': 'test', 'revision': 'pin'}))
        stack.enter_context(patch('fine_alignment.check_cancel'))
        stack.enter_context(patch('fine_alignment.tool_path', side_effect=lambda settings, name: name))
        stack.enter_context(patch('media_audio.aligned_audio_args', side_effect=self.extract))
        stack.enter_context(patch('fine_alignment.command', side_effect=self.command))
        return stack

    def test_absolute_source_clock_cache_and_temporary_cleanup(self):
        with self.patches():
            first = prepare(self.editor, self.rows)
            second = prepare(self.editor, self.rows)
        self.assertEqual(self.runs, 1)
        self.assertTrue(first[0]['alignment_complete'])
        self.assertAlmostEqual(first[0]['words'][0]['start'], 101.08)
        self.assertTrue(second[0]['alignment']['cached'])
        self.assertEqual(self.extracts[0]['track'], 1)
        self.assertEqual(self.rows, [{'id': 1, 'start': 101, 'end': 103, 'text': '原话。'}])
        self.assertFalse(list((self.root/'alignment-cache').glob('*.partial*')))

    def test_processed_audio_uses_event_offset_and_invalidates_source_cache(self):
        audio = self.root/'speech.wav'; audio.write_bytes(b'processed')
        record = {'path': str(audio), 'identity': {'start': 100, 'strength': 1}}
        with self.patches():
            prepare(self.editor, self.rows)
            prepare(self.editor, self.rows, audio=record)
        self.assertEqual(self.runs, 2)
        self.assertEqual(self.extracts[1]['track'], 0)
        self.assertAlmostEqual(self.extracts[1]['start'], .88)

    def test_local_complete_window_does_not_promote_invalid_full_row(self):
        self.rows = [{'id': 1, 'start': 101, 'end': 109, 'text': '候，就就是非常',
                     'tokens': [{'text': t, 'anchor': a} for t,a in
                                [('候',101.2),('，',101.3),('就',102),('就',103),
                                 ('是',104),('非',105),('常',106)]]}]
        def infer(args, *unused, **kwargs):
            if args == ['extract']:
                return ''
            request = Path(args[args.index('--requests')+1])
            for job in [json.loads(line) for line in request.read_text(encoding='utf-8').splitlines()]:
                characters = [c for c in job['text'] if c != '，']
                words = [{'text': c, 'start': job['start']+.2+i*.1,
                          'end': job['start']+.3+i*.1} for i,c in enumerate(characters)]
                if job['text'] == self.rows[0]['text']:
                    words[2]['end'] = words[2]['start']
                kwargs['on_line'](json.dumps({'event': 'alignment', 'id': job['id'], 'words': words}))
        with self.patches(), patch('fine_alignment.command', side_effect=infer):
            row = prepare(self.editor, self.rows)[0]
        self.assertFalse(row['alignment_complete'])
        self.assertEqual(row['words'], [])
        self.assertEqual(row['alignment']['status'], 'invalid')
        window = row['word_windows'][0]
        self.assertTrue(window['alignment_complete'])
        self.assertEqual(window['text'], '候，就就是')
        self.assertEqual([w['text'] for w in window['words']], ['候','就','就','是'])
        self.assertTrue(all(w['id'].startswith(window['id']+':') for w in window['words']))
        self.assertFalse(list((self.root/'alignment-cache').glob('*.partial*')))

    def test_missing_component_and_cancel_fail_safely(self):
        with patch('fine_alignment.locations', return_value=(['missing'], self.root/'missing')):
            rows = prepare(self.editor, self.rows)
        self.assertEqual(rows[0]['words'], [])
        self.assertFalse(rows[0]['alignment_complete'])
        self.assertEqual(rows[0]['alignment']['status'], 'unavailable')
        with self.patches(), patch('fine_alignment.command', side_effect=Cancelled()):
            with self.assertRaises(Cancelled):
                prepare(self.editor, self.rows)
        self.assertFalse(list((self.root/'alignment-cache').glob('*.partial*')))


if __name__ == '__main__':
    unittest.main()
