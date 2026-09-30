"""Read a user-specified recording; write full local ASR and measurements separately."""
import argparse
import json
import os
import subprocess
import threading
import time
from pathlib import Path
import psutil

root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('video');args=parser.parse_args()
video=Path(args.video).resolve();before=video.stat()
folder=root/'.test-artifacts/real-recording';folder.mkdir(parents=True,exist_ok=True)
worker=root/'src-tauri/resources/worker/sliceai-worker.exe'
ffmpeg=worker.parent/'bin/ffmpeg.exe';ffprobe=worker.parent/'bin/ffprobe.exe'
info=json.loads(subprocess.check_output([str(ffprobe),'-v','error','-show_entries','format=duration,size','-of','json',str(video)],creationflags=0x08000000))
duration=float(info['format']['duration'])
output=folder/'transcript.jsonl'
started=time.monotonic();peak=[0];stop=threading.Event()
with (folder/'asr-errors.log').open('wb') as errors:
    proc=subprocess.Popen([str(worker),'--asr','--video',str(video),'--model',
        str(Path(os.environ['LOCALAPPDATA'])/'com.sliceai.desktop/models/sensevoice-int8'),
        '--output',str(output),'--ffmpeg',str(ffmpeg),'--threads','2'],
        stdout=subprocess.PIPE,stderr=errors,creationflags=0x08000000,env={**os.environ,'PYTHONUTF8':'1'})
    process=psutil.Process(proc.pid)
    def monitor():
        while not stop.wait(.1):
            try:peak[0]=max(peak[0],sum(p.memory_info().rss for p in [process,*process.children(recursive=True)]))
            except (psutil.NoSuchProcess,psutil.AccessDenied):pass
    monitor_thread=threading.Thread(target=monitor,daemon=True);monitor_thread.start()
    last=0
    for line in proc.stdout:
        try:event=json.loads(line.decode('utf-8'))
        except (ValueError,UnicodeDecodeError):continue
        elapsed=time.monotonic()-started
        if elapsed-last>=25 or event.get('done'):
            event.update(progress=round(100*event['seconds']/duration,1),wall_seconds=round(elapsed,1),peak_mb=round(peak[0]/1024**2,1))
            print(json.dumps(event,ensure_ascii=False),flush=True)
            (folder/'progress.json').write_text(json.dumps(event,ensure_ascii=False,indent=2),encoding='utf-8')
            last=elapsed
    code=proc.wait();stop.set();monitor_thread.join();proc.stdout.close()
    if code:raise SystemExit(f'ASR exited {code}; see {folder / "asr-errors.log"}')

import sys
sys.path.insert(0,str(root/'backend'))
from formats import write_srt,transcript_windows
rows=[json.loads(line) for line in output.read_text(encoding='utf-8').splitlines() if line.strip()]
for row in rows:row['end']=min(row['end'],duration)
write_srt(folder/'transcript.srt',rows)
(folder/'transcript.json').write_text(json.dumps(rows,ensure_ascii=False),encoding='utf-8')
after=video.stat()
result={'video':str(video),'duration_seconds':duration,'source_bytes':before.st_size,
 'wall_seconds':round(time.monotonic()-started,2),'sampled_peak_worker_and_ffmpeg_mb':round(peak[0]/1024**2,1),
 'sentences':len(rows),'analysis_windows':len(transcript_windows(rows)),
 'source_size_and_mtime_unchanged':before.st_size==after.st_size and before.st_mtime_ns==after.st_mtime_ns,
 'last_speech_end':rows[-1]['end'] if rows else None,'transcript':str(folder/'transcript.srt')}
(folder/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False),flush=True)
