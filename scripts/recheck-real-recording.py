"""Reuse the authorized real task; never repeats ASR or full text analysis."""
import json
import os
import sys
from pathlib import Path

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'backend'))
from storage import Store
from pipeline import Runner
import pipeline

folder=root/'test-results/2026-08-28'
store=Store(Path(os.environ['LOCALAPPDATA'])/'com.sliceai.desktop')
task_id=(folder/'ai-task-id.txt').read_text(encoding='utf-8').strip()
task=store.get(task_id)
backup=folder/'来源复核前.json'
if not backup.exists():backup.write_text(json.dumps(task,ensure_ascii=False,indent=2),encoding='utf-8')
before=task.get('api_usage',{}).copy()
def progress(event):
    if event.get('type')=='task':
        value=event['task']
        print(json.dumps({'stage':value['stage'],'tokens':value.get('api_usage',{}).get('total_tokens',0)},ensure_ascii=False),flush=True)
pipeline.emit=progress
try:
    result=Runner(store,task_id).recheck()
    (folder/'来源复核结果.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    delta={k:v-before.get(k,0) for k,v in result.get('api_usage',{}).items()}
    print(json.dumps({'status':result['status'],'error':result.get('error'),'usage_delta':delta,
        'kept':[{ 'id':c['id'],'title':c['title'],'review':c.get('source_review')} for c in result['clips']],
        'rejected':[{ 'id':c['id'],'title':c['title'],'review':c.get('source_review')} for c in result.get('rejected_clips',[])]},ensure_ascii=False),flush=True)
    if result['status']!='complete':raise SystemExit(1)
finally:store.db.close()
