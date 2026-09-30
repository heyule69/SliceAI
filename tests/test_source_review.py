import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from source_review import validate_review,review_clip
from pipeline import Runner
from storage import Store
from engine import Cancelled

class SourceReviewTest(unittest.TestCase):
    def setUp(self):
        self.clip={'start':0,'end':100,'title':'测试','score':90,'id':1}
        self.rows=[{'id':0,'start':1,'end':6,'text':'他在说啥，为什么转变这么快啊？'},
                   {'id':1,'start':7,'end':9,'text':'一秒就看上了。'},
                   {'id':2,'start':10,'end':40,'text':'这是我自己的观点，我认为这个故事的矛盾需要结合人物背景来分析。'}]
    def evidence(self,source,ids):
        return {'source':source,'reason':'素材审查结论','visual_evidence':[{'frame':1,'description':'可见播放场景'}],
                'streamer_evidence':[{'id':i,'quote':self.rows[i]['text'],'attribution':'结合画面字幕明确是主播对外部内容的评论'} for i in ids]}

    def test_pure_playback_and_incidental_comments_are_excluded(self):
        self.assertEqual(validate_review(self.evidence('external_playback',[]),self.rows,self.clip)['decision'],'exclude')
        result=validate_review(self.evidence('mixed_reaction',[0,1]),self.rows,self.clip)
        self.assertEqual(result['decision'],'exclude');self.assertAlmostEqual(result['estimated_streamer_seconds'],7)

    def test_meaningful_reaction_and_chat_are_kept(self):
        for source in ('mixed_reaction','streamer'):
            self.assertEqual(validate_review(self.evidence(source,[2]),self.rows,self.clip)['decision'],'keep')

    def test_untrusted_or_missing_evidence_is_held(self):
        for raw in (None,{},self.evidence('uncertain',[2]),{'source':'streamer','decision':'keep'},
                    {**self.evidence('streamer',[2]),'visual_evidence':[]}):
            self.assertEqual(validate_review(raw,self.rows,self.clip)['decision'],'hold')
        raw=self.evidence('streamer',[2]);raw['streamer_evidence'][0]['quote']='模型杜撰的主播发言'
        self.assertEqual(validate_review(raw,self.rows,self.clip)['decision'],'hold')
        raw=self.evidence('mixed_reaction',[2]);raw['streamer_evidence'][0]['quote']='这是我自己的观点'
        self.assertEqual(validate_review(raw,self.rows,self.clip)['decision'],'exclude','不能用一句短引用占用整段 ASR 时长')
        raw=self.evidence('mixed_reaction',[0]);raw['streamer_evidence']*=10
        self.assertEqual(validate_review(raw,self.rows,self.clip)['decision'],'exclude','重复引用不能刷贡献时长')

    def make_runner(self,root):
        store=Store(root/'data');video=root/'video.mp4';video.write_bytes(b'test-source')
        task={'id':'01234567-0123-4123-8123-012345678901','created':'2026-09-29T00:00:00Z','title':'测试','video':str(video),'duration':100,
              'prefs':{'exclude_playback':True,'max_clips':1},'clips':[dict(self.clip)],'exports':[],
              'output_root':str(root/'exports'),'status':'complete','stage':'','progress':100,'error':''}
        store.put(task);runner=Runner(store,task['id'])
        (runner.folder/'transcript.json').write_text(json.dumps(self.rows,ensure_ascii=False),encoding='utf-8')
        return store,runner

    def test_filter_refills_limit_and_export_blocks_old_unreviewed_clips(self):
        with tempfile.TemporaryDirectory() as temp:
            store,runner=self.make_runner(Path(temp))
            try:
                other={**self.clip,'id':2,'start':200,'end':300,'score':80}
                with patch('pipeline.review_clip',side_effect=[{'decision':'exclude'},{'decision':'keep'}]),contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(runner.select_sources([self.clip,other],self.rows,1),[other])
                with patch('pipeline.review_clip',return_value={'decision':'exclude'}),patch.object(runner,'render_clip') as render,contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(runner.export([1],'separate'),[]);render.assert_not_called()
                self.assertEqual(runner.task['clips'],[])
            finally:store.db.close()

    def test_api_failure_never_exports_and_recheck_can_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            store,runner=self.make_runner(Path(temp))
            try:
                with patch('pipeline.review_clip',side_effect=ValueError('图片输入不支持')),patch.object(runner,'render_clip') as render,contextlib.redirect_stdout(io.StringIO()):
                    runner.export([1],'separate');render.assert_not_called()
                self.assertEqual(runner.task['status'],'failed');self.assertEqual(len(runner.task['clips']),1)
                with patch('pipeline.review_clip',side_effect=Cancelled()),contextlib.redirect_stdout(io.StringIO()):
                    result=runner.recheck()
                self.assertEqual(result['status'],'cancelled');self.assertEqual(len(result['clips']),1)
            finally:store.db.close()

    def test_cache_binds_source_model_and_transcript(self):
        with tempfile.TemporaryDirectory() as temp:
            store,runner=self.make_runner(Path(temp))
            def frame(args,*a,**kw):Path(args[-1]).write_bytes(b'x'*200)
            try:
                response=json.dumps(self.evidence('streamer',[2]),ensure_ascii=False)
                with patch('source_review.command',side_effect=frame),patch('source_review.chat_api',return_value=response) as api:
                    self.assertEqual(review_clip(runner,self.clip,self.rows)['decision'],'keep')
                    review_clip(runner,self.clip,self.rows);self.assertEqual(api.call_count,1)
                    runner.settings['api_model']='another-model'
                    review_clip(runner,self.clip,self.rows);self.assertEqual(api.call_count,2)
                    changed=[{**r,'text':r['text']+'修改'} for r in self.rows]
                    review_clip(runner,self.clip,changed);self.assertEqual(api.call_count,3)
                    Path(runner.task['video']).write_bytes(b'changed source')
                    review_clip(runner,self.clip,self.rows);self.assertEqual(api.call_count,4)
            finally:store.db.close()

    def test_failed_frame_is_not_sent_and_rejected_clip_gets_stable_id_on_recheck(self):
        with tempfile.TemporaryDirectory() as temp:
            store,runner=self.make_runner(Path(temp))
            try:
                with patch('source_review.command',side_effect=ValueError('抽帧失败')),patch('source_review.chat_api') as api:
                    with self.assertRaisesRegex(ValueError,'复核未完成'):review_clip(runner,self.clip,self.rows)
                    api.assert_not_called()
                runner.task['rejected_clips']=[{'start':200,'end':300,'title':'重新确认的观看评论','score':80}]
                with patch('pipeline.review_clip',return_value={'decision':'keep'}),contextlib.redirect_stdout(io.StringIO()):
                    result=runner.recheck()
                self.assertEqual(result['status'],'complete')
                self.assertEqual({c['id'] for c in result['clips']},{1,2})
            finally:store.db.close()

if __name__=='__main__':unittest.main()
