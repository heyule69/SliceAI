"""Exercise fixed-choice editing on an authorized real event in isolated test storage."""
import contextlib,json,os,shutil,sys,time,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from storage import Store
from fine import create,Editor
from fine_auto import DEFAULTS
from engine import probe

folder=ROOT/'.test-artifacts/fine-wizard-real';folder.mkdir(parents=True,exist_ok=True)
source=Store(Path(os.environ['LOCALAPPDATA'])/'com.sliceai.desktop');store=Store(folder/'data')
try:
    task=source.get('9224c40a-9410-4894-bf6e-4dd33aec7d2b');clip=next(c for c in task['clips'] if '带猫洗澡' in c['title'])
    settings=source.settings(secret=True);settings['asr_model_dir']=str(source.root/'models/sensevoice-int8')
    settings['output_dir']=str(folder/'exports');store.save_settings(settings)
    task['clips']=[clip];task['exports']=[];task['prefs']['exclude_playback']=False;task['output_root']=str(folder/'exports');store.put(task)
    shutil.copy2(source.task_dir(task['id'])/'transcript.json',store.task_dir(task['id'])/'transcript.json')
    project=create(store,task['id'],clip['id']);started=time.monotonic()
    class Progress:
        last=''
        def write(self,line):
            try:
                event=json.loads(line).get('event',{});stage=event.get('project',{}).get('stage')
                if stage and stage!=self.last:self.last=stage;sys.__stdout__.write(stage+'\n');sys.__stdout__.flush()
            except (ValueError,TypeError):pass
        def flush(self):pass
    with contextlib.redirect_stdout(Progress()):
        result=Editor(store,{'cmd':'edit_auto','project_id':project['id'],'options':DEFAULTS}).run()
    if result['error']:raise RuntimeError(result['error'])
    version=result['versions'][-1];info=probe(version['preview'],store.settings(),store)
    report={'project_id':result['id'],'title':result['title'],'elapsed_seconds':round(time.monotonic()-started,1),
        'source_duration':clip['end']-clip['start'],'output_duration':info['duration'],'ranges':version['ranges'],
        'removed':version['removed'],'caption_review':version.get('caption_review'),
        'preview':version['preview'],'usage':result.get('api_usage'),'options':version['edit_options'],
        'auto_review':version['auto_review']}
    (ROOT/'test-results/v0.2/fine-wizard-real.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('source_duration','output_duration','elapsed_seconds','usage')},ensure_ascii=False))
finally:source.db.close();store.db.close()
