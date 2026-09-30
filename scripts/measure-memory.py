"""Development measurement using psutil; not a runtime dependency."""
import json
import os
import subprocess
import time
from pathlib import Path
import psutil

root=Path(__file__).resolve().parents[1]
worker=root/'src-tauri/resources/worker/sliceai-worker.exe'
args=[str(worker),'--asr','--video',str(root/'.test-artifacts/asr-中文.wav'),
      '--model',str(Path(os.environ['LOCALAPPDATA'])/'com.sliceai.desktop/models/sensevoice-int8'),
      '--output',str(root/'.test-artifacts/measured-asr.jsonl'),'--ffmpeg',str(worker.parent/'bin/ffmpeg.exe'),'--threads','2']
child=subprocess.Popen(args,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,creationflags=0x08000000)
process=psutil.Process(child.pid);peak=0;started=time.monotonic()
while child.poll() is None:
    try:
        total=sum(p.memory_info().rss for p in [process,*process.children(recursive=True)] if p.is_running())
        peak=max(peak,total)
    except (psutil.NoSuchProcess,psutil.AccessDenied):pass
    time.sleep(.03)
if child.returncode:raise RuntimeError(child.stderr.read().decode('utf-8',errors='replace'))
result={'asr_sample_seconds':26.694,'wall_seconds':round(time.monotonic()-started,2),'sampled_peak_working_set_mb':round(peak/1024**2,1),
        'notes':'Sum of worker and FFmpeg working sets, sampled every 30 ms; synthetic speech, not a long-stream benchmark.'}
(root/'.test-artifacts/memory-asr.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result))
