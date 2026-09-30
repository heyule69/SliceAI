"""Review existing candidates in a new task; preserve old IDs, edits and exports."""
import contextlib,copy,json,os,shutil,sys,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from storage import Store
from pipeline import Runner,now
from editorial import select_highlights,VERSION
from engine import Cancelled,check_cancel,thumbnail

class Progress:
    last=''
    def write(self,line):
        try:
            task=json.loads(line).get('event',{}).get('task',{})
            stage=task.get('stage','')
            if stage and stage!=self.last:
                self.last=stage;sys.__stdout__.write(json.dumps({'stage':stage},ensure_ascii=False)+'\n');sys.__stdout__.flush()
        except (ValueError,TypeError):pass
    def flush(self):pass

store=Store(Path(os.environ['LOCALAPPDATA'])/'com.sliceai.desktop')
report_dir=ROOT/'test-results/v0.2';id_file=report_dir/'curated-task-id.txt'
try:
    old_id=(report_dir/'real-task-id.txt').read_text(encoding='utf-8').strip();old=store.get(old_id)
    if id_file.is_file():new=store.get(id_file.read_text(encoding='utf-8').strip())
    else:
        new=copy.deepcopy(old);new.update(id=str(uuid.uuid4()),created=now(),title=old['title']+' · 精选复核',
            status='analyzing',stage='严格筛选看点与合并重复事件',progress=0,error='',clips=[],exports=[],rejected_clips=[],
            api_usage={'requests':0,'prompt_tokens':0,'completion_tokens':0,'total_tokens':0},
            reanalyzed_from=old_id,editorial_summary={})
        new.pop('output_folder',None);new['prefs']['auto_export']=False;store.put(new)
        id_file.write_text(new['id'],encoding='utf-8')
        source=store.task_dir(old_id);dest=store.task_dir(new['id'])
        for name in ('transcript.json','transcript.srt'):
            if (source/name).is_file():shutil.copy2(source/name,dest/name)
        if (source/'source-review').is_dir():shutil.copytree(source/'source-review',dest/'source-review')
    runner=Runner(store,new['id'])
    sentences=json.loads((runner.folder/'transcript.json').read_text(encoding='utf-8'))
    try:
        if new['status']!='complete' or new.get('editorial_summary',{}).get('version')!=VERSION:
            with contextlib.redirect_stdout(Progress()):
                runner.task['error']=''
                candidates=select_highlights(runner,old['clips'],sentences)
                (runner.folder/'candidates.json').write_text(json.dumps(candidates,ensure_ascii=False),encoding='utf-8')
                candidates=runner.select_sources(candidates,sentences,len(candidates))
                runner.task['clips']=[]
                for index,c in enumerate(candidates,1):
                    check_cancel(store,runner.task_id);c.update(id=index,preview='',thumbnail='')
                    c['thumbnail']=thumbnail(runner.task['video'],runner.folder/f'clip-{index}.jpg',c['start']+min(3,(c['end']-c['start'])/2),runner.settings,store,runner.task_id)
                    runner.task['clips'].append(c)
                runner.update('complete',f'精选复核完成 · {len(candidates)} 个独立事件',100)
        task=runner.task
        report={k:task.get(k) for k in ('id','title','duration','editorial_summary','editorial_rejected','api_usage','clips','source_review_summary')}
        (report_dir/'curated-events.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'task_id':task['id'],'selected':len(task['clips']),'summary':task.get('editorial_summary'),'usage':task.get('api_usage')},ensure_ascii=False),flush=True)
    except Exception as exc:
        runner.task['error']=str(exc)
        with contextlib.redirect_stdout(Progress()):runner.update('cancelled' if isinstance(exc,Cancelled) else 'failed','精选复核未完成，已保存进度')
        raise
finally:store.db.close()
