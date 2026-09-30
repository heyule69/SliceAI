"""Original-audio evidence for transcript gaps; a VAD gap is never enough."""
from __future__ import annotations
import hashlib
import json
import math
import wave
from pathlib import Path
from engine import command, tool_path
from fine_candidates import emotional, intersects, reliable_words


def characterize(samples, rate, begin, end):
    """Conservative measured evidence, not a sound/emotion classifier."""
    import numpy as np
    section = samples[max(0, int(begin*rate)):min(len(samples), int(end*rate))]
    frame = int(.1*rate)
    count = len(section)//frame
    if count < 5:
        return {'safe': False, 'reason': '停顿采样不足'}
    rms = np.sqrt(np.mean(section[:count*frame].reshape(count, frame).astype(np.float64)**2, axis=1))
    db = 20*np.log10(np.maximum(rms, 1e-8))
    neighbors = np.concatenate((samples[max(0, int((begin-1.5)*rate)):max(0, int(begin*rate))],
                                samples[min(len(samples), int(end*rate)):min(len(samples), int((end+1.5)*rate))]))
    neighbor_rms = float(np.sqrt(np.mean(neighbors.astype(np.float64)**2))) if len(neighbors) else 0.
    interior_rms = float(np.sqrt(np.mean(section.astype(np.float64)**2)))
    ratio = interior_rms/max(neighbor_rms, 1e-8)
    spread = float(np.percentile(db, 90)-np.percentile(db, 10))
    # Quiet original mix is independent corroboration. Relative low energy is
    # accepted only when it is also absolutely quiet and stable; a loud song,
    # laughter burst or whisper cannot pass merely by being outside VAD.
    quiet = float(np.percentile(db, 95)) <= -43
    stable_background = (float(np.percentile(db, 95)) <= -32 and float(np.max(db)) <= -25
                         and ratio <= .32 and spread <= 6)
    safe = quiet or stable_background
    return {'safe': bool(safe), 'type': 'original_audio_measurement',
            'p95_dbfs': round(float(np.percentile(db, 95)), 2), 'max_dbfs': round(float(np.max(db)), 2),
            'neighbor_energy_ratio': round(ratio, 4), 'energy_spread_db': round(spread, 2),
            'criterion': 'quiet_original_mix' if quiet else 'quiet_stable_background' if stable_background else 'insufficient',
            'reason': '原始混音低能量并与语音间隙一致' if quiet else
                      '原始混音持续低能量，较邻接讲话明显安静' if stable_background else
                      '原始音频仍有明显活动，间隙不能证明声音可删'}


def voice_activity(samples, begin, end, model):
    """A second gap-only pass retains VAD sounds with no recognized words."""
    import numpy as np
    import sherpa_onnx
    path=Path(model)/'silero_vad.onnx'
    if not path.is_file():return {'type':'original_gap_vad','available':False,'reason':'缺少原声局部语音检测证据'}
    config=sherpa_onnx.VadModelConfig()
    config.silero_vad.model=str(path)
    config.silero_vad.threshold=.35
    config.silero_vad.min_silence_duration=.1
    config.silero_vad.min_speech_duration=.1
    config.silero_vad.max_speech_duration=10
    config.sample_rate=16000;config.num_threads=1
    vad=sherpa_onnx.VoiceActivityDetector(config,buffer_size_in_seconds=45)
    section=samples[max(0,int(begin*16000)):min(len(samples),int(end*16000))]
    window=config.silero_vad.window_size
    for offset in range(0,len(section),window):
        frame=section[offset:offset+window]
        if len(frame)<window:frame=np.pad(frame,(0,window-len(frame)))
        vad.accept_waveform(frame)
    vad.flush();detected=not vad.empty()
    return {'type':'original_gap_vad','available':True,'detected':detected,'threshold':.35,
            'reason':'原声间隙含语音或类似人声的活动，保留声音' if detected else '原声局部未检测到语音活动；仍需声学及故事复核'}


