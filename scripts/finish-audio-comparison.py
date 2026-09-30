"""Serialize CPU model benchmarks and build aligned audition files."""
import json,os,subprocess,sys,time
from pathlib import Path
root=Path(__file__).resolve().parents[1];out=root/'test-results/v0.2/audio-comparison'
python=str(root/'.audio-venv/Scripts/python.exe')
deadline=time.monotonic()+1200
while True:
    p=out/'bandit-plus-metrics.json'
    rows=json.loads(p.read_text(encoding='utf-8')) if p.exists() else []
    if any(r['exit_code'] for r in rows):raise RuntimeError('Bandit Plus failed')
    if len(rows)==2:break
    if time.monotonic()>deadline:raise TimeoutError('Bandit Plus timeout')
    time.sleep(2)
for model in ['uvr','bandit-v2']:
    subprocess.run([python,'-X','utf8',str(root/'scripts/run-audio-comparison.py'),model],check=True)
for name in ['聊天','背景歌候选']:
    source=root/'test-results/v0.2/audio'/f'{name}-原声.wav'
    target=out/name/'mossformer.wav'
    if name=='聊天' and (root/'test-results/v0.2/audio/聊天-加强.wav').exists():
        target.write_bytes((root/'test-results/v0.2/audio/聊天-加强.wav').read_bytes())
    else:
        subprocess.run([python,'-X','utf8',str(root/'backend/audio_worker.py'),'--input',str(source),'--output',str(target),'--model',str(root/'audio-model/MossFormer2_SE_48K'),'--strength','1'],check=True)
    (out/name/'original.wav').write_bytes(source.read_bytes())
print('All inference jobs finished.',flush=True)
