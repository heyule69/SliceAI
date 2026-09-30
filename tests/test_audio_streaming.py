"""Run in .audio-venv: bounded buffering must preserve samples and edge padding."""
import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
try:
    import numpy as np
    import soundfile as sf
    import torch
    import torchaudio
    AUDIO_AVAILABLE=True
except ImportError:
    AUDIO_AVAILABLE=False
from bandit_worker import resample_file,stream_separate

@unittest.skipUnless(AUDIO_AVAILABLE,'Audio runtime is isolated in .audio-venv')
class StreamingTest(unittest.TestCase):
    def test_thread_adjustments_at_block_boundaries_preserve_output(self):
        with tempfile.TemporaryDirectory() as temp:
            source,target=Path(temp)/'raw.wav',Path(temp)/'out.wav'
            raw=np.random.default_rng(4).normal(0,.1,1001).astype('float32')
            sf.write(source,raw,44100,subtype='FLOAT')
            calls=[];inside=False
            def boundary():
                self.assertFalse(inside)
                threads=1+len(calls)%2;torch.set_num_threads(threads);calls.append(threads)
            def predict(x):
                nonlocal inside
                inside=True
                result=(torch.from_numpy(x)*.6).numpy()
                inside=False
                return result
            stream_separate(source,target,predict,boundary=boundary)
            actual,_=sf.read(target,dtype='float32')
            self.assertGreater(len(calls),2);self.assertIn(2,calls)
            np.testing.assert_allclose(actual,raw*.6,rtol=0,atol=1e-7)

    def test_resampler_matches_whole_track_in_both_directions(self):
        torch.set_num_threads(2)
        with tempfile.TemporaryDirectory() as temp:
            source,target=Path(temp)/'raw.wav',Path(temp)/'out.wav'
            for rate,new_rate in ((48000,44100),(44100,48000)):
                raw=np.random.default_rng(7).normal(0,.1,rate*21+79).astype('float32')
                sf.write(source,raw,rate,subtype='FLOAT')
                resample_file(source,target,new_rate)
                actual,_=sf.read(target,dtype='float32')
                expected=torchaudio.functional.resample(torch.from_numpy(raw),rate,new_rate).numpy()
                np.testing.assert_allclose(actual,expected,rtol=0,atol=1e-6)
    def test_overlap_add_matches_full_buffer_with_context_dependent_prediction(self):
        torch.set_num_threads(2)
        with tempfile.TemporaryDirectory() as temp:
            source,target=Path(temp)/'raw.wav',Path(temp)/'out.wav'
            rate=44100;chunk=6*rate;hop=chunk//4
            # Includes very short files and a last window off the usual grid.
            for n in (1,1001,rate*19+137):
                raw=np.random.default_rng(8).normal(0,.1,n).astype('float32')
                sf.write(source,raw,rate,subtype='FLOAT')
                def predict(x):return x*.6+float(x.mean())*.4
                stream_separate(source,target,predict)
                actual,_=sf.read(target,dtype='float32')
                padded=np.pad(raw,(chunk,chunk),mode='reflect')
                acc=np.zeros(len(padded),dtype='float32');den=np.zeros_like(acc)
                starts=list(range(0,len(padded)-chunk+1,hop))
                if starts[-1]!=len(padded)-chunk:starts.append(len(padded)-chunk)
                window=torch.hann_window(chunk).clamp_min(1e-5).numpy()
                for start in starts:
                    acc[start:start+chunk]+=predict(padded[start:start+chunk])*window
                    den[start:start+chunk]+=window
                expected=(acc/den)[chunk:chunk+n]
                np.testing.assert_allclose(actual,expected,rtol=0,atol=1e-7)

if __name__=='__main__':unittest.main()
