import os
import sys
import datetime
import time
import random
import traceback
from flask import Flask, request, jsonify
import requests as http_requests
import urllib.parse
import re
import json

app = Flask(__name__)

# ─────────────────────────────────────────────────────────────
# Backend Instance Lists (rotated on each request for load balancing)
# ─────────────────────────────────────────────────────────────

PIPED_INSTANCES = [
    "https://api.piped.private.coffee",
    "https://pipedapi.kavin.rocks",
    "https://api-piped.mha.fi",
]

# Cache for dynamic piped instances
_dynamic_piped_instances = []
_last_piped_fetch = 0

INVIDIOUS_INSTANCES = [
    "https://inv.thepixora.com",
    "https://invidious.nerdvpn.de",
    "https://inv.nadeko.net",
    "https://yewtu.be",
    "https://invidious.snopyta.org",
    "https://iv.ggtyler.dev",
    "https://invidious.flokinet.to",
]

# ─────────────────────────────────────────────────────────────
# Instance Health Tracking
# ─────────────────────────────────────────────────────────────
# Track which instances fail and deprioritize them within a request cycle.
_instance_failures = {}  # {url: last_failure_timestamp}
FAILURE_COOLDOWN = 300   # 5 min cooldown for failed instances

def _is_instance_healthy(url):
    last_fail = _instance_failures.get(url)
    if last_fail and (time.time() - last_fail) < FAILURE_COOLDOWN:
        return False
    return True

def _mark_instance_failed(url):
    _instance_failures[url] = time.time()

# Global flag: if yt-dlp direct-URL extraction has already failed once in
# this request, don't retry it for every candidate video (saves ~10s each).
_ytdlp_failed_this_request = False

# Timeout for each backend HTTP call (seconds).
# Reduced to 5s to ensure we can try multiple backends even during a 30s cold start.
BACKEND_TIMEOUT = 5

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
    """Extract numeric height from quality strings like '1080p', '720p', 'best'."""
    if not quality_str or quality_str in ('best', 'worst'):
        return None
    m = re.match(r'(\d+)', str(quality_str))
    return int(m.group(1)) if m else None


