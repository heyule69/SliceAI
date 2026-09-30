"""Run an authorized real API test using only SliceAI's own encrypted configuration."""
import json
import os
import shutil
import sys
from pathlib import Path

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'backend'))
from storage import Store
from pipeline import create_task,Runner
folder=root/'test-results/2026-08-28'
folder.mkdir(parents=True,exist_ok=True)
subtitle=folder/'完整转写.srt'
shutil.copy2(root/'.test-artifacts/real-recording/transcript.srt',subtitle)
store=Store(Path(os.environ['LOCALAPPDATA'])/'com.sliceai.desktop')
task=create_task(store,{'video':r'D:\Download\BaiduNetdisk\2026-08-28_21-32-17_小小霖le_即将流落街头_录播.mp4',
    'subtitle':str(subtitle),'prefs':{'duration':'smart','topics':['自动判断'],'output':'separate','auto_export':True,'max_clips':12}})
task['output_root']=str(folder/'AI精选');store.put(task)
(folder/'ai-task-id.txt').write_text(task['id'],encoding='utf-8')
# Keep the protocol's verbose progress local. Only compact status reaches the console.
import engine,pipeline
def progress(event):
    if event.get('type')=='task':
        t=event['task']
        print(json.dumps({'status':t['status'],'progress':t['progress'],'stage':t['stage'],
                          'clips':len(t['clips']),'api_usage':t.get('api_usage',{})},ensure_ascii=False),flush=True)
pipeline.emit=progress
try:
    result=Runner(store,task['id']).run()
    (folder/'AI测试结果.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'final_status':result['status'],'error':result.get('error'),'clips':len(result['clips']),
                      'exports':len(result['exports']),'api_usage':result.get('api_usage',{})},ensure_ascii=False),flush=True)
    if result['status']!='complete':raise SystemExit(1)
finally:store.db.close()
