"""Real API acceptance in SliceAI's own data, preserving historical tasks."""
import contextlib,json,os,sys,time
from pathlib import Path
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root/'backend'))
from storage import Store
from pipeline import create_task,Runner
import fine
store=Store(Path(os.environ['LOCALAPPDATA'])/'com.sliceai.desktop')
folder=root/'test-results/v0.2';folder.mkdir(parents=True,exist_ok=True)
taskfile=folder/'real-task-id.txt'
class Progress:
    last=''
    def write(self,text):
        try:
            value=json.loads(text);e=value.get('event',{});p=e.get('task') or e.get('project')
            if p and p['stage']!=self.last:
                self.last=p['stage'];sys.__stdout__.write(json.dumps({'stage':self.last,'status':p['status']},ensure_ascii=False)+'\n');sys.__stdout__.flush()
        except (ValueError,KeyError):pass
    def flush(self):pass
try:
    if taskfile.is_file():task=store.get(taskfile.read_text(encoding='utf-8').strip())
    else:
        source=next(Path('D:/Download/BaiduNetdisk').glob('2026-08-28*.mp4'))
        task=create_task(store,{'video':str(source),'subtitle':str(root/'.test-artifacts/real-recording/transcript.srt'),
             'prefs':{'topics':['自动判断'],'exclude_playback':True}})
        task['output_root']=str(folder/'exports');store.put(task);taskfile.write_text(task['id'],encoding='utf-8')
    if task['status']!='complete':
        with contextlib.redirect_stdout(Progress()):task=Runner(store,task['id']).run()
    (folder/'real-events.json').write_text(json.dumps(task,ensure_ascii=False,indent=2),encoding='utf-8')
    if task['status']!='complete':raise ValueError(task.get('error') or task['stage'])
    print(json.dumps({'events':len(task['clips']),'longest_seconds':max([c['end']-c['start'] for c in task['clips']]+[0]),'usage':task.get('api_usage')},ensure_ascii=False),flush=True)
    # Demonstrate the conversation on a modest real event; do not auto-approve AI output.
    if task['clips']:
        clip=min(task['clips'],key=lambda c:abs((c['end']-c['start'])-240))
        p=fine.create(store,task['id'],clip['id'])
        if not p['messages']:
            with contextlib.redirect_stdout(Progress()):p=fine.Editor(store,{'cmd':'edit_chat','project_id':p['id']}).run()
        (folder/'real-edit.json').write_text(json.dumps(p,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'edit_project':p['id'],'status':p['status'],'error':p['error']},ensure_ascii=False),flush=True)
finally:store.db.close()
