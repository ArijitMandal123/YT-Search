---
title: YouTube Search API
emoji: 🔍
colorFrom: red
colorTo: blue
sdk: docker
pinned: false
---

# yt-search API Service

A simple, headless HTTP service that searches YouTube and returns direct stream URLs (video or audio) using `yt-dlp`. Designed to be deployed on the Render Free Tier and called from n8n for automation pipelines.

## Deployment on Render

1. Create a new Web Service on Render.
2. Connect your GitHub repository containing these files.
3. Use the following settings (can be automatically applied if you use the `render.yaml`):
   - **Environment:** Docker
   - **Plan:** Free
   - **Region:** Oregon (or your preferred region)
   - **Start Command:** Automatically inferred from Dockerfile.
   - **Health Check Path:** `/`

## API Usage

### 1. `GET /` - Health Check/Keep-Alive
Returns the current status to keep the Render service awake and verify it's working.
```json
{
  "status": "alive",
  "timestamp": "2026-04-07T12:00:00.000000",
  "service": "yt-search-api"
}
```

### 2. `POST /search` - Search and Extract

Send a JSON body with the following parameters to perform a search.

**Request Body Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | **Yes** | - | Search query OR a direct YouTube video URL. |
| `type` | string | No | `"any"` | `"video"` (prefers combined streams), `"audio"` (prefers audio only), or `"any"`. |
| `max_results` | int | No | `1` | Number of results to return. |
| `duration_min`| int | No | None | Minimum duration in seconds. |
| `duration_max`| int | No | None | Maximum duration in seconds. |
| `prefer_format`| string| No | None | Extension preference, e.g., `"mp4"`, `"webm"`, `"m4a"`. |
| `max_filesize_mb`| float| No | None | Maximum allowed filesize in MB. |
| `quality` | string| No | `"best"`| Quality preference: `"best"`, `"worst"`, `"720p"`, `"1080p"`, etc. |

**Example: Simple Audio Request**
```json
{
  "query": "lofi hip hop radio",
  "type": "audio",
  "max_results": 1,
  "prefer_format": "m4a",
  "quality": "best"
}
```

**Example: Advanced Video Request (Naruto Opening)**
```json
{
  "query": "naruto opening 1 song no lyric",
  "type": "video",
  "max_results": 1,
  "quality": "1080p",
  "duration_min": 30,
  "duration_max": 300,
  "max_filesize_mb": 150
}
```

**Full Specification (All Supported Parameters)**
```json
{
  "query": "your search term or youtube url",
  "type": "video",           // "video" | "audio" | "any"
  "max_results": 1,          // number of results to return
  "duration_min": 60,        // minimum duration in seconds
  "duration_max": 600,       // maximum duration in seconds
  "prefer_format": "mp4",    // "mp4", "webm", "m4a", "mp3", etc.
  "max_filesize_mb": 50.5,   // limit by file size in MB
  "quality": "1080p"         // "best", "worst", "720p", "1080p", "480p", etc.
}
```

**Example Response:**
```json
{
  "success": true,
  "query": "epic cinematic trailer music no copyright",
  "results_count": 1,
  "type": "audio",
  "search_method": "exact",
  "exact_match": true,
  "results": [
    {
      "title": "Epic Cinematic Trailer Music",
      "url": "https://www.youtube.com/watch?v=...",
      "stream_url": "https://rr3---sn-....googlevideo.com/...",
      "duration": 185,
      "duration_formatted": "3:05",
      "length": "0:03:05",
      "length_seconds": 185,
      "format": "m4a",
      "filesize_mb": 4.12,
      "vcodec": "none",
      "acodec": "mp4a.40.2",
      "fps": null,
      "resolution": null,
      "channel": "No Copyright Music",
      "upload_date": "20240101",
      "view_count": 500000,
      "thumbnail": "https://i.ytimg.com/vi/.../maxresdefault.jpg"
    }
  ]
}
```

## n8n Integration

1. Add an **HTTP Request** node to your n8n workflow.
2. Set **Method** to `POST`.
3. Set **URL** to your Render deployment URL (e.g., `https://yt-search-api.onrender.com/search`).
4. Set **Send Body** to `true`.
5. Set **Body Content Type** to `JSON`.
6. Pass the parameters via the node configuration:
   ```json
   {
     "query": "={{ $json.searchTerm }}",
     "type": "video",
     "quality": "1080p"
   }
   ```
7. To access the `stream_url` from the output, use an expression like:
   `{{ $json.results[0].stream_url }}`

## Setup Keep-Alive Cron in n8n

Render free tiers sleep after 15 minutes of inactivity. To prevent this, you can set up a cron job in n8n.
1. Add a **Schedule Trigger** node.
2. Set the interval to **14 minutes**.
3. Connect it to an **HTTP Request** node calling `GET https://your-render-app-url.onrender.com/`.

## Avoiding YouTube's "Sign in to confirm you are not a bot"

If you encounter this error, it means YouTube is blocking your IP. To fix this:

1.  **Update yt-dlp:** Run `.\venv\Scripts\python -m pip install -U yt-dlp` in your terminal.
2.  **Export Cookies:** If updating doesn't work:
    - Install the **"Get cookies.txt"** extension in Chrome or Firefox.
    - Go to YouTube and log in.
    - Click the extension and export your cookies as a text file named `cookies.txt`.
    - Place the `cookies.txt` file in the same folder as `app.py`.
    - The API will automatically detect and use it for authentication.

## Notes
- If an exact match can't be found (or filters exclude all results), the API will attempt a "similar" fallback search by shortening the query.
- Pass a direct YouTube URL in the `query` field to extract streams immediately without searching.
- **Lightweight & Fast:** This tool only extracts metadata; it never downloads or saves files to your server's storage.
