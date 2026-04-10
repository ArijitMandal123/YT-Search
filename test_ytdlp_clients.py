import yt_dlp, sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# Simulate exactly what _fetch_single_video will do on Render
video_id = "elfEfq5SZ_Q"  # First result from your failing attack on titan query

ydl_opts = {
    'format': 'bv*[ext=mp4][height<=1080]+ba[ext=m4a]/bv*[height<=1080]+ba/b[ext=mp4]/b',
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,
    'nocheckcertificate': True,
    'geo_bypass': True,
    'socket_timeout': 20,
    'extractor_args': {
        'youtube': {
            'player_client': ['mediaconnect', 'tv_embedded', 'android'],
        },
    },
}

url = f"https://www.youtube.com/watch?v={video_id}"
print(f"Testing: {url}")
print(f"Using player_client: ['mediaconnect', 'tv_embedded', 'android']")
print()

try:
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if info:
            fmts = info.get('formats', [])
            title = info.get('title', '?').encode('ascii', 'replace').decode('ascii')
            stream_url = info.get('url') or (fmts[-1].get('url') if fmts else None)
            print(f"SUCCESS!")
            print(f"  Title: {title[:70]}")
            print(f"  Formats: {len(fmts)}")
            print(f"  Duration: {info.get('duration')}s")
            if stream_url:
                print(f"  Stream URL: {stream_url[:100]}...")
        else:
            print("FAIL: No info returned")
except Exception as e:
    msg = str(e)
    if "Sign in" in msg or "bot" in msg.lower():
        print(f"BLOCKED: {msg[:100]}")
    else:
        print(f"ERROR: {msg[:150]}")
