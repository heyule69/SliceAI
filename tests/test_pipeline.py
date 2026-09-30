import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from formats import (parse_subtitles,parse_chat,transcript_windows,validate_candidates,deduplicate,
                     clip_cues,write_srt,timestamp)
from storage import Store,protect,unprotect
from pipeline import create_task,Runner
from engine import probe,check_cancel,Cancelled,command,tool_path
from service import dispatch

class FormatsTest(unittest.TestCase):
    def test_utf8_and_cue_boundaries(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'中文.vtt'
            p.write_text('WEBVTT\n\n00:01.250 --> 00:03.000\n你好，世界\n\n00:04.000 --> 00:06.000\n下一句话\n',encoding='utf-8')
            cues=parse_subtitles(p,5)
            self.assertEqual(cues[0]['text'],'你好，世界');self.assertEqual(cues[-1]['end'],5)
            clipped=clip_cues(cues,2,4.5);self.assertEqual(clipped[0]['start'],0);self.assertEqual(clipped[-1]['end'],2.5)
            p.write_bytes(b'\xff\xfeinvalid')
            with self.assertRaisesRegex(ValueError,'UTF-8'):parse_subtitles(p,5)
            self.assertEqual(p.read_bytes(),b'\xff\xfeinvalid')
        for value in ('00:99:12','-1:00:00','00:00:nan'):
            with self.assertRaises(ValueError):timestamp(value)

    def test_chat_offsets_and_formats(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'弹幕.xml';p.write_text('<i><d p="5,1,25">笑死</d><d p="999,1">越界</d></i>',encoding='utf-8')
            self.assertEqual(parse_chat(p,100,2),[{'time':7,'text':'笑死'}])
            p=p.with_suffix('.json');p.write_text('[{"progress":5000,"content":"笑死"}]',encoding='utf-8')
            self.assertEqual(parse_chat(p,100,-2)[0]['time'],3)

    def test_windows_cover_long_recording_and_reject_invented_ids(self):
        sentences=[{'id':i,'start':i*5.,'end':i*5+4.,'text':'内容'*50} for i in range(2000)]
        windows=transcript_windows(sentences)
        self.assertEqual(set(range(2000)),{s['id'] for w in windows for s in w})
        self.assertTrue(all(w[-1]['end']-w[0]['start']<=480 for w in windows))
        raw=[{'start_id':0,'end_id':8,'score':90},{'start_id':99999,'end_id':99999},
             {'start_id':False,'end_id':8},{'start_id':8,'end_id':0},{'start_id':0,'end_id':1}]
        valid=validate_candidates(raw,windows[0],10000,30,60)
        self.assertEqual(len(valid),1)
        duplicate={**valid[0],'score':10,'end':valid[0]['end']+1}
        self.assertEqual(deduplicate([duplicate,*valid],12),valid)

@unittest.skipUnless(os.name=='nt','Windows DPAPI')
class IntegrationTest(unittest.TestCase):
    def test_cancels_running_ffmpeg_promptly(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder))
            def cancel():
                (store.root/'STOP').write_text('stop',encoding='utf-8')
            timer=threading.Timer(.5,cancel);timer.start();started=time.monotonic()
            try:
                with self.assertRaises(Cancelled):
                    command([tool_path(store.settings(),'ffmpeg'),'-v','error','-re','-f','lavfi','-i',
                             'testsrc2=size=160x90:rate=10','-f','null','-'],store)
                self.assertLess(time.monotonic()-started,5)
            finally:timer.join();store.db.close()

    def test_encryption_and_destination_binding(self):
        secret='test-only-key-中文';encrypted=protect(secret)
        self.assertNotIn(secret,encrypted);self.assertEqual(unprotect(encrypted),secret)
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder))
            try:
                store.save_settings({'api_key':secret});self.assertNotIn('api_key',store.settings())
                store.save_settings({'api_base':'https://example.com/v1'})
                self.assertFalse(store.settings()['key_saved'])
            finally:store.db.close()

    def test_real_video_api_selection_exports_and_cancellation(self):
        requests=[]
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                requests.append(body)
                result={'clips':[{'start_id':0,'end_id':7,'title':'测试精彩片段','reason':'完整的中文故事','category':'聊天故事','score':90}]}
                if 'open_events' in str(body['messages'][1]['content']):
                    result={'events':[dict(result['clips'][0],key=None,ended=True,summary='完整故事')]}
                elif '"context"' in str(body['messages'][1]['content']):
                    result={'start_id':0,'end_id':7}
                elif '"components"' in str(body['messages'][1]['content']):
                    payload=json.loads(body['messages'][1]['content']);row=payload['components'][0]['transcript'][0]
                    result={'events':[dict(result['clips'][0],reason='完整故事中的具体冲突及后续回应。',member_ids=[1],evidence=[{'id':row['id'],'quote':row['text'],'role':'payoff'}])],'rejected':[]}
                if isinstance(body['messages'][1]['content'],list):
                    blocks=body['messages'][1]['content']
                    assert len([b for b in blocks if b['type']=='image_url'])==6
                    row=json.loads(blocks[0]['text'])['transcript'][0]
                    result={'source':'streamer','reason':'合成素材仅用于流程测试',
                        'visual_evidence':[{'frame':1,'description':'测试画面'}],
                        'streamer_evidence':[{'id':row['id'],'quote':row['text'],'attribution':'测试服务明确返回可核对的字幕证据'}]}
                payload=json.dumps({'choices':[{'message':{'content':json.dumps(result,ensure_ascii=False)}}],
                                    'usage':{'prompt_tokens':123,'completion_tokens':45,'total_tokens':168}}).encode('utf-8')
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with tempfile.TemporaryDirectory(prefix='sliceai-test-') as folder:
                root=Path(folder);store=Store(root/'data');settings=store.settings()
                video=root/'中文录播.mp4';sub=root/'字幕.srt';chat=root/'弹幕.xml'
                from engine import tool_path
                subprocess.run([tool_path(settings,'ffmpeg'),'-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=10',
                    '-f','lavfi','-i','sine=frequency=440:sample_rate=16000','-t','50','-c:v','libx264','-preset','ultrafast',
                    '-threads','2','-pix_fmt','yuv420p','-c:a','aac','-y',str(video)],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                original=video.stat().st_size
                cues=[{'id':i,'start':i*5,'end':i*5+4,'text':f'这是第{i+1}句精彩故事。'} for i in range(10)]
                write_srt(sub,cues);chat.write_text('<i><d p="10,1,25">哈哈哈哈</d></i>',encoding='utf-8')
                store.save_settings({'api_base':f'http://127.0.0.1:{server.server_port}/v1','api_model':'mock-only','api_key':'mock-only','output_dir':str(root/'exports')})
                try:
                    task=create_task(store,{'video':str(video),'subtitle':str(sub),'chat':str(chat),'prefs':{'duration':'short','auto_export':True}})
                    with contextlib.redirect_stdout(io.StringIO()):result=Runner(store,task['id']).run()
                    self.assertEqual(result['status'],'complete',result.get('error'));self.assertEqual(len(result['clips']),1);self.assertEqual(len(result['exports']),0)
                    self.assertEqual(result['api_usage']['total_tokens'],840)
                    self.assertEqual(result['api_usage']['requests'],5)
                    with contextlib.redirect_stdout(io.StringIO()):Runner(store,task['id']).export([1],'separate')
                    record=store.get(task['id'])['exports'][0];self.assertTrue(Path(record['path']).is_file());self.assertEqual(record['subtitle'],'')
                    actual=probe(record['path'],settings,store)['duration'];self.assertAlmostEqual(actual,39.2,delta=.5)
                    payload=json.loads(requests[0]['messages'][1]['content']);self.assertIsNotNone(payload['danmaku'])
                    self.assertEqual(payload['transcript'][0]['text'],cues[0]['text'])
                    with contextlib.redirect_stdout(io.StringIO()):Runner(store,task['id']).export([1],'compilation')
                    self.assertEqual(len(requests),5,'导出复用有效复核结果，不应重复扣费')
                    self.assertEqual(len(store.get(task['id'])['exports']),2)
                    self.assertAlmostEqual(probe(store.get(task['id'])['exports'][-1]['path'],settings,store)['duration'],actual,delta=.5)
                    self.assertEqual(video.stat().st_size,original)
                    queued=create_task(store,{'video':str(video),'subtitle':str(sub),'prefs':{}})
                    dispatch({'cmd':'cancel_task','task_id':queued['id'],'_data_dir':str(store.root)})
                    with self.assertRaises(Cancelled):check_cancel(store,queued['id'])
                    self.assertEqual(dispatch({'cmd':'run','task_id':queued['id'],'_data_dir':str(store.root)})['status'],'cancelled')
                    self.assertFalse(list((root/'exports').rglob('*.partial.mp4')))
                finally:store.db.close()
        finally:server.shutdown();server.server_close();thread.join()

if __name__=='__main__':unittest.main()
