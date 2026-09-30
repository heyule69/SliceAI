from __future__ import annotations
import hashlib
import json
import math
import sys
from pathlib import Path
from engine import check_cancel,command,resource_dir,tool_path
from audio_identity import ENGINE_ID
from audio_cache import canonical, checked_folder, ensure_space, record_cache
from media_audio import TIMELINE_VERSION, aligned_audio_args, audio_track, probe_audio


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


def model_identity():
    """Bind cached stems to both approved engine and installed model revision."""
    _, model = locations()
    record = {'engine': ENGINE_ID}
    try:
        raw = (model / 'manifest.json').read_bytes()
        manifest = json.loads(raw.decode('utf-8', errors='strict'))
        record['manifest'] = hashlib.sha256(raw).hexdigest()
        for name in ('file', 'config'):
            path = (model / manifest[name]).resolve()
            if path.parent != model.resolve():
                raise ValueError('声音模型路径无效。')
            stat = path.stat()
            record[name] = [str(path), stat.st_size, stat.st_mtime_ns]
    except (OSError, ValueError, KeyError):
        record['missing'] = True
    return hashlib.sha256(canonical(record).encode('utf-8')).hexdigest()[:24]


def source_identity(editor, source, start=None, duration=None):
    source = Path(source).resolve()
    stat = source.stat()
    if start is not None:
        start=float(start)
        if not math.isfinite(start) or start < 0:raise ValueError('音频片段起点无效。')
    if duration is not None:
        duration=float(duration)
        if not math.isfinite(duration) or duration <= 0:raise ValueError('音频片段时长无效。')
    track = audio_track(getattr(editor, 'task', {}).get('audio_track', 0))
    return {'source': str(source), 'size': stat.st_size, 'mtime': stat.st_mtime_ns,
            'start': start, 'end': start + duration if start is not None and duration is not None else duration,
            'audio_track': track, 'timeline_version': TIMELINE_VERSION}


def process_audio(editor,source,folder,strength,start=None,duration=None):
    prefix,model=locations()
    if not ready():raise ValueError('声音组件不完整，请安装包含声音模型的完整版本。')
    strength=float(strength)
    if not math.isfinite(strength) or not 0<=strength<=1:raise ValueError('声音强度无效。')
    source=Path(source).resolve();folder=checked_folder(editor,folder);folder.mkdir(parents=True,exist_ok=True)
    if editor.store is not None:check_cancel(editor.store,editor.p['id'])
    source_key=source_identity(editor,source,start,duration)
    identity={**source_key,'engine':ENGINE_ID,'model_revision':model_identity()}
    raw_key=hashlib.sha256(canonical(source_key).encode('utf-8')).hexdigest()[:20]
    stem_key=hashlib.sha256(canonical(identity).encode('utf-8')).hexdigest()[:20]
    mix_key=hashlib.sha256(canonical({**identity,'strength':strength}).encode('utf-8')).hexdigest()[:20]
    raw=folder/f'original-{raw_key}.wav';speech=folder/f'speech-{stem_key}.wav';processed=folder/f'processed-{mix_key}.wav'
    if processed.is_file() and speech.is_file() and raw.is_file():
        record_cache(folder,stem_key,identity,[raw,speech,processed])
        ensure_space(editor,folder,duration or 1,current_identity=identity,allocate_bytes=0)
        return processed
    ffmpeg=tool_path(editor.settings,'ffmpeg');ffprobe=tool_path(editor.settings,'ffprobe')
    info=probe_audio(source,ffprobe,lambda args:command(args,editor.store,editor.p['id'],timeout=45))
    seconds=duration if duration is not None else info['duration']
    ensure_space(editor,folder,seconds,raw_ready=raw.is_file(),stem_ready=speech.is_file(),current_identity=identity)
    temporary=raw.with_suffix('.partial.wav')
    if not raw.is_file():
        args=aligned_audio_args(ffmpeg,source,temporary,track=source_key['audio_track'],start=start,
                                duration=duration,info=info)
        try:command(args,editor.store,editor.p['id']);temporary.replace(raw)
        finally:temporary.unlink(missing_ok=True)
    record_cache(folder,stem_key,identity,[raw,speech,processed])
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
            command(prefix+['--input',str(raw),'--output',str(processed),'--model',str(model),
                            '--speech-cache',str(speech),'--strength',str(strength)],editor.store,editor.p['id'],on_line=report)
        finally:
            # Parent cleanup also covers cancellation that terminates the worker process tree.
            for suffix in ('.input.partial.wav','.speech.partial.wav','.resampled.partial.wav','.partial.wav'):
                processed.with_suffix(suffix).unlink(missing_ok=True)
            speech.with_suffix('.partial.wav').unlink(missing_ok=True)
            record_cache(folder,stem_key,identity,[raw,speech,processed])
    return processed


def sample(editor):
    start=float(editor.req.get('start',editor.p['source_start']))
    if not editor.p['source_start']<=start<editor.p['source_end']:raise ValueError('试听位置超出原片段。')
    duration=min(20,editor.p['source_end']-start)
    folder=checked_folder(editor,editor.folder/'audio-samples');folder.mkdir(exist_ok=True)
    processed=process_audio(editor,editor.task['video'],folder,1.0,start,duration)
    source_key=source_identity(editor,editor.task['video'],start,duration)
    raw_key=hashlib.sha256(canonical(source_key).encode('utf-8')).hexdigest()[:20]
    raw=folder/f'original-{raw_key}.wav'
    editor.p['audio_sample']={'engine':ENGINE_ID,'start':start,'duration':duration,'strength':1.0,
        'original':{'path':str(raw)},'processed':{'path':str(processed)}}
