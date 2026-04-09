import os
import sys
import datetime
import time
import random
import traceback
from flask import Flask, request, jsonify
import requests as http_requests
import urllib.request
import urllib.parse
import re
import json

app = Flask(__name__)

# ─────────────────────────────────────────────────────────────
# Backend Instance Lists (ordered by reliability — best first)
# ─────────────────────────────────────────────────────────────

PIPED_INSTANCES = [
    "https://api.piped.private.coffee",   # Austria, 100% uptime, proven working
    "https://pipedapi.kavin.rocks",       # Official Piped
    "https://pipedapi.in.projectsegfau.lt",
]

INVIDIOUS_INSTANCES = [
    "https://inv.nadeko.net",
    "https://invidious.nerdvpn.de",
    "https://inv.thepixora.com",
    "https://yewtu.be",
]

# Timeout for each backend HTTP call (seconds)
BACKEND_TIMEOUT = 15

# ─────────────────────────────────────────────────────────────
# Utility helpers
# ─────────────────────────────────────────────────────────────

def parse_duration(duration_str):
    """Parse varied duration representations into integer seconds."""
    if not duration_str:
        return 0
    if isinstance(duration_str, (int, float)):
        return int(duration_str)
    parts = str(duration_str).split(':')
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    elif len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    elif len(parts) == 1:
        try:
            return int(parts[0])
        except ValueError:
            return 0
    return 0


def _quality_height(quality_str):
    """Extract numeric height from quality strings like '1080p', '720p', '4k'."""
    if not quality_str:
        return None
    if quality_str.lower() in ('best', 'worst'):
        return None
    if quality_str.lower() in ('4k', '2160p'):
        return 2160
    if quality_str.lower() in ('2k', '1440p'):
        return 1440
    m = re.match(r'(\d+)', str(quality_str))
    return int(m.group(1)) if m else None


def _calc_relevance_score(title, query, duration=0):
    """
    Score how relevant a video title is to the search query.
    Higher = more relevant to the user's intent.
    """
    title_lower = title.lower()
    query_lower = query.lower()
    query_words = query_lower.split()

    score = 0

    # Exact substring match of the entire query
    if query_lower in title_lower:
        score += 1000

    # Per-word matching
    matched_words = 0
    for word in query_words:
        if word in title_lower:
            matched_words += 1
            score += 100
    # Bonus for matching all/most words
    if query_words and matched_words == len(query_words):
        score += 500
    elif query_words and matched_words >= len(query_words) * 0.7:
        score += 200

    # Quality indicators — boost if query contains "4k" and title has it too
    quality_terms = ['4k', '2160p', '1080p', 'hd', 'uhd', '60fps', 'high quality']
    for qt in quality_terms:
        if qt in query_lower and qt in title_lower:
            score += 300

    # Penalty for very short titles (probably not the right video)
    if len(title) < 15:
        score -= 200

    # Penalty for non-video content markers
    penalty_terms = ['react', 'reaction', 'review', 'explained', 'podcast', 'tier list', 'ranking', 'dub', 'dubbed', '#shorts', 'shorts', '#animeshorts']
    for pt in penalty_terms:
        if pt in title_lower and pt not in query_lower:
            score -= 250

    # Strong penalty for very short videos (unless it's specifically searched)
    if duration > 0 and duration < 65 and 'short' not in query_lower:
        score -= 800
        
    return score


