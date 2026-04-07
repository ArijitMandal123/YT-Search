import os
import datetime
from flask import Flask, request, jsonify
import yt_dlp
import urllib.request
import urllib.parse
import re
import json

app = Flask(__name__)

def parse_duration(duration_str):
    """Fallback if yt-dlp duration isn't a number."""
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

def get_best_format(formats, media_type, prefer_format, max_filesize_mb, quality):
    """Select the best format based on preferences."""
    valid_formats = []
    
    for f in formats:
        # Check filesize if specified
        filesize_bytes = f.get('filesize') or f.get('filesize_approx')
        if max_filesize_mb and filesize_bytes:
            if filesize_bytes > max_filesize_mb * 1024 * 1024:
                continue
                
        # Determine if it's video or audio
        vcodec = f.get('vcodec', 'none')
        acodec = f.get('acodec', 'none')
        has_video = vcodec != 'none'
        has_audio = acodec != 'none'
        
        is_video_only = has_video and not has_audio
        is_audio_only = has_audio and not has_video
        is_both = has_video and has_audio
        
        if media_type == 'video':
            # We want video out of this (it might have audio or just be video)
            if not has_video:
                continue
        elif media_type == 'audio':
            # We want audio
            if not has_audio:
                continue
                
        valid_formats.append(f)
        
    if not valid_formats:
        return None
        
    # Sort by quality/score
    def score_format(f):
        score = 0
        ext = f.get('ext', '')
        vcodec = f.get('vcodec', 'none')
        acodec = f.get('acodec', 'none')
        
        if prefer_format and ext == prefer_format:
            score += 100
            
        if media_type == 'video':
            # Prefer combined video+audio
            if vcodec != 'none' and acodec != 'none':
                score += 500
            if quality == 'best':
                height = f.get('height', 0) or 0
                score += height
            elif quality == 'worst':
                height = f.get('height', 0) or 0
                score -= height
            elif quality.endswith('p'):
                try:
                    target_h = int(quality[:-1])
                    height = f.get('height', 0) or 0
                    score -= abs(target_h - height)
                except ValueError:
                    pass
        elif media_type == 'audio':
            if acodec != 'none' and vcodec == 'none':
                score += 50 # audio only
            abr = f.get('abr', 0) or 0
            if quality == 'best':
                score += abr
            elif quality == 'worst':
                score -= abr
                
        return score

    valid_formats.sort(key=score_format, reverse=True)
    return valid_formats[0]

def extract_video_info(video, media_type, prefer_format, max_filesize_mb, quality):
    """Extract metadata from a yt-dlp video dict."""
    formats = video.get('formats', [])
    best_f = get_best_format(formats, media_type, prefer_format, max_filesize_mb, quality)
    
    stream_url = best_f.get('url') if best_f else video.get('url') # fallback to default url
    fmt_ext = best_f.get('ext') if best_f else video.get('ext')
    
    # Filesize
    filesize_bytes = None
    if best_f:
        filesize_bytes = best_f.get('filesize') or best_f.get('filesize_approx')
    filesize_mb = round(filesize_bytes / (1024 * 1024), 2) if filesize_bytes else None
    
    # Duration
    duration = video.get('duration')
    duration_secs = parse_duration(duration)
    duration_formatted = str(datetime.timedelta(seconds=duration_secs)) if duration_secs else None

    # Resolution
    width = best_f.get('width') if best_f else video.get('width')
    height = best_f.get('height') if best_f else video.get('height')
    resolution = f"{width}x{height}" if width and height else None

    return {
        "title": video.get('title'),
        "url": video.get('webpage_url') or f"https://www.youtube.com/watch?v={video.get('id')}",
        "stream_url": stream_url,
        "duration": duration_secs,
        "duration_formatted": duration_formatted,
        "length": duration_formatted, # Alias for duration_formatted
        "length_seconds": duration_secs, # Alias for duration
        "filesize_mb": filesize_mb,
        "format": fmt_ext,
        "resolution": resolution,
        "fps": best_f.get('fps') if best_f else video.get('fps'),
        "vcodec": best_f.get('vcodec') if best_f else video.get('vcodec'),
        "acodec": best_f.get('acodec') if best_f else video.get('acodec'),
        "thumbnail": video.get('thumbnail'),
        "channel": video.get('uploader'),
        "upload_date": video.get('upload_date'),
        "view_count": video.get('view_count')
    }

def fetch_urls_from_html(query, count):
    """Custom bypass: scrape YouTube search DOM directly to avoid ytsearch: blocks."""
    print(f"Using raw HTML scraper for query: {query}")
    search_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}"
    req = urllib.request.Request(
        search_url, 
        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'}
    )
    try:
        html = urllib.request.urlopen(req, timeout=10).read().decode('utf-8')
        video_ids = re.findall(r'"videoId":"([^"]{11})"', html)
        valid_ids = []
        for vid in video_ids:
            if vid not in valid_ids:
                valid_ids.append(vid)
        return [f"https://www.youtube.com/watch?v={vid}" for vid in valid_ids[:count]]
    except Exception as e:
        print(f"HTML Scraper failed: {e}")
        return []

