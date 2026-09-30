import copy
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from fine_auto import DEFAULTS, reconcile_audio, intervals_after_deletions
from fine_candidates import generate, validate_decisions, reliable_words, merge_removed, execution_summary, timed_streams
from fine_gaps import characterize
from fine_story import final_review


class CandidatesTest(unittest.TestCase):
    def words(self,text='就就是这样'):
        return {'id':7,'start':10.,'end':12.,'text':text,
            'words':[{'id':f'7:{i}','text':char,'start':10+i*.3,'end':10+i*.3+.2,
                      'timing_method':'forced_alignment'} for i,char in enumerate(text)]}

    def options(self,**values):
        return {**DEFAULTS,'cleanup':[],'speech':['retakes'],**values}

    def test_token_emission_cannot_cut_word_or_generate_fake_end(self):
        row={'id':7,'start':10.,'end':12.,'text':'就就是这样',
             'tokens':[{'text':'就','anchor':10.2},{'text':'就','anchor':10.7}]}
        proposals=generate([row],self.options(),{'start':10.,'end':12.})
        self.assertEqual(len(proposals),1)
        self.assertEqual(proposals[0]['status'],'blocked')
        self.assertIsNone(proposals[0]['start']);self.assertIsNone(proposals[0]['end'])
        self.assertEqual(merge_removed(proposals,{'start':10.,'end':12.}),[])

    def test_tandem_word_candidate_is_grounded_and_keeps_neighbor_syllables(self):
        row=self.words();proposals=generate([row],self.options(),{'start':10.,'end':12.})
        self.assertEqual(len(proposals),1)
        c=proposals[0];self.assertEqual(c['word_ids'],['7:0']);self.assertEqual(c['quote'],'就')
        self.assertLessEqual(c['end'],row['words'][1]['start'])
        decision=validate_decisions({'decisions':[{'id':c['id'],'action':'remove','kind':'retakes',
            'reason':'删除前一次无语义重说'}]},proposals,[row],self.options())
        self.assertEqual(decision['decisions'][0]['id'],c['id'])
        c.update(status='applied',reason='删除前一次重说')
        cut=merge_removed(proposals,{'start':10.,'end':12.})[0]
        ranges=intervals_after_deletions({'start':10.,'end':12.},[(cut['start'],cut['end'])])
        self.assertTrue(any(r['start']<=row['words'][1]['start'] and r['end']>=row['words'][-1]['end'] for r in ranges))

    def test_distributive_repetition_keeps_sentence_by_sentence_meaning(self):
        for text in ('一句一句反驳','一步一步来','一点一点说'):
            row=self.words(text)
            row['end']=row['words'][-1]['end']+.1
            proposals=generate([row],self.options(),{'start':10.,'end':row['end']})
            self.assertTrue(proposals)
            self.assertTrue(all(candidate['status']=='blocked' for candidate in proposals))
            self.assertTrue(all('逐一或渐进' in candidate['block_reason'] for candidate in proposals))
        normal=generate([self.words()],self.options(),{'start':10.,'end':12.})
        self.assertEqual(normal[0]['status'],'suggested')

    def test_words_must_match_full_source_and_have_real_nonoverlapping_ends(self):
        for mutation in ('overlap','wrong_text','emission'):
            row=self.words()
            if mutation=='overlap':row['words'][1]['start']=10.1
            if mutation=='wrong_text':row['words'][0]['text']='它'
            if mutation=='emission':row['words'][0]['timing_method']='ctc_emission'
            self.assertEqual(reliable_words(row),[])
            self.assertTrue(all(c['status']=='blocked' for c in generate([row],self.options(),{'start':10.,'end':12.})))

    def test_resegmented_same_audio_does_not_blanket_protect_story(self):
        original=[{'id':0,'start':0.,'end':6.,'text':'猫去洗澡回来生病了'}]
        fresh=[{'id':0,'start':.1,'end':2.,'text':'猫去洗澡'},
               {'id':1,'start':3.,'end':5.,'text':'回来生病了'}]
        rows,protected=reconcile_audio(original,fresh,separated=False)
        self.assertEqual(protected,[]);self.assertFalse(any('analysis_note' in row for row in rows))
        changed=[dict(fresh[0],text='听成别的字'),fresh[1]]
        rows,protected=reconcile_audio(original,changed,separated=False)
        self.assertEqual(protected,[]);self.assertTrue(rows[0]['caption_warning'])
        self.assertNotIn('analysis_note',rows[0])

    def test_separation_loss_stays_local_and_laughter_is_always_preserved(self):
        original=[{'id':0,'start':0.,'end':2.,'text':'开始讲故事'},
                  {'id':1,'start':2.,'end':4.,'text':'哈哈哈'},
                  {'id':2,'start':5.,'end':7.,'text':'最后商家退钱了'}]
        rows,protected=reconcile_audio(original,[dict(original[0]),dict(original[2])],separated=True)
        self.assertTrue(any(p['start']==2 and p['end']==4 for p in protected))
        self.assertFalse(any(p['start']>=5 for p in protected))
        self.assertTrue(next(row for row in rows if row['start']==2)['original_fallback'])

    def test_provider_cannot_invent_ids_unselected_kinds_or_repeat_evidence(self):
        row=self.words('这是故事结尾');options=self.options(cleanup=['repeats'],speech=[])
        candidate=generate([row],options,{'start':10.,'end':12.})[0]
        for decision in ({'id':'invented','action':'remove','kind':'repeats','reason':'重复内容删除'},
                         {'id':candidate['id'],'action':'remove','kind':'greetings','reason':'删除例行招呼'},
                         {'id':candidate['id'],'action':'remove','kind':'repeats','reason':'重复表达删除','reference_ids':[7]}):
            with self.assertRaises(ValueError):validate_decisions({'decisions':[decision]},[candidate],[row],options)
        with self.assertRaises(ValueError):validate_decisions({'decisions':[]},[candidate],[row],options)

    def test_emotional_repetition_is_blocked_before_model_and_summary_is_actual(self):
        row=self.words('呜呜呜');row['asr']={'event':'crying','emotion':'sad'}
        proposals=generate([row],self.options(),{'start':10.,'end':12.})
        self.assertTrue(proposals);self.assertTrue(all(c['status']=='blocked' for c in proposals))
        summary=execution_summary({'start':10.,'end':12.},[{'start':10.,'end':12.}],proposals)
        self.assertIn('未产生精简',summary);self.assertNotIn('删除重复',summary)

    def test_effective_removed_union_does_not_double_count_overlapping_candidates(self):
        ledger=[{'id':'a','start':2.,'end':5.,'kind':'offtopic','status':'applied','reason':'无关闲聊','text':'甲'},
                {'id':'b','start':4.,'end':6.,'kind':'retakes','status':'applied','reason':'重说内容','text':'乙'},
                {'id':'c','start':8.,'end':9.,'kind':'silence','status':'blocked','reason':'原声反应','text':''}]
        removed=merge_removed(ledger,{'start':0.,'end':12.})
        self.assertEqual([(r['start'],r['end']) for r in removed],[(2.,6.)])
        ranges=intervals_after_deletions({'start':0.,'end':12.},[(r['start'],r['end']) for r in removed])
        self.assertIn('删除 4.00 秒',execution_summary({'start':0.,'end':12.},ranges,ledger))

    def test_gap_requires_original_audio_evidence_not_vad_absence(self):
        import numpy as np
        rate=16000;t=np.arange(rate*8)/rate
        song=.15*np.sin(2*np.pi*440*t)
        self.assertFalse(characterize(song,rate,2.,6.)['safe'])
        quiet=song.copy();quiet[2*rate:6*rate]=0
        self.assertTrue(characterize(quiet,rate,2.,6.)['safe'])
        burst=quiet.copy();burst[3*rate:4*rate]=song[3*rate:4*rate]
        self.assertFalse(characterize(burst,rate,2.,6.)['safe'])

    def test_combined_review_can_restore_only_existing_cut_ids(self):
        editor=SimpleNamespace(context=[{'id':0,'start':0.,'end':2.,'text':'完整结局'}],persist=lambda *a:None)
        selected=[{'id':'row:0','kind':'offtopic','quote':'完整结局','row_ids':[0],
                   'reason':'误判断无关','evidence':[]}]
        def cached(editor,kind,system,payload,validate,**kwargs):
            self.assertEqual(payload['combined_candidates'][0]['quote'],'完整结局')
            return validate({'restore_ids':['row:0'],'reason':'恢复原文结尾以保留故事结果'})
        result=final_review(editor,selected,DEFAULTS,{'outline':{'summary':'完整故事'},'nodes':[]},cached)
        self.assertEqual(result['restore_ids'],['row:0'])
        def invented(editor,kind,system,payload,validate,**kwargs):
            return validate({'restore_ids':['row:99'],'reason':'引用不存在的删除编号'})
        with self.assertRaises(ValueError):final_review(editor,selected,DEFAULTS,{'outline':{},'nodes':[]},invented)

    def test_local_complete_window_is_not_vetoed_by_distant_uncertain_words(self):
        row={'id':7,'start':10.,'end':15.,'text':'我心疼，就就是这样','words':[],'alignment_complete':False,
             'asr':{'emotion':'<|SAD|>','event':'<|Speech|>'}}
        first=row['text'].index('就');text=row['text'][first:first+3]
        window={'id':'7:local:4:7','text':text,'char_start':first,'char_end':first+3,'start':11.,'end':13.,
                'alignment_complete':True,'words':[{'id':f'7:local:{i}','text':char,'start':11.1+i*.5,
                    'end':11.3+i*.5,'timing_method':'forced_alignment'} for i,char in enumerate(text)]}
        row['word_windows']=[window]
        self.assertEqual(reliable_words(row),[])
        result=generate([row],self.options(),{'start':10.,'end':15.})
        self.assertEqual(len(result),1);candidate=result[0]
        self.assertEqual(candidate['status'],'suggested');self.assertEqual(candidate['quote'],'就')
        self.assertEqual(candidate['char_start'],first);self.assertEqual(candidate['char_end'],first+1)
        self.assertEqual(candidate['row_ids'],[7]);self.assertEqual(candidate['word_ids'],['7:local:0'])
        self.assertIn(window['id'],candidate['id']);self.assertEqual(row['words'],[])
        self.assertFalse(row['alignment_complete'])
        # Local scope does not cancel whole-row emotional protection.
        semantic=generate([row],self.options(cleanup=['offtopic']),{'start':10.,'end':15.})
        self.assertEqual(next(c for c in semantic if c['kind']=='semantic')['status'],'blocked')

    def test_window_quote_must_literally_match_source_and_bad_span_stays_unusable(self):
        row=self.words();row['words']=[];row['alignment_complete']=False
        window={'id':'local','text':'就就','char_start':0,'char_end':2,'start':10.,'end':11.,
                'alignment_complete':True,'words':[{'id':'local:0','text':'就','start':10.,'end':10.2,'timing_method':'forced_alignment'},
                {'id':'local:1','text':'就','start':10.4,'end':10.6,'timing_method':'forced_alignment'}]}
        for kind in ('quote','zero','incomplete','edited'):
            altered=copy.deepcopy(row);altered['word_windows']=[copy.deepcopy(window)]
            if kind=='quote':altered['word_windows'][0]['text']='甲甲'
            if kind=='zero':altered['word_windows'][0]['words'][1]['end']=10.4
            if kind=='incomplete':altered['word_windows'][0]['alignment_complete']=False
            if kind=='edited':altered['user_edited']=True
            self.assertEqual(timed_streams(altered),[])
            self.assertTrue(all(c['status']=='blocked' for c in generate([altered],self.options(),{'start':10.,'end':12.})))


if __name__=='__main__':unittest.main()
