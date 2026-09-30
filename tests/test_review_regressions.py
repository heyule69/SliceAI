import contextlib
import copy
import io
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

import test_fine
from caption_timeline import crosses_cut, refresh_boundaries, source_rows, mark_partial_groups
from fine import Editor, get, save
from fine_auto import DEFAULTS, plan_event
from pipeline import Runner
from service import dispatch
from engine import probe, tool_path


class ReviewRegressionTest(unittest.TestCase):
    setUp = test_fine.FineTest.setUp
    tearDown = test_fine.FineTest.tearDown
    run_cmd = test_fine.FineTest.run_cmd
    plan = test_fine.FineTest.plan

    def test_cached_export_still_obeys_later_source_recheck(self):
        self.task['clips'][0]['score']=90
        self.store.put(self.task)
        self.plan()
        self.run_cmd('edit_confirm')
        self.run_cmd('edit_export')
        with patch('pipeline.review_clip', return_value={'decision': 'exclude', 'reason': '外部播放'}), \
                contextlib.redirect_stdout(io.StringIO()):
            task = Runner(self.store, self.task['id']).recheck()
        self.assertEqual(task['clips'], [])
        with patch('source_review.review_clip') as review, contextlib.redirect_stdout(io.StringIO()):
            result = Editor(self.store, {'cmd': 'edit_export', 'project_id': self.p['id']}).run()
        self.assertIn('来源复核过滤', result['error'])
        self.assertEqual(len(result['exports']), 1)
        self.assertTrue(Path(result['exports'][0]['path']).is_file())
        review.assert_not_called()

    def test_checked_subtitles_survive_range_changes_and_saved_user_edits(self):
        editor = Editor(self.store, {'project_id': self.p['id']})
        version = editor.version([{'start': 0, 'end': 12}], '字幕核对')
        fresh = copy.deepcopy(self.rows)
        fresh[0]['text'] = '重新核对的正确字幕'
        version['transcript_rows'] = fresh
        version['cues'] = test_fine.mapped_cues(fresh, version['ranges'])
        with contextlib.redirect_stdout(io.StringIO()):
            self.p = editor.persist()
        self.run_cmd('edit_update', ranges=[{'start': 0, 'end': 10}])
        self.assertEqual(self.p['versions'][-1]['cues'][0]['text'], fresh[0]['text'])
        cues = copy.deepcopy(self.p['versions'][-1]['cues'])
        cues[0]['text'] = '用户改好的字幕'
        self.run_cmd('edit_update', cues=cues)
        self.run_cmd('edit_update', ranges=[{'start': 0, 'end': 8}])
        self.assertEqual(self.p['versions'][-1]['cues'][0]['text'], '用户改好的字幕')

    def test_cut_crossing_sentence_relistens_to_only_retained_audio(self):
        editor = Editor(self.store, {'project_id': self.p['id']})
        version = editor.version([{'start': 0, 'end': 2}], '保留前半句')
        version['transcript_rows'] = [{'id': 0, 'start': 0, 'end': 3.8, 'text': '保留部分加上已经删掉的台词'}]
        self.assertTrue(crosses_cut(version['transcript_rows'], version['ranges']))
        with patch('fine_auto.checked_captions', return_value=[{'id': 0, 'start': 0, 'end': 2, 'text': '只有保留部分'}]) as transcribe, \
                contextlib.redirect_stdout(io.StringIO()):
            refresh_boundaries(editor, version)
        self.assertEqual(version['cues'][0]['text'], '只有保留部分')
        self.assertEqual(transcribe.call_args.kwargs['clip'], {'start':0,'end':2})

    def test_boundary_refresh_preserves_user_words_and_unrelated_warning(self):
        editor=Editor(self.store,{'project_id':self.p['id']})
        version=editor.version([{'start':1,'end':6}],'手改保留')
        version['subtitle_rows']=[{'id':0,'start':0,'end':4,'text':'旧整句'},
            {'id':1,'start':2,'end':3,'text':'修正文','user_edited':True},
            {'id':2,'start':4,'end':6,'text':'原声反应','original_fallback':True,'analysis_note':'需要核对'}]
        version['cues']=test_fine.mapped_cues(version['subtitle_rows'],version['ranges'])
        version['caption_review']={'needs_review':[3]}
        calls=[]
        def recognize(editor,audio,clip):
            calls.append(clip)
            return [{'id':0,**clip,'text':'前文' if clip['start']==1 else '后文'}]
        with patch('fine_auto.checked_captions',side_effect=recognize),contextlib.redirect_stdout(io.StringIO()):
            refresh_boundaries(editor,version)
        self.assertEqual(calls,[{'start':1,'end':2},{'start':3,'end':4}])
        self.assertEqual([c['text'] for c in version['cues']],['前文','修正文','后文','原声反应'])
        self.assertEqual(version['caption_review']['needs_review'],[4])

    def test_expanding_range_restores_previously_excluded_subtitles(self):
        editor=Editor(self.store,{'project_id':self.p['id']})
        version=editor.version([{'start':2,'end':4}],'短区间')
        version['transcript_rows']=[{'id':0,'start':0,'end':5,'text':'完整前段'},
                                    {'id':1,'start':5,'end':10,'text':'完整后段'}]
        with patch('fine_auto.checked_captions',return_value=[{'id':0,'start':2,'end':4,'text':'前段中间'}]),contextlib.redirect_stdout(io.StringIO()):
            refresh_boundaries(editor,version)
            self.p=editor.persist()
        self.run_cmd('edit_update',ranges=[{'start':0,'end':10}])
        expanded=self.p['versions'][-1]
        self.assertIn('完整后段',[c['text'] for c in expanded['cues']])
        self.assertEqual(expanded['cues'][0]['start'],0)
        self.assertTrue(expanded['caption_boundary_pending'])

    def test_saved_empty_captions_do_not_revive_but_outside_source_is_kept(self):
        editor=Editor(self.store,{'project_id':self.p['id']})
        editor.version([{'start':0,'end':4}],'删除字幕')
        with contextlib.redirect_stdout(io.StringIO()):self.p=editor.persist()
        self.run_cmd('edit_update',cues=[])
        self.run_cmd('edit_update',ranges=[{'start':0,'end':8}])
        cues=self.p['versions'][-1]['cues']
        self.assertTrue(cues)
        self.assertTrue(all(c['start']>=4 for c in cues))

    def test_saving_captions_preserves_warnings_outside_edited_range(self):
        editor=Editor(self.store,{'project_id':self.p['id']})
        version=editor.version([{'start':0,'end':4}],'核对前段')
        version['subtitle_rows']=copy.deepcopy(self.rows)
        version['caption_review_regions']=[{'start':6,'end':8}]
        with contextlib.redirect_stdout(io.StringIO()):self.p=editor.persist()
        self.run_cmd('edit_update',cues=[{'start':0,'end':4,'text':'用户核对过的前段'}])
        self.run_cmd('edit_update',ranges=[{'start':0,'end':8}])
        restored=self.p['versions'][-1]
        self.assertTrue(restored['caption_review']['needs_review'])
        self.assertNotIn(1,restored['caption_review']['needs_review'])

    def test_merged_user_cue_maps_once_and_partial_group_requires_relistening(self):
        from fine import mapped_cues
        ranges=[{'start':0,'end':1},{'start':3,'end':4}]
        rows=source_rows([{'id':1,'start':0,'end':2,'text':'前后合并'}],ranges)
        self.assertEqual(mapped_cues(rows,ranges),[{'id':1,'start':0,'end':2,'text':'前后合并'}])
        self.assertTrue(crosses_cut(mark_partial_groups(rows,ranges[:1]),ranges[:1]))

    def test_restoring_half_of_previously_merged_cue_cannot_restore_full_sentence(self):
        editor=Editor(self.store,{'project_id':self.p['id']})
        ranges=[{'start':0,'end':1},{'start':3,'end':4}]
        version=editor.version(ranges[:1],'保留前段')
        version['subtitle_rows']=source_rows([{'id':1,'start':0,'end':2,'text':'前段后段合并'}],ranges)
        def recognize(editor,audio,clip):return [{'id':0,**clip,'text':'前段' if clip['start']==0 else '后段'}]
        with patch('fine_auto.checked_captions',side_effect=recognize),contextlib.redirect_stdout(io.StringIO()):
            refresh_boundaries(editor,version)
            version['ranges']=ranges
            self.assertTrue(crosses_cut(mark_partial_groups(version['subtitle_rows'],ranges),ranges))
            refresh_boundaries(editor,version)
        self.assertEqual([cue['text'] for cue in version['cues']],['前段','后段'])

    def test_failed_render_cleans_all_intermediates_and_keeps_final(self):
        from fine import render_scratch
        folder=self.root/'scratch';folder.mkdir()
        names=['part-0.mp4','part-0.partial.mp4','joined.mp4','render.partial.mp4','edited-audio.wav']
        for name in names:(folder/name).write_bytes(b'partial')
        (folder/'render.mp4').write_bytes(b'completed')
        with self.assertRaises(RuntimeError),render_scratch(folder,1):raise RuntimeError('worker failed')
        self.assertTrue((folder/'render.mp4').is_file())
        self.assertFalse(any((folder/name).exists() for name in names))

    def test_grounded_outline_rejects_cross_batch_and_parent_evidence(self):
        from analysis_budget import grounded_outline
        from types import SimpleNamespace
        runner=SimpleNamespace(store=None,task_id='fixture')
        rows=[{'id':i,'start':i,'end':i+.5,'text':'相同原文'} for i in range(50)]
        def wrong(*args):return {'summary':'无效跨批','evidence':[{'id':0,'quote':'相同原文'}]}
        with patch('events.cached_api',side_effect=wrong),patch('engine.check_cancel'):
            with self.assertRaises(ValueError):grounded_outline(runner,rows)
        def wrong_parent(runner,kind,system,payload):
            if 'transcript' in payload:
                return {'summary':'此批','evidence':[{'id':payload['transcript'][0]['id'],'quote':'相同原文'}]}
            return {'summary':'父层捏造证据','evidence':[{'id':1,'quote':'相同原文'}]}
        with patch('events.cached_api',side_effect=wrong_parent),patch('engine.check_cancel'):
            with self.assertRaises(ValueError):grounded_outline(runner,rows)

    def test_fine_outline_uses_only_source_excerpts_after_invalid_quotes(self):
        from analysis_budget import grounded_outline
        from types import SimpleNamespace
        runner=SimpleNamespace(store=None,task_id='fixture')
        rows=[{'id':i,'text':f'第{i}段原话，含起因及后续。'} for i in range(50)]
        requests=[]
        def invalid(runner,kind,system,payload):
            requests.append(payload)
            return {'summary':'改写内容','evidence':[{'id':0,'quote':'模型编写的引文'}]}
        with patch('engine.check_cancel'):
            outline=grounded_outline(runner,rows,request=invalid,source_fallback=True)
        self.assertEqual(outline['method'],'source_excerpts')
        source={row['id']:row['text'] for row in rows}
        self.assertTrue(all(item['quote'] in source[item['id']] for item in outline['evidence']))
        self.assertEqual(outline['evidence'][0]['id'],0)
        self.assertEqual(outline['evidence'][-1]['id'],49)
        self.assertTrue(any('ordered_sections' in payload for payload in requests))
        def failure(*args):raise RuntimeError('provider unavailable')
        with patch('engine.check_cancel'),self.assertRaises(RuntimeError):
            grounded_outline(runner,rows,request=failure,source_fallback=True)

    def test_fine_outline_rebinds_only_unique_literal_quotes_in_current_input(self):
        from analysis_budget import grounded_outline
        from types import SimpleNamespace
        runner=SimpleNamespace(store=None,task_id='fixture')
        rows=[{'id':10,'text':'开端原文。'},{'id':20,'text':'唯一结尾原话。'}]
        wrong={'summary':'完整经过','evidence':[{'id':1,'quote':'唯一结尾原话'}]}
        with patch('engine.check_cancel'):
            outline=grounded_outline(runner,rows,request=lambda *args:wrong,source_fallback=True)
        self.assertEqual(outline['evidence'],[{'id':20,'quote':'唯一结尾原话'}])
        self.assertTrue(outline['source_quote_id_repair'])
        self.assertEqual(wrong['evidence'][0]['id'],1)
        repeated=[{'id':10,'text':'相同原文'},{'id':20,'text':'相同原文'}]
        with patch('engine.check_cancel'):
            ambiguous=grounded_outline(runner,repeated,request=lambda *args:{
                'summary':'含糊引用','evidence':[{'id':1,'quote':'相同原文'}]},source_fallback=True)
        self.assertTrue(ambiguous['source_excerpt_fallback'])
        self.assertNotIn('source_quote_id_repair',ambiguous)

    def test_story_nodes_rebind_only_unique_exact_source_quote(self):
        from fine_story import build_story
        from types import SimpleNamespace
        rows=[{'id':10,'start':0,'end':1,'text':'开端原文'},
              {'id':20,'start':1,'end':2,'text':'唯一后续原话'}]
        editor=SimpleNamespace(context=rows,store=None,p={'id':'fixture'},persist=lambda *args:None)
        def cached(editor,kind,system,payload,validate,**kwargs):
            self.assertIn('json',system.lower())
            return validate({'nodes':[{'id':1,'quote':'唯一后续原话','role':'ending'}]})
        with patch('fine_story.grounded_outline',return_value={'summary':'完整经过','evidence':[]}):
            story=build_story(editor,cached)
        self.assertEqual(story['nodes'][0]['id'],20)
        self.assertTrue(story['nodes'][0]['source_quote_id_repair'])
        rows[0]['text']='唯一后续原话'
        with patch('fine_story.grounded_outline',return_value={'summary':'完整经过','evidence':[]}),self.assertRaises(ValueError):
            build_story(editor,cached)

    def test_invalid_story_nodes_fall_back_to_literal_protected_section(self):
        from fine_story import build_story
        from types import SimpleNamespace
        rows=[{'id':10,'start':0,'end':1,'text':'开端原文'},
              {'id':20,'start':1,'end':2,'text':'结尾原话'}]
        editor=SimpleNamespace(context=rows,store=None,p={'id':'fixture'},persist=lambda *args:None)
        def cached(editor,kind,system,payload,validate,on_invalid=None):
            bad={'summary':'缺失节点结构'}
            try:return validate(bad)
            except ValueError as error:return validate(on_invalid(error,bad))
        with patch('fine_story.grounded_outline',return_value={'summary':'完整经过','evidence':[]}):
            story=build_story(editor,cached)
        self.assertEqual(story['source_excerpt_sections'],[[10,20]])
        self.assertEqual(story['nodes'],[{'id':10,'quote':'开端原文','role':'source'},
                                       {'id':20,'quote':'结尾原话','role':'source'}])

    def test_candidate_and_final_prompts_support_provider_json_mode(self):
        from fine_story import decide,final_review
        from types import SimpleNamespace
        rows=[{'id':10,'start':0,'end':1,'text':'原文示例'}]
        editor=SimpleNamespace(context=rows,persist=lambda *args:None)
        story={'outline':{'summary':'完整故事'},'nodes':[]}
        candidate={'id':'row:10','kind':'offtopic','status':'suggested','quote':'原文示例',
                   'row_ids':[10],'reason':'无关闲聊','evidence':[]}
        options={'cleanup':['offtopic'],'speech':[]}
        requests=[]
        def cached(editor,kind,system,payload,validate,**kwargs):
            requests.append(kind)
            self.assertIn('json',system.lower())
            return validate({'decisions':[{'id':'row:10','action':'keep','reason':'完整故事需要'}]}
                            if 'judge' in kind else {'restore_ids':[],'reason':'保留完整故事'})
        decide(editor,[candidate],options,story,cached)
        final_review(editor,[candidate],options,story,cached)
        self.assertEqual(len(requests),2)

    def test_failed_final_review_restores_every_unverified_cut(self):
        from fine_story import final_review
        from types import SimpleNamespace
        editor=SimpleNamespace(context=[{'id':10,'start':0,'end':1,'text':'原文示例'}],persist=lambda *args:None)
        candidates=[{'id':'word:10:0:1:retakes','kind':'retakes','quote':'就','row_ids':[10],
                     'reason':'前一次重说','evidence':[]}]
        def cached(editor,kind,system,payload,validate,on_invalid=None):
            bad={'restore_ids':['不存在的候选'],'reason':'无效编号'}
            try:return validate(bad)
            except ValueError as error:return validate(on_invalid(error,bad))
        result=final_review(editor,candidates,{'speech':['retakes']},
                            {'outline':{'summary':'完整故事'},'nodes':[]},cached)
        self.assertEqual(result['restore_ids'],[candidates[0]['id']])
        self.assertIn('未通过校验',result['reason'])

    def test_worker_crash_recovery_preserves_results_and_does_not_interrupt_neighbors(self):
        self.task['status'] = 'transcribing'
        self.store.put(self.task)
        neighbor = {**self.task, 'id': test_fine.uuid.uuid4().hex, 'status': 'analyzing'}
        self.store.put(neighbor)
        with contextlib.redirect_stdout(io.StringIO()):
            state = dispatch({'cmd': 'recover_failure', 'original_cmd': 'run', 'task_id': self.task['id'],
                              'message': '引擎异常退出', '_data_dir': str(self.store.root)})
        restored = next(task for task in state['tasks'] if task['id'] == self.task['id'])
        self.assertEqual(restored['status'], 'interrupted')
        self.assertEqual(restored['clips'], self.task['clips'])
        self.assertEqual(self.store.get(neighbor['id'])['status'], 'analyzing')
        self.p['status'] = 'queued'
        with contextlib.redirect_stdout(io.StringIO()):
            save(self.store, self.p)
            dispatch({'cmd': 'recover_failure', 'original_cmd': 'edit_auto', 'project_id': self.p['id'],
                      'message': '引擎异常退出', '_data_dir': str(self.store.root)})
        restored = get(self.store, self.p['id'])
        self.assertEqual(restored['status'], 'idle')
        self.assertEqual(restored['execution']['state'], 'failed')

    def test_subtitle_burn_with_apostrophe_directory(self):
        from storage import Store
        previous = self.store
        self.store = Store(self.root / "user's data")
        self.store.put(self.task)
        (self.store.task_dir(self.task['id']) / 'transcript.json').write_text(json.dumps(self.rows, ensure_ascii=False), encoding='utf-8')
        self.p = test_fine.create(self.store, self.task['id'], 1)
        try:
            self.plan()
            self.run_cmd('edit_confirm')
            self.assertTrue(Path(self.p['versions'][-1]['preview']).is_file())
        finally:
            self.store.db.close()
            self.store = previous

    def test_odd_width_input_can_preview_and_export(self):
        odd = self.root / 'odd.mkv'
        subprocess.run([tool_path(self.store.settings(), 'ffmpeg'), '-v', 'error', '-y', '-f', 'lavfi',
                        '-i', 'testsrc=size=321x181:rate=10', '-t', '12', '-c:v', 'ffv1', str(odd)],
                       capture_output=True, check=True)
        self.task['video'] = str(odd)
        self.store.put(self.task)
        self.plan()
        self.run_cmd('edit_confirm')
        media = probe(self.p['versions'][-1]['preview'], self.store.settings(), self.store)
        self.assertEqual(media['width'] % 2, 0)
        self.assertEqual(media['height'] % 2, 0)
        self.run_cmd('edit_export')

    def test_long_event_plan_has_bounded_batches_and_exact_sentence_coverage(self):
        editor = Editor(self.store, {'project_id': self.p['id']})
        editor.context = [{'id': i, 'start': i*2, 'end': i*2+1.8, 'text': '完整故事中的必要原文。'*12} for i in range(150)]
        seen = []
        def api(settings, messages, *args):
            payload = json.loads(messages[1]['content'])
            rows = payload['transcript']
            self.assertLessEqual(len(rows), 24)
            self.assertLess(len(messages[1]['content']), 7000)
            seen.append([row['id'] for row in rows])
            return json.dumps({'summary': '保留完整故事', 'kept_ids': [row['id'] for row in rows], 'removed': []})
        with patch('fine_auto.chat_api', side_effect=api), contextlib.redirect_stdout(io.StringIO()):
            result = plan_event(editor, DEFAULTS)
        self.assertGreater(len(seen), 2)
        self.assertEqual(sorted(result['kept_ids']), list(range(150)))
        self.assertEqual(result['removed'], [])

    def test_legacy_conversation_bounds_history_and_does_not_resend_full_version_transcripts(self):
        editor=Editor(self.store,{'project_id':self.p['id'],'message':'保留完整故事'})
        editor.context=[{'id':i,'start':i,'end':i+1,'text':'完整原文内容。'*30} for i in range(100)]
        version=editor.version([{'start':0,'end':12}],'现有方案')
        version['transcript_rows']=editor.context
        editor.p['messages']=[{'role':'user' if i%2==0 else 'assistant','content':'前面的对话'*1000} for i in range(24)]
        def api(settings,messages,*args):
            payload=json.loads(messages[1]['content'])
            self.assertLess(len(messages[1]['content']),4000)
            self.assertNotIn('transcript_rows',payload['current_plan'])
            self.assertLessEqual(sum(len(row['content']) for row in messages[2:]),12000)
            self.assertEqual(messages[-1]['content'],'保留完整故事')
            return json.dumps({'reply':'保留完整故事','plan':None})
        with patch('analysis_budget.grounded_outline',return_value={'summary':'完整经过','evidence':[{'id':50,'quote':'完整原文'}]}), \
                patch('fine.chat_api',side_effect=api),contextlib.redirect_stdout(io.StringIO()):editor.converse()

    def test_large_component_consolidates_ownership_windows_without_splitting_event(self):
        from types import SimpleNamespace
        from editorial import review_pass
        rows=[{'id':i,'start':i*2.,'end':i*2+1.8,'text':'必要铺垫和结尾。'} for i in range(30)]
        candidates=[{'title':'同一完整故事','start_id':0,'end_id':29,'start':0,'end':59.8,'score':90} for _ in range(25)]
        runner=SimpleNamespace(task={'duration':60,'prefs':{'topics':['自动判断']}},store=None,task_id='fixture',update=lambda *a:None)
        def review(runner,kind,system,payload):
            group=payload['components'][0]
            self.assertLessEqual(len(group['candidates']),8)
            return {'events':[{'member_ids':[c['candidate_id'] for c in group['candidates']],
                'title':'完整故事','start_id':0,'end_id':29,'score':90,'reason':'保留同一件事完整的铺垫经过及结尾。',
                'evidence':[{'id':29,'quote':rows[-1]['text'],'role':'payoff'}]}],'rejected':[]}
        with patch('editorial.cached_api',side_effect=review),patch('editorial.check_cancel'):
            kept,_=review_pass(runner,candidates,rows)
        self.assertEqual(len(kept),1)
        self.assertEqual(sorted(kept[0]['editorial']['member_ids']),list(range(1,26)))
        self.assertEqual((kept[0]['start_id'],kept[0]['end_id']),(0,29))

    def test_distant_retelling_is_compared_across_bounded_groups(self):
        from types import SimpleNamespace
        from editorial import dedupe_retellings
        rows=[{'id':i,'start':i*30.,'end':i*30+20,'text':f'事件{i}的原文和完整经过'} for i in range(12)]
        events=[{'title':f'事件{i}','reason':'独立故事经过','start_id':i,'end_id':i,
                 'editorial':{'member_ids':[i]}} for i in range(12)]
        runner=SimpleNamespace(store=None,task_id='fixture',update=lambda *a:None)
        def review(runner,kind,system,payload):
            pack=payload['events']
            self.assertLessEqual(len(pack),6)
            by_source={c['transcript'][0]['id']:c['event_id'] for c in pack}
            duplicates=[by_source[i] for i in (0,11) if i in by_source]
            if len(duplicates)==2:
                return {'groups':[{'event_ids':duplicates,'keep_id':by_source[11],'reason':'相同事情的完整版本',
                    'evidence':[{'event_id':by_source[i],'id':i,'quote':rows[i]['text']} for i in (0,11)]}],
                    'distinct_ids':[c['event_id'] for c in pack if c['event_id'] not in duplicates]}
            return {'groups':[],'distinct_ids':[c['event_id'] for c in pack]}
        with patch('editorial.cached_api',side_effect=review),patch('editorial.check_cancel'):
            kept=dedupe_retellings(runner,events,rows)
        self.assertEqual(len(kept),11)
        replacement=next(c for c in kept if c['start_id']==11)
        self.assertEqual(sorted(replacement['editorial']['member_ids']),[0,11])


if __name__ == '__main__':
    unittest.main()
