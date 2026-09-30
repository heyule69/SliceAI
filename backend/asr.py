"""Runs in its own short-lived process. Audio is streamed; no whole-recording WAV."""
from __future__ import annotations
import argparse
import json
import math
import re
import subprocess
import sys
from pathlib import Path

ASR_FORMAT = 2


def result_row(result, start, end, row_id, runtime_version='1.12.40'):
    """Retain CTC emission anchors; they are deliberately not word spans."""
    text = re.sub(r'<\|[^>]+\|>', '', result.text).strip()
    if not text:
        return None
    tokens = []
    previous = -1
    for token, timestamp in zip(getattr(result, 'tokens', ()) or (),
                                getattr(result, 'timestamps', ()) or ()):
        if not isinstance(token, str) or re.fullmatch(r'<\|[^>]+\|>', token):
            continue
        try:
            anchor = start + float(timestamp)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(anchor) or anchor < start or anchor > end or anchor < previous:
            continue
        tokens.append({'text': token, 'anchor': round(anchor, 6), 'timing_method': 'ctc_emission'})
        previous = anchor
    return {'id': row_id, 'start': start, 'end': end, 'text': text,
            'asr_format': ASR_FORMAT, 'timing_method': 'vad_segment', 'tokens': tokens,
            'timing_metadata': {'token_boundaries': 'ctc_emission_only',
                                'event_labels': 'model_hints_not_verified'},
            'vad': {'start': start, 'end': end, 'method': 'silero_vad', 'sample_rate': 16000},
            'asr': {'model': 'SenseVoiceSmall-int8', 'runtime': 'sherpa-onnx',
                    'version': runtime_version, 'use_itn': True,
                    **{field: str(getattr(result, field, '') or '')
                       for field in ('lang', 'emotion', 'event')}}}


def shift_row_timing(row, offset):
    """Move all ASR coordinates together when a file is an extracted event."""
    row['start'] += offset
    row['end'] += offset
    for token in row.get('tokens', []):
        token['anchor'] += offset
    vad = row.get('vad')
    if isinstance(vad, dict):
        vad['start'] += offset
        vad['end'] += offset
    return row

def run_asr(args):
    import numpy as np
    import sherpa_onnx
    from engine import CREATE_FLAGS, kill_tree
    from media_audio import aligned_audio_args
    model=Path(args.model)
    recognizer=sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=str(model/'model.int8.onnx'),tokens=str(model/'tokens.txt'),
        num_threads=args.threads,use_itn=True,language='auto',provider='cpu')
    config=sherpa_onnx.VadModelConfig()
    config.silero_vad.model=str(model/'silero_vad.onnx')
    config.silero_vad.min_silence_duration=.45
    config.silero_vad.min_speech_duration=.25
    config.silero_vad.max_speech_duration=18
    config.sample_rate=16000
    config.num_threads=1
    vad=sherpa_onnx.VoiceActivityDetector(config,buffer_size_in_seconds=45)
    window=config.silero_vad.window_size
    count=0;consumed=0;last_report=0
    log=Path(args.output).with_suffix('.ffmpeg.log')
    with log.open('wb') as error,Path(args.output).open('w',encoding='utf-8',newline='\n') as out:
        decode=aligned_audio_args(args.ffmpeg,args.video,'pipe:1',track=args.audio_track,
                                  rate=16000,ffprobe=args.ffprobe,pcm='pcm_s16le')
        proc=subprocess.Popen(decode,
                              stdout=subprocess.PIPE,stderr=error,stdin=subprocess.DEVNULL,creationflags=CREATE_FLAGS)
        def drain():
            nonlocal count
            while not vad.empty():
                segment=vad.front
                samples=segment.samples
                # The VAD max duration prevents unbounded inference on music or long speech.
                if len(samples)>0:
                    stream=recognizer.create_stream()
                    stream.accept_waveform(16000,samples)
                    recognizer.decode_stream(stream)
                    row=result_row(stream.result,segment.start/16000,
                                   (segment.start+len(samples))/16000,count,
                                   getattr(sherpa_onnx,'__version__','1.12.40'))
                    if row:
                        out.write(json.dumps(row,ensure_ascii=False)+'\n');out.flush();count+=1
                    del stream,samples
                vad.pop()
        try:
            while True:
                raw=proc.stdout.read(window*2)
                if not raw:
                    break
                samples=np.frombuffer(raw,dtype=np.int16).astype(np.float32)/32768
                consumed+=len(samples)
                if len(samples)<window:
                    samples=np.pad(samples,(0,window-len(samples)))
                vad.accept_waveform(samples);drain()
                if consumed-last_report>=16000*5:
                    print(json.dumps({'seconds':consumed/16000,'sentences':count}),flush=True)
                    last_report=consumed
            vad.flush();drain()
            if proc.wait(timeout=30):
                raise RuntimeError('无法解码音轨，请检查录播文件。')
            if not count:
                raise RuntimeError('没有识别到语音，请检查音轨，或直接导入字幕。')
            print(json.dumps({'seconds':consumed/16000,'sentences':count,'done':True}),flush=True)
        finally:
            kill_tree(proc)
            proc.stdout.close()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--video',required=True);parser.add_argument('--model',required=True)
    parser.add_argument('--output',required=True);parser.add_argument('--ffmpeg',required=True)
    parser.add_argument('--threads',type=int,default=2)
    parser.add_argument('--audio-track',type=int,default=0)
    parser.add_argument('--ffprobe')
    run_asr(parser.parse_args())

if __name__=='__main__':
    main()
