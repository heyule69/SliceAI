"""Run in .audio-venv: bounded buffering must preserve samples and edge padding."""
import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
try:
    import numpy as np
    import soundfile as sf
    import torch
    import torchaudio
    AUDIO_AVAILABLE=True
except ImportError:
    AUDIO_AVAILABLE=False
from bandit_worker import main,mix_files,resample_file,save_stem,stream_separate

@unittest.skipUnless(AUDIO_AVAILABLE,'Audio runtime is isolated in .audio-venv')
class StreamingTest(unittest.TestCase):
    def test_strength_updates_reuse_stem_without_loading_model_and_preserve_mix(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);source=folder/'raw.wav';stem=folder/'speech.wav'
            raw=np.random.default_rng(4).normal(0,.1,48000+37).astype('float32')
            sf.write(source,raw,48000,subtype='FLOAT')
            loaded=[]
            def model(x):return x[:,None]*.6
            def load_model(folder):loaded.append(folder);return model
            resources=SimpleNamespace(initial_threads=2,start=lambda:None,close=lambda:None,boundary=lambda setter:None)
            for number,strength in enumerate((1,.5)):
                target=folder/f'mixed-{number}.wav'
                args=['worker','--input',str(source),'--output',str(target),'--model',str(folder/'model'),
                      '--speech-cache',str(stem),'--strength',str(strength)]
                with patch('sys.argv',args),patch('bandit_worker.load_model',side_effect=load_model),\
                     patch('audio_resources.AdaptiveResources',return_value=resources),patch('torch.set_num_interop_threads'):
                    main()
                speech,_=sf.read(stem,dtype='float32');actual,_=sf.read(target,dtype='float32')
                np.testing.assert_array_equal(actual,raw*(1-strength)+speech*strength)
            self.assertEqual(len(loaded),1)
            self.assertFalse(list(folder.glob('*.partial.wav')))

    def test_mix_cancellation_keeps_immutable_speech_and_original_samples(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);source=folder/'raw.wav';stem=folder/'speech.wav';mixed=folder/'mix.partial.wav'
            raw=np.random.default_rng(2).normal(0,.1,1001).astype('float32')
            speech=raw*.6
            sf.write(source,raw,48000,subtype='FLOAT');sf.write(stem,speech,48000,subtype='FLOAT')
            def cancelled():raise RuntimeError('cancelled')
            with self.assertRaisesRegex(RuntimeError,'cancelled'):
                mix_files(source,stem,mixed,.5,cancelled)
            original,_=sf.read(source,dtype='float32');cached,_=sf.read(stem,dtype='float32')
            np.testing.assert_array_equal(original,raw);np.testing.assert_array_equal(cached,speech)

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