def perform_search(query, is_direct_url=False, **kwargs):
    """Perform yt-dlp extraction."""
    max_results = kwargs.get('max_results', 1)
    
    # Check for YOUTUBE_COOKIES environment variable or Render Secret Files
    render_secret_path = '/etc/secrets/cookies.txt'
    local_cookie_path = os.path.join(os.getcwd(), 'cookies.txt')
    writable_cookie_path = '/tmp/yt_cookies.txt'
    
    import shutil
    
    final_cookie_path = None
    
    if os.path.exists(render_secret_path):
        try:
            shutil.copyfile(render_secret_path, writable_cookie_path)
            final_cookie_path = writable_cookie_path
        except Exception as e:
            print(f"Failed to copy secret cookies to writable path: {e}")
            final_cookie_path = render_secret_path
    elif os.path.exists(local_cookie_path):
        final_cookie_path = local_cookie_path
        
    ydl_opts = {
        # CRITICAL FIX: "best" fails on many iOS/Android clients because merged 720p 
        # streams were removed by YouTube. Use bestvideo+bestaudio/best.
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best',
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'nocheckcertificate': True,
        'geo_bypass': True,
        # Allow yt-dlp to cycle through all modern clients (web, mweb, ios, tv).
        # We explicitly DO NOT skip 'dash' streams, because skipping DASH destroys 
        # most high-quality separate audio/video chunks.
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        }
    }
    
    if final_cookie_path:
        ydl_opts['cookiefile'] = final_cookie_path
        print(f"Using cookies from {final_cookie_path}")
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            entries = []
            
            if is_direct_url:
                try:
                    info = ydl.extract_info(query, download=False)
                    if info: entries.append(info)
                except Exception as e:
                    return {"error": str(e)}
            else:
                # Bypass yt-dlp's blocked ytsearch API entirely
                urls_to_try = fetch_urls_from_html(query, max_results * 5)
                
                if not urls_to_try:
                    return {"error": "YouTube blocked the raw HTML search scraper."}
                    
                for url in urls_to_try:
                    try:
                        info = ydl.extract_info(url, download=False)
                        if info: entries.append(info)
                    except Exception as e:
                        print(f"Failed to extract info for {url}: {e}")
                        continue
            
            if not entries:
                return []
                
            results = []
            
            for video in entries:
                if not video:
                    continue
                
                # Skip live streams
                if video.get('is_live') or video.get('live_status') == 'is_live' or video.get('duration') == 0:
                    continue
                    
                # Apply filters
                duration_secs = parse_duration(video.get('duration'))
                dur_min = kwargs.get('duration_min')
                dur_max = kwargs.get('duration_max')
                
                if dur_min and duration_secs < dur_min:
                    continue
                if dur_max and duration_secs > dur_max:
                    continue
                    
                extracted = extract_video_info(
                    video,
                    media_type=kwargs.get('type', 'any'),
                    prefer_format=kwargs.get('prefer_format'),
                    max_filesize_mb=kwargs.get('max_filesize_mb'),
                    quality=kwargs.get('quality', 'best')
                )
                
                if kwargs.get('max_filesize_mb') and extracted and extracted.get('filesize_mb'):
                    if extracted['filesize_mb'] > kwargs.get('max_filesize_mb'):
                        continue
                
                if extracted:
                    results.append(extracted)
                
                if len(results) >= max_results:
                    break
                    
            return results
    except Exception as e:
        error_msg = str(e)
        print(f"Internal error during extraction: {error_msg}")
        return {"error": f"Internal server error: {error_msg}"}

@app.route('/', methods=['GET'])
def health_check():
    print("Health check accessed", flush=True)
    return jsonify({
        "status": "alive",
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "service": "yt-search-api",
        "engine": "yt-dlp-custom"
    })

@app.route('/search', methods=['POST'])
def search_youtube():
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
        'quality': data.get('quality', 'best')
    }
    
    is_direct_url = query.startswith('http://') or query.startswith('https://')
    
    results = perform_search(query, is_direct_url=is_direct_url, **search_kwargs)
    
    if isinstance(results, dict) and "error" in results:
        return jsonify({
            "success": False,
            "error": results["error"],
            "query": query
        }), 500

    if results and len(results) > 0:
        return jsonify({
            "success": True,
            "query": query,
            "type": search_kwargs['type'],
            "results_count": len(results),
            "exact_match": True,
            "search_method": "exact" if not is_direct_url else "direct_url",
            "results": results
        })
        
    if not is_direct_url:
        words = query.split()
        if len(words) > 1:
            similar_query = " ".join(words[:max(1, len(words) - 1)])
            fallback_kwargs = dict(search_kwargs)
            similar_results = perform_search(similar_query, is_direct_url=False, **fallback_kwargs)
            
            if isinstance(similar_results, dict) and "error" in similar_results:
                 return jsonify({
                    "success": False,
                    "error": similar_results["error"],
                    "query": query,
                    "search_method": "similar_attempted"
                }), 500

            if similar_results and len(similar_results) > 0:
                return jsonify({
                    "success": True,
                    "query": query,
                    "type": search_kwargs['type'],
                    "results_count": len(similar_results),
                    "exact_match": False,
                    "search_method": "similar",
                    "similar_query_used": similar_query,
                    "results": similar_results
                })
                
    return jsonify({
        "success": False,
        "query": query,
        "error": "No videos found matching criteria (skipping livestreams)."
    }), 404

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 7860))
    app.run(host='0.0.0.0', port=port, debug=True)
