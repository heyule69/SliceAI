"""One video-relative clock and explicit audio-stream selection for FFmpeg.

FFmpeg's normal input clock starts at format.start_time. SliceAI's clock starts
at the first video stream's start_time (or the audio clock for a WAV). Keeping
packet timestamps until aresample lets it fill late audio and timestamp gaps.
"""
from __future__ import annotations
import json
import math
import subprocess
from pathlib import Path

TIMELINE_VERSION = 2


def audio_track(value=0):
    if type(value) is not int or value < 0:
        raise ValueError('音轨编号无效，请重新选择音轨。')
    return value


def _number(value, default=0):
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def video_duration(info):
    """Return the first video stream's span, excluding container PTS origin.

    Matroska's DURATION tag and format.duration describe an end timestamp;
    MPEG/MP4 stream.duration describes a span. Prefer stream metadata so a
    longer or delayed audio track never extends the editing/video timeline.
    """
    video = next((s for s in info.get('streams', []) if s.get('codec_type') == 'video'), None)
    if video:
        duration = _number(video.get('duration'))
        if duration > 0:
            return duration
        tag = video.get('tags', {}).get('DURATION')
        if tag:
            try:
                h, m, s = tag.split(':')
                end = int(h) * 3600 + int(m) * 60 + float(s)
                duration = end - _number(video.get('start_time'))
                if duration > 0 and math.isfinite(duration):
                    return duration
            except (AttributeError, TypeError, ValueError):
                pass
    fmt = info.get('format', {})
    duration = _number(fmt.get('duration'))
    if not video:
        return duration
    video_start = _number(video.get('start_time'), _number(fmt.get('start_time')))
    # FFmpeg Matroska metadata stores Segment Duration as the final PTS.
    if {'matroska', 'webm'}.intersection(str(fmt.get('format_name', '')).split(',')):
        return max(0, duration - video_start)
    return max(0, duration - (video_start - _number(fmt.get('start_time'))))


def probe_audio(source, ffprobe, run=None):
    args = [str(ffprobe), '-v', 'error', '-show_entries',
            'format=format_name,start_time,duration:stream=index,codec_type,start_time,duration,channels:stream_tags=title,language,DURATION',
            '-of', 'json', str(source)]
    if run:
        raw = run(args)
    else:
        from engine import CREATE_FLAGS
        proc = subprocess.run(args, capture_output=True, creationflags=CREATE_FLAGS, timeout=45)
        if proc.returncode:
            raise ValueError('无法读取音轨时间戳，请检查录播文件。')
        raw = proc.stdout.decode('utf-8', errors='strict')
    info = json.loads(raw)
    streams = info.get('streams', [])
    format_start = _number(info.get('format', {}).get('start_time'))
    video = next((s for s in streams if s.get('codec_type') == 'video'), None)
    video_start = _number(video.get('start_time'), format_start) if video else format_start
    tracks = []
    for stream in streams:
        if stream.get('codec_type') == 'audio':
            tags = stream.get('tags', {})
            tracks.append({'index': len(tracks), 'stream_index': stream.get('index'),
                           'start': _number(stream.get('start_time'), format_start),
                           'title': str(tags.get('title', '')), 'language': str(tags.get('language', '')),
                           'channels': stream.get('channels', 0)})
    return {'video_start': video_start, 'format_start': format_start,
            'origin_shift': video_start - format_start, 'audio_tracks': tracks,
            'duration': video_duration(info), 'has_video': video is not None}


def input_seek(info, start):
    """Input -ss is relative to the container start, not the video start."""
    position = float(start) + info['origin_shift']
    if not math.isfinite(position) or position < -.001:
        raise ValueError('录播起始时间戳无效。')
    return max(0, position)


def audio_filter(info, rate=48000, start=0, seek=None, duration=None):
    """Normalize to video/event zero, then fill leading silence and PTS gaps.

    Pass the actual input -ss as seek. Without input seeking this also drops
    audio preceding video zero. A duration pads a short audio tail to match
    video exactly; it does not move speech into deleted/empty time.
    """
    shift = info['origin_shift'] + float(start) - (float(seek) if seek is not None else 0)
    filters = []
    if abs(shift) > 1e-9:
        filters.append(f'asetpts=PTS-({shift:.9f})/TB')
    # The FFmpeg default hard-compensation threshold is 100 ms and would
    # collapse short dropped-packet gaps. One ms tolerates common container
    # timestamp rounding while preserving short, real interruptions.
    filters.append(f'aresample={int(rate)}:async=1:min_hard_comp=0.001:first_pts=0')
    if duration is not None:
        duration = float(duration)
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError('音频片段时长无效。')
        filters.extend((f'apad=whole_dur={duration:.9f}', f'atrim=duration={duration:.9f}'))
    return ','.join(filters)


def aligned_audio_args(ffmpeg, source, output, *, track=0, start=None, duration=None,
                       rate=48000, ffprobe=None, run=None, info=None, pcm='pcm_f32le'):
    track = audio_track(track)
    if info is None:
        ffprobe = ffprobe or str(Path(ffmpeg).with_name('ffprobe.exe' if Path(ffmpeg).suffix == '.exe' else 'ffprobe'))
        info = probe_audio(source, ffprobe, run)
    if track >= len(info['audio_tracks']):
        raise ValueError('所选音轨不存在，请重新选择音轨。')
    if duration is None and info.get('has_video') and info['duration'] > 0:
        duration = max(0, info['duration'] - (float(start) if start is not None else 0))
    args = [str(ffmpeg), '-hide_banner', '-v', 'error', '-nostdin', '-y']
    seek = input_seek(info, start) if start is not None else None
    if seek is not None:
        args += ['-ss', f'{seek:.9f}']
    args += ['-i', str(source), '-map', f'0:a:{track}', '-vn', '-ac', '1',
             '-af', audio_filter(info, rate, start or 0, seek, duration), '-ar', str(rate)]
    if str(output) == 'pipe:1':
        args += ['-f', 's16le' if pcm == 'pcm_s16le' else 'f32le', str(output)]
    else:
        args += ['-c:a', pcm, '-rf64', 'auto', str(output)]
    return args
