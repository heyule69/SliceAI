import contextlib,copy,io,json,unittest
from unittest.mock import patch
import test_fine
from fine import Editor,get
from fine_auto import DEFAULTS,options_checked,validate_plan,intervals_after_deletions
from service import dispatch
from engine import probe


def grounded_response(messages, remove_ids=()):
    """Provider fixture covers independent schemas, never invents cut times."""
    data=json.loads(messages[1]['content']);system=messages[0]['content']
    if 'combined_candidates' in data:
        return json.dumps({'restore_ids':[],'reason':'合并删点没有破坏关键故事节点与结局'})
    if 'candidates' in data:
        decisions=[]
        for candidate in data['candidates']:
            remove=candidate['id'] in remove_ids
            decisions.append({'id':candidate['id'],'action':'remove' if remove else 'keep',
                'kind':('offtopic' if candidate['kind']=='semantic' else candidate['kind']) if remove else candidate['kind'],
                'reason':'独立闲聊与完整故事无关' if remove else '属于必要故事表达，保留原文','reference_ids':[]})
        return json.dumps({'decisions':decisions})
    rows=data.get('transcript')
    if '只返回 {"nodes"' in system:
        return json.dumps({'nodes':[{'id':rows[0]['id'],'quote':rows[0]['text'][:80],'role':'setup'},
                                    {'id':rows[-1]['id'],'quote':rows[-1]['text'][:80],'role':'ending'}]})
    evidence=([{'id':row['id'],'quote':row['text'][:80]} for row in (rows[0],rows[-1])]
              if rows else [section['evidence'][0] for section in data['ordered_sections']][:4])
    return json.dumps({'summary':'完整的故事铺垫、经过与最终回应','evidence':evidence})


