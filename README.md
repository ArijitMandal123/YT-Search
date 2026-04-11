# 🎥 YouTube Discovery & Metadata API

A lightning-fast, highly-resilient REST API for searching YouTube and extracting rich video metadata **without getting IP blocked**. 

Built for automation pipelines, headless applications, and automated video generators that need reliable YouTube data without the unreliability of scraping or direct `yt-dlp` IP bans on datacenter networks.

---

## ⚡ Why Use This?
If you've tried running automated YouTube searches from cloud platforms, you know that YouTube aggressively blocks datacenter IPs with `429 Too Many Requests`, `404` stream errors, or "Sign in to confirm you're not a bot" screens.

**This API bypasses that entirely.**

Instead of scraping YouTube directly, it acts as an intelligent router that queries a massive rotating pool of public **Piped** and **Invidious** privacy frontends. It automatically falls back to healthy instances, ensuring maximum uptime for your search queries.

### Key Features
*   🛡️ **No IP Blocks:** Rotates through 20+ public API instances automatically.
*   ⏱️ **Lightning Fast:** Fast timeout thresholds drop dead proxies instantly to guarantee quick responses.
*   📊 **Rich Metadata:** Returns views, likes, exact durations, tags, descriptions, categories, and channel sub counts.
*   🎛️ **Pre-Filtering:** Built-in exact `duration_min` and `duration_max` filters prevents API starvation and returns exactly what you need.
*   🐳 **Universal Deployment:** Tiny Docker footprint (`python:3.11-slim`). Ready to be deployed to *any* cloud provider or local machine.

---

## 🚀 Deployment

You can deploy this API anywhere Docker or Python is supported.

### 1. Deploy via Docker (Any Cloud Provider)
Because the `Dockerfile` is included, you can instantly deploy this repository to **Hugging Face Spaces, Render, Heroku, AWS, DigitalOcean**, or any other container-based hosting platform.
Simply point your hosting provider to the repository and it will build and run on port `7860`.

### 2. Deploy Locally
```bash
# Clone the repository
git clone https://github.com/yourusername/yt-discovery-api.git
cd yt-discovery-api

# Install requirements
pip install -r requirements.txt

# Run the Flask server
python app.py
# Server runs on http://localhost:7860
```

---

## 📖 API Documentation

**Endpoint:** `POST /search`  
**Content-Type:** `application/json`

### Complete JSON Request Parameters

This API accepts the following payload. You can mix and match parameters to precisely narrow down your search results.

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `query` | string | **[Required]** | The search terms (e.g., "anime raw aesthetic 4k") |
| `max_results` | int | `10` | The maximum number of videos to return. |
| `duration_min` | int | `null` | Minimum video duration in **seconds**. (Filters out live-streams and clips that are too short). |
| `duration_max` | int | `null` | Maximum video duration in **seconds**. (Filters out long movies/podcasts). |
| `enrich` | bool | `true` | Set to `false` for raw speed. `true` fetches deep metrics (tags, likes, category) per video. |

### The Ultimate Example Request
```json
{
  "query": "Jujutsu Kaisen Gojo vs Sukuna raw 1080p no subs",
  "max_results": 1,
  "duration_min": 30,
  "duration_max": 240,
  "enrich": true
}
```

### Complete Details of the JSON Response
When a video is found and enriched, the API provides every possible detail you could need for automation:

```json
{
  "backend_used": "piped:https://pipedapi.kavin.rocks",
  "error": null,
  "query": "Jujutsu Kaisen Gojo vs Sukuna raw 1080p no subs",
  "results_count": 1,
  "success": true,
  "results": [
    {
      "allow_ratings": null,
      "category": "Entertainment",
      "channel": "Anime Raw Clips Daily",
      "channel_subscribers": 450000,
      "channel_subscribers_display": "450,000",
      "channel_url": "https://www.youtube.com/channel/UC...",
      "description": "Gojo vs Sukuna full fight raw 1080p high quality without subtitles...",
      "dislikes": null,
      "duration_display": "2:30",
      "duration_seconds": 150,
      "genre": null,
      "is_family_friendly": null,
      "is_short": false,
      "likes": 125430,
      "live_now": false,
      "paid": null,
      "premium": null,
      "published_timestamp": 1690000000,
      "rating": null,
      "tags": [
        "anime",
        "jujutsu kaisen",
        "gojo",
        "raw",
        "1080p"
      ],
      "thumbnail": "https://proxy.piped.../hq720.jpg",
      "title": "Gojo vs Sukuna Epic Fight [RAW]",
      "upload_date_iso": "2023-07-22",
      "upload_display": "2 years ago",
      "verified": false,
      "video_id": "ABC123xyz45",
      "views": 2500000,
      "views_display": "2,500,000",
      "youtube_url": "https://www.youtube.com/watch?v=ABC123xyz45"
    }
  ]
}
```

---

## 💡 Example Queries for specific use-cases

**1. Finding vertical Shorts/TikToks:**
```json
{
  "query": "Motivational stoic speech vertical 9:16",
  "duration_max": 59,
  "max_results": 3,
  "enrich": true
}
```

**2. Finding cinematic background B-Roll:**
```json
{
  "query": "Cyberpunk 2077 Night City rain driving 4k raw no commentary",
  "duration_min": 300,
  "duration_max": 1200,
  "max_results": 1,
  "enrich": false
}
```

**3. Finding pure audio/soundtracks:**
```json
{
  "query": "Hans Zimmer Interstellar Stay official soundtrack",
  "duration_min": 200,
  "max_results": 1,
  "enrich": true
}
```

---

## 🛠️ Architecture Notes

*   **`app.py`**: The main Flask web wrapper. It handles JSON payload parsing and graceful fallback filtering. It intelligently drops overly-specific keywords if the first search yields 0 results.
*   **`youtube_fetcher.py`**: The core extraction algorithm. It houses hardcoded lists of verified `PIPED_API_BASES` and `INVIDIOUS_BASES`. It routes the request sequentially through independent proxies, enforces duration filters natively, coordinates JSON mapping, handles stream timeouts, and fires off secondary "enrichment" requests for metadata.

## 🤝 Contributing
If the API starts timing out or returning empty results, it usually means the default public instances have temporarily rate-limited the network. Feel free to submit a pull request modifying the `PIPED_API_BASES` or `INVIDIOUS_BASES` lists inside `youtube_fetcher.py`!
