from __future__ import annotations
import json
import os
import shutil
import sys
import uuid
from pathlib import Path

if hasattr(sys.stdout,'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8',errors='strict')
    sys.stderr.reconfigure(encoding='utf-8',errors='replace')

def install_model(store):
    """Compatibility for old queued commands; runtime never downloads ASR assets."""
    from engine import emit
    from pipeline import model_dir,model_ready
    settings=store.settings()
    if not model_ready(store,settings):
        raise ValueError('内置转写模型不完整，请重新安装完整版，或指定有效的本地模型目录。')
    emit({'type':'model','stage':'内置转写模型已就绪','progress':100,'ready':True})
    return {'ready':True,'path':str(model_dir(store,settings))}


def state(store):
    from pipeline import model_dir,model_ready
    from engine import tool_path
    settings=store.settings();tools={}
    for name in ('ffmpeg','ffprobe'):
        try:tools[name]=tool_path(settings,name)
        except ValueError:tools[name]=''
    import fine
    edits=[{k:p[k] for k in ('id','task_id','clip_id','title','status','exports')} for p in fine.summaries(store)]
    return {'settings':settings,'tasks':store.tasks(),'edits':edits,'data_dir':str(store.root),
            'model':{'ready':model_ready(store,settings),'path':str(model_dir(store,settings))},'tools':tools}


def recover_failure(store, request):
    """Repair persisted state when a worker dies before its Python cleanup runs."""
    from engine import emit
    from pipeline import ACTIVE
    import fine
    message = str(request.get('message') or '处理引擎意外退出，已保留结果，可重试。')[:2000]
    if request.get('project_id'):
        project = fine.get(store, request['project_id'])
        if project['status'] in ('busy', 'queued'):
            if project.get('execution',{}).get('state')!='running':
                fine.fine_progress.begin(project,str(request.get('original_cmd') or 'edit_auto'))
            project.update(status='idle', stage='处理已中断，可重试', error=message)
            fine.fine_progress.finish(project, 'failed')
            fine.save(store, project)
    elif request.get('task_id'):
        task = store.get(request['task_id'])
        if task['status'] in ACTIVE:
            task.update(status='interrupted', stage='处理引擎已中断，可重试或导出已有片段', error=message)
            store.put(task)
            emit({'type': 'task', 'task': task})
    return state(store)

