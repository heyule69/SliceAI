"""Validate and package local audition tracks without per-track gain changes."""
import hashlib,json,re,shutil,subprocess
from pathlib import Path
import numpy as np
import soundfile as sf
import torchaudio,torch
root=Path(__file__).resolve().parents[1];out=root/'test-results/v0.2/audio-comparison'
metrics={s:{} for s in ['聊天','背景歌候选']}
for model in ['uvr','bandit-plus','bandit-v2']:
    rows=json.loads((out/(model+'-metrics.json')).read_text(encoding='utf-8'))
    assert len(rows)==2 and all(r['exit_code']==0 for r in rows),model
    for row in rows:metrics[row['sample']][model]=row
rows=[]
for sample in metrics:
    for name in ['original','mossformer','uvr','bandit-plus-speech','bandit-v2-speech']:
        p=out/sample/(name+'.wav');raw=p.parent/'raw'/p.name;raw.parent.mkdir(exist_ok=True)
        if not raw.exists():shutil.copyfile(p,raw)
        audio,rate=sf.read(raw,dtype='float32',always_2d=True)
        audio=audio.mean(axis=1)
        if rate!=48000:audio=torchaudio.functional.resample(torch.from_numpy(audio),rate,48000).numpy()
        assert len(audio)==960000 and np.isfinite(audio).all(),p
        peak=float(np.abs(audio).max())
        assert peak<1,('Needs shared headroom adjustment',p,peak)
        sf.write(p,audio,48000,subtype='PCM_24')
        rows.append({'sample':sample,'model':name,'seconds':20,'sample_rate':48000,'channels':1,'peak':round(peak,6),'rms':round(float(np.sqrt(np.mean(audio**2))),6),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
data={'metrics':metrics,'audio':rows,'inference':{'device':'CPU','torch_threads':4,'uvr':'UVR-MDX-NET-Inst_HQ_3.onnx; audio-separator 0.30.2; denoise on; segment 256; overlap 0.25; ONNX threads 4','bandit-plus':'MSST official model_bandit_plus_dnr_sdr_11.47.chpt; 6-second windows; 75% overlap; batch 1','bandit-v2':'UVR-distributed checkpoint-multi_fixed.ckpt; original Bandit v2 model; strict weights match; 8-second windows; 50% overlap; batch 1','mossformer':'MossFormer2_SE_48K; strength 1.0; CPU threads 2'},'source':'2026-08-28_21-32-17_小小霖le_即将流落街头_录播.mp4','segments':[{'name':'聊天','start':11590,'duration':20},{'name':'背景歌候选','start':9000,'duration':20}]}
(out/'report.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
p=out/'index.html';html=p.read_text(encoding='utf-8');html=re.sub(r'const DATA = .*?;\nconst samples=',lambda _: 'const DATA = '+json.dumps({'metrics':metrics},ensure_ascii=False)+';\nconst samples=',html,flags=re.S);p.write_text(html,encoding='utf-8')
print(json.dumps({'tracks':len(rows),'metrics':metrics},ensure_ascii=False,indent=2))
