"""Generated PTS/track fixtures exercise the PCM clock used by ASR and audio."""
import json
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from media_audio import aligned_audio_args, audio_filter, audio_track, input_seek, probe_audio


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class TimelineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def media(self, name, audio_delay=0, video_delay=0, output_delay=0, gap=False, two_tracks=False):
        path = self.root / name
        cmd = ['ffmpeg', '-v', 'error', '-y', '-itsoffset', str(video_delay), '-f', 'lavfi',
               '-i', 'color=s=64x64:r=10:d=4', '-itsoffset', str(audio_delay), '-f', 'lavfi',
               '-i', 'sine=frequency=350:sample_rate=48000:d=4']
        if two_tracks:
            cmd += ['-f', 'lavfi', '-i', 'sine=frequency=880:sample_rate=48000:d=4']
        cmd += ['-map', '0:v:0', '-map', '1:a:0']
        if two_tracks:
            cmd += ['-map', '2:a:0', '-ac:a:1', '2']
        if gap:
            end=1.05 if gap == 'short' else 2
            cmd += ['-af', f"aselect='not(between(t,1,{end}))'"]
        cmd += ['-c:v', 'ffv1', '-c:a', 'pcm_f32le', '-output_ts_offset', str(output_delay), str(path)]
        subprocess.run(cmd, check=True, capture_output=True)
        return path

    def pcm(self, path, track=0, start=None, duration=4, rate=48000):
        args = aligned_audio_args('ffmpeg', path, 'pipe:1', track=track, start=start,
                                  duration=duration, rate=rate, ffprobe='ffprobe')
        raw = subprocess.run(args, capture_output=True, check=True).stdout
        return struct.unpack('<' + 'f' * (len(raw) // 4), raw)

    def sound_start(self, samples):
        return next((i / 48000 for i, v in enumerate(samples) if abs(v) > .01), None)

    def test_audio_late_start_and_nonzero_container_pts_are_video_relative(self):
        path = self.media('late.mkv', audio_delay=2, output_delay=5)
        info = probe_audio(path, 'ffprobe')
        self.assertEqual((info['video_start'], info['format_start']), (5, 5))
        self.assertEqual(info['duration'], 4)
        samples = self.pcm(path)
        self.assertEqual(len(samples), 4 * 48000)
        self.assertAlmostEqual(self.sound_start(samples), 2, delta=.002)
        event = self.pcm(path, start=1, duration=2)
        self.assertEqual(len(event), 2 * 48000)
        self.assertAlmostEqual(self.sound_start(event), 1, delta=.002)
        full=self.pcm(path,duration=None)
        self.assertEqual(len(full),4*48000) # audio continues beyond the video

    def test_audio_before_video_and_container_zero_are_removed_consistently(self):
        path = self.media('early.mkv', video_delay=1, output_delay=5)
        info = probe_audio(path, 'ffprobe')
        self.assertEqual((info['video_start'], info['format_start']), (6, 5))
        self.assertEqual(info['duration'], 4)
        self.assertEqual(input_seek(info, 2), 3)
        full = self.pcm(path, duration=4)
        event = self.pcm(path, start=0, duration=4)
        self.assertEqual(len(full), len(event))
        # Matroska packet timestamps have millisecond granularity when seeking.
        self.assertAlmostEqual(self.sound_start(full), 0, delta=.01)
        self.assertAlmostEqual(self.sound_start(event), 0, delta=.01)
        for samples in (full, event):
            crossings = sum(a <= 0 < b for a, b in zip(samples[48000:96000], samples[48001:96001]))
            self.assertAlmostEqual(crossings, 350, delta=2)
        self.assertTrue(all(abs(v) < .001 for v in full[-10000:]))

    def test_timestamp_gap_is_silence_and_keeps_later_sound_in_place(self):
        path = self.media('gap.mkv', gap=True)
        samples = self.pcm(path)
        quiet = samples[60000:85000]
        self.assertLess(max(abs(v) for v in quiet), .001)
        self.assertGreater(max(abs(v) for v in samples[110000:130000]), .05)

    def test_sub_100ms_packet_gap_is_not_collapsed_by_resampler_defaults(self):
        path=self.media('short-gap.mkv',gap='short')
        samples=self.pcm(path)
        self.assertLess(max(abs(v) for v in samples[49000:49800]), .001)
        self.assertGreater(max(abs(v) for v in samples[53000:54000]), .05)

    def test_selected_audio_ordinal_does_not_follow_ffmpeg_auto_selection(self):
        path = self.media('tracks.mkv', two_tracks=True)
        tracks = probe_audio(path, 'ffprobe')['audio_tracks']
        self.assertEqual([t['index'] for t in tracks], [0, 1])
        for ordinal, frequency in ((0, 350), (1, 880)):
            samples = self.pcm(path, track=ordinal, duration=1)
            crossings = sum(a <= 0 < b for a, b in zip(samples, samples[1:]))
            self.assertAlmostEqual(crossings, frequency, delta=2)
        with self.assertRaisesRegex(ValueError, '不存在'):
            self.pcm(path, track=2)

    def test_plain_zero_timestamp_float_audio_samples_are_unchanged(self):
        source = self.root / 'plain.wav'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                        'sine=frequency=350:sample_rate=48000:d=1', '-c:a', 'pcm_f32le', str(source)],
                       capture_output=True, check=True)
        old = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(source), '-map', '0:a:0',
                              '-vn', '-ac', '1', '-ar', '48000', '-f', 'f32le', 'pipe:1'],
                             capture_output=True, check=True).stdout
        new = subprocess.run(aligned_audio_args('ffmpeg', source, 'pipe:1', ffprobe='ffprobe'),
                             capture_output=True, check=True).stdout
        self.assertEqual(new, old)


class TrackTest(unittest.TestCase):
    def test_invalid_ordinals_are_not_silently_coerced(self):
        for value in (-1, True, 1.2, '1', None):
            with self.assertRaises(ValueError):
                audio_track(value)
        self.assertEqual(audio_track(1), 1)


if __name__ == '__main__':
    unittest.main()
