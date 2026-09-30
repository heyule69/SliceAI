"""Persist real execution checkpoints for the desktop activity panel."""
from datetime import datetime, timezone
import math
import re
import uuid


def begin(project, command, options=None):
    options = options or project.get('edit_options', {})
    version = next((v for v in project['versions'] if v['id'] == project.get('current_version')), {})
    steps = [('prepare', '检查素材与处理要求')]
    reduce_audio = options.get('music') == 'reduce' if command == 'edit_auto' else bool(version.get('audio_strength'))
    if reduce_audio and command in ('edit_auto', 'edit_preview', 'edit_confirm', 'edit_export'):
        steps += [('audio', '降低背景音乐')]
    if command == 'edit_auto':
        if reduce_audio:
            steps += [('transcribe', '重新转写与对照原声')]
        steps += [('plan', '理解片段与制定方案'), ('review', '复核故事与删减依据')]
        if 'silence' in options.get('speech', []):
            steps += [('silence', '检测长静音')]
        if options.get('subtitles') == 'checked' and not reduce_audio:
            steps += [('captions', '核对字幕')]
    if command in ('edit_auto', 'edit_preview', 'edit_confirm', 'edit_export'):
        steps += [('video', '处理视频区间')]
        steps += [('finish', '导出成片' if command == 'edit_export' else '合成并校验成片')]
    elif command == 'edit_audio_sample':
        steps += [('audio', '处理声音试听')]
    elif command == 'edit_source_preview':
        steps += [('source', '准备兼容播放片段')]
    elif command == 'edit_chat':
        steps += [('plan', '理解片段与制定方案')]
    else:
        steps += [('save', '保存修改')]
    project['execution'] = {
        'id': str(uuid.uuid4()), 'command': command, 'state': 'running',
        'started_at': datetime.now(timezone.utc).isoformat(), 'active': 'prepare',
        'steps': [{'id': key, 'title': title, 'state': 'running' if i == 0 else 'pending',
                   'detail': '', 'percent': None} for i, (key, title) in enumerate(steps)],
    }


def update(project, stage):
    execution = project.get('execution')
    if not execution or execution['state'] != 'running':
        return
    mapping = (
        ('理解片段与剪辑要求', 'plan'), ('AI 正在拟定方案', 'plan'),
        ('复核故事完整性', 'review'), ('检测音频长静音', 'silence'),
        ('重新转写处理后音频', 'transcribe'), ('对照原声转写', 'transcribe'),
        ('核对字幕', 'captions'), ('按所选要求生成预览', 'video'),
        ('检查素材与来源', 'video'), ('生成预览区间', 'video'), ('导出区间', 'video'),
        ('拼接视频区间', 'video'), ('降低背景音乐', 'audio'), ('准备声音试听', 'audio'),
        ('按剪辑区间裁切已处理音频', 'video'),
        ('合成画面与声音', 'finish'), ('校验成片', 'finish'), ('写入导出文件', 'finish'),
        ('正在准备粗剪片段', 'source'), ('保存修改', 'save'),
    )
    key = next((key for prefix, key in mapping if stage.startswith(prefix)), None)
    step = next((s for s in execution['steps'] if s['id'] == key), None)
    if step is None:
        return
    for previous in execution['steps']:
        if previous is not step and previous['state'] == 'running':
            previous['state'] = 'done'
    step.update(state='running', detail=stage)
    # Only the audio worker currently reports measured percentage. An interval
    # index such as 1/1 is not render completion and must never become 100%.
    match = re.search(r'([\d.]+)%', stage) if key == 'audio' else None
    value = float(match.group(1)) if match else None
    step['percent'] = max(0, min(100, value)) if value is not None and math.isfinite(value) else None
    execution['active'] = key


def finish(project, state):
    execution = project.get('execution')
    if not execution or execution['state'] != 'running':
        return
    execution['state'] = state
    execution['finished_at'] = datetime.now(timezone.utc).isoformat()
    for step in execution['steps']:
        if step['state'] == 'running':
            step['state'] = 'done' if state == 'done' else state
        elif step['state'] == 'pending' and state == 'done':
            step['state'] = 'skipped'
            step['detail'] = '本次无需重复处理'