def select_best_stream(streams, media_type='video', quality='best', max_filesize_mb=None):
    """
    Unified format selector that works across Piped, Invidious, and yt-dlp
    format lists.

    Key improvement: correctly detects combined (audio+video) streams from
    Piped's videoOnly field, and strongly prefers high-bitrate combined streams.
    """
    if not streams:
        return None

    candidates = []
    for s in streams:
        url = s.get('url') or s.get('stream_url')
        if not url:
            continue

        # Filesize filter — but only hard-filter if content_length is known
        content_length = s.get('contentLength') or s.get('filesize') or s.get('filesize_approx') or s.get('clen')
        if content_length:
            try:
                content_length = int(content_length)
            except (ValueError, TypeError):
                content_length = None

        # Determine audio/video nature
        mime = s.get('mimeType') or s.get('type') or ''

        # CRITICAL FIX: Use videoOnly field directly from Piped/Invidious.
        # If videoOnly is explicitly False, it's a COMBINED stream with audio.
        # If videoOnly is True or missing, it's video-only.
        video_only = s.get('videoOnly', None)
        is_video = 'video' in mime or s.get('height') or s.get('qualityLabel') or s.get('resolution')
        is_audio_only = 'audio' in mime and not is_video

        # Detect combined streams:
        # 1. Piped: videoOnly=false means combined audio+video
        # 2. Invidious formatStreams: always combined (videoOnly not set but they have both)
        # 3. yt-dlp: check both vcodec and acodec
        if video_only is False:
            has_both = True  # Piped explicitly says it has audio
        elif video_only is True:
            has_both = False
        else:
            # Fallback: check mime and codec fields
            has_audio_indicator = 'audio' in mime or s.get('audioQuality') or s.get('audioSampleRate') or s.get('acodec', 'none') != 'none'
            has_video_indicator = is_video
            has_both = has_video_indicator and has_audio_indicator

        if media_type == 'video':
            if is_audio_only:
                continue
        elif media_type == 'audio':
            if not (is_audio_only or has_both):
                continue

        height = int(s.get('height') or 0)
        width = int(s.get('width') or 0)
        bitrate = int(s.get('bitrate') or 0)

        # Parse qualityLabel for height if height is 0
        if height == 0 and s.get('qualityLabel'):
            ql = s.get('qualityLabel', '')
            m = re.match(r'(\d+)p', ql)
            if m:
                height = int(m.group(1))

        candidates.append({
            'url': url,
            'height': height,
            'width': width,
            'bitrate': bitrate,
            'content_length': content_length,
            'has_both': has_both,
            'video_only': video_only is True,
            'ext': s.get('ext') or s.get('container') or _guess_ext(mime),
            'fps': s.get('fps'),
            'mime': mime,
            'quality_label': s.get('qualityLabel') or s.get('quality'),
            'audio_quality': s.get('audioQuality'),
            'raw': s,
        })

    if not candidates:
        return None

    target_h = _quality_height(quality)

    # Separate combined and video-only candidates
    combined = [c for c in candidates if c['has_both']]
    video_only_list = [c for c in candidates if not c['has_both'] and not ('audio' in (c.get('mime') or ''))]

    def _score(c, filesize_limit=None):
        score = 0

        # === Tier 1: Strongly prefer combined audio+video ===
        # If the stream is silent (no audio), it requires muxing via ffmpeg. n8n pipelines need a fully playable URL.
        if c['has_both']:
            score += 50000

        # === Tier 2: Resolution matching ===
        if media_type == 'video':
            if quality == 'best':
                score += c['height'] * 10
            elif quality == 'worst':
                score -= c['height'] * 10
            elif target_h:
                # Prefer streams at or above target, penalize those below more
                diff = c['height'] - target_h
                if diff >= 0:
                    # At or above target: small penalty for being too high
                    score -= diff * 2
                    score += 5000  # bonus for meeting target
                else:
                    # Below target: heavy penalty
                    score += diff * 15
        else:
            score += c['height'] * 10

        # === Tier 3: Bitrate (quality indicator) ===
        if c['bitrate'] > 0:
            score += min(c['bitrate'] // 1000, 5000)  # cap bitrate bonus

        # === Tier 4: Prefer higher content length (= higher quality encoding) ===
        if c['content_length'] and c['content_length'] > 0:
            # Normalize: 100MB = 500 points, 50MB = 250 points
            score += min(c['content_length'] // (200 * 1024), 2000)

        # === Tier 5: Format preference ===
        if c['ext'] in ('mp4', 'm4a'):
            score += 500
        elif c['ext'] in ('webm',):
            score += 100

        # === Tier 6: FPS bonus ===
        if c.get('fps') and c['fps'] >= 60:
            score += 200

        # === Filesize filter (soft) ===
        if filesize_limit and c['content_length']:
            if c['content_length'] > filesize_limit * 1024 * 1024:
                score -= 20000  # Heavy penalty but don't exclude

        return score

    # Score all candidates
    for c in candidates:
        c['_score'] = _score(c, filesize_limit=max_filesize_mb)

    candidates.sort(key=lambda c: c['_score'], reverse=True)

    best = candidates[0]
    print(f"[StreamSelect] Best: {best['height']}p, combined={best['has_both']}, "
          f"ext={best['ext']}, bitrate={best['bitrate']}, "
          f"size={best['content_length']}, score={best['_score']}", flush=True)

    return best


def _guess_ext(mime):
    if 'mp4' in mime:
        return 'mp4'
    if 'webm' in mime:
        return 'webm'
    if 'm4a' in mime:
        return 'm4a'
    if 'opus' in mime:
        return 'opus'
    return 'mp4'


def _build_result(title, video_id, stream, duration_secs, thumbnail, channel, upload_date, view_count, backend_name):
    """Build the unified result dict returned to the caller."""
    stream_url = stream['url'] if stream else None
    resolution = f"{stream['width']}x{stream['height']}" if stream and stream.get('width') and stream.get('height') else None
    filesize_bytes = stream.get('content_length') if stream else None
    filesize_mb = round(filesize_bytes / (1024 * 1024), 2) if filesize_bytes else None
    duration_formatted = str(datetime.timedelta(seconds=duration_secs)) if duration_secs else None

    return {
        "title": title,
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "stream_url": stream_url,
        "duration": duration_secs,
        "duration_formatted": duration_formatted,
        "length": duration_formatted,
        "length_seconds": duration_secs,
        "filesize_mb": filesize_mb,
        "format": stream.get('ext', 'mp4') if stream else None,
        "resolution": resolution,
        "fps": stream.get('fps') if stream else None,
        "vcodec": None,
        "acodec": None,
        "thumbnail": thumbnail,
        "channel": channel,
        "upload_date": upload_date,
        "view_count": view_count,
        "backend_used": backend_name,
        "has_audio": stream.get('has_both', False) if stream else False,
    }


# ─────────────────────────────────────────────────────────────
# Backend 1: Piped API
# ─────────────────────────────────────────────────────────────

class PipedBackend:
    name = "piped"

    @staticmethod
    def _get_instances():
        """Return instances in order (best first) — no random shuffle."""
        return list(PIPED_INSTANCES)

    @staticmethod
    def search(query, max_results=5, **kwargs):
        """Search via Piped. Returns list of search result dicts."""
        for base in PipedBackend._get_instances():
            try:
                url = f"{base}/search?q={urllib.parse.quote(query)}&filter=videos"
                print(f"[Piped] Searching: {url}", flush=True)
                r = http_requests.get(url, timeout=BACKEND_TIMEOUT)
                if r.status_code != 200:
                    print(f"[Piped] {base} returned {r.status_code}", flush=True)
                    continue
                data = r.json()
                items = data.get('items') or data.get('results') or []
                results = []
                # Get many more results than requested for better relevance ranking
                for item in items[:max(20, max_results * 5)]:
                    vid_url = item.get('url', '')
                    vid = vid_url.replace('/watch?v=', '') if '/watch?v=' in vid_url else ''
                    if not vid or len(vid) != 11:
                        continue
                    results.append({
                        'videoId': vid,
                        'title': item.get('title', ''),
                        'duration': item.get('duration', 0),
                        'thumbnail': item.get('thumbnail', ''),
                        'channel': item.get('uploaderName') or item.get('uploader', ''),
                        'views': item.get('views', 0),
                    })
                if results:
                    print(f"[Piped] Found {len(results)} raw results from {base}", flush=True)
                    return results
            except Exception as e:
                print(f"[Piped] {base} error: {e}", flush=True)
                continue
        return []

    @staticmethod
    def get_streams(video_id):
        """Get stream URLs from Piped for a video ID."""
        for base in PipedBackend._get_instances():
            try:
                url = f"{base}/streams/{video_id}"
                print(f"[Piped] Getting streams: {url}", flush=True)
                r = http_requests.get(url, timeout=BACKEND_TIMEOUT)
                if r.status_code != 200:
                    print(f"[Piped] {base} streams returned {r.status_code}", flush=True)
                    continue
                data = r.json()
                if data.get('error'):
                    print(f"[Piped] {base} stream error: {data['error']}", flush=True)
                    continue

                all_streams = []

                # Video streams — Piped provides videoOnly boolean
                for s in data.get('videoStreams', []):
                    s['mimeType'] = s.get('mimeType') or s.get('type') or 'video/mp4'
                    # CRITICAL: Preserve Piped's videoOnly field exactly as-is
                    # videoOnly=false means this stream has BOTH audio and video
                    if 'videoOnly' not in s:
                        s['videoOnly'] = True  # safe default
                    all_streams.append(s)

                # Audio streams
                for s in data.get('audioStreams', []):
                    s['mimeType'] = s.get('mimeType') or s.get('type') or 'audio/mp4'
                    s['videoOnly'] = False
                    all_streams.append(s)

                meta = {
                    'title': data.get('title', ''),
                    'duration': data.get('duration', 0),
                    'thumbnail': data.get('thumbnailUrl', ''),
                    'channel': data.get('uploader', ''),
                    'upload_date': data.get('uploadDate', ''),
                    'views': data.get('views', 0),
                    'hls': data.get('hls'),
                }

                # Log stream breakdown
                combined_count = sum(1 for s in all_streams if s.get('videoOnly') == False and 'video' in (s.get('mimeType') or ''))
                video_only_count = sum(1 for s in all_streams if s.get('videoOnly') == True)
                audio_count = sum(1 for s in all_streams if 'audio' in (s.get('mimeType') or ''))
                print(f"[Piped] Got {len(all_streams)} streams from {base} "
                      f"(combined={combined_count}, video-only={video_only_count}, audio={audio_count})", flush=True)

                if all_streams:
                    return all_streams, meta

                # HLS fallback
                if data.get('hls'):
                    print(f"[Piped] Using HLS from {base}", flush=True)
                    return [{'url': data['hls'], 'mimeType': 'video/mp4', 'height': 720,
                             'width': 1280, 'bitrate': 0, 'videoOnly': False}], meta

            except Exception as e:
                print(f"[Piped] {base} stream error: {e}", flush=True)
                continue
        return [], {}


# ─────────────────────────────────────────────────────────────
# Backend 2: Invidious API
# ─────────────────────────────────────────────────────────────

class InvidiousBackend:
    name = "invidious"

    @staticmethod
    def _get_instances():
        return list(INVIDIOUS_INSTANCES)

    @staticmethod
    def search(query, max_results=5, **kwargs):
        """Search via Invidious API."""
        for base in InvidiousBackend._get_instances():
            try:
                url = f"{base}/api/v1/search?q={urllib.parse.quote(query)}&type=video&sort_by=relevance"
                print(f"[Invidious] Searching: {url}", flush=True)
                r = http_requests.get(url, timeout=BACKEND_TIMEOUT)
                if r.status_code != 200:
                    print(f"[Invidious] {base} returned {r.status_code}", flush=True)
                    continue
                data = r.json()
                if not isinstance(data, list):
                    continue
                results = []
                for item in data[:max(20, max_results * 5)]:
                    if item.get('type') != 'video':
                        continue
                    thumbs = item.get('videoThumbnails', [])
                    thumb_url = ''
                    for t in thumbs:
                        if t.get('quality') == 'maxresdefault':
                            thumb_url = t.get('url', '')
                            break
                    if not thumb_url and thumbs:
                        thumb_url = thumbs[0].get('url', '')

                    results.append({
                        'videoId': item.get('videoId', ''),
                        'title': item.get('title', ''),
                        'duration': item.get('lengthSeconds', 0),
                        'thumbnail': thumb_url,
                        'channel': item.get('author', ''),
                        'views': item.get('viewCount', 0),
                    })
                if results:
                    print(f"[Invidious] Found {len(results)} results from {base}", flush=True)
                    return results
            except Exception as e:
                print(f"[Invidious] {base} error: {e}", flush=True)
                continue
        return []

    @staticmethod
    def get_streams(video_id):
        """Get stream URLs from Invidious for a video ID."""
        for base in InvidiousBackend._get_instances():
            try:
                url = f"{base}/api/v1/videos/{video_id}"
                print(f"[Invidious] Getting streams: {url}", flush=True)
                r = http_requests.get(url, timeout=BACKEND_TIMEOUT)
                if r.status_code != 200:
                    print(f"[Invidious] {base} video returned {r.status_code}", flush=True)
                    continue
                data = r.json()
                if data.get('error'):
                    print(f"[Invidious] {base} video error: {data['error']}", flush=True)
                    continue

                all_streams = []

                # formatStreams = COMBINED audio+video (always preferred)
                for s in data.get('formatStreams', []):
                    stream = {
                        'url': s.get('url', ''),
                        'mimeType': s.get('type', ''),
                        'height': _extract_height(s),
                        'width': _extract_width(s),
                        'bitrate': int(s.get('bitrate', '0').replace(',', '')) if s.get('bitrate') else 0,
                        'container': s.get('container', 'mp4'),
                        'qualityLabel': s.get('qualityLabel', ''),
                        'videoOnly': False,  # formatStreams are always combined
                        'fps': s.get('fps'),
                    }
                    all_streams.append(stream)

                # adaptiveFormats = separate audio and video
                for s in data.get('adaptiveFormats', []):
                    mime = s.get('type', '')
                    stream = {
                        'url': s.get('url', ''),
                        'mimeType': mime,
                        'height': _extract_height(s),
                        'width': _extract_width(s),
                        'bitrate': int(s.get('bitrate', '0').replace(',', '')) if s.get('bitrate') else 0,
                        'contentLength': s.get('clen'),
                        'container': s.get('container', ''),
                        'qualityLabel': s.get('qualityLabel', ''),
                        'audioQuality': s.get('audioQuality', ''),
                        'audioSampleRate': s.get('audioSampleRate', ''),
                        'videoOnly': 'video' in mime and 'audio' not in mime,
                        'fps': s.get('fps'),
                    }
                    all_streams.append(stream)

                meta = {
                    'title': data.get('title', ''),
                    'duration': data.get('lengthSeconds', 0),
                    'thumbnail': '',
                    'channel': data.get('author', ''),
                    'upload_date': data.get('publishedText', ''),
                    'views': data.get('viewCount', 0),
                    'hls': data.get('hlsUrl'),
                }
                thumbs = data.get('videoThumbnails', [])
                for t in thumbs:
                    if t.get('quality') == 'maxresdefault':
                        meta['thumbnail'] = t.get('url', '')
                        break
                if not meta['thumbnail'] and thumbs:
                    meta['thumbnail'] = thumbs[0].get('url', '')

                if all_streams:
                    print(f"[Invidious] Got {len(all_streams)} streams from {base}", flush=True)
                    return all_streams, meta

                if data.get('hlsUrl'):
                    return [{'url': data['hlsUrl'], 'mimeType': 'video/mp4', 'height': 720,
                             'width': 1280, 'bitrate': 0, 'videoOnly': False}], meta

            except Exception as e:
                print(f"[Invidious] {base} stream error: {e}", flush=True)
                continue
        return [], {}


def _extract_height(s):
    if s.get('height'):
        return int(s['height'])
    res = s.get('resolution') or s.get('size') or ''
    m = re.search(r'(\d+)x(\d+)', res)
    if m:
        return int(m.group(2))
    ql = s.get('qualityLabel', '')
    m2 = re.match(r'(\d+)p', ql)
    if m2:
        return int(m2.group(1))
    return 0


def _extract_width(s):
    if s.get('width'):
        return int(s['width'])
    res = s.get('resolution') or s.get('size') or ''
    m = re.search(r'(\d+)x(\d+)', res)
    if m:
        return int(m.group(1))
    return 0


# ─────────────────────────────────────────────────────────────
# Backend 3: Direct YouTube Innertube API
# ─────────────────────────────────────────────────────────────

class InnertubeBackend:
    """
    Direct YouTube innertube API client — no third-party proxy needed.
    Calls YouTube's /youtubei/v1/player endpoint with various client
    configurations to get stream URLs. This is the same API that
    Piped, Invidious, and yt-dlp use internally.
    """
    name = "innertube"

    # Client configurations ordered by reliability (2025-2026)
    CLIENTS = [
        {
            "name": "ANDROID_VR",
            "payload": {
                "context": {
                    "client": {
                        "clientName": "ANDROID_VR",
                        "clientVersion": "1.57.29",
                        "androidSdkVersion": 30,
                        "hl": "en",
                        "gl": "US",
                    }
                },
            },
            "headers": {
                "Content-Type": "application/json",
                "User-Agent": "com.google.android.apps.youtube.vr.oculus/1.57.29 (Linux; U; Android 12L; eureka-user Build/SQ3A.220605.009.A1) gzip",
            },
        },
        {
            "name": "ANDROID_TESTSUITE",
            "payload": {
                "context": {
                    "client": {
                        "clientName": "ANDROID_TESTSUITE",
                        "clientVersion": "1.9",
                        "androidSdkVersion": 30,
                        "hl": "en",
                        "gl": "US",
                        "platform": "MOBILE",
                    }
                },
            },
            "headers": {
                "Content-Type": "application/json",
                "User-Agent": "com.google.android.youtube/19.09.37 (Linux; U; Android 11) gzip",
                "X-YouTube-Client-Name": "30",
                "X-YouTube-Client-Version": "1.9",
            },
        },
        {
            "name": "MWEB",
            "payload": {
                "context": {
                    "client": {
                        "clientName": "MWEB",
                        "clientVersion": "2.20240304.08.00",
                        "hl": "en",
                        "gl": "US",
                    }
                },
            },
            "headers": {
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
                "Referer": "https://m.youtube.com/",
                "Origin": "https://m.youtube.com",
            },
        },
    ]

    INNERTUBE_API_KEY = "AIzaSyA8eiZmM1FaDVjRy-df2KTyQ_vz_yYM39w"

    @staticmethod
    def get_streams(video_id):
        """Get stream URLs directly from YouTube's innertube player API."""
        for client_cfg in InnertubeBackend.CLIENTS:
            client_name = client_cfg["name"]
            try:
                url = f"https://www.youtube.com/youtubei/v1/player?key={InnertubeBackend.INNERTUBE_API_KEY}"
                payload = dict(client_cfg["payload"])
                payload["videoId"] = video_id
                payload["playbackContext"] = {
                    "contentPlaybackContext": {
                        "html5Preference": "HTML5_PREF_WANTS",
                    }
                }
                payload["contentCheckOk"] = True
                payload["racyCheckOk"] = True

                headers = dict(client_cfg["headers"])
                print(f"[Innertube] Trying {client_name} for {video_id}", flush=True)

                r = http_requests.post(url, json=payload, headers=headers, timeout=15)
                if r.status_code != 200:
                    print(f"[Innertube] {client_name} returned HTTP {r.status_code}", flush=True)
                    continue

                data = r.json()
                playability = data.get("playabilityStatus", {})
                status = playability.get("status", "")

                if status != "OK":
                    reason = playability.get("reason", playability.get("messages", ["unknown"]))
                    print(f"[Innertube] {client_name} playability: {status} - {reason}", flush=True)
                    continue

                streaming_data = data.get("streamingData", {})
                all_streams = []

                # "formats" = combined audio+video (lower quality, usually 360p/720p)
                for f in streaming_data.get("formats", []):
                    stream_url = f.get("url")
                    # Skip streams that need signature decryption
                    if not stream_url and f.get("signatureCipher"):
                        continue
                    if not stream_url:
                        continue
                    all_streams.append({
                        "url": stream_url,
                        "mimeType": f.get("mimeType", "video/mp4"),
                        "height": f.get("height", 0),
                        "width": f.get("width", 0),
                        "bitrate": f.get("bitrate", 0),
                        "contentLength": f.get("contentLength"),
                        "qualityLabel": f.get("qualityLabel", ""),
                        "videoOnly": False,  # "formats" always have audio+video
                        "fps": f.get("fps"),
                    })

                # "adaptiveFormats" = separate audio and video (high quality)
                for f in streaming_data.get("adaptiveFormats", []):
                    stream_url = f.get("url")
                    if not stream_url and f.get("signatureCipher"):
                        continue
                    if not stream_url:
                        continue
                    mime = f.get("mimeType", "")
                    is_video = "video" in mime
                    has_audio_quality = bool(f.get("audioQuality"))
                    all_streams.append({
                        "url": stream_url,
                        "mimeType": mime,
                        "height": f.get("height", 0),
                        "width": f.get("width", 0),
                        "bitrate": f.get("bitrate", 0),
                        "contentLength": f.get("contentLength"),
                        "qualityLabel": f.get("qualityLabel", ""),
                        "videoOnly": is_video and not has_audio_quality,
                        "audioQuality": f.get("audioQuality", ""),
                        "fps": f.get("fps"),
                    })

                video_details = data.get("videoDetails", {})
                thumbs = video_details.get("thumbnail", {}).get("thumbnails", [])
                thumb_url = thumbs[-1].get("url", "") if thumbs else ""

                meta = {
                    "title": video_details.get("title", ""),
                    "duration": int(video_details.get("lengthSeconds", 0)),
                    "thumbnail": thumb_url,
                    "channel": video_details.get("author", ""),
                    "upload_date": "",
                    "views": int(video_details.get("viewCount", 0)),
                }

                if all_streams:
                    combined = sum(1 for s in all_streams if not s.get("videoOnly", True) and "video" in s.get("mimeType", ""))
                    video_only = sum(1 for s in all_streams if s.get("videoOnly"))
                    audio_only = sum(1 for s in all_streams if "audio" in s.get("mimeType", "") and not s.get("height"))
                    print(f"[Innertube] {client_name} got {len(all_streams)} streams "
                          f"(combined={combined}, video-only={video_only}, audio={audio_only})", flush=True)
                    return all_streams, meta
                else:
                    # Check if we got an HLS manifest
                    hls = streaming_data.get("hlsManifestUrl")
                    if hls:
                        print(f"[Innertube] {client_name} using HLS manifest", flush=True)
                        return [{"url": hls, "mimeType": "video/mp4", "height": 720,
                                 "width": 1280, "bitrate": 0, "videoOnly": False}], meta
                    print(f"[Innertube] {client_name} got response but no usable stream URLs "
                          f"(may need signature decryption)", flush=True)

            except Exception as e:
                print(f"[Innertube] {client_name} error: {e}", flush=True)
                continue

        return [], {}


# ─────────────────────────────────────────────────────────────
# Backend 4: yt-dlp fallback (last resort)
# ─────────────────────────────────────────────────────────────

class YtDlpBackend:
    name = "yt-dlp"

    @staticmethod
    def search_and_extract(query, max_results=1, is_direct_url=False, **kwargs):
        """Fallback: use yt-dlp to search + extract."""
        try:
            import yt_dlp
        except ImportError:
            print("[yt-dlp] Not installed, skipping fallback", flush=True)
            return []

        media_type = kwargs.get('type', 'video')
        quality = kwargs.get('quality', 'best')
        max_filesize_mb = kwargs.get('max_filesize_mb')
        duration_min = kwargs.get('duration_min')
        duration_max = kwargs.get('duration_max')

        ydl_opts = {
            # Since download=False, we CANNOT use `+` (e.g. bestvideo+bestaudio) because it requires ffmpeg merging and returns no single URL.
            # Try to grab the best combined mp4. If none exists (or it's low quality), grab the best 1080p video-only, or anything.
            'format': 'best[ext=mp4]/bestvideo[ext=mp4][height<=1080]/best',
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'nocheckcertificate': True,
            'geo_bypass': True,
            'socket_timeout': 15,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            },
        }

        cookie_paths = ['/etc/secrets/cookies.txt', '/tmp/yt_cookies.txt', os.path.join(os.getcwd(), 'cookies.txt')]
        for cp in cookie_paths:
            if os.path.exists(cp):
                ydl_opts['cookiefile'] = cp
                print(f"[yt-dlp] Using cookies from {cp}", flush=True)
                break

        results = []
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                if is_direct_url:
                    urls = [query]
                else:
                    urls = [f"ytsearch{max_results * 3}:{query}"]

                for search_url in urls:
                    try:
                        info = ydl.extract_info(search_url, download=False)
                    except Exception as e:
                        print(f"[yt-dlp] Extraction failed: {e}", flush=True)
                        continue

                    entries = info.get('entries', [info]) if info else []
                    for video in entries:
                        if not video:
                            continue
                        if video.get('is_live') or video.get('live_status') == 'is_live':
                            continue

                        dur = parse_duration(video.get('duration'))
                        if duration_min and dur < duration_min:
                            continue
                        if duration_max and dur > duration_max:
                            continue

                        stream_url = video.get('url')
                        formats = video.get('formats', [])

                        if formats:
                            best = select_best_stream(
                                [{'url': f.get('url'), 'height': f.get('height', 0),
                                  'width': f.get('width', 0),
                                  'bitrate': f.get('tbr', 0) * 1000 if f.get('tbr') else 0,
                                  'mimeType': f.get('ext', 'mp4'),
                                  'videoOnly': f.get('vcodec', 'none') != 'none' and f.get('acodec', 'none') == 'none',
                                  'ext': f.get('ext', 'mp4'),
                                  'fps': f.get('fps'),
                                  'contentLength': f.get('filesize') or f.get('filesize_approx'),
                                  } for f in formats if f.get('url')],
                                media_type=media_type,
                                quality=quality,
                                max_filesize_mb=max_filesize_mb,
                            )
                            if best:
                                stream_url = best['url']

                        if not stream_url:
                            continue

                        result = _build_result(
                            title=video.get('title', ''),
                            video_id=video.get('id', ''),
                            stream={
                                'url': stream_url,
                                'height': video.get('height', 0),
                                'width': video.get('width', 0),
                                'ext': video.get('ext', 'mp4'),
                                'fps': video.get('fps'),
                                'content_length': video.get('filesize') or video.get('filesize_approx'),
                                'has_both': True,
                            },
                            duration_secs=dur,
                            thumbnail=video.get('thumbnail', ''),
                            channel=video.get('uploader', ''),
                            upload_date=video.get('upload_date', ''),
                            view_count=video.get('view_count'),
                            backend_name='yt-dlp',
                        )
                        results.append(result)
                        if len(results) >= max_results:
                            return results
        except Exception as e:
            print(f"[yt-dlp] Fatal error: {e}", flush=True)
            traceback.print_exc()
        return results


# ─────────────────────────────────────────────────────────────
# YouTube HTML search scraper (backup search method)
# ─────────────────────────────────────────────────────────────

def fetch_urls_from_html(query, count):
    """Scrape YouTube search page directly to get video IDs — bypasses API limits."""
    print(f"[HTMLScraper] Searching YouTube HTML for: {query}", flush=True)
    search_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}&sp=EgIQAQ%253D%253D"
    req = urllib.request.Request(
        search_url,
        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'}
    )
    try:
        html = urllib.request.urlopen(req, timeout=10).read().decode('utf-8')

        # Extract video data from ytInitialData JSON
        video_data = []
        video_ids_seen = set()

        # Method 1: Extract from ytInitialData
        match = re.search(r'var ytInitialData = ({.*?});</script>', html)
        if match:
            try:
                yt_data = json.loads(match.group(1))
                contents = (yt_data.get('contents', {})
                           .get('twoColumnSearchResultsRenderer', {})
                           .get('primaryContents', {})
                           .get('sectionListRenderer', {})
                           .get('contents', []))
                for section in contents:
                    items = (section.get('itemSectionRenderer', {})
                            .get('contents', []))
                    for item in items:
                        vr = item.get('videoRenderer', {})
                        vid = vr.get('videoId')
                        if vid and vid not in video_ids_seen:
                            video_ids_seen.add(vid)
                            title = ''
                            runs = vr.get('title', {}).get('runs', [])
                            if runs:
                                title = runs[0].get('text', '')
                            dur_text = vr.get('lengthText', {}).get('simpleText', '0:00')
                            video_data.append({
                                'videoId': vid,
                                'title': title,
                                'duration': parse_duration(dur_text),
                                'thumbnail': f'https://i.ytimg.com/vi/{vid}/hqdefault.jpg',
                                'channel': vr.get('ownerText', {}).get('runs', [{}])[0].get('text', '') if vr.get('ownerText') else '',
                                'views': 0,
                            })
            except (json.JSONDecodeError, KeyError) as e:
                print(f"[HTMLScraper] JSON parse error: {e}", flush=True)

        # Method 2: Fallback regex extraction
        if not video_data:
            raw_ids = re.findall(r'"videoId":"([^"]{11})"', html)
            for vid in raw_ids:
                if vid not in video_ids_seen:
                    video_ids_seen.add(vid)
                    video_data.append({
                        'videoId': vid,
                        'title': '',
                        'duration': 0,
                        'thumbnail': f'https://i.ytimg.com/vi/{vid}/hqdefault.jpg',
                        'channel': '',
                        'views': 0,
                    })

        print(f"[HTMLScraper] Found {len(video_data)} videos", flush=True)
        return video_data[:count]
    except Exception as e:
        print(f"[HTMLScraper] Failed: {e}", flush=True)
        return []


