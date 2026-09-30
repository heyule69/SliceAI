import copy,sys,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from editorial import batches,validate,select_highlights,dedupe_retellings

class EditorialTest(unittest.TestCase):
    def setUp(self):
        self.rows=[{'id':i,'start':i*30.,'end':i*30+28.,'text':f'第{i}句，这是完整的故事原文。'} for i in range(80)]
        self.candidates=[{'title':'同一故事短版','start_id':4,'end_id':15,'start':120,'end':478,'score':95},
            {'title':'同一故事完整版本','start_id':1,'end_id':35,'start':30,'end':1078,'score':85},
            {'title':'感谢礼物','start_id':50,'end_id':50,'start':1500,'end':1528,'score':90}]
        self.groups=next(batches(self.candidates,self.rows))
        self.raw={'events':[{'member_ids':[1,2],'title':'一个完整故事','start_id':1,'end_id':35,'score':88,
            'reason':'具体冲突发生后产生反转并讲完后续回应。','evidence':[{'id':15,'quote':self.rows[15]['text'],'role':'payoff'}]}],
            'rejected':[{'candidate_id':3,'reason':'只是普通感谢，没有独立看点。'}]}
    def test_merges_boundary_variants_keeps_long_event_and_drops_greeting(self):
        kept,rejected=validate(self.raw,self.groups,self.candidates,self.rows,2400)
        self.assertEqual(len(kept),1);self.assertGreater(kept[0]['end']-kept[0]['start'],1000)
        self.assertEqual(kept[0]['start_id'],1);self.assertEqual(kept[0]['end_id'],35)
        self.assertEqual(rejected[0]['candidate_id'],3)
    def test_no_fabricated_evidence_missing_decisions_or_overlapping_results(self):
        mutations=[]
        bad=copy.deepcopy(self.raw);bad['events'][0]['evidence'][0]['quote']='虚构内容';mutations.append(bad)
        bad=copy.deepcopy(self.raw);bad['rejected']=[];mutations.append(bad)
        bad=copy.deepcopy(self.raw);bad['events'][0]['score']=60;mutations.append(bad)
        bad=copy.deepcopy(self.raw);bad['events'][0]['member_ids']=[1]
        extra=copy.deepcopy(bad['events'][0]);extra['member_ids']=[2];bad['events'].append(extra);mutations.append(bad)
        for raw in mutations:
            with self.assertRaises(ValueError):validate(raw,self.groups,self.candidates,self.rows,2400)
    def test_empty_selection_is_valid_and_real_events_are_not_capped_at_twelve(self):
        rejected={'events':[],'rejected':[{'candidate_id':i,'reason':'没有独立看点'} for i in (1,2,3)]}
        self.assertEqual(validate(rejected,self.groups,self.candidates,self.rows,2400)[0],[])
        candidates=[{'title':f'独立事件{i}','start_id':i*4,'end_id':i*4+1,'start':i*120.,'end':i*120+58.,'score':90} for i in range(16)]
        runner=SimpleNamespace(task={'duration':2400,'prefs':{'topics':['自动判断']}},store=None,task_id='test',update=lambda *a:None)
        def review(runner,kind,system,payload):
            if kind.startswith('retelling'):return {'groups':[],'distinct_ids':[e['event_id'] for e in payload['events']]}
            return {'events':[{'member_ids':[c['candidate_id']],'title':c['title'],'start_id':c['start_id'],'end_id':c['end_id'],
                'score':85,'reason':'每个事件都有独立的冲突和明确结果。','evidence':[{'id':c['end_id'],'quote':self.rows[c['end_id']]['text'],'role':'payoff'}]}
                for g in payload['components'] for c in g['candidates']],'rejected':[]}
        with patch('editorial.cached_api',side_effect=review),patch('editorial.check_cancel'):
            self.assertEqual(len(select_highlights(runner,candidates,self.rows)),16)

    def test_distant_retelling_keeps_complete_range_and_distinct_new_incident(self):
        events=[{'title':'短版','reason':'同一件事','start_id':1,'end_id':3,'editorial':{'member_ids':[1]}},
            {'title':'完整版本','reason':'同一件事的完整讲述','start_id':30,'end_id':45,'editorial':{'member_ids':[2,3]}},
            {'title':'另一位观众的新事件','reason':'引用旧事但有新的冲突','start_id':60,'end_id':65,'editorial':{'member_ids':[4]}}]
        original=copy.deepcopy(events)
        response={'groups':[{'event_ids':[1,2],'keep_id':2,'reason':'同一人物同一经过，第二次讲述完整。',
            'evidence':[{'event_id':1,'id':2,'quote':self.rows[2]['text']},
                        {'event_id':2,'id':31,'quote':self.rows[31]['text']}]}],'distinct_ids':[3]}
        runner=SimpleNamespace(store=None,task_id='test',update=lambda *a:None)
        with patch('editorial.cached_api',return_value=response),patch('editorial.check_cancel'):
            kept=dedupe_retellings(runner,events,self.rows)
        self.assertEqual(events,original)
        self.assertEqual({(c['start_id'],c['end_id']) for c in kept},{(30,45),(60,65)})
        self.assertEqual(next(c for c in kept if c['start_id']==30)['editorial']['member_ids'],[1,2,3])
        invalid=copy.deepcopy(response);invalid['groups'][0]['evidence'][0]['quote']='没有说过的话'
        for raw in (None,invalid,{'groups':[],'distinct_ids':[3]}, {'groups':[None],'distinct_ids':[]}):
            with patch('editorial.cached_api',return_value=raw),patch('editorial.check_cancel'):
                with self.assertRaises(ValueError):dedupe_retellings(runner,events,self.rows)
            self.assertEqual(events,original)

if __name__=='__main__':unittest.main()
