import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from fine_progress import begin, update, finish


class ProgressTest(unittest.TestCase):
    def project(self):
        return {'versions': [], 'current_version': None}

    def test_optional_steps_and_only_measured_percentage(self):
        p = self.project()
        begin(p, 'edit_auto', {'speech': [], 'subtitles': 'none', 'music': 'original'})
        self.assertEqual([s['id'] for s in p['execution']['steps']], ['prepare', 'plan', 'review', 'video', 'finish'])
        update(p, '生成预览区间 · 1/1')
        step = next(s for s in p['execution']['steps'] if s['id'] == 'video')
        self.assertIsNone(step['percent'])
        self.assertEqual(step['state'], 'running')
        self.assertEqual(next(s for s in p['execution']['steps'] if s['id'] == 'plan')['state'], 'pending')

    def test_audio_completion_is_not_whole_task_completion(self):
        p = self.project()
        begin(p, 'edit_auto', {'speech': ['silence'], 'subtitles': 'checked', 'music': 'reduce'})
        self.assertEqual([s['id'] for s in p['execution']['steps']],
                         ['prepare','audio','transcribe','plan','review','silence','video','finish'])
        update(p, '降低背景音乐 · 100%')
        steps = {s['id']: s for s in p['execution']['steps']}
        self.assertEqual(steps['audio']['percent'], 100)
        self.assertEqual(steps['audio']['state'], 'running')
        self.assertEqual(steps['finish']['state'], 'pending')
        update(p, '重新转写处理后音频')
        self.assertEqual(steps['audio']['state'], 'done')
        self.assertEqual(steps['transcribe']['state'], 'running')
        self.assertEqual(steps['plan']['state'], 'pending')
        for stage in ('对照原声转写与保留反应','理解片段与剪辑要求', '复核故事完整性与删减依据',
                      '检测音频长静音','生成预览区间 · 1/1','合成画面与声音'):
            update(p, stage)
        self.assertEqual(steps['finish']['state'], 'running')
        finish(p, 'done')
        self.assertTrue(all(s['state'] == 'done' for s in steps.values()))

    def test_failure_cancellation_and_retry_do_not_invent_completed_steps(self):
        p = self.project()
        for outcome in ('failed', 'cancelled', 'interrupted'):
            begin(p, 'edit_auto', {'speech': [], 'subtitles': 'none'})
            update(p, '理解片段与剪辑要求')
            update(p, '复核故事完整性与删减依据')
            run_id = p['execution']['id']
            finish(p, outcome)
            self.assertEqual(p['execution']['state'], outcome)
            steps = {s['id']: s for s in p['execution']['steps']}
            self.assertEqual(steps['plan']['state'], 'done')
            self.assertEqual(steps['review']['state'], outcome)
            self.assertEqual(steps['video']['state'], 'pending')
            begin(p, 'edit_auto', {'speech': [], 'subtitles': 'none'})
            self.assertNotEqual(p['execution']['id'], run_id)
            self.assertTrue(all(s['state'] == 'pending' for s in p['execution']['steps'][1:]))

    def test_cached_render_does_not_claim_audio_ran(self):
        p = self.project()
        p.update(current_version='v1', versions=[{'id': 'v1', 'audio_strength': 1}])
        begin(p, 'edit_export')
        update(p, '写入导出文件')
        finish(p, 'done')
        steps = {s['id']: s for s in p['execution']['steps']}
        self.assertEqual(steps['audio']['state'], 'skipped')
        self.assertEqual(steps['video']['state'], 'skipped')
        self.assertEqual(steps['finish']['state'], 'done')


if __name__ == '__main__':
    unittest.main()