# ─────────────────────────────────────────────────────────────
# Orchestrator: cascading multi-backend search
# ─────────────────────────────────────────────────────────────

def perform_search_multi(query, is_direct_url=False, **kwargs):
    """
    Try backends in order: Piped → Invidious → HTML scraper → yt-dlp.
    Ranks results by relevance to query before extracting streams.
    Returns (results_list, error_string_or_None).
    """
    max_results = kwargs.get('max_results', 1)
    media_type = kwargs.get('type', 'video')
    quality = kwargs.get('quality', 'best')
    max_filesize_mb = kwargs.get('max_filesize_mb')
    duration_min = kwargs.get('duration_min')
    duration_max = kwargs.get('duration_max')

    # For direct URLs, extract video ID and go straight to stream extraction
    if is_direct_url:
        video_id = _extract_video_id(query)
        if video_id:
            result = _fetch_single_video(video_id, media_type, quality, max_filesize_mb)
            if result:
                return [result], None
        results = YtDlpBackend.search_and_extract(query, max_results=1, is_direct_url=True, **kwargs)
        if results:
            return results, None
        return [], "Could not extract video from URL"

    # ── Phase 1: Search for video IDs (try multiple sources) ──
    search_results = []
    search_backend = None

    # Try HTML scraper FIRST (gets real, highly relevant YouTube results!)
    search_results = fetch_urls_from_html(query, max_results * 5)
    if search_results:
        search_backend = 'html_scraper'

    # Try Piped search if HTML scraping fails
    if not search_results:
        search_results = PipedBackend.search(query, max_results=max_results)
        if search_results:
            search_backend = 'piped'

    # Try Invidious search
    if not search_results:
        search_results = InvidiousBackend.search(query, max_results=max_results)
        if search_results:
            search_backend = 'invidious'

    # Last resort: yt-dlp
    if not search_results:
        print("[Orchestrator] All searches failed, trying yt-dlp fallback...", flush=True)
        results = YtDlpBackend.search_and_extract(query, max_results=max_results, is_direct_url=False, **kwargs)
        if results:
            return results, None
        return [], "All backends failed to find results"

    print(f"[Orchestrator] Search phase done via {search_backend}: {len(search_results)} candidates", flush=True)

    # ── Phase 2: Rank by relevance to query ──
    for sr in search_results:
        dur = parse_duration(sr.get('duration', 0))
        sr['_relevance'] = _calc_relevance_score(sr.get('title', ''), query, dur)
        # Bonus for higher view count (popular = usually higher quality)
        views = sr.get('views', 0)
        if views > 1000000:
            sr['_relevance'] += 200
        elif views > 100000:
            sr['_relevance'] += 100
        elif views > 10000:
            sr['_relevance'] += 50

    search_results.sort(key=lambda x: x['_relevance'], reverse=True)

    print(f"[Orchestrator] Top candidates after relevance ranking:", flush=True)
    for i, sr in enumerate(search_results[:5]):
        print(f"  #{i+1}: [{sr['_relevance']}] {sr.get('title', 'N/A')[:60]} (id={sr['videoId']}, dur={sr.get('duration', '?')}s)", flush=True)

    # ── Phase 3: Filter by duration ──
    filtered = []
    for sr in search_results:
        dur = parse_duration(sr.get('duration', 0))
        if duration_min and dur > 0 and dur < duration_min:
            continue
        if duration_max and dur > 0 and dur > duration_max:
            continue
        # Allow duration=0 through (HTML scraper might not know duration)
        filtered.append(sr)

    if not filtered and search_results:
        filtered = list(search_results)  # relax all filters

    # ── Phase 4: Get stream URLs for top candidates ──
    final_results = []
    # Try more candidates to find good quality streams
    candidates_to_try = min(len(filtered), max(max_results * 3, 5))

    for sr in filtered[:candidates_to_try]:
        if len(final_results) >= max_results:
            break

        video_id = sr['videoId']
        result = _fetch_single_video(
            video_id, media_type, quality, max_filesize_mb,
            fallback_meta=sr
        )
        if result:
            # Only accept results with valid stream URLs
            if result.get('stream_url'):
                final_results.append(result)
                print(f"[Orchestrator] Accepted: {result['title'][:50]} "
                      f"res={result['resolution']} has_audio={result.get('has_audio')}", flush=True)

    if final_results:
        return final_results, None

    # Absolute last resort
    print("[Orchestrator] Stream extraction failed for all, trying yt-dlp...", flush=True)
    results = YtDlpBackend.search_and_extract(query, max_results=max_results, is_direct_url=False, **kwargs)
    if results:
        return results, None

    return [], "Found videos but could not extract stream URLs from any backend"


