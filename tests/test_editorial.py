import copy,sys,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from editorial import batches,validate,select_highlights,dedupe_retellings,merge_duplicate_windows,review_pass

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

    def _event(self, start_id, end_id, members, score=90, quote_id=None):
        quote_id = start_id if quote_id is None else quote_id
        return {'title':'事件','reason':'具体冲突和结果都在原文里','category':'聊天故事','score':score,
                'start_id':start_id,'end_id':end_id,
                'start':self.rows[start_id]['start'],'end':self.rows[end_id]['end'],
                'editorial':{'version':4,'member_ids':list(members),'reason':'具体冲突和结果都在原文里',
                             'evidence':[{'id':quote_id,'quote':self.rows[quote_id]['text'],'role':'payoff'}]}}

    def test_overlapping_and_near_duplicate_windows_merge_distinct_neighbors_do_not(self):
        rows=self.rows
        wide=self._event(0,40,[1],score=90,quote_id=20)
        inner=self._event(10,30,[2,3],score=88,quote_id=25)
        shifted=self._event(8,42,[4],score=86,quote_id=15)
        original=copy.deepcopy([wide,inner,shifted])
        merged=merge_duplicate_windows([wide,inner,shifted],rows)
        self.assertEqual([wide,inner,shifted],original)
        self.assertEqual(len(merged),1)
        self.assertEqual((merged[0]['start_id'],merged[0]['end_id']),(0,42))
        self.assertEqual(merged[0]['editorial']['member_ids'],[1,4,2,3])
        self.assertEqual(merged[0]['editorial']['window_merge']['method'],'overlapping-window')
        self.assertTrue(any(item['role']=='payoff' for item in merged[0]['editorial']['evidence']))
        # Sentence padding overlaps by a fraction of a second; different text stays split.
        left=self._event(0,3,[1],quote_id=1)
        right=self._event(4,7,[2],quote_id=6)
        right['start']=left['end']-.35
        self.assertEqual(len(merge_duplicate_windows([left,right],rows)),2)
        # Near-verbatim retelling a few seconds later keeps the longer span and does not swallow the gap.
        story='猫去洗澡发现皮肤病随后找店家处理并且拿到退款'
        for index in range(10,17):
            rows[index]['text']=story
        short=self._event(10,12,[7],score=90,quote_id=11)
        longer=self._event(13,16,[8],score=91,quote_id=15)
        other=self._event(20,22,[9],score=90,quote_id=21)
        other['start']=longer['end']+5
        kept=merge_duplicate_windows([short,longer,other],rows)
        self.assertEqual(len(kept),2)
        story_event=next(event for event in kept if event['start_id']==13)
        self.assertEqual(story_event['end_id'],16)
        self.assertEqual(story_event['editorial']['member_ids'],[8,7])
        self.assertEqual(story_event['editorial']['window_merge']['method'],'near-duplicate-window')
        self.assertEqual(next(event['start_id'] for event in kept if event['start_id']!=13),20)
        self.assertEqual(len(merge_duplicate_windows(kept,rows)),2)

    def test_cross_window_overlap_merges_before_a_second_model_pass(self):
        rows=[{'id':i,'start':i*2.,'end':i*2+1.8,'text':'必要铺垫和结尾。'} for i in range(30)]
        candidates=[{'title':'同一完整故事','start_id':0,'end_id':29,'start':0,'end':59.8,'score':90} for _ in range(9)]
        runner=SimpleNamespace(task={'duration':80,'prefs':{'topics':['自动判断']}},store=None,task_id='fixture',update=lambda *a:None)
        calls=[]
        def review(runner,kind,system,payload):
            calls.append(kind)
            if 'final' in kind:
                raise AssertionError('重叠窗口应先合并，不能再依赖会重复输出的二次模型')
            group=payload['components'][0]
            return {'events':[{'member_ids':[c['candidate_id'] for c in group['candidates']],
                'title':'完整故事','start_id':0,'end_id':29,'score':90,'reason':'保留同一件事完整的铺垫经过及结尾。',
                'evidence':[{'id':29,'quote':rows[-1]['text'],'role':'payoff'}]}],'rejected':[]}
        with patch('editorial.cached_api',side_effect=review),patch('editorial.check_cancel'):
            kept,rejected=review_pass(runner,candidates,rows)
        self.assertEqual(len(kept),1)
        self.assertEqual(sorted(kept[0]['editorial']['member_ids']),list(range(1,10)))
        self.assertTrue(calls)
        self.assertTrue(all('final' not in kind for kind in calls))
        self.assertEqual(rejected,[])

    def test_select_highlights_collapses_near_duplicate_windows_the_model_kept_apart(self):
        story='猫去洗澡发现皮肤病随后找店家处理并且拿到退款'
        other='另一位观众的快递纠纷有明确冲突和当场回应'
        rows=[]
        for i in range(12):
            text=story if i<=3 or 5<=i<=8 else other
            rows.append({'id':i,'start':i*5.,'end':i*5+4.5,'text':text})
        candidates=[{'title':'洗澡短版','start_id':0,'end_id':3,'start':0,'end':19.5,'score':90},
                    {'title':'洗澡稍后复述','start_id':5,'end_id':8,'start':25,'end':44.5,'score':91},
                    {'title':'快递纠纷','start_id':10,'end_id':11,'start':50,'end':59.5,'score':88}]
        runner=SimpleNamespace(task={'duration':80,'prefs':{'topics':['自动判断']}},store=None,task_id='test',update=lambda *a:None)
        def review(runner,kind,system,payload):
            if kind.startswith('retelling'):
                return {'groups':[],'distinct_ids':[event['event_id'] for event in payload['events']]}
            events=[]
            for group in payload['components']:
                for candidate in group['candidates']:
                    events.append({'member_ids':[candidate['candidate_id']],'title':candidate['title'],
                        'start_id':candidate['start_id'],'end_id':candidate['end_id'],'score':90,
                        'reason':'同一件事的具体经过和结果都在原文里。','category':'聊天故事',
                        'evidence':[{'id':candidate['end_id'],'quote':rows[candidate['end_id']]['text'],'role':'payoff'}]})
            return {'events':events,'rejected':[]}
        with patch('editorial.cached_api',side_effect=review),patch('editorial.check_cancel'):
            kept=select_highlights(runner,candidates,rows)
        self.assertEqual(sorted(event['start_id'] for event in kept),[5,10])
        story_event=next(event for event in kept if event['start_id']==5)
        self.assertEqual(story_event['end_id'],8)
        self.assertEqual(set(story_event['editorial']['member_ids']),{1,2})
        self.assertEqual(runner.task['editorial_summary']['merged_duplicates'],1)
        self.assertEqual(runner.task['editorial_summary']['version'],5)

if __name__=='__main__':unittest.main()
