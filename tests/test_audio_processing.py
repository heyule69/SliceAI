import json,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from audio_processing import process_audio

class AudioCacheTest(unittest.TestCase):
    def test_resource_updates_are_saved_separately_from_measured_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);source=folder/'source.mp4';source.write_bytes(b'source')
            stages=[]
            editor=SimpleNamespace(settings={},store=None,p={'id':'test'},persist=lambda stage=None:stages.append(stage))
            def command(args,*unused,**kwargs):
                if '-show_entries' in args:
                    return json.dumps({'streams':[{'codec_type':'video','duration':20},{'codec_type':'audio'}],'format':{'duration':20}})
                if '--output' in args:
                    kwargs['on_line']('{"resources":{"threads":8,"reason":"空闲","available_memory_mb":4096}}')
                    kwargs['on_line']('{"progress":25}')
                    kwargs['on_line']('{"resources":{"threads":2,"reason":"其他程序繁忙","available_memory_mb":2048}}')
                    Path(args[args.index('--output')+1]).write_bytes(b'processed')
                    Path(args[args.index('--speech-cache')+1]).write_bytes(b'speech')
                else:Path(args[-1]).write_bytes(b'raw')
            with patch('audio_processing.ready',return_value=True),patch('audio_processing.tool_path',return_value='ffmpeg'),patch('audio_processing.command',side_effect=command):
                process_audio(editor,source,folder,1)
            self.assertEqual(editor.p['audio_resources']['threads'],2)
            self.assertEqual(stages,[None,'降低背景音乐 · 25%',None])

    def test_model_upgrade_changes_cache_and_cancel_keeps_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);source=folder/'source.mp4';source.write_bytes(b'source')
            editor=SimpleNamespace(settings={},store=None,p={'id':'test'},persist=lambda message:None)
            calls=[];fail=False
            def command(args,*unused,**kwargs):
                calls.append(args)
                if '-show_entries' in args:
                    return json.dumps({'streams':[{'codec_type':'video','duration':20},{'codec_type':'audio'}],'format':{'duration':20}})
                if '--output' in args:
                    dest=Path(args[args.index('--output')+1])
                    if fail:
                        dest.with_suffix('.speech.partial.wav').write_bytes(b'partial')
                        raise ValueError('cancelled')
                    dest.write_bytes(b'processed')
                    Path(args[args.index('--speech-cache')+1]).write_bytes(b'speech')
                else:Path(args[-1]).write_bytes(b'raw')
            with patch('audio_processing.ready',return_value=True),patch('audio_processing.tool_path',return_value='ffmpeg'),patch('audio_processing.command',side_effect=command):
                first=process_audio(editor,source,folder,1)
                self.assertEqual(first,process_audio(editor,source,folder,1));self.assertEqual(len(calls),3)
                with patch('audio_processing.ENGINE_ID','next-model'):
                    fail=True
                    with self.assertRaisesRegex(ValueError,'cancelled'):process_audio(editor,source,folder,1)
                    self.assertFalse(list(folder.glob('*.partial.wav')))
                    before=len(calls);fail=False
                    second=process_audio(editor,source,folder,1)
                    self.assertNotEqual(first,second);self.assertEqual(len(calls),before+2)
                    self.assertTrue(first.is_file());self.assertTrue(second.is_file())
                    self.assertEqual(len(list(folder.glob('original-*.wav'))),1)

    def test_strength_and_track_changes_bind_stem_and_explicit_track(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);source=folder/'source.mp4';source.write_bytes(b'source')
            editor=SimpleNamespace(settings={},store=None,p={'id':'test'},task={'audio_track':0},folder=folder,persist=lambda message:None)
            calls=[]
            def command(args,*unused,**kwargs):
                calls.append(args)
                if '--output' in args:
                    Path(args[args.index('--output')+1]).write_bytes(b'processed')
                    Path(args[args.index('--speech-cache')+1]).write_bytes(b'speech')
                elif '-show_entries' in args:
                    return json.dumps({'streams':[{'codec_type':'video','duration':20},{'codec_type':'audio'},{'codec_type':'audio'}],'format':{'duration':20}})
                else:Path(args[-1]).write_bytes(b'raw')
            with patch('audio_processing.ready',return_value=True),patch('audio_processing.tool_path',return_value='ffmpeg'),patch('audio_processing.command',side_effect=command):
                first=process_audio(editor,source,folder,1,start=2,duration=10)
                second=process_audio(editor,source,folder,.5,start=2,duration=10)
                self.assertNotEqual(first,second)
                workers=[a for a in calls if '--speech-cache' in a]
                self.assertEqual(len(workers),2)
                self.assertEqual(workers[0][workers[0].index('--speech-cache')+1],workers[1][workers[1].index('--speech-cache')+1])
                self.assertEqual(len([a for a in calls if '-af' in a]),1)
                before=len(calls)
                self.assertEqual(second,process_audio(editor,source,folder,.5,start=2,duration=10))
                self.assertEqual(len(calls),before)
                editor.task['audio_track']=1
                third=process_audio(editor,source,folder,1,start=2,duration=10)
                self.assertNotEqual(first,third)
                self.assertEqual([a[a.index('-map')+1] for a in calls if '-af' in a],['0:a:0','0:a:1'])

if __name__=='__main__':unittest.main()
