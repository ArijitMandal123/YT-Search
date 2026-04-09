"""Test the exact failing query with the fixed code."""
import sys
sys.path.insert(0, '.')
from app import perform_search_multi

print("=" * 70)
print("Testing: The Apothecary Diaries Maomao Jinshi investigation 4k")
print("=" * 70)

results, error = perform_search_multi(
    'The Apothecary Diaries Maomao Jinshi investigation 4k',
    is_direct_url=False,
    type='video',
    max_results=1,
    quality='1080p',
    max_filesize_mb=150,
)
print("\n" + "=" * 70)
print(f"Error: {error}")
print(f"Results count: {len(results)}")
if results:
    r = results[0]
    print(f"Title: {r['title']}")
    print(f"URL: {r['url']}")
    print(f"Resolution: {r['resolution']}")
    print(f"Format: {r['format']}")
    print(f"Filesize MB: {r['filesize_mb']}")
    print(f"Duration: {r['duration_formatted']}")
    print(f"Channel: {r['channel']}")
    print(f"Views: {r['view_count']}")
    print(f"Backend: {r['backend_used']}")
    print(f"Stream URL: {r['stream_url'][:100]}..." if r.get('stream_url') else "Stream: None")
