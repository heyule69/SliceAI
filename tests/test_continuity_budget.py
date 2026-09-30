"""No external AI: exact source anchors, bounded requests and whole-story spans."""
import copy
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from events import CONTINUITY_BUDGET, analyze_events, review_continuity


class ContinuityBudgetTest(unittest.TestCase):
    def setUp(self):
        self.rows = [{'id': i, 'start': i * 10., 'end': i * 10 + 9.,
                      'text': f'Original row {i}: ' + 'the same story has a cause and a result. ' * 8} for i in range(220)]
        self.event = {'start_id': 0, 'end_id': 219, 'start': 0., 'end': 2199.,
                      'title': 'A complete long story', 'summary': 'cause, process and result',
                      'reason': 'A grounded story', 'category': 'story', 'score': 90, 'ended': True}
        self.runner = SimpleNamespace(task={'duration': 2300, 'prefs': {'topics': ['auto']}},
                                      store=None, task_id='fixture', update=lambda *args: None)
        self.requests = []

    def outline(self, payload):
        if 'transcript' in payload:
            rows = payload['transcript']
            evidence = [{'id': row['id'], 'quote': row['text'][:40]} for row in (rows[0], rows[-1])]
        else:
            sections = payload['ordered_sections']
            evidence = [sections[0]['evidence'][0], sections[-1]['evidence'][-1]]
        return {'summary': 'A cause and a result belong to the same complete story.', 'evidence': evidence}

    def candidate(self, start=0, end=219, evidence=None):
        result = {key: self.event[key] for key in ('title', 'reason', 'category', 'score')}
        result.update(start_id=start, end_id=end)
        if evidence:
            result['evidence'] = [{'id': evidence['id'], 'quote': evidence['quote'][:40]}]
        return result

    def section_response(self, payload, same_story=True):
        if same_story:
            events = [self.candidate(evidence=payload['original_boundary_anchors'][0])]
        else:
            events = [self.candidate(section['start_id'], section['end_id'], section['evidence'][0])
                      for section in payload['sections']]
        return {'events': events, 'more_events': False,
                'coverage': [{'section_id': section['section_id'], 'decision': 'story',
                              'reason': 'The quote belongs to a complete story.',
                              'evidence': {'id': section['evidence'][0]['id'],
                                           'quote': section['evidence'][0]['quote'][:40]}}
                             for section in payload['sections']]}

    def api(self, runner, kind, system, payload):
        self.requests.append((kind, copy.deepcopy(payload)))
        if kind != 'discover':
            self.assertLessEqual(len(json.dumps(payload, ensure_ascii=False)), CONTINUITY_BUDGET)
        if kind.startswith('grounded-outline'):
            return self.outline(payload)
        if kind.startswith('continuity-full'):
            return {'events': [self.candidate()], 'more_events': False}
        if kind.startswith('continuity-sections'):
            return self.section_response(payload)
        if kind == 'discover':
            return {'events': [dict(self.candidate(), key=None, ended=True, summary='A complete story')]}
        if kind.startswith('boundary'):
            return {'start_id': payload['event']['start_id'], 'end_id': payload['event']['end_id']}
        self.fail(f'Unexpected request {kind}')

    def run_review(self, api=None):
        with patch('events.cached_api', side_effect=api or self.api), patch('events.check_cancel'), patch('engine.check_cancel'):
            return review_continuity(self.runner, self.event, self.rows)

    def test_large_same_story_is_one_full_original_span_and_every_request_is_bounded(self):
        result = self.run_review()
        self.assertEqual(len(result), 1)
        self.assertEqual((result[0]['start'], result[0]['end']), (0., 2199.))
        self.assertEqual((result[0]['start_id'], result[0]['end_id']), (0, 219))
        reviewed = [payload for kind, payload in self.requests if kind == 'continuity-sections-v2']
        self.assertGreater(len(reviewed), 1)
        section_ids = [section['section_id'] for payload in reviewed for section in payload['sections']]
        self.assertEqual(len(section_ids), len(set(section_ids)))
        self.assertNotIn('continuity_warnings', self.runner.task)

    def test_integrated_900_second_path_and_overlapping_stories_remain_deduplicated(self):
        def api(runner, kind, system, payload):
            if kind == 'discover':
                row = dict(self.candidate(), key=None, ended=True, summary='Whole story')
                return {'events': [row, dict(row)]}
            return self.api(runner, kind, system, payload)
        with patch('events.transcript_windows', return_value=[self.rows]), patch('events.cached_api', side_effect=api), \
                patch('events.check_cancel'), patch('engine.check_cancel'):
            result = analyze_events(self.runner, self.rows, [])
        self.assertEqual(len(result), 1)
        self.assertEqual((result[0]['start_id'], result[0]['end_id']), (0, 219))
        self.assertAlmostEqual(result[0]['end'], 2199.2)
        self.assertTrue(any(kind.startswith('continuity-sections') for kind, _ in self.requests))
        boundary = next(payload for kind, payload in self.requests if kind.startswith('boundary'))
        self.assertFalse(boundary['context_complete'])

    def test_overlapping_long_candidates_keep_whole_spans_for_editorial_story_consolidation(self):
        from editorial import review_pass
        def api(runner, kind, system, payload):
            if kind == 'discover':
                return {'events': [dict(self.candidate(0, 199), key=None, ended=True, summary='Same story'),
                                   dict(self.candidate(20, 219), key=None, ended=True, summary='Same story')]}
            if kind.startswith('continuity-sections'):
                self.requests.append((kind, copy.deepcopy(payload)))
                self.assertLessEqual(len(json.dumps(payload)), CONTINUITY_BUDGET)
                result = self.section_response(payload)
                result['events'][0].update(start_id=payload['event']['start_id'], end_id=payload['event']['end_id'])
                return result
            return self.api(runner, kind, system, payload)
        with patch('events.transcript_windows', return_value=[self.rows]), patch('events.cached_api', side_effect=api), \
                patch('events.check_cancel'), patch('engine.check_cancel'):
            candidates = analyze_events(self.runner, self.rows, [])
        self.assertEqual(sorted((item['start_id'], item['end_id']) for item in candidates), [(0, 199), (20, 219)])
        def editorial_api(runner, kind, system, payload):
            group = payload['components'][0]
            return {'events': [dict(self.candidate(), member_ids=[candidate['candidate_id'] for candidate in group['candidates']],
                                   evidence=[{'id': 219, 'quote': self.rows[-1]['text'][:40], 'role': 'payoff'}])], 'rejected': []}
        with patch('editorial.cached_api', side_effect=editorial_api), patch('editorial.check_cancel'), \
                patch('events.cached_api', side_effect=self.api), patch('engine.check_cancel'):
            consolidated, _ = review_pass(self.runner, candidates, self.rows)
        self.assertEqual(len(consolidated), 1)
        self.assertEqual((consolidated[0]['start_id'], consolidated[0]['end_id']), (0, 219))

    def test_independent_stories_are_not_capped_at_four_for_the_complete_event(self):
        def api(runner, kind, system, payload):
            if kind.startswith('continuity-sections'):
                self.requests.append((kind, copy.deepcopy(payload)))
                self.assertLessEqual(len(json.dumps(payload)), CONTINUITY_BUDGET)
                return self.section_response(payload, same_story=False)
            return self.api(runner, kind, system, payload)
        result = self.run_review(api)
        self.assertGreater(len(result), 4)
        covered = {sid for item in result for sid in range(item['start_id'], item['end_id'] + 1)}
        self.assertEqual(covered, set(range(220)))

    def test_missing_section_coverage_falls_back_with_a_visible_warning(self):
        def api(runner, kind, system, payload):
            if kind.startswith('continuity-sections'):
                result = self.section_response(payload); result['coverage'] = []
                return result
            return self.api(runner, kind, system, payload)
        result = self.run_review(api)
        self.assertEqual((result[0]['start_id'], result[0]['end_id']), (0, 219))
        self.assertTrue(self.runner.task['continuity_warnings'])

    def test_unseen_anchor_id_and_wrong_quote_cannot_publish_a_shortened_event(self):
        def api(runner, kind, system, payload):
            if kind.startswith('continuity-sections'):
                result = self.section_response(payload)
                result['events'][0].update(start_id=1, evidence=[{'id': 1, 'quote': 'invented quote'}])
                return result
            return self.api(runner, kind, system, payload)
        result = self.run_review(api)
        self.assertEqual((result[0]['start_id'], result[0]['end_id']), (0, 219))
        self.assertTrue(self.runner.task['continuity_warnings'])

    def test_uncertain_section_keeps_confirmed_independent_stories_and_full_source(self):
        def api(runner, kind, system, payload):
            if kind.startswith('continuity-sections'):
                result = self.section_response(payload, same_story=False)
                result['coverage'][0]['decision'] = 'uncertain'
                return result
            return self.api(runner, kind, system, payload)
        result = self.run_review(api)
        self.assertGreater(len(result), 2)
        self.assertTrue(any((item['start_id'], item['end_id']) == (0, 219) for item in result))
        self.assertTrue(self.runner.task['continuity_warnings'])

    def test_more_output_adapts_transport_without_cutting_the_story(self):
        def api(runner, kind, system, payload):
            if kind.startswith('continuity-sections'):
                result = self.section_response(payload)
                result['more_events'] = len(payload['sections']) > 1
                return result
            return self.api(runner, kind, system, payload)
        result = self.run_review(api)
        self.assertEqual(len(result), 1)
        self.assertEqual((result[0]['start_id'], result[0]['end_id']), (0, 219))
        self.assertNotIn('continuity_warnings', self.runner.task)

    def test_oversized_single_sentence_preserves_source_without_oversized_api_input(self):
        self.rows[0]['text'] = 'x' * 7000
        with patch('events.cached_api') as api:
            result = review_continuity(self.runner, self.event, self.rows)
        api.assert_not_called()
        self.assertEqual((result[0]['start_id'], result[0]['end_id']), (0, 219))
        self.assertTrue(self.runner.task['continuity_warnings'])

    def test_small_input_keeps_original_time_range_and_provider_errors_are_not_hidden(self):
        self.rows = [dict(row, text='short sentence') for row in self.rows[:8]]
        self.event.update(end_id=7)
        with patch('events.cached_api', return_value={'events': [self.candidate(0, 7)], 'more_events': False}):
            result = review_continuity(self.runner, self.event, self.rows)
        self.assertEqual((result[0]['start'], result[0]['end']), (0., 2199.))
        with patch('events.cached_api', side_effect=ValueError('Provider authentication failed')):
            with self.assertRaisesRegex(ValueError, 'authentication'):
                review_continuity(self.runner, self.event, self.rows)


if __name__ == '__main__':
    unittest.main()
