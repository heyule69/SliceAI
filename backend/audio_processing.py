from __future__ import annotations
import hashlib
import json
import sys
from pathlib import Path
from engine import command,resource_dir,tool_path
from audio_identity import ENGINE_ID


def locations():
    if getattr(sys,'frozen',False):
        root=resource_dir()/'audio'
        return [str(root/'sliceai-audio.exe')],root/'model'
    root=Path(__file__).resolve().parents[1]
    return [str(root/'.audio-venv/Scripts/python.exe'),str(root/'backend/audio_worker.py')],root/'audio-model/BandItPlus'


def ready():
    prefix,model=locations()
    try:
        manifest=json.loads((model/'manifest.json').read_text(encoding='utf-8'))
        return (Path(prefix[0]).is_file() and manifest.get('engine')==ENGINE_ID
                and (model/manifest['file']).is_file() and (model/manifest['config']).is_file())
    except (OSError,ValueError,KeyError):return False


def process_audio(editor,source,folder,strength,start=None,duration=None):
    prefix,model=locations()
    if not ready():raise ValueError('声音组件不完整，请安装包含声音模型的完整版本。')
    source=Path(source);stat=source.stat()
    key=hashlib.sha256(json.dumps([ENGINE_ID,str(source),stat.st_size,stat.st_mtime_ns,strength,start,duration]).encode()).hexdigest()[:20]
    raw=folder/f'original-{key}.wav';processed=folder/f'processed-{key}.wav'
    args=[tool_path(editor.settings,'ffmpeg'),'-v','error','-nostdin','-y']
    if start is not None:args+=['-ss',str(start)]
    args+=['-i',str(source)]
    if duration is not None:args+=['-t',str(duration)]
    temporary=raw.with_suffix('.partial.wav')
    args+=['-vn','-ar','48000','-ac','1','-c:a','pcm_f32le',str(temporary)]
    if not raw.is_file():
        try:command(args,editor.store,editor.p['id']);temporary.replace(raw)
        finally:temporary.unlink(missing_ok=True)
    def report(line):
        try:
            event=json.loads(line)
            resource=event.get('resources')
            if isinstance(resource,dict) and type(resource.get('threads')) is int:
                editor.p['audio_resources']={'threads':max(1,min(16,resource['threads'])),
                    'reason':str(resource.get('reason',''))[:100],
                    'available_memory_mb':resource.get('available_memory_mb')}
                editor.persist()
            p=event.get('progress')
            if p is not None:editor.persist(f'降低背景音乐 · {p:.0f}%')
        except (ValueError,TypeError):pass
    if not processed.is_file():
        try:
            command(prefix+['--input',str(raw),'--output',str(processed),'--model',str(model),'--strength',str(strength)],editor.store,editor.p['id'],on_line=report)
        finally:
            # Parent cleanup also covers cancellation that terminates the worker process tree.
            for suffix in ('.input.partial.wav','.speech.partial.wav','.resampled.partial.wav','.partial.wav'):
                processed.with_suffix(suffix).unlink(missing_ok=True)
    return processed


def sample(editor):
    start=float(editor.req.get('start',editor.p['source_start']))
    if not editor.p['source_start']<=start<editor.p['source_end']:raise ValueError('试听位置超出原片段。')
    duration=min(20,editor.p['source_end']-start)
    folder=editor.folder/'audio-samples';folder.mkdir(exist_ok=True)
    processed=process_audio(editor,editor.task['video'],folder,1.0,start,duration)
    raw=processed.with_name(processed.name.replace('processed-','original-'))
    editor.p['audio_sample']={'engine':ENGINE_ID,'start':start,'duration':duration,'strength':1.0,
        'original':{'path':str(raw)},'processed':{'path':str(processed)}}
