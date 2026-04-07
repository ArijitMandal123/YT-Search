# YouTube Search API Service (yt-search)

A REST API service that accepts search queries via n8n, uses `yt-dlp` to find YouTube videos/audio, and returns direct stream URLs with full metadata.

## Proposed Changes

### Project Structure

```
yt-search/
├── app.py              # Flask API server with all endpoints
├── requirements.txt    # Python dependencies
├── Dockerfile          # For Render deployment
├── render.yaml         # Render service config
├── .gitignore          # Git ignore rules
└── README.md           # Documentation
```

---

### [NEW] app.py — Main API Server (Flask)

**Endpoints:**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/` | GET | Health check / cron keep-alive endpoint |
| `/search` | POST | Search YouTube & return URL + metadata |

**`/search` Request Body (JSON):**

```json
{
  "query": "epic anime battle OST",
  "type": "video",           // "video" | "audio" | "any"
  "max_results": 3,          // how many results to return (default: 1)
  "duration_min": null,       // minimum duration in seconds
  "duration_max": null,       // maximum duration in seconds
  "prefer_format": "mp4",    // preferred format (mp4, webm, m4a, etc.)
  "max_filesize_mb": null,   // max filesize filter in MB
  "quality": "best"          // "best" | "worst" | "720p" | "1080p" | "480p"
}
```

**`/search` Response (JSON):**

```json
{
  "success": true,
  "query": "epic anime battle OST",
  "type": "video",
  "results_count": 2,
  "exact_match": true,
  "results": [
    {
      "title": "Epic Anime Battle OST Mix",
      "url": "https://www.youtube.com/watch?v=...",
      "stream_url": "https://rr3---sn-...googlevideo.com/...",
      "duration": 345,
      "duration_formatted": "5:45",
      "filesize_mb": 42.5,
      "format": "mp4",
      "resolution": "1280x720",
      "fps": 30,
      "vcodec": "avc1.64001F",
      "acodec": "mp4a.40.2",
      "thumbnail": "https://i.ytimg.com/vi/.../maxresdefault.jpg",
      "channel": "AnimeOST",
      "upload_date": "2025-08-15",
      "view_count": 1234567
    }
  ],
  "search_method": "exact"    // "exact" | "similar"
}
```

**Search Logic:**
1. First search with the exact query using `yt-dlp`'s `ytsearch` extractor
2. Filter results by user-specified criteria (type, duration, filesize, etc.)
3. If no results match filters → relax filters slightly and retry with **similar** keywords (strip adjectives, try related terms)
4. Return `"search_method": "similar"` flag if fallback was used
5. Always return `"exact_match": false` if using fallback

**yt-dlp Integration:**
- Use `yt_dlp` Python library (not subprocess) for reliability
- Extract format info, stream URLs, and metadata in one call
- Select best matching format based on user preferences
- Handle geo-blocks, age-restrictions gracefully with error messages

---

### [NEW] requirements.txt

```
flask==3.1.1
gunicorn==23.0.0
yt-dlp>=2025.3.31
```

---

### [NEW] Dockerfile

- Based on `python:3.11-slim`
- Install `ffmpeg` (needed by yt-dlp for some operations)
- Install Python dependencies
- Run with `gunicorn` on port `10000` (Render default)

---

### [NEW] render.yaml

- Free tier web service
- Docker deployment
- Auto-deploy on push

---

### [NEW] .gitignore

Standard Python gitignore

---

### [NEW] README.md

Full API documentation with n8n integration examples

---

## Cron Keep-Alive

The `GET /` endpoint returns `{"status": "alive", "timestamp": "..."}` — you can point a cron job (e.g., from n8n or cron-job.org) to this URL every 14 minutes to keep the Render free tier service awake.

## n8n Integration

In n8n, use an **HTTP Request** node:
- Method: POST
- URL: `https://your-render-app.onrender.com/search`
- Body: JSON with search parameters
- Parse the response to extract `stream_url` and metadata

## Open Questions

> [!IMPORTANT]
> 1. Do you want **authentication** (API key) on the `/search` endpoint, or leave it open?
> 2. Should the service also support searching by **direct YouTube URL** (to just extract stream URLs from a known video)?
> 3. The Render free tier has **750 hours/month** and **512 MB RAM** — yt-dlp can be memory-hungry. Should I add memory-optimized settings?

## Verification Plan

### Automated Tests
- Start the Flask server locally and test endpoints with `curl`
- Verify search returns valid stream URLs
- Test edge cases (no results, invalid query, etc.)

### Manual Verification
- Deploy to Render and test via n8n HTTP Request node
- Verify cron keep-alive works
