"""Prepare offline BandIt Plus inference sources and model assets."""
import hashlib,json,shutil
from pathlib import Path
import yaml
ROOT=Path(__file__).resolve().parents[1]
assets=ROOT/'.test-artifacts/audio-comparison'
source=assets/'msst/models/bandit/core/model'
target=ROOT/'backend/bandit'
for path in source.rglob('*.py'):
    dest=target/path.relative_to(source);dest.parent.mkdir(parents=True,exist_ok=True)
    code=path.read_text(encoding='utf-8').replace('models.bandit.core.model','bandit')
    code=code.replace('import pytorch_lightning as pl','').replace('pl.LightningModule','nn.Module')
    code=code.replace('from librosa import hz_to_midi, midi_to_hz','''# Equivalent MIDI conversion without the training/audio-analysis stack.
def hz_to_midi(frequencies):
    return 12 * (np.log2(np.asanyarray(frequencies)) - np.log2(440.0)) + 69

def midi_to_hz(notes):
    return 440.0 * (2.0 ** ((np.asanyarray(notes) - 69.0) / 12.0))
''')
    dest.write_text('# Vendored from ZFTurbo/Music-Source-Separation-Training, BandIt model.\n'
        '# SliceAI changes: local imports, inference-only nn.Module, MIDI formulas.\n'
        '# See LICENSE-MIT.txt, LICENSE-Apache-2.0.txt and NOTICE.txt.\n'+code,encoding='utf-8')
shutil.copy2(assets/'msst/LICENSE',target/'LICENSE-MIT.txt')
shutil.copy2(assets/'bandit-v2/LICENSE',target/'LICENSE-Apache-2.0.txt')
(target/'NOTICE.txt').write_text('BandIt by Karn N. Watcharasupat and contributors (Apache-2.0).\n'
    'https://github.com/kwatcharasupat/bandit\n'
    'Inference adapted from Music-Source-Separation-Training\n'
    'Copyright (c) 2024 Roman Solovyev (ZFTurbo), MIT.\n'
    'https://github.com/ZFTurbo/Music-Source-Separation-Training\n'
    'SliceAI modifications: local package imports; training base replaced with torch.nn.Module;\n'
    'equivalent MIDI formulas to omit librosa; disk-streamed inference wrapper.\n'
    'Model: BandIt Plus DnR SDR 11.47, speech stem only.\n',encoding='utf-8')
model=ROOT/'audio-model/BandItPlus';model.mkdir(parents=True,exist_ok=True)
shutil.copy2(assets/'models/bandit-plus.chpt',model/'bandit-plus.chpt')
config=yaml.safe_load((assets/'models/bandit-plus.yaml').read_text(encoding='utf-8'))['model']
(model/'config.json').write_text(json.dumps(config,indent=2),encoding='utf-8')
def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
(model/'manifest.json').write_text(json.dumps({
    'engine':'bandit-plus-dnr-11.47-speech-v1','model':'BandIt Plus',
    'file':'bandit-plus.chpt','sha256':digest(model/'bandit-plus.chpt'),
    'config':'config.json','config_sha256':digest(model/'config.json'),
    'source':'https://github.com/ZFTurbo/Music-Source-Separation-Training/releases/download/v.1.0.3/model_bandit_plus_dnr_sdr_11.47.chpt',
    'sample_rate':44100,'chunk_seconds':6,'overlap':.75,'stem':'speech','precision':'float32','threads':4,
},indent=2),encoding='utf-8')
print('Prepared BandIt Plus model and inference sources')
