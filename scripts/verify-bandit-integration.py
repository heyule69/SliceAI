"""Regression against user-approved 04 plus process-tree memory measurement."""
import argparse,json,os,subprocess,sys,time
from pathlib import Path
import numpy as np
import psutil
import soundfile as sf
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--frozen',action='store_true');args=p.parse_args()
folder=ROOT/'test-results/v0.2/audio-comparison/笑声'
label='frozen' if args.frozen else 'production'
output=folder/f'04-{label}-verified.wav'
if args.frozen:
    prefix=[str(ROOT/'src-tauri/resources/worker/audio/sliceai-audio.exe')]
    model=ROOT/'src-tauri/resources/worker/audio/model'
else:
    prefix=[sys.executable,str(ROOT/'backend/audio_worker.py')];model=ROOT/'audio-model/BandItPlus'
started=time.monotonic();peak=0
with (folder/f'{label}.log').open('w',encoding='utf-8') as log:
    proc=subprocess.Popen(prefix+['--input',str(ROOT/'test-results/v0.2/audio/笑声-原声.wav'),'--output',str(output),'--model',str(model),'--strength','1'],
        stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),env={**os.environ,'PYTHONUTF8':'1'})
    while proc.poll() is None:
        try:
            parent=psutil.Process(proc.pid);total=0
            for child in [parent,*parent.children(recursive=True)]:
                try:total+=child.memory_info().rss
                except psutil.Error:pass
            peak=max(peak,total)
        except psutil.Error:pass
        time.sleep(.2)
    if proc.returncode:raise RuntimeError((folder/f'{label}.log').read_text(encoding='utf-8'))
actual,rate=sf.read(output,dtype='float32')
expected,reference_rate=sf.read(folder/'bandit-plus-speech.wav',dtype='float32')
assert rate==reference_rate==48000 and actual.shape==expected.shape
delta=actual-expected
report={'engine':'bandit-plus-dnr-11.47-speech-v1','worker':label,'duration':len(actual)/rate,
    'elapsed_seconds':round(time.monotonic()-started,2),'peak_process_tree_mb':round(peak/1024**2,1),
    'max_abs_error':float(np.abs(delta).max()),'rms_error':float(np.sqrt(np.mean(delta**2))),
    'correlation':float(np.corrcoef(actual,expected)[0,1]),'finite':bool(np.isfinite(actual).all()),
    'scratch_files_left':[str(f) for f in folder.glob(output.stem+'*.partial.wav')]}
report['passed']=report['correlation']>.99999 and report['max_abs_error']<.0001 and report['finite'] and not report['scratch_files_left']
(folder/f'{label}-regression.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False),flush=True)
if not report['passed']:raise SystemExit('Audio regression failed')
