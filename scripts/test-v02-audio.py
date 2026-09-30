"""Measure real sample inference without modifying source recordings."""
import json,os,subprocess,time,threading
from pathlib import Path
import psutil
root=Path(__file__).resolve().parents[1]
folder=root/'test-results/v0.2/audio';folder.mkdir(parents=True,exist_ok=True)
source=next(Path('D:/Download/BaiduNetdisk').glob('2026-08-28*.mp4'))
ffmpeg=root/'src-tauri/resources/worker/bin/ffmpeg.exe'
results=[]
for name,start in [('聊天',11590),('情绪与低声',17200),('笑声候选',2180),('背景歌候选',9000)]:
    raw=folder/(name+'-原声.wav');out=folder/(name+'-处理.wav')
    subprocess.run([str(ffmpeg),'-v','error','-y','-ss',str(start),'-i',str(source),'-t','20','-vn','-ac','1','-ar','48000','-c:a','pcm_f32le',str(raw)],check=True,creationflags=0x08000000)
    begin=time.monotonic();peak=0
    with (folder/(name+'.log')).open('wb') as log:
        proc=subprocess.Popen([str(root/'.audio-venv/Scripts/python.exe'),'-X','utf8',str(root/'backend/audio_worker.py'),
            '--input',str(raw),'--output',str(out),'--model',str(root/'audio-model/MossFormer2_SE_48K'),'--strength','0.6'],stdout=log,stderr=log,creationflags=0x08000000)
        process=psutil.Process(proc.pid)
        while proc.poll() is None:
            try:peak=max(peak,sum(p.memory_info().rss for p in [process,*process.children(recursive=True)]))
            except psutil.Error:pass
            time.sleep(.2)
        row={'sample':name,'start':start,'seconds':20,'wall_seconds':round(time.monotonic()-begin,2),'peak_mb':round(peak/1024**2,1),'exit_code':proc.returncode}
        results.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
        (folder/'metrics.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
        if proc.returncode:raise SystemExit((folder/(name+'.log')).read_text(encoding='utf-8'))
