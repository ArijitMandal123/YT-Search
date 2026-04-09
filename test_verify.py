"""Verify the fixed code works correctly."""
import sys
sys.path.insert(0, '.')
from app import PIPED_INSTANCES, perform_search_multi

print("Piped instances:", PIPED_INSTANCES)
print()

results, error = perform_search_multi(
    "The Apothecary Diaries Maomao Jinshi investigation 4k",
    type="video", max_results=1, quality="1080p", max_filesize_mb=150
)
if results:
    r = results[0]
    print("Video:", r["title"])
    print("URL:", r["url"])
    print("Views:", r["view_count"])
    print("Resolution:", r["resolution"])
    print("Format:", r["format"])
    print("Backend:", r["backend_used"])
else:
    print("Error:", error)
