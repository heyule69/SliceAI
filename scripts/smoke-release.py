"""Exercise the packaged worker with local ASR, a mock API, and real video exports."""
import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
WORKER=ROOT/'src-tauri/resources/worker/sliceai-worker.exe'
ARTIFACTS=ROOT/'.test-artifacts/release-smoke'
DATA=ARTIFACTS/'data'

class MockAPI(BaseHTTPRequestHandler):
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        content=body['messages'][1]['content']
        text=json.loads(content[0]['text'] if isinstance(content,list) else content)
        rows=text['transcript']
        assert '小猫' in ''.join(row['text'] for row in rows)
        response={'clips':[{'start_id':rows[0]['id'],'end_id':rows[-1]['id'],
            'title':'小猫更喜欢快递盒子','reason':'测试接口选取完整故事，实际语音来自本地合成样本。',
            'category':'聊天故事','score':90}]}
        if isinstance(content,list):
            assert len([b for b in content if b['type']=='image_url'])==6
            response={'source':'streamer','reason':'本地合成样本的来源复核接口测试',
                'visual_evidence':[{'frame':1,'description':'合成测试画面'}],
                'streamer_evidence':[{'id':rows[0]['id'],'quote':rows[0]['text'],'attribution':'模拟服务返回样本的真实字幕句子用于验证'}]}
        payload=json.dumps({'choices':[{'message':{'content':json.dumps(response,ensure_ascii=False)}}]}).encode('utf-8')
        self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(payload)
    def log_message(self,*args):pass

def call(cmd,**values):
    request={'cmd':cmd,'_data_dir':str(DATA),**values}
    result=subprocess.run([str(WORKER)],input=json.dumps(request,ensure_ascii=False).encode('utf-8'),
                          stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=0x08000000,timeout=180)
    rows=[json.loads(line) for line in result.stdout.decode('utf-8').splitlines() if line.strip()]
    if result.returncode:raise RuntimeError(rows[-1] if rows else result.stderr.decode('utf-8',errors='replace'))
    return rows[-1]['result']

def main():
    ARTIFACTS.mkdir(parents=True,exist_ok=True)
    video=ARTIFACTS/'本地转写测试.mp4'
    subprocess.run([str(WORKER.parent/'bin/ffmpeg.exe'),'-v','error','-f','lavfi','-i','testsrc2=size=640x360:rate=24',
        '-i',str(ROOT/'.test-artifacts/asr-中文.wav'),'-shortest','-c:v','libx264','-preset','ultrafast','-threads','2',
        '-c:a','aac','-y',str(video)],check=True,creationflags=0x08000000)
    server=ThreadingHTTPServer(('127.0.0.1',0),MockAPI)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        call('save_settings',values={'api_base':f'http://127.0.0.1:{server.server_port}/v1','api_model':'local-mock-only',
             'api_key':'local-mock-not-a-real-key','asr_model_dir':str(Path(os.environ['LOCALAPPDATA'])/'com.sliceai.desktop/models/sensevoice-int8'),
             'output_dir':str(ARTIFACTS/'exports')})
        info=call('probe',path=str(video));assert info['audio'] and info['duration']>25
        task=call('create_task',video=str(video),prefs={'duration':'smart','auto_export':True})
        result=call('run',task_id=task['id'])
        assert result['status']=='complete',result.get('error')
        assert result['sentence_count']>=4 and len(result['clips'])==1 and len(result['exports'])==1
        assert Path(result['exports'][0]['path']).is_file()
        preview=call('preview',task_id=task['id'],clip_id=1);assert Path(preview['path']).is_file()
        result=call('export',task_id=task['id'],clip_ids=[1],mode='compilation',subtitle='srt')
        assert result['status']=='complete' and len(result['exports'])==2
        call('save_settings',values={'clear_key':True})
        (ARTIFACTS/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'status':'passed','transcript_sentences':result['sentence_count'],
            'clips':len(result['clips']),'exported_files':len(result['exports']),'artifacts':str(ARTIFACTS)},ensure_ascii=False))
    finally:server.shutdown();server.server_close();thread.join()

if __name__=='__main__':main()
