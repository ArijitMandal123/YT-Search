"""Quick smoke test for the multi-backend YouTube search API."""
import sys
import json
import time

# Add the project to path
sys.path.insert(0, '.')
from app import PipedBackend, InvidiousBackend, select_best_stream, perform_search_multi

def test_piped_search():
    print("\n=== Test: Piped Search ===")
    results = PipedBackend.search("naruto 4k", max_results=2)
    if results:
        print(f"  ✅ Found {len(results)} results")
        for r in results[:2]:
            print(f"     - {r['title'][:60]}  (dur={r['duration']}s, id={r['videoId']})")
        return results[0]['videoId']
    else:
        print("  ❌ No results from Piped")
        return None

def test_invidious_search():
    print("\n=== Test: Invidious Search ===")
    results = InvidiousBackend.search("naruto 4k", max_results=2)
    if results:
        print(f"  ✅ Found {len(results)} results")
        for r in results[:2]:
            print(f"     - {r['title'][:60]}  (dur={r['duration']}s, id={r['videoId']})")
        return results[0]['videoId']
    else:
        print("  ❌ No results from Invidious")
        return None

def test_piped_streams(video_id):
    print(f"\n=== Test: Piped Streams ({video_id}) ===")
    streams, meta = PipedBackend.get_streams(video_id)
    if streams:
        print(f"  ✅ Got {len(streams)} streams")
        best = select_best_stream(streams, media_type='video', quality='1080p')
        if best:
            print(f"     Best: {best['height']}p, ext={best['ext']}, url={best['url'][:80]}...")
        return True
    else:
        print("  ❌ No streams from Piped")
        return False

def test_invidious_streams(video_id):
    print(f"\n=== Test: Invidious Streams ({video_id}) ===")
    streams, meta = InvidiousBackend.get_streams(video_id)
    if streams:
        print(f"  ✅ Got {len(streams)} streams")
        best = select_best_stream(streams, media_type='video', quality='1080p')
        if best:
            print(f"     Best: {best['height']}p, ext={best['ext']}, url={best['url'][:80]}...")
        return True
    else:
        print("  ❌ No streams from Invidious")
        return False

def test_full_search():
    print("\n=== Test: Full Multi-Backend Search (naruto 4k) ===")
    start = time.time()
    results, error = perform_search_multi(
        "naruto 4k",
        is_direct_url=False,
        type='video',
        max_results=1,
        quality='1080p',
        duration_min=30,
        duration_max=300,
        max_filesize_mb=150,
    )
    elapsed = time.time() - start
    if results:
        print(f"  ✅ Got {len(results)} result(s) in {elapsed:.1f}s")
        for r in results:
            print(f"     Title: {r['title'][:60]}")
            print(f"     URL: {r['url']}")
            print(f"     Stream: {r['stream_url'][:80]}..." if r.get('stream_url') else "     Stream: None")
            print(f"     Duration: {r['duration_formatted']}")
            print(f"     Resolution: {r['resolution']}")
            print(f"     Backend: {r['backend_used']}")
    else:
        print(f"  ❌ No results. Error: {error}")

if __name__ == '__main__':
    vid = test_piped_search()
    vid2 = test_invidious_search()
    
    target_id = vid or vid2
    if target_id:
        test_piped_streams(target_id)
        test_invidious_streams(target_id)
    
    test_full_search()
    print("\n=== All tests completed ===")