def select_best_stream(streams, media_type='video', quality='best', max_filesize_mb=None):
    """
    Unified format selector that works across Piped, Invidious, and yt-dlp
    format lists.

    DESIGN: For video, we prioritize resolution + bitrate above all else.
    Video-only streams at 1080p are FAR superior to combined 360p streams.
    This matches the local fetcher.py approach: 'bestvideo[ext=mp4][height<=1080]'
    which explicitly picks the highest quality video-only stream.

    Returns the single best stream dict, or None.
    """
    if not streams:
        return None

    candidates = []
    for s in streams:
        url = s.get('url') or s.get('stream_url')
        if not url:
            continue

        # Filesize filter
        content_length = s.get('contentLength') or s.get('filesize') or s.get('filesize_approx') or s.get('clen')
        if content_length:
            try:
                content_length = int(content_length)
            except (ValueError, TypeError):
                content_length = None
        if max_filesize_mb and content_length:
            if content_length > max_filesize_mb * 1024 * 1024:
                continue

        # Determine audio/video nature
        mime = s.get('mimeType') or s.get('type') or ''
        video_only = s.get('videoOnly', False)
        is_video = 'video' in mime or s.get('height') or s.get('qualityLabel') or s.get('resolution')
        is_audio = 'audio' in mime or s.get('audioQuality') or s.get('audioSampleRate')
        has_both = is_video and is_audio and not video_only

        if media_type == 'video':
            if not is_video:
                continue
            # Skip 0x0 / unknown resolution combined streams — they are
            # always extremely low-quality progressive downloads.
            height = int(s.get('height') or 0)
            if has_both and height == 0:
                continue
        elif media_type == 'audio':
            if not is_audio:
                continue

        candidates.append({
            'url': url,
            'height': int(s.get('height') or 0),
            'width': int(s.get('width') or 0),
            'bitrate': int(s.get('bitrate') or 0),
            'content_length': content_length,
            'has_both': has_both,
            'video_only': video_only,
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

    def _score(c):
        score = 0

        if media_type == 'video':
            # ── PRIMARY: Resolution is king ──
            # Height dominates the score. A 1080p video-only stream is always
            # better than a 360p combined stream for background-video use.
            if quality == 'best':
                score += c['height'] * 100 + c['bitrate'] // 1000
            elif quality == 'worst':
                score -= c['height'] * 100
            elif target_h:
                # Closer to target is better; strong penalty for distance
                score -= abs(target_h - c['height']) * 100
                # Among same-height, prefer higher bitrate (= better quality)
                score += c['bitrate'] // 1000
            else:
                score += c['height'] * 100

            # ── SECONDARY: Small bonus for combined audio+video ──
            # Only a tiebreaker — never enough to override a resolution jump.
            # 500 < one resolution tier (e.g. 720→1080 = 360*100 = 36000)
            if c['has_both']:
                score += 500

            # ── TERTIARY: Format preference ──
            if c['ext'] == 'mp4':
                score += 200
            elif c['ext'] == 'm4a':
                score += 100

            # ── Small bonus for higher fps ──
            if c.get('fps') and c['fps'] > 30:
                score += 50

        elif media_type == 'audio':
            score += c['bitrate'] // 1000
            if c['ext'] in ('mp4', 'm4a'):
                score += 500

        return score

    candidates.sort(key=_score, reverse=True)
    winner = candidates[0]
    print(f"[StreamSelect] Picked: {winner['height']}p {winner['ext']} "
          f"bitrate={winner['bitrate']} videoOnly={winner['video_only']} "
          f"has_both={winner['has_both']} filesize={winner.get('content_length')}", flush=True)
    return winner


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
    }


# ─────────────────────────────────────────────────────────────
# Backend 1: Piped API
# ─────────────────────────────────────────────────────────────

class PipedBackend:
    name = "piped"

    @staticmethod
    def _refresh_piped_instances():
        global _dynamic_piped_instances, _last_piped_fetch
        # Refresh hourly to avoid spamming
        if time.time() - _last_piped_fetch < 3600 and _dynamic_piped_instances:
            return

        try:
            r = http_requests.get("https://piped-instances.kavin.rocks/", timeout=10)
            if r.status_code == 200:
                data = r.json()
                new_instances = []
                for inst in data:
                    if inst.get('up_to_date') and inst.get('api_url') and inst.get('uptime_24h', 0) > 95:
                        api_url = inst['api_url']
                        if api_url not in PIPED_INSTANCES:
                            new_instances.append(api_url)
                _dynamic_piped_instances = new_instances
                _last_piped_fetch = time.time()
                print(f"[Piped] Refreshed {len(new_instances)} dynamic instances", flush=True)
        except Exception as e:
            print(f"[Piped] Failed to fetch instances: {e}", flush=True)

    @staticmethod
    def _get_instance():
        PipedBackend._refresh_piped_instances()
        all_instances = PIPED_INSTANCES + _dynamic_piped_instances
        
        # Prioritize healthy instances over recently failed ones
        healthy = [inst for inst in all_instances if _is_instance_healthy(inst)]
        unhealthy = [inst for inst in all_instances if not _is_instance_healthy(inst)]
        
        return healthy + unhealthy

    @staticmethod
    def search(query, max_results=5, **kwargs):
        """Search via Piped and return list of {videoId, title, duration, thumbnail, uploaderName}."""
        for base in PipedBackend._get_instance():
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
                for item in items[:20]:  # Grab many candidates to rank ourselves
                    vid = item.get('url', '').replace('/watch?v=', '')
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
                    # Re-rank by relevance (title match) and slightly by view count
                    query_words = set(query.lower().split())
                    def _relevance_score(r):
                        s = 0
                        title = r.get('title', '').lower()
                        title_words = set(title.split())
                        # Points for matching words
                        s += len(query_words.intersection(title_words)) * 2
                        # Points for full query match
                        if query.lower() in title:
                            s += 5
                        # Small tiebreaker for views
                        s += min(r.get('views', 0) / 1000000.0, 1.5)
                        return s
                    
                    results.sort(key=_relevance_score, reverse=True)
                    print(f"[Piped] Found {len(results)} results from {base}", flush=True)
                    for i, r in enumerate(results[:5]):
                        try:
                            print(f"  #{i+1} views={r['views']:>10,} dur={r['duration']:>4}s [{r['videoId']}] {r['title'][:60]}", flush=True)
                        except UnicodeEncodeError:
                            clean_title = r['title'][:60].encode('ascii', 'ignore').decode('ascii')
                            print(f"  #{i+1} views={r['views']:>10,} dur={r['duration']:>4}s [{r['videoId']}] {clean_title}", flush=True)
                    return results
            except Exception as e:
                print(f"[Piped] {base} search error: {e}", flush=True)
                _mark_instance_failed(base)
                continue
        return []

    @staticmethod
    def get_streams(video_id):
        """Get stream URLs from Piped for a video ID."""
        for base in PipedBackend._get_instance():
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
                    _mark_instance_failed(base)
                    continue

                # Combine all available streams
                all_streams = []
                for s in data.get('videoStreams', []):
                    s['mimeType'] = s.get('mimeType') or s.get('type', '')
                    s['videoOnly'] = s.get('videoOnly', True)
                    all_streams.append(s)
                for s in data.get('audioStreams', []):
                    s['mimeType'] = s.get('mimeType') or s.get('type', 'audio/mp4')
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
                if all_streams:
                    print(f"[Piped] Got {len(all_streams)} streams from {base}", flush=True)
                    return all_streams, meta

                if data.get('hls'):
                    print(f"[Piped] Using HLS from {base}", flush=True)
                    return [{'url': data['hls'], 'mimeType': 'video/mp4', 'height': 720, 'width': 1280, 'bitrate': 0, 'videoOnly': False}], meta

            except Exception as e:
                print(f"[Piped] {base} stream error: {e}", flush=True)
                _mark_instance_failed(base)
                continue
        return [], {}


# ─────────────────────────────────────────────────────────────
# Backend 2: Invidious API
# ─────────────────────────────────────────────────────────────

class InvidiousBackend:
    name = "invidious"

    @staticmethod
    def _get_instance():
        # Order matters
        healthy = [inst for inst in INVIDIOUS_INSTANCES if _is_instance_healthy(inst)]
        unhealthy = [inst for inst in INVIDIOUS_INSTANCES if not _is_instance_healthy(inst)]
        return healthy + unhealthy

    @staticmethod
    def search(query, max_results=5, **kwargs):
        """Search via Invidious API."""
        for base in InvidiousBackend._get_instance():
            try:
                url = f"{base}/api/v1/search?q={urllib.parse.quote(query)}&type=video&sort_by=relevance"
                print(f"[Invidious] Searching: {url}", flush=True)
                r = http_requests.get(url, timeout=BACKEND_TIMEOUT)
                if r.status_code != 200:
                    print(f"[Invidious] {base} returned {r.status_code}", flush=True)
                    _mark_instance_failed(base)
                    continue
                data = r.json()
                if not isinstance(data, list):
                    continue
                results = []
                for item in data[:max_results * 3]:
                    if item.get('type') != 'video':
                        continue
                    # Get best thumbnail
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
                print(f"[Invidious] {base} search error: {e}", flush=True)
                _mark_instance_failed(base)
                continue
        return []

    @staticmethod
    def get_streams(video_id):
        """Get stream URLs from Invidious for a video ID."""
        for base in InvidiousBackend._get_instance():
            try:
                url = f"{base}/api/v1/videos/{video_id}"
                print(f"[Invidious] Getting streams: {url}", flush=True)
                r = http_requests.get(url, timeout=BACKEND_TIMEOUT)
                if r.status_code != 200:
                    print(f"[Invidious] {base} video returned {r.status_code}", flush=True)
                    _mark_instance_failed(base)
                    continue
                data = r.json()
                if data.get('error'):
                    print(f"[Invidious] {base} video error: {data['error']}", flush=True)
                    _mark_instance_failed(base)
                    continue

                all_streams = []

                # formatStreams = combined audio+video
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
                # Best thumbnail
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

                # HLS fallback
                if data.get('hlsUrl'):
                    print(f"[Invidious] Using HLS from {base}", flush=True)
                    return [{'url': data['hlsUrl'], 'mimeType': 'video/mp4', 'height': 720, 'width': 1280, 'bitrate': 0, 'videoOnly': False}], meta

            except Exception as e:
                print(f"[Invidious] {base} stream error: {e}", flush=True)
                _mark_instance_failed(base)
                continue
        return [], {}


def _extract_height(s):
    """Extract height from various format fields."""
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
    """Extract width from various format fields."""
    if s.get('width'):
        return int(s['width'])
    res = s.get('resolution') or s.get('size') or ''
    m = re.search(r'(\d+)x(\d+)', res)
    if m:
        return int(m.group(1))
    return 0


# ─────────────────────────────────────────────────────────────
# Backend 3: yt-dlp fallback (last resort)
# ─────────────────────────────────────────────────────────────

class YtDlpBackend:
    name = "yt-dlp"

    @staticmethod
    def search_and_extract(query, max_results=1, is_direct_url=False, **kwargs):
        """
        Fallback: use yt-dlp to search + extract.
        Returns list of result dicts (same schema as _build_result).
        """
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
            'format': 'bv*[ext=mp4][height<=1080]+ba[ext=m4a]/b[ext=mp4]/b',  # Select best video + best audio directly
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'nocheckcertificate': True,
            'geo_bypass': True,
            'socket_timeout': 10,
            'sleep_requests': 2,
            'sleep_interval': 3,
            'max_sleep_interval': 6,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            },
            'extractor_args': {
                'youtube': {
                    'player_client': ['ios', 'android', 'web'],
                },
            },
        }

        import tempfile
        writable_cookie = os.path.join(tempfile.gettempdir(), 'yt_cookies.txt')
        cookie_paths = []
        
        passed_cookies = kwargs.get('cookies_content')
        if passed_cookies:
            # Ensure passed_cookies is handled correctly
            if not isinstance(passed_cookies, str):
                passed_cookies = str(passed_cookies)
            try:
                # Write as binary to avoid encoding/newline issues with different OS sources
                with open(writable_cookie, 'wb') as f:
                    f.write(passed_cookies.encode('utf-8'))
                cookie_paths.append(writable_cookie)
                print("[yt-dlp] Using cookies provided in API payload!", flush=True)
            except Exception as e:
                print(f"[yt-dlp] Failed to write cookie payload: {e}", flush=True)
        
        # Fallback to local disk paths
        cookie_paths.extend(['/etc/secrets/cookies.txt', writable_cookie, os.path.join(os.getcwd(), 'cookies.txt')])
        
        for cp in cookie_paths:
            if os.path.exists(cp):
                # If the cookie file is on a read-only FS or we just want to ensure it's writable
                if cp != writable_cookie:
                    try:
                        import shutil
                        shutil.copy2(cp, writable_cookie)
                        print(f"[yt-dlp] Copied cookies from {cp} -> {writable_cookie}", flush=True)
                        cp = writable_cookie
                    except Exception as copy_err:
                        print(f"[yt-dlp] Could not copy cookies: {copy_err}", flush=True)
                ydl_opts['cookiefile'] = cp
                print(f"[yt-dlp] Using cookies from {cp}", flush=True)
                break

        results = []
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                if is_direct_url:
                    urls = [query]
                else:
                    # Use ytsearch
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

                        # Try to pick best format from available formats
                        if formats:
                            best = select_best_stream(
                                [{'url': f.get('url'), 'height': f.get('height', 0), 'width': f.get('width', 0),
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

                        vid_id = video.get('id', '')
                        result = _build_result(
                            title=video.get('title', ''),
                            video_id=vid_id,
                            stream={
                                'url': stream_url,
                                'height': video.get('height', 0),
                                'width': video.get('width', 0),
                                'ext': video.get('ext', 'mp4'),
                                'fps': video.get('fps'),
                                'content_length': video.get('filesize') or video.get('filesize_approx'),
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
# Orchestrator: cascading multi-backend search
# ─────────────────────────────────────────────────────────────

def perform_search_multi(query, is_direct_url=False, **kwargs):
    """
    Try backends in order: Piped → Invidious → yt-dlp.
    Returns (results_list, error_string_or_None).
    """
    start_time = time.time()
    def elapsed():
        return time.time() - start_time

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
        # Fallback to yt-dlp for direct URL
        # remove max_results from kwargs to avoid TypeError
        kw = {k: v for k, v in kwargs.items() if k != 'max_results'}
        results = YtDlpBackend.search_and_extract(query, max_results=1, is_direct_url=True, **kw)
        if results:
            return results, None
        return [], "Could not extract video from URL"

    # ── Phase 1: Search for video IDs ──
    search_results = []
    search_backend = None

    # Check time budget before starting search
    if elapsed() < 15:
        # Try Piped search
        search_results = PipedBackend.search(query, max_results=max(max_results, 10))
        if search_results:
            search_backend = 'piped'

    # Try Invidious search if Piped failed and time budget allows
    if not search_results and elapsed() < 20:
        search_results = InvidiousBackend.search(query, max_results=max(max_results, 10))
        if search_results:
            search_backend = 'invidious'

    # Last resort: yt-dlp search (Disabled on Render for search due to blocks/slowness)
    is_on_render = os.environ.get('RENDER') or os.environ.get('PORT') == '7860'
    if not search_results and not is_on_render and elapsed() < 25:
        print("[Orchestrator] Proxy searches failed, trying yt-dlp fallback...", flush=True)
        kw = {k: v for k, v in kwargs.items() if k != 'max_results'}
        results = YtDlpBackend.search_and_extract(query, max_results=max_results, is_direct_url=False, **kw)
        if results:
            return results, None

    if not search_results:
        if elapsed() >= 25:
            return [], "Search timed out (cold start or proxy delays). Please try again."
        return [], "All search backends failed to find results"

    print(f"[Orchestrator] Search done via {search_backend} in {elapsed():.1f}s: {len(search_results)} candidates", flush=True)

    # ── Phase 2: Filter search results by duration ──
    filtered = []
    for sr in search_results:
        dur = parse_duration(sr.get('duration', 0))
        if duration_min and dur < duration_min:
            continue
        if duration_max and dur > duration_max:
            continue
        # Skip live streams (duration=0)
        if dur == 0:
            continue
        filtered.append(sr)

    if not filtered and search_results:
        # If all filtered out, relax and try all
        filtered = [sr for sr in search_results if parse_duration(sr.get('duration', 0)) > 0]

    # ── Phase 3: Get stream URLs for each video ──
    # Reset the per-request yt-dlp failure flag
    global _ytdlp_failed_this_request
    _ytdlp_failed_this_request = False

    final_results = []
    total_found = 0
    # Iterate through all filtered candidates until we find enough or time out
    for sr in filtered:
        if total_found >= max_results:
            break

        if elapsed() > 45:
            print("[Orchestrator] Timed out before completing candidates", flush=True)
            break

        video_id = sr['videoId']
        result = _fetch_single_video(video_id, media_type, quality, max_filesize_mb, fallback_meta=sr, **kwargs)
        if result:
            final_results.append(result)
            total_found += 1
        else:
            print(f"[Orchestrator] Extraction failed for {video_id}, trying next candidate...", flush=True)

    if final_results:
        return final_results, None

    # Final fallback logic
    if elapsed() > 35:
        return [], "Timed out extracting streams. Please try again."

    return [], "Found videos but could not extract stream URLs from any backend"


def _fetch_single_video(video_id, media_type, quality, max_filesize_mb, fallback_meta=None, **kwargs):
    """Fetch stream URL for a single video ID, trying Piped then Invidious then yt-dlp."""
    # Try Piped streams
    streams, meta = PipedBackend.get_streams(video_id)
    backend_name = 'piped'
    if not streams:
        streams, meta = InvidiousBackend.get_streams(video_id)
        backend_name = 'invidious'

    best = None
    if streams:
        best = select_best_stream(streams, media_type=media_type, quality=quality, max_filesize_mb=max_filesize_mb)

    # ── yt-dlp stream-only fallback (always enabled, even on Render) ──
    # We already have the video ID from the proxy search. Fetching a single known
    # direct URL with yt-dlp is fast (~5-10s) and bypasses YouTube's search blocks.
    # BUT: if yt-dlp already failed once this request, don't retry — YouTube is
    # blocking this server's IP entirely, and retrying just wastes 10s per attempt.
    global _ytdlp_failed_this_request
    if not best:
        if _ytdlp_failed_this_request:
            print(f"[_fetch_single_video] Skipping yt-dlp for {video_id} (already failed this request)", flush=True)
            return None

        print(f"[_fetch_single_video] Proxy streams failed for {video_id}, trying yt-dlp direct URL...", flush=True)
        yt_url = f"https://www.youtube.com/watch?v={video_id}"
        
        kw = {k: v for k, v in kwargs.items() if k != 'max_results'}
        yt_results = YtDlpBackend.search_and_extract(
            yt_url, max_results=1, is_direct_url=True,
            type=media_type, quality=quality, max_filesize_mb=max_filesize_mb, **kw
        )
        if yt_results:
            print(f"[_fetch_single_video] yt-dlp direct URL succeeded for {video_id}", flush=True)
            # Merge fallback_meta (view count, etc.) into the yt-dlp result
            if fallback_meta:
                r = yt_results[0]
                r.setdefault('view_count', fallback_meta.get('views'))
                r.setdefault('thumbnail', fallback_meta.get('thumbnail', ''))
            return yt_results[0]
        else:
            _ytdlp_failed_this_request = True
            print(f"[_fetch_single_video] yt-dlp failed for {video_id}, will skip for remaining candidates", flush=True)
        return None

    # Use meta from stream extraction, fallback to search meta
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

STRIP_WORDS = ['4k', '1080p', '720p', 'raw', 'no subs', 'subs', 'hd', 'uhd', 'amv', 'edit', 'remastered', 'no']

def simplify_query(q):
    """Progressively simplify a query by removing common qualifiers."""
    words = q.lower().split()
    for strip in STRIP_WORDS:
        strip_parts = strip.split()
        # Fast path for single-word
        if len(strip_parts) == 1:
            if strip in words:
                words.remove(strip)
        else:
            # multi-word strip (like "no subs")
            joined = " ".join(words)
            if strip in joined:
                joined = joined.replace(strip, "").strip()
                # fix double spaces
                joined = " ".join(joined.split())
                words = joined.split()
                
    # Also strip the last word as a fallback if not much changed
    if len(words) > 2:
        return " ".join(words[:max(1, len(words) - 1)])
    return " ".join(words)

@app.route('/', methods=['GET'])
def health_check():
    """Health check endpoint for Render."""
    print("Health check accessed", flush=True)
    return jsonify({
        "status": "alive",
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "service": "yt-search-api",
        "engine": "multi-backend (piped/invidious/yt-dlp)",
        "backends": {
            "piped_instances": len(PIPED_INSTANCES),
            "invidious_instances": len(INVIDIOUS_INSTANCES),
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
        'cookies_content': data.get('cookies_content'),
    }

    is_direct_url = query.startswith('http://') or query.startswith('https://')

    print(f"\n{'='*60}", flush=True)
    print(f"[Search] query='{query}' direct_url={is_direct_url} kwargs={search_kwargs}", flush=True)
    print(f"{'='*60}", flush=True)

    results, error = perform_search_multi(query, is_direct_url=is_direct_url, **search_kwargs)

    if error and not results:
        # If we got a timeout error, do NOT try a similar query, as it will also timeout
        # and cause a 502 Bad Gateway on Render's 100s Load Balancer limit.
        if "Timed out" in error:
            print(f"[Search] Skipping similar query because error was a timeout: {error}", flush=True)
            return jsonify({
                "success": False,
                "error": error,
                "query": query,
            }), 404

        # Try similar query as fallback
        if not is_direct_url:
            similar_query = simplify_query(query)
            if similar_query and similar_query != query.lower():
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


@app.route('/debug', methods=['GET'])
def debug_instances():
    """Test all backends with a small video to find which are active."""
    test_video = 'BaW_jenozKc' # youtube-dl test video (~10s)
    
    report = {
        "piped": [],
        "invidious": []
    }
    
    # Check Piped
    PipedBackend._refresh_piped_instances()
    all_piped = PIPED_INSTANCES + _dynamic_piped_instances
    for inst in all_piped:
        try:
            r = http_requests.get(f"{inst}/streams/{test_video}", timeout=3)
            report["piped"].append({"instance": inst, "status": r.status_code, "healthy": _is_instance_healthy(inst)})
        except Exception as e:
             report["piped"].append({"instance": inst, "status": str(e), "healthy": _is_instance_healthy(inst)})
             
    # Check Invidious
    for inst in INVIDIOUS_INSTANCES:
        try:
            r = http_requests.get(f"{inst}/api/v1/videos/{test_video}", timeout=3)
            report["invidious"].append({"instance": inst, "status": r.status_code, "healthy": _is_instance_healthy(inst)})
        except Exception as e:
             report["invidious"].append({"instance": inst, "status": str(e), "healthy": _is_instance_healthy(inst)})

    return jsonify({
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "report": report
    })


# ─────────────────────────────────────────────────────────────
# Health / keepalive endpoint
# Ping this every 5-10 min from cron-job.org or similar to prevent
# Render free-tier cold starts (which add 30-50s to first request).
# ─────────────────────────────────────────────────────────────

@app.route('/health', methods=['GET'])
@app.route('/ping', methods=['GET'])
def health():
    return jsonify({"status": "ok"}), 200


# ─────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 7860))
    app.run(host='0.0.0.0', port=port, debug=True)
