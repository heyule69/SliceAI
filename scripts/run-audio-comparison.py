import json,subprocess,sys,time
from pathlib import Path
import psutil
root=Path(__file__).resolve().parents[1]
out=root/'test-results/v0.2/audio-comparison';out.mkdir(parents=True,exist_ok=True)
model=sys.argv[1];samples=sys.argv[2:] or ['聊天','背景歌候选']
metrics_name=model+'-metrics'+('-'+ '-'.join(samples) if sys.argv[2:] else '')+'.json'
results=[]
for sample in samples:
    begin=time.monotonic();peak=0
    logfile=out/(sample+'-'+model+'.log')
    with logfile.open('wb') as log:
        proc=subprocess.Popen([str(root/'.audio-venv/Scripts/python.exe'),'-X','utf8',str(root/'scripts/compare-audio-model.py'),model,'--sample',sample],stdout=log,stderr=log,creationflags=0x08000000)
        process=psutil.Process(proc.pid)
        while proc.poll() is None:
            try:peak=max(peak,sum(p.memory_info().rss for p in [process,*process.children(recursive=True)]))
            except psutil.Error:pass
            time.sleep(.2)
    row={'sample':sample,'model':model,'wall_seconds':round(time.monotonic()-begin,2),'peak_mb':round(peak/1024**2,1),'exit_code':proc.returncode}
    results.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
    (out/metrics_name).write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    if proc.returncode:print(logfile.read_text(encoding='utf-8')[-7000:],flush=True);break