class AutoTest(unittest.TestCase):
    def setUp(self):
        test_fine.FineTest.setUp(self)
        self.align_patch=patch('fine_alignment.prepare',side_effect=self.aligned_fixture)
        self.asr_patch=patch('fine_auto.checked_captions',side_effect=lambda *a,**kw:copy.deepcopy(self.rows))
        self.align_patch.start()
        self.asr_patch.start()
    def tearDown(self):
        self.align_patch.stop();self.asr_patch.stop();test_fine.FineTest.tearDown(self)
    run_cmd=test_fine.FineTest.run_cmd

    def aligned_fixture(self,editor,rows,row_ids=None,audio=None):
        result=copy.deepcopy(rows)
        # Synthetic fixture speech was generated with known segment bounds.
        # Production code never substitutes such distributed timings.
        for row in result:
            if row_ids is not None and row['id'] not in row_ids:continue
            width=(row['end']-row['start'])/len(row['text'])
            row['words']=[{'id':f"{row['id']}:{i}",'text':text,'start':row['start']+i*width,
                           'end':row['start']+(i+1)*width,'timing_method':'forced_alignment'}
                          for i,text in enumerate(row['text'])]
            row['alignment_complete']=True
        return result

    def options(self,**values):return {**DEFAULTS,'cleanup':['offtopic'],'speech':[],'subtitles':'none','normalize':True,**values}
    def plan(self,delete=True):return {'summary':'删掉重复表达，保留故事与反应。','kept_ids':[0,2,3,4,5] if delete else list(range(6)),
        'removed':[{'id':1,'kind':'offtopic','reason':'独立闲聊与故事无关','quote':self.rows[1]['text']}] if delete else []}

    def test_fixed_choices_review_then_preview_and_export_use_same_ranges(self):
        with patch('fine_auto.chat_api',side_effect=lambda settings,messages,*a:grounded_response(messages,['row:1'])) as api:
            self.run_cmd('edit_auto',options=self.options())
            self.assertEqual(api.call_count,4)
        v=self.p['versions'][-1];self.assertTrue(v['confirmed']);self.assertFalse(v['subtitles'])
        self.assertEqual([(r['start'],r['end']) for r in v['ranges']],[(0,2),(3.8,12)])
        self.assertAlmostEqual(v['duration'],10.2);self.assertTrue(v['normalize_audio'])
        self.assertAlmostEqual(probe(v['preview'],self.store.settings(),self.store)['duration'],10.2,delta=.3)
        self.run_cmd('edit_export');self.assertAlmostEqual(self.p['exports'][-1]['duration'],10.2)
        self.assertEqual(self.store.get(self.task['id'])['clips'],self.task['clips'])

    def test_failed_review_keeps_draft_and_retry_reuses_completed_plan(self):
        def fail_final(settings,messages,*a):
            if 'combined_candidates' in json.loads(messages[1]['content']):raise ValueError('API timeout')
            return grounded_response(messages,['row:1'])
        with patch('fine_auto.chat_api',side_effect=fail_final),contextlib.redirect_stdout(io.StringIO()):
            self.p=Editor(self.store,{'cmd':'edit_auto','project_id':self.p['id'],'options':self.options()}).run()
        self.assertIn('timeout',self.p['error']);self.assertEqual(self.p['versions'],[])
        with patch('fine_auto.chat_api',side_effect=lambda settings,messages,*a:grounded_response(messages)) as api:
            self.run_cmd('edit_auto',options=self.options())
            self.assertEqual(api.call_count,1)
        self.assertAlmostEqual(self.p['versions'][-1]['duration'],10.2)

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
        with patch('fine_auto.chat_api',side_effect=lambda settings,messages,*a:grounded_response(messages)) as api,patch.object(Editor,'render') as render,\
                patch('fine_audio.prepare',return_value={'identity':{'test':True}}),\
                patch('fine_auto.checked_captions',return_value=copy.deepcopy(self.rows)),contextlib.redirect_stdout(io.StringIO()):
            self.p=Editor(self.store,{'cmd':'edit_auto','project_id':self.p['id'],'options':self.options(music='reduce')}).run()
        self.assertFalse(self.p['error']);self.assertEqual(api.call_count,3);render.assert_called_once()
        self.assertEqual(self.p['versions'][-1]['audio_strength'],1);self.assertIsNone(self.p['audio_sample'])

    def test_subtitle_audio_disagreement_is_flagged(self):
        fresh=copy.deepcopy(self.rows);fresh[0]['text']='重新听到的不同内容'
        with patch('fine_auto.chat_api',side_effect=lambda settings,messages,*a:grounded_response(messages)),patch('fine_auto.checked_captions',return_value=fresh):
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
        with patch('fine_auto.chat_api',side_effect=lambda settings,messages,*a:grounded_response(messages,['row:1'])),patch.object(Editor,'render'):
            self.run_cmd('edit_auto',options=self.options())
        v=self.p['versions'][-1]
        self.assertEqual(v['duration'],12);self.assertEqual(v['removed'],[])
        self.assertEqual(v['auto_review']['protected'][0]['id'],1)

    def test_word_retakes_use_same_source_clock_for_audio_and_hidden_captions(self):
        fresh=copy.deepcopy(self.rows);fresh[1]['text']='就就是这样'
        fresh[1]['words']=[{'id':f'1:{i}','text':text,'start':2+i*.25,'end':2+i*.25+.2,
                            'timing_method':'forced_alignment'} for i,text in enumerate(fresh[1]['text'])]
        fresh[1]['alignment_complete']=True
        cid='word:1:0:1:retakes'
        with patch('fine_auto.checked_captions',return_value=fresh) as asr,\
                patch('fine_alignment.prepare',return_value=fresh) as align,\
                patch('fine_auto.chat_api',side_effect=lambda settings,messages,*a:grounded_response(messages,[cid])):
            self.run_cmd('edit_auto',options=self.options(cleanup=[],speech=['retakes'],subtitles='none'))
        asr.assert_called_once();self.assertEqual(align.call_args.kwargs['row_ids'],{1})
        version=self.p['versions'][-1]
        self.assertFalse(version['subtitles'])
        self.assertAlmostEqual(version['removed_duration'],.225)
        self.assertEqual(version['removed'][0]['candidate_ids'],[cid])
        self.assertIn('就是这样',[cue['text'] for cue in version['cues']])
        self.assertNotIn('就就是这样',[cue['text'] for cue in version['cues']])
        self.run_cmd('edit_export',srt=True)
        self.assertAlmostEqual(self.p['exports'][-1]['duration'],11.775)

    def test_final_combined_review_restores_cut_and_reports_zero_actual_removal(self):
        def provider(settings,messages,*args):
            payload=json.loads(messages[1]['content'])
            if 'combined_candidates' in payload:
                return json.dumps({'restore_ids':['row:1'],'reason':'该句承载回应，组合删除后故事缺少因果'})
            return grounded_response(messages,['row:1'])
        with patch('fine_auto.chat_api',side_effect=provider),patch.object(Editor,'render'):
            self.run_cmd('edit_auto',options=self.options())
        version=self.p['versions'][-1]
        self.assertEqual(version['removed'],[]);self.assertEqual(version['duration'],12)
        self.assertEqual(version['auto_review']['applied_removals'],0)
        self.assertIn('未产生精简',version['summary'])
        candidate=next(c for c in version['cut_ledger'] if c['id']=='row:1')
        self.assertEqual(candidate['status'],'blocked');self.assertIn('全事件复核恢复',candidate['block_reason'])

    def test_model_approved_whole_row_still_requires_reliable_speech_boundaries(self):
        with patch('fine_auto.chat_api',side_effect=lambda settings,messages,*a:grounded_response(messages,['row:1'])),\
                patch('fine_alignment.prepare',side_effect=lambda editor,rows,**kw:rows),patch.object(Editor,'render'):
            self.run_cmd('edit_auto',options=self.options())
        version=self.p['versions'][-1]
        self.assertEqual(version['duration'],12);self.assertEqual(version['removed'],[])
        candidate=next(c for c in version['cut_ledger'] if c['id']=='row:1')
        self.assertEqual(candidate['status'],'blocked');self.assertIn('字词边界',candidate['block_reason'])

    def test_aligned_words_expose_long_internal_gap_but_original_sound_still_blocks(self):
        fresh=[{'id':0,'start':0.,'end':10.,'text':'甲乙','alignment_complete':True,
                'words':[{'id':'0:0','text':'甲','start':.5,'end':1.,'timing_method':'forced_alignment'},
                         {'id':'0:1','text':'乙','start':7.,'end':8.,'timing_method':'forced_alignment'}]}]
        with patch('fine_auto.checked_captions',return_value=fresh),patch.object(Editor,'render'),\
                patch('fine_auto.chat_api',side_effect=lambda settings,messages,*a:grounded_response(messages)):
            self.run_cmd('edit_auto',options=self.options(cleanup=[],speech=['silence']))
        version=self.p['versions'][-1]
        gap=next(c for c in version['cut_ledger'] if c['evidence'][0]['type']=='forced_word_gap')
        self.assertEqual(gap['word_ids'],['0:0','0:1']);self.assertEqual(gap['row_ids'],[0])
        self.assertEqual(gap['status'],'blocked');self.assertEqual(version['removed'],[])

    def test_partial_local_alignment_cuts_retakes_and_relistens_retained_caption(self):
        fresh=copy.deepcopy(self.rows);row=fresh[1];row.update(text='就就是这样',words=[],alignment_complete=False)
        window={'id':'1:local:0:3','text':'就就是','char_start':0,'char_end':3,'start':2.,'end':3.2,
            'alignment_complete':True,'words':[{'id':f'1:local:0:3:{i}','text':text,'start':2+i*.25,
                'end':2+i*.25+.2,'timing_method':'forced_alignment'} for i,text in enumerate('就就是')]}
        row['word_windows']=[window]
        targets=[]
        def captions(editor,audio=None,clip=None):
            if clip is None:return fresh
            targets.append(clip)
            return [{'id':0,'start':clip['start'],'end':clip['end'],'text':'就是这样'}]
        cid='word:1:1:local:0:3:0:1:retakes'
        with patch('fine_auto.checked_captions',side_effect=captions),\
                patch('fine_alignment.prepare',return_value=fresh),\
                patch('fine_auto.chat_api',side_effect=lambda settings,messages,*a:grounded_response(messages,[cid])):
            self.run_cmd('edit_auto',options=self.options(cleanup=[],speech=['retakes'],subtitles='basic'))
        version=self.p['versions'][-1]
        self.assertEqual(targets,[{'start':2.225,'end':3.8}])
        self.assertAlmostEqual(version['removed_duration'],.225)
        self.assertIn('就是这样',[cue['text'] for cue in version['cues']])
        self.assertFalse(version['transcript_rows'][1]['alignment_complete'])
        self.assertEqual(version['transcript_rows'][1]['words'],[])

if __name__=='__main__':unittest.main()
