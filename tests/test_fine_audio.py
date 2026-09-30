"""Isolated generated media; never use the desktop store or installed worker."""
import contextlib
import copy
import io
import json
import os
import subprocess
import struct
import unittest
from pathlib import Path
from unittest.mock import patch

import test_fine
from engine import Cancelled, probe, tool_path
from fine import Editor, save
from fine_audio import prepare, cut, audio_duration
from fine_auto import DEFAULTS, checked_captions, reconcile_audio


class AudioFirstTest(unittest.TestCase):
    setUp = test_fine.FineTest.setUp
    tearDown = test_fine.FineTest.tearDown
    run_cmd = test_fine.FineTest.run_cmd

    def separated(self, editor, source, folder, strength, start, duration):
        # Stand in for the expensive model with a distinguishable 880 Hz signal.
        self.assertEqual(str(source),str(self.video))
        path=folder/'speech.wav'
        subprocess.run([tool_path(editor.settings,'ffmpeg'),'-v','error','-y','-f','lavfi',
                        '-i','sine=frequency=880:sample_rate=48000','-t',str(duration),
                        '-c:a','pcm_f32le',str(path)],check=True,capture_output=True)
        return path

    def options(self,**kwargs):
        return {**DEFAULTS,'music':'reduce','subtitles':'none','speech':[],**kwargs}

    def keep(self,rows):
        return {'summary':'保留完整事件','kept_ids':[s['id'] for s in rows],'removed':[]}

    def test_audio_precedes_analysis_without_subtitles_and_is_shared_across_exports(self):
        fresh=copy.deepcopy(self.rows);fresh[0]['text']='处理后识别的内容'
        order=[]
        def separate(*args):order.append('audio');return self.separated(*args)
        def asr(editor,audio):
            self.assertTrue(Path(audio['path']).is_file());order.append('asr');return fresh
        def api(settings,messages,*args):
            order.append('ai');payload=json.loads(messages[1]['content'])
            self.assertEqual(payload['transcript'][0]['text'],fresh[0]['text'])
            return json.dumps(self.keep(payload['transcript']))
        with patch('fine_audio.process_audio',side_effect=separate) as model,\
                patch('fine_auto.checked_captions',side_effect=asr) as transcribe,\
                patch('fine_auto.chat_api',side_effect=api):
            self.run_cmd('edit_auto',options=self.options())
            self.assertEqual(order,['audio','asr','ai','ai'])
            v=self.p['versions'][-1];self.assertFalse(v['subtitles'])
            self.assertEqual(v['transcript_rows'][0]['text'],fresh[0]['text'])
            self.assertEqual(v['cues'][0]['text'],fresh[0]['text'])
            self.assertTrue(v['audio_review']['protected_ranges'])
            self.run_cmd('edit_export')
            self.assertEqual(model.call_count,1)
            self.assertEqual(transcribe.call_count,1)
            decoded=subprocess.run([tool_path(self.store.settings(),'ffmpeg'),'-v','error',
                 '-i',self.p['exports'][-1]['path'],'-t','1','-vn','-ac','1','-ar','48000',
                 '-f','f32le','pipe:1'],check=True,capture_output=True).stdout
            samples=struct.unpack('<'+'f'*(len(decoded)//4),decoded)
            crossings=sum(a<=0<b for a,b in zip(samples,samples[1:]))
            self.assertAlmostEqual(crossings,880,delta=5) # original source is 350 Hz
            # Reordered manual cuts use stored fine-ASR rows, not rough subtitles.
            self.run_cmd('edit_update',ranges=[{'start':6,'end':9},{'start':0,'end':2}])
            v=self.p['versions'][-1];self.assertEqual(v['cues'][-1]['text'],fresh[0]['text'])
            self.assertEqual(v['cues'][-1]['start'],3)
            self.run_cmd('edit_confirm');self.run_cmd('edit_export')
            self.assertEqual(model.call_count,1)
            self.assertAlmostEqual(probe(self.p['exports'][-1]['path'],self.store.settings(),self.store)['duration'],5,delta=.15)
        rough=json.loads((self.store.task_dir(self.task['id'])/'transcript.json').read_text(encoding='utf-8'))
        self.assertEqual(rough,self.rows)

    def test_asr_failure_preserves_previous_version_and_retry_reuses_audio(self):
        editor=Editor(self.store,{'project_id':self.p['id']})
        version=editor.version([{'start':0,'end':12}],'已有方案')
        with contextlib.redirect_stdout(io.StringIO()):self.p=editor.persist()
        old_id=version['id']
        with patch('fine_audio.process_audio',side_effect=self.separated) as model,\
                patch('fine_auto.checked_captions',side_effect=ValueError('ASR failed')),\
                patch('fine_auto.chat_api') as api,contextlib.redirect_stdout(io.StringIO()):
            self.p=Editor(self.store,{'cmd':'edit_auto','project_id':self.p['id'],'options':self.options()}).run()
            self.assertIn('ASR failed',self.p['error']);api.assert_not_called()
            self.assertEqual(self.p['current_version'],old_id)
            self.assertEqual(len(self.p['versions']),1)
            self.assertEqual(model.call_count,1)
        with patch('fine_audio.process_audio',side_effect=AssertionError('Must reuse cached audio')),\
                patch('fine_auto.checked_captions',return_value=copy.deepcopy(self.rows)),\
                patch('fine_auto.chat_api',return_value=json.dumps(self.keep(self.rows))):
            self.run_cmd('edit_auto',options=self.options())
        steps={s['id']:s for s in self.p['execution']['steps']}
        self.assertEqual(steps['audio']['state'],'done')
        self.assertEqual(steps['audio']['detail'],'降低背景音乐 · 复用已处理音频')
        self.assertNotEqual(self.p['current_version'],old_id)
        self.assertEqual(len(self.p['versions']),2)
        stat=self.video.stat();os.utime(self.video,ns=(stat.st_atime_ns,stat.st_mtime_ns+1000000000))
        with contextlib.redirect_stdout(io.StringIO()):
            self.p=Editor(self.store,{'cmd':'edit_export','project_id':self.p['id']}).run()
        self.assertIn('原素材已变化',self.p['error'])
        self.assertEqual(len(self.p['versions']),2)

    def test_missing_words_disagreement_and_laughter_cannot_be_deleted(self):
        original=[{'id':0,'start':0,'end':2,'text':'今天讲个故事'},
                  {'id':1,'start':2,'end':4,'text':'哈哈哈'},
                  {'id':2,'start':4,'end':6,'text':'低声说出的关键原因'}]
        fresh=[dict(original[0]),{'id':1,'start':4,'end':6,'text':'识别成了另一句话'}]
        rows,protected=reconcile_audio(original,fresh)
        self.assertEqual(len(rows),3)
        self.assertTrue(rows[1]['original_fallback'])
        self.assertTrue(all('analysis_note' in r for r in rows[1:]))
        self.assertTrue(any(p['start']==2 for p in protected))
        (self.store.task_dir(self.task['id'])/'transcript.json').write_text(json.dumps(original,ensure_ascii=False),encoding='utf-8')
        def api(settings,messages,*args):
            data=json.loads(messages[1]['content'])['transcript']
            return json.dumps({'summary':'删除重复','kept_ids':[0],
                 'removed':[{'id':r['id'],'kind':'repeats','reason':'重复内容','quote':r['text']} for r in data[1:]]})
        with patch('fine_audio.prepare',return_value={'identity':{'test':True}}),\
                patch('fine_auto.checked_captions',return_value=fresh),\
                patch('fine_auto.chat_api',side_effect=api),patch.object(Editor,'render'):
            self.run_cmd('edit_auto',options=self.options(subtitles='checked'))
        v=self.p['versions'][-1]
        self.assertEqual(v['removed'],[]);self.assertEqual(v['duration'],12)
        self.assertEqual(len(v['auto_review']['protected']),2)
        self.assertTrue(v['caption_review']['needs_review'])

    def test_cleaned_only_silence_does_not_delete_original_reactions(self):
        def silence(editor,audio=None):return [(2,8)] if audio else []
        with patch('fine_audio.prepare',return_value={'identity':{'test':True}}),\
                patch('fine_auto.checked_captions',return_value=copy.deepcopy(self.rows)),\
                patch('fine_auto.detect_silence',side_effect=silence) as detect,\
                patch('fine_auto.chat_api',return_value=json.dumps(self.keep(self.rows))),patch.object(Editor,'render'):
            self.run_cmd('edit_auto',options=self.options(speech=['silence']))
        self.assertEqual(detect.call_count,2)
        self.assertEqual(self.p['versions'][-1]['duration'],12)

    def test_audio_cache_invalidates_on_source_or_strength_and_cut_uses_event_offsets(self):
        self.p.update(source_start=3,source_end=10)
        with contextlib.redirect_stdout(io.StringIO()):save(self.store,self.p)
        editor=Editor(self.store,{'project_id':self.p['id']})
        with patch('fine_audio.process_audio',side_effect=self.separated) as model,contextlib.redirect_stdout(io.StringIO()):
            first=prepare(editor);self.assertEqual(first,prepare(editor));self.assertEqual(model.call_count,1)
            folder=self.root/'cut';folder.mkdir()
            path=cut(editor,first,[{'start':8,'end':10},{'start':3,'end':4}],folder)
            self.assertAlmostEqual(audio_duration(editor,path),3,delta=.03)
            script=(folder/'audio-ranges.txt').read_text(encoding='utf-8')
            self.assertIn('start=5.000000:end=7.000000',script)
            self.assertIn('start=0.000000:end=1.000000',script)
            prepare(editor,.5);self.assertEqual(model.call_count,2)
            stat=self.video.stat();os.utime(self.video,ns=(stat.st_atime_ns,stat.st_mtime_ns+1000000000))
            newer=prepare(editor);self.assertNotEqual(first['identity'],newer['identity']);self.assertEqual(model.call_count,3)

    def test_cancel_or_bad_duration_does_not_publish_audio_or_replace_version(self):
        editor=Editor(self.store,{'project_id':self.p['id']})
        with patch('fine_audio.process_audio',side_effect=Cancelled),contextlib.redirect_stdout(io.StringIO()):
            result=Editor(self.store,{'cmd':'edit_auto','project_id':self.p['id'],'options':self.options()}).run()
        self.assertEqual(result['execution']['state'],'cancelled');self.assertEqual(result['versions'],[])
        self.assertFalse(list(editor.folder.rglob('ready-*.json')))
        editor=Editor(self.store,{'project_id':self.p['id']})
        with patch('fine_audio.process_audio',return_value=self.video),\
                patch('fine_audio.audio_duration',return_value=2),contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError,'时长'):prepare(editor)
        self.assertFalse(list(editor.folder.rglob('ready-*.json')))

    def test_processed_transcription_uses_zero_seek_and_preserves_source_timestamps(self):
        self.p.update(source_start=3,source_end=10)
        with contextlib.redirect_stdout(io.StringIO()):save(self.store,self.p)
        editor=Editor(self.store,{'project_id':self.p['id']})
        model=self.root/'model';model.mkdir()
        for name in ('model.int8.onnx','tokens.txt','silero_vad.onnx'):(model/name).write_bytes(b'model')
        audio={'path':str(self.video)};calls=[]
        def command(args,*rest,**kwargs):
            calls.append(args)
            if '--output' in args:
                Path(args[args.index('--output')+1]).write_text(json.dumps({'id':0,'start':1,'end':3,'text':'片段语音'})+'\n',encoding='utf-8')
        with patch('pipeline.model_ready',return_value=True),patch('pipeline.model_dir',return_value=model),\
                patch('fine_auto.command',side_effect=command):
            rows=checked_captions(editor,audio)
            self.assertEqual((rows[0]['start'],rows[0]['end']),(4,6))
            self.assertEqual(float(calls[0][calls[0].index('-ss')+1]),0)
            self.assertEqual(calls[0][calls[0].index('-map')+1],'0:a:0')
            self.assertEqual(checked_captions(editor,audio),rows);self.assertEqual(len(calls),2)
            self.assertEqual(checked_captions(editor),rows);self.assertEqual(len(calls),4)
            self.assertEqual(float(calls[2][calls[2].index('-ss')+1]),3)


if __name__=='__main__':unittest.main()
