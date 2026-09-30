import contextlib
import io
import subprocess
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from fine import Editor
from fine_audio import cut
from engine import tool_path
import test_fine


class AudioTimelineTest(unittest.TestCase):
    setUp = test_fine.FineTest.setUp
    tearDown = test_fine.FineTest.tearDown

    def test_nonframe_cut_lengths_keep_pcm_clock_stereo_and_declick_without_overlap(self):
        rate = 48000
        # Two different constant channels make every splice discontinuity
        # observable and reveal accidental downmixing.
        samples = np.tile(np.array([.2, -.1], dtype='<f4'), (rate*2, 1))
        ffmpeg = tool_path(self.store.settings(), 'ffmpeg')
        source = self.root / 'stereo.wav'
        subprocess.run([ffmpeg, '-v', 'error', '-y', '-f', 'f32le', '-ar', str(rate), '-ac', '2',
                        '-i', 'pipe:0', '-c:a', 'pcm_f32le', str(source)],
                       input=samples.tobytes(), check=True, capture_output=True)
        editor = Editor(self.store, {'project_id': self.p['id']})
        folder = editor.folder / 'renders' / 'pcm-clock'
        folder.mkdir(parents=True)
        lengths = [.2412, .3006, .6502]
        starts = [.0711, .5027, 1.1119]
        ranges = [dict(start=start, end=start+length) for start, length in zip(starts, lengths)]
        with contextlib.redirect_stdout(io.StringIO()):
            target = cut(editor, {'path': str(source), 'duration': 2, 'channels': 2,
                                  'identity': {'start': 0}}, ranges, folder)
        output = subprocess.run([ffmpeg, '-v', 'error', '-i', str(target), '-f', 'f32le', '-ac', '2',
                                 '-ar', str(rate), 'pipe:1'], check=True, capture_output=True).stdout
        decoded = np.frombuffer(output, dtype='<f4').reshape(-1, 2)
        self.assertLessEqual(abs(len(decoded)-round(sum(lengths)*rate)), 2)
        np.testing.assert_allclose(decoded[1000], [.2, -.1], atol=1e-6)
        for join in np.cumsum(lengths)[:-1]:
            position = round(join*rate)
            self.assertLess(float(np.max(np.abs(decoded[position-1:position+1]))), .002)
            np.testing.assert_allclose(decoded[position+500], [.2, -.1], atol=1e-6)
        # There is no crossfade overlap, which would shorten the output clock.
        self.assertAlmostEqual(len(decoded)/rate, sum(lengths), delta=2/rate)


if __name__ == '__main__':
    unittest.main()
