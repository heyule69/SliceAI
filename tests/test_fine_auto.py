import contextlib,copy,io,json,unittest
from unittest.mock import patch
import test_fine
from fine import Editor,get
from fine_auto import DEFAULTS,options_checked,validate_plan,intervals_after_deletions
from service import dispatch
from engine import probe


class AutoTest(unittest.TestCase):
    setUp=test_fine.FineTest.setUp
    tearDown=test_fine.FineTest.tearDown
    run_cmd=test_fine.FineTest.run_cmd

    def options(self,**values):return {**DEFAULTS,'cleanup':['repeats'],'speech':[],'subtitles':'none','normalize':True,**values}
    def plan(self,delete=True):return {'summary':'删掉重复表达，保留故事与反应。','kept_ids':[0,2,3,4,5] if delete else list(range(6)),
        'removed':[{'id':1,'kind':'repeats','reason':'与前一句重复','quote':self.rows[1]['text']}] if delete else []}

    def test_fixed_choices_review_then_preview_and_export_use_same_ranges(self):
        with patch('fine_auto.chat_api',return_value=json.dumps(self.plan())) as api:
            self.run_cmd('edit_auto',options=self.options())
            self.assertEqual(api.call_count,2)
        v=self.p['versions'][-1];self.assertTrue(v['confirmed']);self.assertFalse(v['subtitles'])
        self.assertEqual([(r['start'],r['end']) for r in v['ranges']],[(0,2),(3.8,12)])
        self.assertAlmostEqual(v['duration'],10.2);self.assertTrue(v['normalize_audio'])
        self.assertAlmostEqual(probe(v['preview'],self.store.settings(),self.store)['duration'],10.2,delta=.3)
        self.run_cmd('edit_export');self.assertAlmostEqual(self.p['exports'][-1]['duration'],10.2)
        self.assertEqual(self.store.get(self.task['id'])['clips'],self.task['clips'])

    def test_failed_review_keeps_draft_and_retry_reuses_completed_plan(self):
        with patch('fine_auto.chat_api',side_effect=[json.dumps(self.plan()),ValueError('API timeout')]),contextlib.redirect_stdout(io.StringIO()):
            self.p=Editor(self.store,{'cmd':'edit_auto','project_id':self.p['id'],'options':self.options()}).run()
        self.assertIn('timeout',self.p['error']);self.assertEqual(self.p['versions'],[])
        with patch('fine_auto.chat_api',return_value=json.dumps(self.plan(False))) as api:
            self.run_cmd('edit_auto',options=self.options())
            self.assertEqual(api.call_count,1)
        self.assertEqual(self.p['versions'][-1]['duration'],12)

    def test_unselected_deletions_missing_sentences_and_false_evidence_fail_closed(self):
        raw=self.plan()
        with self.assertRaises(ValueError):validate_plan(raw,self.rows,self.options(cleanup=[]))
        for field,value in [('quote','不存在的文字'),('kind','invented')]:
            bad=copy.deepcopy(raw);bad['removed'][0][field]=value
            with self.assertRaises(ValueError):validate_plan(bad,self.rows,self.options())
        bad=copy.deepcopy(raw);bad['kept_ids'].pop()
        with self.assertRaises(ValueError):validate_plan(bad,self.rows,self.options())
        bad=copy.deepcopy(raw);bad['kept_ids'].append(1)
        with self.assertRaises(ValueError):validate_plan(bad,self.rows,self.options())

    def test_options_persist_and_music_applies_without_audition(self):
        req={'cmd':'edit_options','_data_dir':str(self.store.root),'project_id':self.p['id'],'revision':self.p['revision'],'options':self.options(),'step':3}
        with contextlib.redirect_stdout(io.StringIO()),patch('fine_auto.chat_api') as api:self.p=dispatch(req)
        api.assert_not_called();self.assertEqual(get(self.store,self.p['id'])['question_step'],3)
        with self.assertRaisesRegex(ValueError,'新修改'):dispatch(req)
        with patch('fine_auto.chat_api',return_value=json.dumps(self.plan(False))) as api,patch.object(Editor,'render') as render,\
                patch('fine_audio.prepare',return_value={'identity':{'test':True}}),\
                patch('fine_auto.checked_captions',return_value=copy.deepcopy(self.rows)),contextlib.redirect_stdout(io.StringIO()):
            self.p=Editor(self.store,{'cmd':'edit_auto','project_id':self.p['id'],'options':self.options(music='reduce')}).run()
        self.assertFalse(self.p['error']);self.assertEqual(api.call_count,2);render.assert_called_once()
        self.assertEqual(self.p['versions'][-1]['audio_strength'],1);self.assertIsNone(self.p['audio_sample'])

    def test_subtitle_audio_disagreement_is_flagged(self):
        fresh=copy.deepcopy(self.rows);fresh[0]['text']='重新听到的不同内容'
        with patch('fine_auto.chat_api',return_value=json.dumps(self.plan(False))),patch('fine_auto.checked_captions',return_value=fresh):
            self.run_cmd('edit_auto',options=self.options(subtitles='checked'))
        v=self.p['versions'][-1];self.assertIn(1,v['caption_review']['needs_review'])
        self.assertEqual(v['cues'][0]['text'],fresh[0]['text'])

    def test_untranscribed_reactions_are_retained_and_overlapping_deletions_merge(self):
        ranges=intervals_after_deletions({'start':0,'end':12},[(2,4),(3,5),(8,9)])
        self.assertEqual([(r['start'],r['end']) for r in ranges],[(0,2),(5,8),(9,12)])
        self.assertEqual(options_checked(self.options(cleanup=[]))['cleanup'],[])

    def test_sparse_transcript_cannot_delete_a_long_unverified_audio_span(self):
        rows=copy.deepcopy(self.rows);rows[1].update(start=2,end=8,text='啊')
        self.rows=rows
        (self.store.task_dir(self.task['id'])/'transcript.json').write_text(json.dumps(rows,ensure_ascii=False),encoding='utf-8')
        with patch('fine_auto.chat_api',return_value=json.dumps(self.plan())),patch.object(Editor,'render'):
            self.run_cmd('edit_auto',options=self.options())
        v=self.p['versions'][-1]
        self.assertEqual(v['duration'],12);self.assertEqual(v['removed'],[])
        self.assertEqual(v['auto_review']['protected'][0]['id'],1)

if __name__=='__main__':unittest.main()
