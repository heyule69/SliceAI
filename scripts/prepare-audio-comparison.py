"""Download official experimental assets into a separate test directory."""
import concurrent.futures,hashlib,io,json,time,urllib.request,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/'.test-artifacts/audio-comparison'
ROOT.mkdir(parents=True,exist_ok=True)
def fetch(url,path):
    path=ROOT/path;path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():return path
    print('Downloading '+path.name,flush=True)
    tmp=path.with_suffix(path.suffix+'.partial')
    with urllib.request.urlopen(url,timeout=90) as response,tmp.open('wb') as out:
        while data:=response.read(1024*1024):out.write(data)
    tmp.replace(path)
    print('Ready '+path.name+' '+str(path.stat().st_size),flush=True)
    return path
def repo(name,owner):
    path=fetch('https://codeload.github.com/'+owner+'/zip/refs/heads/main',name+'.zip')
    target=ROOT/name
    if not target.exists():
        target.mkdir()
        with zipfile.ZipFile(path) as z:
            for item in z.infolist():
                rel=Path(*Path(item.filename).parts[1:])
                dest=(target/rel).resolve()
                if not dest.is_relative_to(target.resolve()):raise ValueError('Unsafe zip')
                if item.is_dir():dest.mkdir(parents=True,exist_ok=True)
                else:
                    dest.parent.mkdir(parents=True,exist_ok=True)
                    dest.write_bytes(z.read(item))
    return str(target)
jobs=[
 ('repo','bandit-v2','kwatcharasupat/bandit-v2'),
 ('repo','msst','ZFTurbo/Music-Source-Separation-Training'),
 ('file','https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/checkpoint-multi_fixed.ckpt','models/bandit-v2-fixed.ckpt'),
 ('file','https://github.com/ZFTurbo/Music-Source-Separation-Training/releases/download/v.1.0.3/model_bandit_plus_dnr_sdr_11.47.chpt','models/bandit-plus.chpt'),
 ('file','https://github.com/ZFTurbo/Music-Source-Separation-Training/releases/download/v.1.0.3/config_dnr_bandit_bsrnn_multi_mus64.yaml','models/bandit-plus.yaml'),
]
def run(job):
    try:return str(repo(job[1],job[2]) if job[0]=='repo' else fetch(job[1],job[2]))
    except Exception as exc:return str(exc)
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
    for result in pool.map(run,jobs):print(result,flush=True)
