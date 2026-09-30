import contextlib,copy,io,json,subprocess,sys,tempfile,unittest,uuid
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from storage import Store
from pipeline import now
from fine import Editor,create,get,save,valid_ranges,mapped_cues,validate_cues
from engine import probe,tool_path
from events import analyze_events

class FineTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.store=Store(self.root/'data')
        self.video=self.root/'源录播.mp4'
        subprocess.run([tool_path(self.store.settings(),'ffmpeg'),'-v','error','-y','-f','lavfi','-i','testsrc2=size=320x180:rate=25',
            '-f','lavfi','-i','sine=frequency=350:sample_rate=48000','-t','12','-c:v','libx264','-preset','ultrafast','-threads','2','-c:a','aac',str(self.video)],check=True,capture_output=True)
        self.rows=[{'id':i,'start':i*2.,'end':i*2+1.8,'text':f'这是第{i}句中文故事'} for i in range(6)]
        self.task={'id':str(uuid.uuid4()),'created':now(),'title':'中文故事','video':str(self.video),'duration':12,
            'prefs':{'exclude_playback':False},'output_root':str(self.root/'exports'),'exports':[],
            'clips':[{'id':1,'title':'完整事件','start':0,'end':12}]}
        self.store.put(self.task);(self.store.task_dir(self.task['id'])/'transcript.json').write_text(json.dumps(self.rows,ensure_ascii=False),encoding='utf-8')
        self.p=create(self.store,self.task['id'],1)
    def tearDown(self):self.store.db.close();self.tmp.cleanup()
    def run_cmd(self,cmd,**kwargs):
        with contextlib.redirect_stdout(io.StringIO()):self.p=Editor(self.store,{'cmd':cmd,'project_id':self.p['id'],'revision':self.p['revision'],**kwargs}).run()
        self.assertFalse(self.p['error'],self.p['error']);return self.p
    def plan(self):
        editor=Editor(self.store,{'project_id':self.p['id']})
        editor.version([{'start':6,'end':10,'reason':'先给出看点'},{'start':0,'end':4,'reason':'补充来由'}],'重排方案')
        with contextlib.redirect_stdout(io.StringIO()):self.p=editor.persist()
    def test_confirmation_render_reorder_subtitles_versions_and_export(self):
        self.plan();editor=Editor(self.store,{'project_id':self.p['id']})
        with self.assertRaisesRegex(ValueError,'确认'):editor.render()
        self.assertFalse(list(self.store.task_dir(self.p['id']).rglob('*.mp4')))
        first=self.p['current_version'];self.run_cmd('edit_confirm')
        v=self.p['versions'][-1];self.assertTrue(v['reordered']);self.assertTrue(Path(v['preview']).is_file())
        self.assertAlmostEqual(probe(v['preview'],self.store.settings(),self.store)['duration'],8,delta=.4)
        self.assertIn('第3',v['cues'][0]['text']);self.assertEqual(v['cues'][2]['start'],4)
        cues=copy.deepcopy(v['cues']);cues[0]['text']='修改后的中文';self.run_cmd('edit_update',cues=cues)
        self.assertNotEqual(self.p['current_version'],first);self.assertTrue(self.p['versions'][-1]['confirmed'])
        self.run_cmd('edit_export',srt=True);record=self.p['exports'][-1]
        self.assertIn('修改后的中文',Path(record['subtitle']).read_text(encoding='utf-8'));self.assertTrue(Path(record['path']).is_file())
        self.run_cmd('edit_restore',version_id=first);self.assertEqual(self.p['current_version'],first)
        self.run_cmd('edit_update',ranges=[{'start':1,'end':3}]);self.assertFalse(self.p['versions'][-1]['confirmed'])
        self.assertEqual(self.store.get(self.task['id'])['clips'][0]['end'],12)
    def test_stale_reply_invalid_boundaries_and_cues(self):
        stale=copy.deepcopy(self.p)
        with contextlib.redirect_stdout(io.StringIO()):save(self.store,self.p)
        with self.assertRaisesRegex(ValueError,'新修改'):save(self.store,stale)
        for ranges in ([{'start':-1,'end':2}],[{'start':float('nan'),'end':2}],[{'start':0,'end':5},{'start':3,'end':6}]):
            with self.assertRaises(ValueError):valid_ranges(ranges,{'start':0,'end':12})
        with self.assertRaises(ValueError):validate_cues([{'start':1,'end':99,'text':'字幕'}],12)

    def test_cancelled_or_failed_export_preserves_completed_preview(self):
        from engine import Cancelled
        self.plan();self.run_cmd('edit_confirm')
        completed=copy.deepcopy(self.p['versions'])
        path=Path(completed[-1]['preview']);stamp=path.stat().st_mtime_ns
        for failure,state in ((Cancelled(),'cancelled'),(ValueError('磁盘空间不足'),'failed')):
            with patch.object(Editor,'render',side_effect=failure),contextlib.redirect_stdout(io.StringIO()):
                self.p=Editor(self.store,{'cmd':'edit_export','project_id':self.p['id']}).run()
            self.assertEqual(self.p['execution']['state'],state)
            self.assertEqual(self.p['execution']['command'],'edit_export')
            self.assertEqual(self.p['versions'],completed)
            self.assertEqual(path.stat().st_mtime_ns,stamp)
            self.assertEqual(self.p['exports'],[])
            self.assertEqual(get(self.store,self.p['id'])['versions'],completed)
    def test_audio_can_apply_without_audition_and_binds_version(self):
        from audio_identity import ENGINE_ID
        self.plan();editor=Editor(self.store,{'project_id':self.p['id'],'audio_strength':1})
        editor.p['audio_sample']={'processed':{'path':'old-moss.wav'}}
        editor.update_version();v=editor.current()
        self.assertEqual(v['audio_engine'],ENGINE_ID);self.assertEqual(v['audio_strength'],1)
        v['confirmed']=True;v['audio_engine']='old-moss'
        with self.assertRaisesRegex(ValueError,'旧声音模型'):editor.render()
        editor.req['audio_strength']=0;editor.update_version()
        self.assertIsNone(editor.current()['audio_engine']);self.assertEqual(editor.current()['audio_strength'],0)
    def test_event_player_is_trimmed_cached_and_uses_relative_timeline(self):
        from service import dispatch
        from event_preview import prepare
        from pipeline import Runner
        self.task['clips'][0].update(start=3,end=10)
        self.store.put(self.task)
        self.p.update(source_start=3,source_end=10)
        with contextlib.redirect_stdout(io.StringIO()):save(self.store,self.p)
        req={'cmd':'edit_source','_data_dir':str(self.store.root),'project_id':self.p['id']}
        self.assertEqual(dispatch(req)['path'],str(self.video));self.assertEqual(dispatch(req)['start'],3)
        self.run_cmd('edit_source_preview')
        result=dispatch(req)
        self.assertEqual((result['start'],result['end']),(0,7))
        self.assertNotEqual(result['path'],str(self.video))
        self.assertAlmostEqual(probe(result['path'],self.store.settings(),self.store)['duration'],7,delta=.15)
        stamp=Path(result['path']).stat().st_mtime_ns
        cached=prepare(Runner(self.store,self.task['id']),self.task['clips'][0])
        self.assertEqual(cached['path'],result['path']);self.assertEqual(Path(result['path']).stat().st_mtime_ns,stamp)
        # Changing the source invalidates the source preview; final ranges stay absolute.
        import os
        info=self.video.stat();os.utime(self.video,ns=(info.st_atime_ns,info.st_mtime_ns+1000000000))
        self.assertEqual(dispatch(req)['path'],str(self.video));self.assertEqual(dispatch(req)['start'],3)
    def test_playback_resolves_without_rendering_and_reuses_export(self):
        from event_preview import playback
        from pipeline import Runner
        from service import dispatch
        self.task['clips'][0].update(start=3,end=10)
        self.store.put(self.task)
        with patch.object(Runner,'render_clip',side_effect=AssertionError('Viewing must not render')):
            result=dispatch({'cmd':'preview','task_id':self.task['id'],'clip_id':1,'_data_dir':str(self.store.root)})
            self.assertEqual((result['path'],result['start'],result['end']),(str(self.video),3,10))
            self.assertEqual(self.store.get(self.task['id']),self.task)
            exported=self.root/'exported.mp4';exported.write_bytes(b'completed export')
            self.task['exports']=[{'mode':'separate','clip_ids':[1],'duration':7,'path':str(exported)}]
            self.store.put(self.task)
            result=playback(Runner(self.store,self.task['id']),self.task['clips'][0])
            self.assertEqual((result['path'],result['start'],result['end']),(str(exported),0,7))
            self.video.unlink()
            self.assertEqual(playback(Runner(self.store,self.task['id']),self.task['clips'][0])['path'],str(exported))
            exported.unlink()
            with self.assertRaisesRegex(ValueError,'移动'):playback(Runner(self.store,self.task['id']),self.task['clips'][0])
    def test_conversation_failure_keeps_message_and_retry(self):
        with patch('fine.chat_api',return_value=json.dumps({'reply':'这段是聊天故事，你希望突出情绪还是笑点？','plan':None})):
            self.run_cmd('edit_chat')
        with patch('fine.chat_api',side_effect=ValueError('API timeout')),contextlib.redirect_stdout(io.StringIO()):
            self.p=Editor(self.store,{'cmd':'edit_chat','project_id':self.p['id'],'message':'保留故事删重复'}).run()
        self.assertIn('timeout',self.p['error']);self.assertEqual(self.p['messages'][-1]['role'],'user')
        with patch('fine.chat_api',return_value=json.dumps({'reply':'保留原顺序，删掉重复。','plan':{'summary':'保留故事','ranges':[{'start_id':0,'end_id':4}],'subtitles':True}})):
            self.run_cmd('edit_chat',message='保留故事删重复')
        self.assertEqual(sum(m['role']=='user' for m in self.p['messages']),1)
        self.assertFalse(self.p['versions'][-1]['confirmed'])

