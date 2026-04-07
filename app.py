import os
import datetime
from flask import Flask, request, jsonify
import yt_dlp

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
            # Prefer merged formats (both video and audio)
            if not has_video:
                continue
        elif media_type == 'audio':
            # Prefer audio-only or anything with audio
            if not has_audio:
                continue
                
        # Filter by preferred format extension if strictly requested
        # We might not strictly filter if we don't find it, but we can score it higher.
        
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
                score += 50
            if quality == 'best':
                height = f.get('height', 0) or 0
                score += height
            elif quality == 'worst':
                height = f.get('height', 0) or 0
                score -= height
            elif quality.endswith('p'):
                target_h = int(quality[:-1])
                height = f.get('height', 0) or 0
                # Penalize distance from target
                score -= abs(target_h - height)
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

def perform_search(query, is_direct_url=False, **kwargs):
    """Perform yt-dlp extraction."""
    max_results = kwargs.get('max_results', 1)
    
    # Check for YOUTUBE_COOKIES environment variable (Great for Render deployments)
    cookie_path = os.path.join(os.getcwd(), 'cookies.txt')
    env_cookies = os.environ.get('YOUTUBE_COOKIES')
    
    if env_cookies and not os.path.exists(cookie_path):
        try:
            with open(cookie_path, 'w', encoding='utf-8') as f:
                # Replace literal \n with actual newlines if the user pasted them flat
                f.write(env_cookies.replace('\\n', '\n'))
            print("Successfully created cookies.txt from environment variable.")
        except Exception as e:
            print(f"Failed to write environment cookies to file: {e}")
            
    ydl_opts = {
        'format': 'best',
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'nocheckcertificate': True, # Avoid SSL/Empty response issues
        'geo_bypass': True,         # Help with regional blocks
        # Browser impersonation to avoid "Sign in to confirm you're not a bot"
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
        },
        'extractor_args': {
            'youtube': {
                'player_client': ['ios', 'android'], # ios is currently the most resilient
                'skip': ['hls', 'dash']
            }
        }
    }
    
    if os.path.exists(cookie_path):
        ydl_opts['cookiefile'] = cookie_path
        print(f"Using cookies from {cookie_path}")
    
    if is_direct_url:
        search_query = query
    else:
        # Avoid huge default search limits if we need specific matches
        search_query = f"ytsearch{max_results * 5}:{query}" # Increased depth for robustness

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(search_query, download=False)
            except Exception as e:
                error_msg = str(e)
                # Specific help for JSONDecodeError (Common YouTube Bot Block)
                if "JSONDecodeError" in error_msg or "Expecting value" in error_msg or "Sign in" in error_msg:
                    return {
                        "error": "YouTube is blocking your server IP (Bot Detection).",
                        "solution": "You MUST add a 'cookies.txt' file to the project folder to bypass this. See README.md for instructions.",
                        "details": error_msg
                    }
                return {"error": error_msg}
            
            if not info:
                return []
                
            if 'entries' in info:
                # It's a search result or playlist
                entries = info['entries']
            else:
                # Direct URL single video
                entries = [info]
                
            results = []
            
            for video in entries:
                if not video:
                    continue
                
                # Skip live streams (they don't have a stable direct URL for easy download)
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
                
                # Check filesize filter again (sometimes format extraction finds different size)
                if kwargs.get('max_filesize_mb') and extracted['filesize_mb']:
                    if extracted['filesize_mb'] > kwargs.get('max_filesize_mb'):
                        continue
                
                results.append(extracted)
                
                if len(results) >= max_results:
                    break
                    
            return results
    except Exception as e:
        error_msg = str(e)
        print(f"Internal error during extraction: {error_msg}")
        
        # Specific help for JSONDecodeError (Common YouTube Bot Block)
        if "JSONDecodeError" in error_msg or "Expecting value" in error_msg:
            return {
                "error": "YouTube is blocking your server IP (Bot Detection).",
                "solution": "You MUST add a 'cookies.txt' file to the project folder to bypass this. See README.md for instructions.",
                "details": error_msg
            }
            
        return {"error": f"Internal server error: {error_msg}"}

@app.route('/', methods=['GET'])
def health_check():
    return jsonify({
        "status": "alive",
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "service": "yt-search-api"
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
    
    # 1. Check if direct URL
    is_direct_url = query.startswith('http://') or query.startswith('https://')
    
    # 2. Try Exact Search
    results = perform_search(query, is_direct_url=is_direct_url, **search_kwargs)
    
    # Check if we got an error from yt-dlp
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
        
    # 3. Fallback: Similar Search (if not direct URL and no results found)
    if not is_direct_url:
        words = query.split()
        if len(words) > 1:
            # Simple fallback: try using just the first 2-3 words, dropping potential overly-restrictive words
            similar_query = " ".join(words[:max(1, len(words) - 1)])
            
            # Relax some constraints for the fallback
            fallback_kwargs = dict(search_kwargs)
            
            similar_results = perform_search(similar_query, is_direct_url=False, **fallback_kwargs)
            
            # Check for error in fallback too
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
    # For local testing, use PORT env var or default to 7860 (HF Spaces default)
    port = int(os.environ.get("PORT", 7860))
    app.run(host='0.0.0.0', port=port, debug=True)
