"""Technical export validation from a real recording; no claim of AI selection."""
import json
import subprocess
import sys
import uuid
from pathlib import Path

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'backend'))
from storage import Store
from formats import validate_candidates
from pipeline import now
source=Path(r'D:\Download\BaiduNetdisk\2026-08-28_21-32-17_小小霖le_即将流落街头_录播.mp4')
folder=root/'.test-artifacts/real-recording'
rows=[json.loads(line) for line in (folder/'transcript.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
# A manually identified story provides known boundaries to check long-video seeking.
chosen=[row for row in rows if 11443<=row['start']<11628]
assert len(chosen)>15
clip=validate_candidates([{'start_id':chosen[0]['id'],'end_id':chosen[-1]['id'],'title':'长视频定位导出验证_非AI筛选',
    'score':0,'category':'技术验证','reason':'手工选定真实转写中的连续故事，只验证定位、视频和字幕导出；不是 AI 精彩判断结果。'}],rows,19786.944,20,360)[0]
clip.update(id=1,thumbnail='',preview='')
store=Store(folder/'render-data');task_id=str(uuid.uuid4())
task={'id':task_id,'created':now(),'title':source.stem,'video':str(source),'subtitle':'','chat':'','duration':19786.944,
      'status':'complete','stage':'技术验证','progress':100,'error':'','thumbnail':'','clips':[clip],'exports':[],
      'prefs':{'duration':'smart','topics':['聊天故事'],'output':'separate','auto_export':False,'max_clips':12},
      'output_root':str(root/'test-results/2026-08-28'),'settings_snapshot':{}}
store.put(task)
(store.task_dir(task_id)/'transcript.json').write_text(json.dumps(rows,ensure_ascii=False),encoding='utf-8')
store.db.close()
worker=root/'src-tauri/resources/worker/sliceai-worker.exe'
request={'cmd':'export','_data_dir':str(folder/'render-data'),'task_id':task_id,'clip_ids':[1],'mode':'separate','subtitle':'srt'}
result=subprocess.run([str(worker)],input=json.dumps(request,ensure_ascii=False).encode('utf-8'),
                      stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=0x08000000,timeout=300)
events=[json.loads(line) for line in result.stdout.decode('utf-8').splitlines() if line.strip()]
assert result.returncode==0,events[-1]
task=events[-1]['result'];assert task['status']=='complete',task.get('error')
record=task['exports'][0]
info=json.loads(subprocess.check_output([str(worker.parent/'bin/ffprobe.exe'),'-v','error','-show_entries',
     'format=duration,size:stream=codec_type,codec_name,start_time,width,height','-of','json',record['path']],creationflags=0x08000000))
expected=clip['end']-clip['start'];actual=float(info['format']['duration'])
assert abs(expected-actual)<.5
assert {s['codec_type'] for s in info['streams']}=={'video','audio'}
assert not Path(record['subtitle']).read_bytes().startswith(b'\xef\xbb\xbf')
summary={'selection':'manual export validation, NOT AI-selected','source':str(source),'start':clip['start'],'end':clip['end'],
         'expected_duration':expected,'actual_duration':actual,'video':record['path'],'subtitle':record['subtitle'],'probe':info}
(folder/'export-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False),flush=True)
