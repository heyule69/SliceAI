"""Offline, streamed CPU inference matching the approved BandIt Plus 04 sample."""
from __future__ import annotations
import argparse,hashlib,json,math,os,sys
from pathlib import Path
from audio_identity import ENGINE_ID


def resample_file(source, target, rate, boundary=lambda: None):
    """Phase-aligned blocks with sinc context, equivalent to whole-track resampling."""
    import numpy as np
    import soundfile as sf
    import torch
    import torchaudio
    with sf.SoundFile(source) as src,sf.SoundFile(target,'w',samplerate=rate,channels=1,subtype='FLOAT',format='RF64') as dst:
        common=math.gcd(src.samplerate,rate)
        period_in,period_out=src.samplerate//common,rate//common
        context=max(period_in,math.ceil(32*max(1,src.samplerate/rate)/period_in)*period_in)
        block=src.samplerate*10;block-=block%period_in
        convert=torchaudio.transforms.Resample(src.samplerate,rate,dtype=torch.float32)
        for start in range(0,len(src),block):
            boundary()
            end=min(len(src),start+block)
            left,right=max(0,start-context),min(len(src),end+context)
            src.seek(left)
            raw=src.read(right-left,dtype='float32',always_2d=True).mean(axis=1)
            result=convert(torch.from_numpy(raw)).numpy()
            offset=(start-left)*period_out//period_in
            count=(end*period_out+period_in-1)//period_in-start*period_out//period_in
            segment=result[offset:offset+count]
            if len(segment)!=count or not np.isfinite(segment).all():raise ValueError('声音重采样失败。')
            dst.write(segment)


def reflected_read(src,start,size):
    import numpy as np
    if len(src)==1:
        src.seek(0);return np.full(size,src.read(1,dtype='float32')[0],dtype=np.float32)
    period=2*(len(src)-1)
    indices=np.arange(start,start+size)%period
    indices=np.minimum(indices,period-indices)
    low,high=int(indices.min()),int(indices.max())
    src.seek(low);raw=src.read(high-low+1,dtype='float32')
    return raw[indices-low]


def stream_separate(source,target,predict,progress=lambda value:None,boundary=lambda:None):
    import numpy as np
    import soundfile as sf
    import torch
    rate=44100;chunk,hop=6*rate,6*rate//4
    window=torch.hann_window(chunk).clamp_min(1e-5).numpy()
    acc,den=np.zeros(chunk,dtype=np.float32),np.zeros(chunk,dtype=np.float32)
    with sf.SoundFile(source) as src,sf.SoundFile(target,'w',samplerate=rate,channels=1,subtype='FLOAT',format='RF64') as dst:
        if src.samplerate!=rate or src.channels!=1 or len(src)<1:raise ValueError('声音输入格式无效。')
        last=len(src)+chunk;start=0
        while True:
            boundary()
            estimates=predict(reflected_read(src,start-chunk,chunk))
            if estimates.shape!=(chunk,) or not np.isfinite(estimates).all():raise ValueError('声音模型产生了无效音频。')
            acc+=estimates*window;den+=window
            following=min(start+hop,last) if start<last else start+chunk
            flush=following-start
            left,right=max(start,chunk),min(following,chunk+len(src))
            if right>left:
                lo,hi=left-start,right-start;dst.write(acc[lo:hi]/den[lo:hi])
            progress(min(99,100*following/(last+chunk)))
            if start==last:break
            acc[:-flush]=acc[flush:];acc[-flush:]=0
            den[:-flush]=den[flush:];den[-flush:]=0
            start=following
        if dst.tell()!=len(src):raise ValueError('声音分块时长不匹配。')


def load_model(folder):
    import torch
    from bandit import MultiMaskMultiSourceBandSplitRNNSimple
    manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('engine')!=ENGINE_ID:raise ValueError('声音模型版本不匹配，请重新安装完整版本。')
    for name,checksum in (('file','sha256'),('config','config_sha256')):
        path=(folder/manifest[name]).resolve()
        if path.parent!=folder.resolve():raise ValueError('声音模型路径无效。')
        with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        if digest!=manifest[checksum]:raise ValueError('声音模型校验失败，请重新安装完整版本。')
    config=json.loads((folder/manifest['config']).read_text(encoding='utf-8'))
    model=MultiMaskMultiSourceBandSplitRNNSimple(**config)
    weights=torch.load(folder/manifest['file'],map_location='cpu',weights_only=True)
    model.load_state_dict(weights,strict=True);model.eval()
    return model


def valid_stem(path, total):
    import soundfile as sf
    try:
        with sf.SoundFile(path) as src:
            return src.samplerate == 48000 and src.channels == 1 and src.subtype == 'FLOAT' and len(src) == total
    except (OSError, RuntimeError):
        return False