class EventTest(unittest.TestCase):
    def test_event_crosses_windows_and_more_than_twelve(self):
        rows=[{'id':i,'start':i*20.,'end':i*20+18.,'text':'主播继续讲同一个故事'} for i in range(110)]
        class Runner:
            task={'duration':2200,'prefs':{'topics':['自动判断']}}
            task_id='test';store=None
            def update(self,*args):pass
        def api(runner,kind,system,payload):
            if kind=='boundary':return payload['event']
            if kind=='continuity':return {'events':[payload['event']]}
            window=payload['transcript'];pending=payload['open_events']
            result=[]
            if window[0]['id']==0:result=[{'key':None,'start_id':0,'end_id':window[-1]['id'],'ended':False,'score':95}]
            elif pending:
                end=min(65,window[-1]['id']);result=[{'key':pending[0]['key'],'start_id':0,'end_id':end,'ended':end==65,'score':95}]
            if window[-1]['id']>65:
                result += [{'key':None,'start_id':s['id'],'end_id':s['id'],'ended':True,'score':70} for s in window if s['id']>65]
            return {'events':result}
        with patch('events.cached_api',side_effect=api),patch('events.check_cancel'):
            result=analyze_events(Runner(),rows,[])
        self.assertGreater(len(result),12)
        story=next(e for e in result if e['start_id']==0)
        self.assertEqual(story['end_id'],65);self.assertGreater(story['end']-story['start'],1200)

if __name__=='__main__':unittest.main()
