"""Malformed candidate groups retain locally; provider failures still abort."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from engine import Cancelled
from fine_auto import DEFAULTS, cached, run
from fine_candidates import generate, validate_decisions


class FixtureEditor:
    def __init__(self,root,count=14):
        self.folder=root/'work';self.folder.mkdir()
        video=root/'source.bin';video.write_bytes(b'isolated source identity')
        self.task={'video':str(video)}
        self.settings={'api_base':'http://fixture.invalid/v1','api_model':'fixture'}
        self.store=SimpleNamespace(root=root,task_dir=lambda task_id:root/task_id)
        self.p={'id':'candidate-fixture','title':'完整故事'}
        self.req={'options':{**DEFAULTS,'cleanup':['offtopic'],'speech':[],
                             'subtitles':'none','normalize':False}}
        self.clip={'start':0.,'end':count*2.}
        self.context=[{'id':index,'start':index*2.,'end':index*2.+1.5,'text':f'片段{index}',
                       'alignment_complete':True,'words':[{'id':f'{index}:0','text':f'片段{index}',
                           'start':index*2.,'end':index*2.+1.5,'timing_method':'forced_alignment'}]}
                      for index in range(count)]
        self.stages=[];self.rendered=False

    def persist(self,stage=None):
        if stage:self.stages.append(stage)

    def usage(self,*args):
        pass

    def version(self,ranges,summary,**options):
        self.result={'ranges':ranges,'duration':sum(row['end']-row['start'] for row in ranges),
                     'summary':summary,**options}
        return self.result

    def render(self):
        self.rendered=True


class CandidateFallbackTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.editor=FixtureEditor(self.root)
        self.options=self.editor.req['options']

    def tearDown(self):
        self.tmp.cleanup()

    def bad(self,items):
        return {'decisions':[{'id':item['id'],'action':'remove','kind':'offtopic',
                             'reason':'模型提出删除无关内容','reference_ids':[9999],
                             'provider_body':'untrusted-provider-body'} for item in items]}

    def keep(self,items,blocked=True):
        return {'decisions':[{'id':item['id'],'action':'keep','kind':item['kind'],
            'reason':'候选引用或结构未核验，保留原文','reference_ids':[],
            **({'validation_blocked':True} if blocked else {})} for item in items]}

    def single(self):
        items=generate(self.editor.context[:1],self.options,self.editor.clip)
        validate=lambda raw:validate_decisions(raw,items,self.editor.context,self.options)
        return items,validate

    def test_late_invalid_group_preserves_earlier_valid_cut_and_visible_blocked_ledger(self):
        invalid_groups=[];final_candidates=[]
        def provider(settings,messages,*args):
            payload=json.loads(messages[1]['content'])
            if 'combined_candidates' in payload:
                final_candidates.extend(item['id'] for item in payload['combined_candidates'])
                return json.dumps({'restore_ids':[],'reason':'保留完整故事及未核验的原文声音'})
            items=payload['candidates']
            if any(item['row_ids']==[13] for item in items):
                invalid_groups.append([item['id'] for item in items])
                return json.dumps(self.bad(items))
            return json.dumps({'decisions':[{'id':item['id'],'action':'remove' if item['id']=='row:0' else 'keep',
                'kind':'offtopic' if item['id']=='row:0' else item['kind'],
                'reason':'开端的独立闲聊可删除' if item['id']=='row:0' else '保留必要故事表达','reference_ids':[]}
                for item in items]})
        story={'outline':{'summary':'有开端与完整结局的故事'},'nodes':[]}
        with patch('fine_auto.checked_captions',return_value=copy.deepcopy(self.editor.context)),\
                patch('fine_story.build_story',return_value=story),patch('fine_auto.chat_api',side_effect=provider):
            run(self.editor)
        self.assertTrue(self.editor.rendered);self.assertEqual(len(invalid_groups),2)
        self.assertEqual(final_candidates,['row:0'])
        version=self.editor.result;ledger={item['id']:item for item in version['cut_ledger']}
        self.assertEqual(ledger['row:0']['status'],'applied')
        self.assertAlmostEqual(version['removed_duration'],1.5)
        self.assertEqual(version['removed'][0]['candidate_ids'],['row:0'])
        for cid in invalid_groups[-1]:
            self.assertEqual(ledger[cid]['status'],'blocked')
            self.assertEqual(ledger[cid]['decision'],'keep')
            self.assertTrue(ledger[cid]['validation_blocked'])
            self.assertIn('删除依据引用了不存在的原文',ledger[cid]['block_reason'])
        records=[json.loads(path.read_text(encoding='utf-8')) for path in (self.editor.folder/'auto-cache').glob('*.json')]
        blocked=next(record for record in records if record.get('decisions') and record['decisions'][0].get('validation_blocked'))
        self.assertTrue(all(item['action']=='keep' and item['reference_ids']==[] for item in blocked['decisions']))
        self.assertNotIn('provider_body',json.dumps(blocked))

    def test_only_valid_fallback_is_cached_and_retry_does_not_requery_provider(self):
        items,validate=self.single();fallback=Mock(side_effect=lambda error,raw:self.keep(items))
        with patch('fine_auto.chat_api',return_value=json.dumps(self.bad(items))) as api:
            result=cached(self.editor,'fixture','system',{'candidates':items},validate,on_invalid=fallback)
        self.assertEqual(api.call_count,2);fallback.assert_called_once()
        self.assertEqual(fallback.call_args.args[1]['decisions'][0]['reference_ids'],[9999])
        self.assertTrue(result['decisions'][0]['validation_blocked'])
        records=list((self.editor.folder/'auto-cache').glob('*.json'));self.assertEqual(len(records),1)
        saved=json.loads(records[0].read_text(encoding='utf-8'));self.assertEqual(saved,result)
        self.assertNotIn('provider_body',json.dumps(saved))
        with patch('fine_auto.chat_api',side_effect=AssertionError('cached keep must be reused')):
            again=cached(self.editor,'fixture','system',{'candidates':items},validate,on_invalid=fallback)
        self.assertEqual(again,result);fallback.assert_called_once()

    def test_provider_cancellation_and_decode_errors_never_enter_validation_fallback(self):
        items,validate=self.single()
        for index,failure in enumerate((ValueError('API 400'),OSError('network failure'),Cancelled('cancelled'))):
            fallback=Mock(return_value=self.keep(items))
            with self.subTest(error=type(failure).__name__),patch('fine_auto.chat_api',side_effect=[json.dumps(self.bad(items)),failure]):
                with self.assertRaises(type(failure)):
                    cached(self.editor,f'transport-{index}','system',{'candidates':items},validate,on_invalid=fallback)
            fallback.assert_not_called()
        fallback=Mock(return_value=self.keep(items))
        with patch('fine_auto.chat_api',return_value='not JSON'),patch('fine_auto.decode_json',side_effect=ValueError('decode failure')):
            with self.assertRaisesRegex(ValueError,'decode failure'):
                cached(self.editor,'decode','system',{'candidates':items},validate,on_invalid=fallback)
        fallback.assert_not_called()
        self.assertFalse(list((self.editor.folder/'auto-cache').glob('*.json')))

    def test_valid_second_response_is_used_without_fallback(self):
        items,validate=self.single();fallback=Mock(return_value=self.keep(items))
        good=self.keep(items,blocked=False)
        with patch('fine_auto.chat_api',side_effect=[json.dumps(self.bad(items)),json.dumps(good)]):
            result=cached(self.editor,'repair','system',{'candidates':items},validate,on_invalid=fallback)
        fallback.assert_not_called();self.assertNotIn('validation_blocked',result['decisions'][0])

    def test_validation_marker_cannot_authorize_remove_and_invalid_fallback_is_not_cached(self):
        items,validate=self.single()
        marked=self.bad(items);marked['decisions'][0].update(reference_ids=[],validation_blocked=True)
        with self.assertRaisesRegex(ValueError,'只能保留原文'):validate(marked)
        with patch('fine_auto.chat_api',return_value=json.dumps(self.bad(items))):
            with self.assertRaisesRegex(ValueError,'只能保留原文'):
                cached(self.editor,'bad-fallback','system',{'candidates':items},validate,
                       on_invalid=lambda error,raw:marked)
        self.assertFalse(list((self.editor.folder/'auto-cache').glob('*.json')))


if __name__=='__main__':unittest.main()
