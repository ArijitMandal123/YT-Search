import sys
sys.path.insert(0, '.')
from app import InnertubeBackend, select_best_stream

test_ids = ['sEAPQEtaTuM', 'fV2LLgBOKzc', 'dQw4w9WgXcQ']
for vid in test_ids:
    print(f'\n=== Testing innertube for {vid} ===')
    streams, meta = InnertubeBackend.get_streams(vid)
    if streams:
        best = select_best_stream(streams, media_type='video', quality='1080p')
        if best:
            title = meta.get('title', '')[:60]
            print(f'  Title: {title}')
            print(f'  Best: {best["height"]}p combined={best["has_both"]} ext={best["ext"]} bitrate={best["bitrate"]}')
            print(f'  URL: {best["url"][:80]}...')
        else:
            print('  No suitable stream found')
    else:
        print('  FAILED - no streams returned')