def save_stem(source, target, total, boundary=lambda:None):
    """Keep precisely the samples the approved mixer reads, without inference."""
    import numpy as np
    import soundfile as sf
    temp=target.with_suffix('.partial.wav')
    try:
        with sf.SoundFile(source) as speech,sf.SoundFile(temp,'w',samplerate=48000,channels=1,subtype='FLOAT',format='RF64') as dst:
            for start in range(0,total,480000):
                boundary()
                count=min(480000,total-start)
                samples=speech.read(count,dtype='float32')
                if len(samples)!=count or not np.isfinite(samples).all():raise ValueError('声音模型产生了无效音频。')
                dst.write(samples)
        if not valid_stem(temp,total):raise ValueError('声音缓存时长不匹配。')
        temp.replace(target)
    finally:
        temp.unlink(missing_ok=True)


def mix_files(original, speech, target, strength, boundary=lambda:None):
    """The unchanged Float32 mix: strength 1 is exactly the approved speech."""
    import numpy as np
    import soundfile as sf
    with sf.SoundFile(original) as raw,sf.SoundFile(speech) as clean,sf.SoundFile(target,'w',samplerate=48000,channels=1,subtype='FLOAT',format='RF64') as dst:
        if raw.samplerate!=48000 or raw.channels!=1 or clean.samplerate!=48000 or clean.channels!=1:
            raise ValueError('声音输入必须是 48kHz 单声道。')
        total=len(raw)
        if total < 1 or len(clean)<total:raise ValueError('声音时长不匹配。')
        for start in range(0,total,480000):
            boundary()
            count=min(480000,total-start)
            source=raw.read(count,dtype='float32');processed=clean.read(count,dtype='float32')
            if len(source)!=count or len(processed)!=count:raise ValueError('声音时长不匹配。')
            # Preserve the accepted computation, including Float32 rounding.
            mixed=source*(1-strength)+processed*strength
            if not np.isfinite(mixed).all():raise ValueError('声音处理结果无效。')
            dst.write(mixed)
    if not valid_stem(target,total):raise ValueError('声音时长不匹配。')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--model',required=True);parser.add_argument('--strength',type=float,default=1.0)
    parser.add_argument('--speech-cache')
    opts=parser.parse_args()
    if not math.isfinite(opts.strength) or not 0<=opts.strength<=1:raise ValueError('声音强度无效。')
    from audio_resources import AdaptiveResources
    resources=AdaptiveResources(report=lambda value:print(json.dumps({'resources':value},ensure_ascii=False),flush=True))
    os.environ['HF_HUB_OFFLINE']='1';os.environ['CUDA_VISIBLE_DEVICES']=''
    os.environ['OMP_NUM_THREADS']=str(resources.initial_threads)
    os.environ['MKL_NUM_THREADS']=str(resources.initial_threads)
    import soundfile as sf
    import torch
    torch.set_num_threads(resources.initial_threads);torch.set_num_interop_threads(1)
    target=Path(opts.output)
    scratch=[target.with_suffix(s) for s in ('.input.partial.wav','.speech.partial.wav','.resampled.partial.wav','.partial.wav')]
    stem=Path(opts.speech_cache) if opts.speech_cache else scratch[2]
    def report(value):print(json.dumps({'progress':round(value,1),'engine':ENGINE_ID}),flush=True)
    def boundary():resources.boundary(torch.set_num_threads)
    resources.start()
    try:
        with sf.SoundFile(opts.input) as src:
            if src.samplerate!=48000 or src.channels!=1 or len(src)==0:raise ValueError('声音输入必须是非空 48kHz 单声道。')
            total=len(src)
        if not valid_stem(stem,total):
            model=load_model(Path(opts.model))
            with torch.inference_mode():
                resample_file(opts.input,scratch[0],44100,boundary)
                def predict(raw):return model(torch.from_numpy(raw)[None,None])[0,0,0].numpy()
                stream_separate(scratch[0],scratch[1],predict,report,boundary)
                resample_file(scratch[1],scratch[2],48000,boundary)
            if opts.speech_cache:
                save_stem(scratch[2],stem,total,boundary)
                # Release the inference scratch before allocating the mixed WAV.
                for path in scratch[:3]:path.unlink(missing_ok=True)
            del model
        else:
            print(json.dumps({'cached_speech':True,'engine':ENGINE_ID}),flush=True)
        mix_files(opts.input,stem,scratch[3],opts.strength,boundary)
        scratch[3].replace(target);report(100)
    finally:
        resources.close()
        for path in scratch:path.unlink(missing_ok=True)


if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    main()
