"""An event-only playback file. Final edits still render from the original source."""
import hashlib
import json
from pathlib import Path


def playback(runner, clip):
    """Resolve a playable interval without decoding, rendering, or queueing work."""
    duration = clip['end'] - clip['start']
    current = next((c for c in runner.task.get('clips', []) if c.get('id') == clip.get('id')
        and abs(c['start'] - clip['start']) < .001 and abs(c['end'] - clip['end']) < .001), None)
    def existing(value):
        if not value:
            return None
        path = Path(value)
        if path.is_file() and '.partial.' not in path.name and path.resolve() != Path(runner.task['video']).resolve():
            return {'path': str(path), 'start': 0, 'end': duration, 'kind': 'clip'}
    if current:
        ready = existing(current.get('preview'))
        if ready:
            return ready
        for record in reversed(runner.task.get('exports', [])):
            if record.get('mode') == 'separate' and record.get('clip_ids') == [current['id']] and abs(record.get('duration', 0) - duration) < .1:
                ready = existing(record.get('path'))
                if ready:
                    return ready
    source = Path(runner.task['video'])
    if not source.is_file():
        raise ValueError('原录播已移动，请重新定位素材。')
    ready = existing(location(runner, clip))
    if ready:
        return ready
    from engine import probe,tool_path
    from media_audio import probe_audio
    media=probe(source,runner.settings,runner.store)
    timeline=probe_audio(source,tool_path(runner.settings,'ffprobe'))
    default=next((track['index'] for track in media['audio_tracks'] if track['default']),0)
    selected=runner.task.get('audio_track',0)
    compatible=selected!=default or abs(timeline['video_start'])>.001 or abs(timeline['origin_shift'])>.001
    return {'path': str(source), 'start': clip['start'], 'end': clip['end'], 'kind': 'source',
            'audio_track':selected,'compatible_required':compatible}


def location(runner, clip):
    source = Path(runner.task['video'])
    if not source.is_file():
        raise ValueError('原录播已移动，请重新定位素材。')
    stat = source.stat()
    key = hashlib.sha256(json.dumps([str(source.resolve()), stat.st_size,
        stat.st_mtime_ns, clip['start'], clip['end'], runner.task.get('audio_track',0), 2]).encode('utf-8')).hexdigest()[:24]
    return runner.folder / 'previews' / f'event-{key}.mp4'


def prepare(runner, clip):
    path = location(runner, clip)
    if not path.is_file():
        runner.render_clip(clip, path, preview=True)
    return {'path': str(path), 'start': 0, 'end': clip['end'] - clip['start']}
