"""Reproducible local A/B inference; does not change the app audio module."""
import argparse,gc,json,os,sys,time,types
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ASSETS=ROOT/'.test-artifacts/audio-comparison'
OUT=ROOT/'test-results/v0.2/audio-comparison'
OUT.mkdir(parents=True,exist_ok=True)
p=argparse.ArgumentParser();p.add_argument('model',choices=['uvr','bandit-plus','bandit-v2']);p.add_argument('--sample',default='聊天');args=p.parse_args()
os.environ['CUDA_VISIBLE_DEVICES']=''
os.environ['OMP_NUM_THREADS']='4'
os.environ['PATH']=str(ROOT/'src-tauri/resources/worker/bin')+os.pathsep+os.environ['PATH']
import numpy as np
import soundfile as sf
import torch
import torchaudio
import yaml
torch.set_num_threads(4);torch.set_num_interop_threads(1)
raw=ROOT/'test-results/v0.2/audio'/f'{args.sample}-原声.wav'
dest=OUT/args.sample;dest.mkdir(exist_ok=True)
if args.model=='uvr':
    import onnxruntime as ort
    original_session=ort.InferenceSession
    def cpu_session(*a,**kw):
        options=kw.get('sess_options') or ort.SessionOptions()
        options.intra_op_num_threads=4;options.inter_op_num_threads=1
        kw['sess_options']=options
        return original_session(*a,**kw)
    ort.InferenceSession=cpu_session
    from audio_separator.separator import Separator
    sep=Separator(model_file_dir=str(ASSETS/'models'),output_dir=str(dest),output_format='WAV',
        output_single_stem='Vocals',normalization_threshold=.99,sample_rate=44100,
        mdx_params={'hop_length':1024,'segment_size':256,'overlap':.25,'batch_size':1,'enable_denoise':True})
    sep.load_model(model_filename='UVR-MDX-NET-Inst_HQ_3.onnx')
    results=sep.separate(str(raw),custom_output_names={'Vocals':'uvr'})
    print(json.dumps({'outputs':results}),flush=True)
    raise SystemExit()

if args.model=='bandit-v2':
    sys.path.insert(0,str(ASSETS/'bandit-v2'))
    from src.models.bandit.bandit import Bandit
    cfg=yaml.safe_load((ASSETS/'bandit-v2/configs/models/bandit-mus64.yaml').read_text(encoding='utf-8'))
    checkpoint=torch.load(ASSETS/'models/bandit-v2-fixed.ckpt',map_location='cpu',weights_only=True)
    weights=checkpoint
    stems=list(dict.fromkeys(k.split('.')[1] for k in weights if k.startswith('mask_estim.')))
    model=Bandit(fs=48000,stems=stems,**cfg['kwargs'])
    model.load_state_dict(weights,strict=True)
    fs=48000;chunk=8*fs;hop=4*fs
    def predict(x):
        result=model({'mixture':{'audio':x}})['estimates']
        return torch.stack([result[s]['audio'][0] for s in stems])
else:
    sys.path.insert(0,str(ASSETS/'msst'))
    # Upstream core/__init__ imports training datasets. Inference needs only its model package.
    pkg=types.ModuleType('models.bandit.core');pkg.__path__=[str(ASSETS/'msst/models/bandit/core')]
    sys.modules['models.bandit.core']=pkg
    from models.bandit.core.model import MultiMaskMultiSourceBandSplitRNNSimple
    cfg=yaml.safe_load((ASSETS/'models/bandit-plus.yaml').read_text(encoding='utf-8'))
    model=MultiMaskMultiSourceBandSplitRNNSimple(**cfg['model'])
    weights=torch.load(ASSETS/'models/bandit-plus.chpt',map_location='cpu',weights_only=True)
    model.load_state_dict(weights,strict=True)
    stems=cfg['model']['stems'];fs=44100;chunk=6*fs;hop=chunk//4
    def predict(x):return model(x)[0]
model.eval()
del weights
if 'checkpoint' in globals():del checkpoint
gc.collect()
audio,sr=sf.read(raw,dtype='float32',always_2d=True)
x=torch.from_numpy(audio.T)
if sr!=fs:x=torchaudio.functional.resample(x,sr,fs)
n=x.shape[-1];padding=chunk
x=torch.nn.functional.pad(x,(padding,padding),mode='reflect')
window=torch.hann_window(chunk).clamp_min(1e-5)
acc=torch.zeros(len(stems),1,x.shape[-1]);den=torch.zeros(x.shape[-1])
starts=list(range(0,x.shape[-1]-chunk+1,hop))
if starts[-1]!=x.shape[-1]-chunk:starts.append(x.shape[-1]-chunk)
with torch.inference_mode():
    for idx,start in enumerate(starts):
        estimates=predict(x[:,start:start+chunk][None])
        acc[:,:,start:start+chunk]+=estimates*window
        den[start:start+chunk]+=window
        if idx%5==0:print(f'{args.model} {idx+1}/{len(starts)}',flush=True)
output=acc[:,:,padding:padding+n]/den[padding:padding+n]
for idx,stem in enumerate(stems):
    track=output[idx]
    if fs!=sr:track=torchaudio.functional.resample(track,fs,sr)
    track=track[:,:len(audio)]
    if track.shape[-1]!=len(audio) or not torch.isfinite(track).all():raise ValueError('Invalid audio output')
    sf.write(dest/(args.model+'-'+stem+'.wav'),track.T.numpy(),sr,subtype='FLOAT')
print(json.dumps({'stems':stems,'samples':len(audio),'rate':sr}),flush=True)
