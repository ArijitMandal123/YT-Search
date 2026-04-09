"""Test the exact failing query with the fixed code."""
import sys
sys.path.insert(0, '.')
from app import perform_search_multi

print("=" * 70)
print("Testing: One Piece Laboon whale tragic promise 4k raw no subs")
print("=" * 70)

# Simulate what the /search endpoint does for a normal query (which includes simplifying the query as fallback)
from app import simplify_query

query = 'One Piece Laboon whale tragic promise 4k raw no subs'
results, error = perform_search_multi(
    query,
    is_direct_url=False,
    type='video',
    max_results=1,
    quality='1080p',
    max_filesize_mb=250,
)

if not results:
    s_query = simplify_query(query)
    print(f"\nTrying simplified query: {s_query}")
    results, error = perform_search_multi(
        s_query,
        is_direct_url=False,
        type='video',
        max_results=1,
        quality='1080p',
        max_filesize_mb=250,
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
