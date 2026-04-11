import os
import datetime
from flask import Flask, request, jsonify

# Import the new fetching algorithm
from youtube_fetcher import search_youtube_links

app = Flask(__name__)

# ─────────────────────────────────────────────────────────────
# Flask Routes
# ─────────────────────────────────────────────────────────────

STRIP_WORDS = ['4k', '1080p', '720p', 'raw', 'no subs', 'hd', 'uhd', 'amv', 'edit', 'no']

def simplify_query(q):
    """Fallback query simplification if no results are found."""
    words = q.lower().split()
    for s in STRIP_WORDS:
        if s in words: words.remove(s)
    if len(words) > 2: return " ".join(words[:-1])
    return " ".join(words)

@app.route('/search', methods=['POST'])
def search_youtube():
    """
    Main API Endpoint for searching YouTube.
    Utilizes the heavily enriched Piped/Invidious search_youtube_links algorithm.
    """
    data = request.json or {}
    query = data.get('query')
    if not query:
        return jsonify({"success": False, "error": "Query is required"}), 400

    max_results = int(data.get('max_results', 10))
    # Option to skip heavy per-video enrichment API calls
    enrich = data.get('enrich', True)
    
    # ── Phase 1: Try Original Query ──
    print(f"[Search Request] query='{query}' results={max_results} enrich={enrich}", flush=True)
    
    # Call the imported algorithm
    results, backend_used = search_youtube_links(
        query=query, 
        max_results=max_results, 
        timeout=25.0, 
        enrich=enrich
    )

    # ── Phase 2: Fallback to Simplified Query ──
    if not results and query:
        simp = simplify_query(query)
        if simp != query.lower():
            print(f"[Search] No results, fallback to: '{simp}'", flush=True)
            results, backend_used = search_youtube_links(
                query=simp, 
                max_results=max_results, 
                timeout=25.0, 
                enrich=enrich
            )

    # ── Filter by duration if requested in JSON ──
    d_min = data.get('duration_min')
    d_max = data.get('duration_max')
    if d_min or d_max:
        filtered_results = []
        for r in results:
            dur = r.get('duration_seconds')
            if dur is None:
                continue
            if d_min and dur < d_min:
                continue
            if d_max and dur > d_max:
                continue
            filtered_results.append(r)
        results = filtered_results

    # ── Return Final JSON ──
    return jsonify({
        "success": len(results) > 0,
        "query": query,
        "results_count": len(results),
        "backend_used": backend_used,
        "results": results,
        "error": "No results found" if not results else None
    })


@app.route('/health', methods=['GET'])
@app.route('/ping', methods=['GET'])
def health():
    return jsonify({
        "status": "ok", 
        "service": "yt-enriched-search"
    }), 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 7860))
    app.run(host='0.0.0.0', port=port)
