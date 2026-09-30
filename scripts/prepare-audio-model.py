"""Validate the selected offline audio model before packaging."""
import hashlib,json
from pathlib import Path
root=Path(__file__).resolve().parents[1]/'audio-model/BandItPlus'
manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
if manifest.get('engine')!='bandit-plus-dnr-11.47-speech-v1':
    raise SystemExit('BandIt Plus model not prepared; run scripts/vendor-bandit.py first')
for name,key in (('file','sha256'),('config','config_sha256')):
    path=(root/manifest[name]).resolve()
    if path.parent!=root.resolve():raise SystemExit('Invalid model path')
    with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    if digest!=manifest[key]:raise SystemExit('Model checksum mismatch')
print(json.dumps({'model':manifest['model'],'engine':manifest['engine'],'verified':True}))