def _fetch_single_video(video_id, media_type, quality, max_filesize_mb, fallback_meta=None):
    """
    Fetch stream URL for a single video ID.
    Tries backends in order: Piped → Innertube → Invidious → yt-dlp (per-video).
    """
    streams = []
    meta = {}
    backend_name = None

    # 1. Try Piped (fast proxy, works when their backend is healthy)
    streams, meta = PipedBackend.get_streams(video_id)
    if streams:
        backend_name = 'piped'

    # 2. Try Innertube (direct YouTube API — no third-party dependency)
    if not streams:
        streams, meta = InnertubeBackend.get_streams(video_id)
        if streams:
            backend_name = 'innertube'

    # 3. Try Invidious
    if not streams:
        streams, meta = InvidiousBackend.get_streams(video_id)
        if streams:
            backend_name = 'invidious'

    # 4. Try yt-dlp for this specific video ID
    if not streams:
        print(f"[Orchestrator] All proxy backends failed for {video_id}, trying yt-dlp...", flush=True)
        try:
            import yt_dlp
            ydl_opts = {
                'format': 'best[ext=mp4]/bestvideo[ext=mp4][height<=1080]/best',
                'noplaylist': True,
                'quiet': True,
                'no_warnings': True,
                'nocheckcertificate': True,
                'geo_bypass': True,
                'socket_timeout': 15,
            }
            cookie_paths = ['/etc/secrets/cookies.txt', '/tmp/yt_cookies.txt', os.path.join(os.getcwd(), 'cookies.txt')]
            for cp in cookie_paths:
                if os.path.exists(cp):
                    ydl_opts['cookiefile'] = cp
                    break

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
                if info:
                    stream_url = info.get('url')
                    formats = info.get('formats', [])
                    if formats and not stream_url:
                        best = select_best_stream(
                            [{'url': f.get('url'), 'height': f.get('height', 0),
                              'width': f.get('width', 0),
                              'bitrate': (f.get('tbr') or 0) * 1000,
                              'mimeType': f.get('ext', 'mp4'),
                              'videoOnly': f.get('vcodec', 'none') != 'none' and f.get('acodec', 'none') == 'none',
                              'ext': f.get('ext', 'mp4'),
                              'fps': f.get('fps'),
                              'contentLength': f.get('filesize') or f.get('filesize_approx'),
                              } for f in formats if f.get('url')],
                            media_type=media_type, quality=quality, max_filesize_mb=max_filesize_mb,
                        )
                        if best:
                            stream_url = best['url']

                    if stream_url:
                        fm = fallback_meta or {}
                        return _build_result(
                            title=info.get('title', fm.get('title', '')),
                            video_id=video_id,
                            stream={
                                'url': stream_url,
                                'height': info.get('height', 0),
                                'width': info.get('width', 0),
                                'ext': info.get('ext', 'mp4'),
                                'fps': info.get('fps'),
                                'content_length': info.get('filesize') or info.get('filesize_approx'),
                                'has_both': True,
                            },
                            duration_secs=parse_duration(info.get('duration')),
                            thumbnail=info.get('thumbnail', ''),
                            channel=info.get('uploader', ''),
                            upload_date=info.get('upload_date', ''),
                            view_count=info.get('view_count'),
                            backend_name='yt-dlp',
                        )
        except Exception as e:
            print(f"[yt-dlp] Per-video extraction failed for {video_id}: {e}", flush=True)

    if not streams:
        return None

    best = select_best_stream(streams, media_type=media_type, quality=quality, max_filesize_mb=max_filesize_mb)
    if not best:
        return None

    fm = fallback_meta or {}
    title = meta.get('title') or fm.get('title', '')
    duration = parse_duration(meta.get('duration') or fm.get('duration', 0))
    thumbnail = meta.get('thumbnail') or fm.get('thumbnail', '')
    channel = meta.get('channel') or fm.get('channel', '')
    upload_date = meta.get('upload_date', '')
    views = meta.get('views') or fm.get('views')

    return _build_result(
        title=title,
        video_id=video_id,
        stream=best,
        duration_secs=duration,
        thumbnail=thumbnail,
        channel=channel,
        upload_date=upload_date,
        view_count=views,
        backend_name=backend_name,
    )