def dispatch(request):
    from storage import Store
    from engine import Cancelled,chat_api,emit,probe,thumbnail
    from pipeline import ACTIVE,Runner,create_task
    store=Store(Path(request['_data_dir']))
    cmd=request['cmd']
    try:
        if cmd.startswith('edit_'):
            import fine
            if cmd=='edit_create':return fine.create(store,request['task_id'],request['clip_id'])
            if cmd=='edit_get':return fine.get(store,request['project_id'])
            if cmd=='edit_options':
                from fine_auto import options_checked
                project=fine.get(store,request['project_id'])
                if project['revision']!=request['revision'] or project['status'] in ('busy','queued'):raise ValueError('项目正在处理或已有新修改。')
                project['edit_options']=options_checked(request['options'])
                step=request.get('step',0)
                if type(step) is not int or not 0<=step<=5:raise ValueError('问答步骤无效。')
                project['question_step']=step
                return fine.save(store,project)
            if cmd=='edit_prepare':
                project=fine.get(store,request['project_id'])
                if project['revision']!=request['revision'] or project['status'] in ('busy','queued'):raise ValueError('项目已有其他操作，请等待完成后重试。')
                (store.task_dir(project['id'])/'cancel').unlink(missing_ok=True)
                project['status']='queued';project['stage']='等待处理';return fine.save(store,project)
            if cmd=='edit_abandon':
                project=fine.get(store,request['project_id'])
                if project['status']=='queued':project['status']='idle';return fine.save(store,project)
                return project
            if cmd=='edit_cancel':
                project=fine.get(store,request['project_id'])
                (store.task_dir(project['id'])/'cancel').write_text('cancel',encoding='utf-8')
                return project
            if cmd=='edit_source':
                project=fine.get(store,request['project_id']);task=store.get(project['task_id'])
                from event_preview import playback
                return playback(Runner(store,task['id']),{'id':project['clip_id'],'start':project['source_start'],'end':project['source_end']})
            return fine.Editor(store,request).run()
        if cmd=='relocate':
            task=store.get(request['task_id']);info=probe(request['path'],store.settings(),store)
            old=task.get('media',{})
            if abs(info['duration']-task['duration'])>1 or (old and any(info[k]!=old.get(k) for k in ('width','height','size'))):
                raise ValueError('新文件的时长、大小或画面尺寸不匹配，请选择原录播文件。')
            task['video']=info['path'];task['media']=info;store.put(task);return task
        if cmd=='bootstrap':
            import fine
            for project in fine.summaries(store):
                if project['status'] in ('busy','queued'):
                    project['status']='idle';project['stage']='上次处理已中断，草稿已保留'
                    fine.fine_progress.finish(project, 'interrupted')
                    fine.save(store,project)
            (store.root/'STOP').unlink(missing_ok=True)
            for task in store.tasks():
                if task['status'] in ACTIVE and task['status']!='queued':
                    task['status']='interrupted';task['stage']='上次运行被中断，可以重试或导出已有片段';store.put(task)
            return state(store)
        if cmd=='state':return state(store)
        if cmd=='recover_failure':return recover_failure(store,request)
        if cmd=='save_settings':return store.save_settings(request['values'])
        if cmd=='probe':
            settings=store.settings();result=probe(request['path'],settings,store)
            output=store.root/'imports'/(uuid.uuid4().hex+'.jpg')
            try:result['thumbnail']=thumbnail(result['path'],output,min(15,result['duration']/3),settings,store)
            except Exception:result['thumbnail']=''
            return result
        if cmd=='create_task':return create_task(store,request)
        if cmd=='delete_task':
            from task_deletion import delete_task
            return delete_task(store,request['task_id'],request.get('delete_files',False))
        if cmd=='retry_task':
            task=store.get(request['task_id'])
            return create_task(store,{'video':task['video'],'subtitle':task['subtitle'],'chat':task['chat'],'prefs':task['prefs'],
                                      'audio_track':task.get('audio_track',0)})
        if cmd=='cancel_task':
            task=store.get(request['task_id'])
            (store.task_dir(task['id'])/'cancel').write_text('cancel',encoding='utf-8')
            if task['status']=='queued':
                task['status']='cancelled';task['stage']='任务已取消';store.put(task)
            return task
        if cmd=='run':
            task=store.get(request['task_id'])
            if task['status']=='cancelled':return task
            return Runner(store,task['id']).run()
        if cmd=='export':
            task=store.get(request['task_id'])
            (store.task_dir(task['id'])/'cancel').unlink(missing_ok=True)
            runner=Runner(store,task['id'])
            runner.export(request['clip_ids'],'separate','none')
            return runner.task
        if cmd=='recheck':
            (store.task_dir(request['task_id'])/'cancel').unlink(missing_ok=True)
            return Runner(store,request['task_id']).recheck()
        if cmd in ('preview','preview_compatible'):
            runner=Runner(store,request['task_id'])
            clip=next((c for c in runner.task['clips'] if c['id']==request['clip_id']),None)
            if not clip:raise ValueError('片段不存在。')
            from event_preview import playback
            if cmd=='preview_compatible':
                from event_preview import prepare
                (runner.folder/'cancel').unlink(missing_ok=True)
                return prepare(runner,clip)
            return playback(runner,clip)
        if cmd=='install_model':return install_model(store)
        if cmd=='api_test':
            settings=store.settings(secret=True)
            usage={}
            chat_api(settings,[{'role':'system','content':'Return only valid JSON.'},
                               {'role':'user','content':'Reply with {"ok":true}.'}],store,on_usage=usage.update)
            return {'ok':True,'model':settings['api_model'],'usage':usage}
        if cmd=='reveal':
            if request.get('project_id') is not None or request.get('export_id') is not None:
                project_id=request.get('project_id');export_id=request.get('export_id')
                if not isinstance(project_id,str) or not project_id.strip() or not isinstance(export_id,str) or not export_id.strip():
                    raise ValueError('请提供有效的细剪项目与导出记录。')
                import fine
                project=fine.get(store,project_id)
                record=next((r for r in project.get('exports',[]) if isinstance(r,dict) and r.get('id')==export_id),None)
                if record is None:raise ValueError('此细剪项目没有该导出记录。')
                raw=record.get('path')
                if not isinstance(raw,str) or not raw or '\x00' in raw or not Path(raw).is_absolute():
                    raise ValueError('导出记录的文件路径无效。')
                path=Path(raw)
                if not path.is_file():raise ValueError('导出文件已被移动或删除。')
                path=path.resolve().parent
            elif request.get('task_id'):
                task=store.get(request['task_id']);path=Path(task.get('output_folder') or task['video']).resolve()
            else:path=store.root
            if not path.exists():raise ValueError('目标文件夹已被移动或删除。')
            return {'path':str(path),'is_file':path.is_file()}
        raise ValueError('不支持的操作。')
    finally:
        store.db.close()

def main():
    if len(sys.argv)>1 and sys.argv[1]=='--asr':
        sys.argv.pop(1)
        import asr
        asr.main();return
    request=json.loads(sys.stdin.buffer.readline().decode('utf-8',errors='strict'))
    try:
        result=dispatch(request)
        print(json.dumps({'result':result},ensure_ascii=False),flush=True)
    except Exception as exc:
        # Request bodies, paths to credentials, and provider response bodies are never logged.
        print(json.dumps({'error':str(exc)[:2500]},ensure_ascii=False),flush=True)
        sys.exit(1)

if __name__=='__main__':main()
