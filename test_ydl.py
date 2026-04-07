import yt_dlp

clients_to_test = [
    ['mweb', 'web'],
    ['ios', 'android'],
    ['android', 'ios'],
    ['tv', 'mweb'],
    ['web'],
    [] # no client set
]

print("Testing yt-dlp clients against dlE9AY9sXGs")

for clients in clients_to_test:
    print("\n" + "="*50)
    print(f"Testing client list: {clients}")
    
    ydl_opts = {
        'format': 'best',
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'nocheckcertificate': True,
        'geo_bypass': True,
    }
    
    if clients:
        ydl_opts['extractor_args'] = {
            'youtube': {
                'player_client': clients
            }
        }
        
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info("https://www.youtube.com/watch?v=dlE9AY9sXGs", download=False)
                if 'formats' in info:
                    print("SUCCESS! This client list works.")
                    print("First format found:", info['formats'][0].get('url')[:60] + "...")
                else:
                    print("Object returned but no formats")
            except Exception as e:
                print(f"FAILED: {e}")
    except Exception as e:
        print(f"Fatal setup error: {e}")