def _extract_video_id(url):
    """Extract YouTube video ID from various URL formats."""
    patterns = [
        r'(?:v=|/v/|youtu\.be/)([a-zA-Z0-9_-]{11})',
        r'(?:embed/)([a-zA-Z0-9_-]{11})',
        r'(?:shorts/)([a-zA-Z0-9_-]{11})',
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return None


# ─────────────────────────────────────────────────────────────
# Flask Routes
# ─────────────────────────────────────────────────────────────

@app.route('/', methods=['GET'])
def health_check():
    """Health check endpoint for Render."""
    print("Health check accessed", flush=True)
    return jsonify({
        "status": "alive",
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "service": "yt-search-api",
        "engine": "multi-backend (piped/invidious/html/yt-dlp)",
        "backends": {
            "piped_instances": len(PIPED_INSTANCES),
            "invidious_instances": len(INVIDIOUS_INSTANCES),
            "html_scraper": True,
            "ytdlp_fallback": True,
        }
    })


@app.route('/search', methods=['POST'])
def search_youtube():
    """Main search endpoint — same API contract as before."""
    data = request.json or {}

    query = data.get('query')
    if not query:
        return jsonify({"success": False, "error": "Query is required"}), 400

    search_kwargs = {
        'type': data.get('type', 'any'),
        'max_results': int(data.get('max_results', 1)),
        'duration_min': data.get('duration_min'),
        'duration_max': data.get('duration_max'),
        'prefer_format': data.get('prefer_format'),
        'max_filesize_mb': data.get('max_filesize_mb'),
        'quality': data.get('quality', 'best'),
    }

    is_direct_url = query.startswith('http://') or query.startswith('https://')

    print(f"\n{'='*60}", flush=True)
    print(f"[Search] query='{query}' direct_url={is_direct_url} kwargs={search_kwargs}", flush=True)
    print(f"{'='*60}", flush=True)

    results, error = perform_search_multi(query, is_direct_url=is_direct_url, **search_kwargs)

    if error and not results:
        if not is_direct_url:
            words = query.split()
            if len(words) > 1:
                similar_query = " ".join(words[:max(1, len(words) - 1)])
                print(f"[Search] Trying similar query: '{similar_query}'", flush=True)
                results, error2 = perform_search_multi(similar_query, is_direct_url=False, **search_kwargs)
                if results:
                    return jsonify({
                        "success": True,
                        "query": query,
                        "type": search_kwargs['type'],
                        "results_count": len(results),
                        "exact_match": False,
                        "search_method": "similar",
                        "similar_query_used": similar_query,
                        "results": results,
                    })

        return jsonify({
            "success": False,
            "error": error or "No videos found matching criteria",
            "query": query,
        }), 404

    return jsonify({
        "success": True,
        "query": query,
        "type": search_kwargs['type'],
        "results_count": len(results),
        "exact_match": True,
        "search_method": "multi_backend",
        "results": results,
    })


# ─────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 7860))
    app.run(host='0.0.0.0', port=port, debug=True)
