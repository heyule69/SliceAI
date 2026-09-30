"""Objective diagnostics only; these scores do not replace listening feedback."""
import csv,json
from pathlib import Path
import numpy as np,soundfile as sf,onnxruntime as ort
from scipy.signal import resample_poly
root=Path(__file__).resolve().parents[1];folder=root/'test-results/v0.2/audio-comparison/笑声';assets=root/'.test-artifacts/audio-comparison/yamnet'
labels=list(csv.DictReader((assets/'yamnet_class_map.csv').open(encoding='utf-8',newline='')))
indices=[int(r['index']) for r in labels if any(s in r['display_name'].lower() for s in ['laugh','giggle','snicker','chuckle','chortle'])]
options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
model=ort.InferenceSession(str(assets/'yamnet.onnx'),sess_options=options,providers=['CPUExecutionProvider'])
original,sr=sf.read(folder/'01-原声.wav',dtype='float32')
a,b=int(9.9*sr),int(14*sr);base=original[a:b];rows=[]
for path in sorted(folder.glob('0*.wav')):
    data,rate=sf.read(path,dtype='float32');assert len(data)==1200000 and rate==48000
    snippet=data[a:b]
    scores=model.run(['output_0'],{model.get_inputs()[0].name:resample_poly(data,1,3).astype(np.float32)})[0]
    low=int(9.9/.48);high=int(14/.48)+1
    row={'file':path.name,'laughter_detector_peak':round(float(scores[low:high,indices].max()),4),'laughter_interval_rms_db_vs_original':round(float(20*np.log10((np.sqrt(np.mean(snippet**2))+1e-10)/(np.sqrt(np.mean(base**2))+1e-10))),2),'laughter_interval_correlation_with_original':round(float(np.corrcoef(base,snippet)[0,1]),4)}
    rows.append(row);print(json.dumps(row,ensure_ascii=False))
(folder/'retention-diagnostics.json').write_text(json.dumps({'note':'Laughter detector scores and waveform diagnostics only. No ground-truth isolated voice; listening approval required.','window':[9.9,14],'rows':rows},ensure_ascii=False,indent=2),encoding='utf-8')