def candidates(editor, rows, options, protected=()):
    if 'silence' not in options['speech']:
        return []
    sorted_rows = sorted(rows, key=lambda row: row['start'])
    spans=[]
    for row in sorted_rows:
        words=reliable_words(row)
        if words:
            spans.extend({'id':f"word:{word['id']}",'row_id':row['id'],'word_id':word['id'],
                          'start':word['start'],'end':word['end']} for word in words)
        else:spans.append({'id':f"row:{row['id']}",'row_id':row['id'],'start':row['start'],'end':row['end']})
    spans.sort(key=lambda span:span['start'])
    padding = {'light': .8, 'standard': .5, 'tight': .3}[options['pace']]
    minimum = {'light': 3.5, 'standard': 2., 'tight': 1.5}[options['pace']]
    gaps = []
    for left, right in zip(spans, spans[1:]):
        a, b = left['end']+padding, right['start']-padding
        if right['start']-left['end'] <= minimum or b-a < .5:
            continue
        candidate = {'id': f"gap:{left['id']}:{right['id']}", 'kind': 'silence', 'start': a, 'end': b,
                     'text': '', 'quote': '', 'row_ids': list(dict.fromkeys((left['row_id'],right['row_id']))),
                     'word_ids': [span['word_id'] for span in (left,right) if 'word_id' in span],
                     'status': 'suggested', 'reason': '', 'block_reason': '',
                     'evidence': [{'type': 'forced_word_gap' if left['row_id']==right['row_id'] else 'transcript_gap',
                                   'start': left['end'], 'end': right['start']} ]}
        neighbors = [row for row in sorted_rows if row['end'] > a-8 and row['start'] < b+8]
        if any(emotional(row) for row in neighbors):
            candidate.update(status='blocked', block_reason='邻近情绪、笑哭或歌曲；保留表达性停顿')
        elif any(intersects(candidate, region) for region in protected):
            candidate.update(status='blocked', block_reason='原声局部内容存在丢失风险')
        gaps.append(candidate)
    if not any(candidate['status'] == 'suggested' for candidate in gaps):
        return gaps
    source = Path(editor.task['video']); stat = source.stat()
    from pipeline import model_dir
    model=model_dir(editor.store,editor.settings);vad_file=model/'silero_vad.onnx'
    vad_identity=[str(vad_file),vad_file.stat().st_size,vad_file.stat().st_mtime_ns] if vad_file.is_file() else ['unavailable']
    key = hashlib.sha256(json.dumps(['gap-evidence-v2-original-vad', str(source.resolve()), stat.st_size, stat.st_mtime_ns,
                                    editor.clip, editor.task.get('audio_track', 0), options['pace'],
                                    vad_identity,[(c['id'],c['start'],c['end']) for c in gaps]]).encode()).hexdigest()[:20]
    folder = editor.folder/'gap-check'; folder.mkdir(exist_ok=True)
    cache = folder/(key+'.json')
    measurements = json.loads(cache.read_text(encoding='utf-8')) if cache.is_file() else {}
    needed = [candidate for candidate in gaps if candidate['status'] == 'suggested' and candidate['id'] not in measurements]
    if needed:
        from media_audio import aligned_audio_args
        import numpy as np
        wav = folder/(key+'.wav')
        try:
            editor.persist('检测音频长静音 · 对照原始混音与局部声音')
            command(aligned_audio_args(tool_path(editor.settings, 'ffmpeg'), source, wav,
                track=editor.task.get('audio_track', 0), start=editor.clip['start'],
                duration=editor.clip['end']-editor.clip['start'], rate=16000, pcm='pcm_s16le',
                ffprobe=tool_path(editor.settings, 'ffprobe')), editor.store, editor.p['id'])
            with wave.open(str(wav), 'rb') as stream:
                if stream.getframerate() != 16000 or stream.getnchannels() != 1 or stream.getsampwidth() != 2:
                    raise ValueError('原始音频间隙采样格式无效。')
                samples = np.frombuffer(stream.readframes(stream.getnframes()), dtype='<i2').astype(np.float32)/32768
            for candidate in needed:
                measurements[candidate['id']] = characterize(samples, 16000,
                    candidate['start']-editor.clip['start'], candidate['end']-editor.clip['start'])
                evidence=measurements[candidate['id']]
                if evidence['safe'] and evidence['p95_dbfs']>-80:
                    activity=voice_activity(samples,candidate['start']-editor.clip['start'],
                                            candidate['end']-editor.clip['start'],model)
                    evidence['voice_activity']=activity
                    if not activity['available'] or activity.get('detected'):
                        evidence.update(safe=False,reason=activity['reason'])
            temporary = cache.with_suffix('.partial')
            temporary.write_text(json.dumps(measurements, ensure_ascii=False), encoding='utf-8'); temporary.replace(cache)
        finally:
            wav.unlink(missing_ok=True)
    for candidate in gaps:
        if candidate['status'] != 'suggested':
            continue
        evidence = measurements[candidate['id']]; candidate['evidence'].append(evidence)
        if not evidence['safe']:
            candidate.update(status='blocked', block_reason=evidence['reason'])
    return gaps
