"""
Search YouTube by query using public Piped API instances, then Invidious APIs.
Tries several instances in order because public hosts often move, rate-limit, or go offline.

Each hit is a dict with URL, title, duration, views, likes/dislikes (when enrichment succeeds),
channel + subscriber counts, thumbnails, tags, category/genre, and other fields; see
``search_youtube_links`` return value and ``--json`` CLI output.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from typing import Any

import requests

# Piped: GET {base}/search?q=...&filter=videos  → JSON { "items": [ ... ] }
# From https://github.com/TeamPiped/documentation/blob/main/content/docs/public-instances/index.md
# (trim or reorder this list as you like)
PIPED_API_BASES: tuple[str, ...] = (
    "https://pipedapi.kavin.rocks",
    "https://pipedapi-libre.kavin.rocks",
    "https://piped-api.privacy.com.de",
    "https://pipedapi.adminforge.de",
    "https://api.piped.yt",
    "https://pipedapi.leptons.xyz",
    "https://pipedapi.nosebs.ru",
    "https://pipedapi.drgns.space",
    "https://pipedapi.owo.si",
    "https://pipedapi.ducks.party",
    "https://piped-api.codespace.cz",
    "https://pipedapi.reallyaweso.me",
    "https://api.piped.private.coffee",
    "https://pipedapi.darkness.services",
    "https://pipedapi.orangenet.cc",
)

# Invidious: GET {base}/api/v1/search?q=...&type=video  → JSON array
INVIDIOUS_BASES: tuple[str, ...] = (
    "https://vid.puffyan.us",
    "https://invidious.fdn.fr",
    "https://inv.tux.pizza",
    "https://invidious.flokinet.to",
    "https://invidious.privacydev.net",
    "https://yt.artemislena.eu",
    "https://invidious.projectsegfau.lt",
    "https://inv.nadeko.net",
)

YT_VIDEO_URL = "https://www.youtube.com/watch?v={video_id}"

# YouTube video IDs are 11 characters from this set (covers normal and some livestream ids)
_VIDEO_ID_RE = re.compile(r"(?:[?&/]v=|youtu\.be/|^)([0-9A-Za-z_-]{11})(?:\?|&|$|/|\")?")


def _looks_like_json_object(body: str) -> bool:
    b = body.lstrip()
    return bool(b) and b[0] == "{"


def _looks_like_json_array(body: str) -> bool:
    b = body.lstrip()
    return bool(b) and b[0] == "["


def extract_video_id(text: str | None) -> str | None:
    if not text:
        return None
    m = _VIDEO_ID_RE.search(text.strip())
    return m.group(1) if m else None


def _positive_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    if n < 0:
        return None
    return n


def _format_duration(seconds: int | None) -> str | None:
    if seconds is None or seconds < 0:
        return None
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _format_int(n: int | None) -> str | None:
    if n is None:
        return None
    return f"{n:,}"


def _snippet_plain_text(html_text: str, max_len: int) -> str:
    """Strip basic HTML for terminal display (JSON output keeps the original string)."""
    t = html.unescape(re.sub(r"<br\s*/?>", "\n", html_text, flags=re.I))
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"[ \t\r\f\v]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n", t).strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 1].rstrip() + "…"


def _absolute_youtube_url(path_or_url: str | None) -> str | None:
    if not path_or_url or not isinstance(path_or_url, str):
        return None
    u = path_or_url.strip()
    if u.startswith("http://") or u.startswith("https://"):
        return u
    if u.startswith("/"):
        return f"https://www.youtube.com{u}"
    return u


def _invidious_best_thumbnail(item: dict[str, Any]) -> str | None:
    thumbs = item.get("videoThumbnails")
    if not isinstance(thumbs, list) or not thumbs:
        return None
    best = None
    best_w = -1
    for t in thumbs:
        if not isinstance(t, dict):
            continue
        url = t.get("url")
        if not isinstance(url, str):
            continue
        w = t.get("width")
        wi = int(w) if isinstance(w, (int, float)) else 0
        if wi >= best_w:
            best_w = wi
            best = url
    return best


def _video_from_piped_item(item: dict[str, Any]) -> dict[str, Any] | None:
    if item.get("type") != "stream":
        return None
    title = str(item.get("title") or "").strip() or "(no title)"
    vid = extract_video_id(item.get("url")) or extract_video_id(item.get("id"))
    if not vid:
        return None
    un = item.get("uploaderName")
    channel = str(un).strip() if isinstance(un, str) and str(un).strip() else None
    dur = _positive_int(item.get("duration"))
    views = _positive_int(item.get("views"))
    upload_ms = item.get("uploaded")
    published_ts: int | None = None
    if isinstance(upload_ms, (int, float)) and upload_ms > 0:
        published_ts = int(upload_ms // 1000) if upload_ms > 10_000_000_000 else int(upload_ms)

    return {
        "youtube_url": YT_VIDEO_URL.format(video_id=vid),
        "video_id": vid,
        "title": title,
        "channel": channel,
        "channel_url": _absolute_youtube_url(item.get("uploaderUrl")),
        "duration_seconds": dur,
        "duration_display": _format_duration(dur),
        "views": views,
        "views_display": _format_int(views),
        "likes": None,
        "dislikes": None,
        "rating": None,
        "upload_display": str(item.get("uploadedDate")).strip() if item.get("uploadedDate") else None,
        "upload_date_iso": None,
        "published_timestamp": published_ts,
        "channel_subscribers": None,
        "channel_subscribers_display": None,
        "category": None,
        "genre": None,
        "tags": None,
        "verified": bool(item.get("uploaderVerified")) if item.get("uploaderVerified") is not None else None,
        "is_short": bool(item.get("isShort")) if item.get("isShort") is not None else None,
        "live_now": bool(item.get("isLive")) if item.get("isLive") is not None else None,
        "thumbnail": item.get("thumbnail") if isinstance(item.get("thumbnail"), str) else None,
        "description": str(item.get("shortDescription")).strip() if item.get("shortDescription") else None,
        "allow_ratings": None,
        "is_family_friendly": None,
        "paid": None,
        "premium": None,
    }


def _merge_piped_streams_payload(payload: dict[str, Any], video: dict[str, Any]) -> None:
    likes = _positive_int(payload.get("likes"))
    dislikes = _positive_int(payload.get("dislikes"))
    views = _positive_int(payload.get("views"))
    subs = _positive_int(payload.get("uploaderSubscriberCount"))
    dur = _positive_int(payload.get("duration"))
    if likes is not None:
        video["likes"] = likes
    if dislikes is not None:
        video["dislikes"] = dislikes
    if views is not None:
        video["views"] = views
        video["views_display"] = _format_int(views)
    if dur is not None:
        video["duration_seconds"] = dur
        video["duration_display"] = _format_duration(dur)
    if isinstance(payload.get("uploadDate"), str) and payload.get("uploadDate"):
        video["upload_date_iso"] = str(payload["uploadDate"])
    if isinstance(payload.get("category"), str) and payload.get("category"):
        video["category"] = str(payload["category"]).strip()
    if subs is not None:
        video["channel_subscribers"] = subs
        video["channel_subscribers_display"] = _format_int(subs)
    tags = payload.get("tags")
    if isinstance(tags, list) and tags:
        video["tags"] = [str(t) for t in tags if isinstance(t, str)]
    if isinstance(payload.get("description"), str) and payload.get("description").strip():
        video["description"] = str(payload["description"]).strip()


def _enrich_piped_video(session: requests.Session, api_base: str, video: dict[str, Any], timeout: float) -> None:
    vid = video.get("video_id")
    if not isinstance(vid, str):
        return
    url = f"{api_base.rstrip('/')}/streams/{vid}"
    try:
        r = session.get(url, timeout=timeout)
    except requests.RequestException:
        return
    if r.status_code != 200 or not _looks_like_json_object(r.text):
        return
    try:
        payload = r.json()
    except ValueError:
        return
    if not isinstance(payload, dict):
        return
    _merge_piped_streams_payload(payload, video)


def _video_from_invidious_item(item: dict[str, Any]) -> dict[str, Any] | None:
    if item.get("type") != "video":
        return None
    vid = item.get("videoId")
    if not isinstance(vid, str) or not re.fullmatch(r"[0-9A-Za-z_-]{11}", vid):
        return None
    title = str(item.get("title") or "").strip() or "(no title)"
    dur = _positive_int(item.get("lengthSeconds"))
    views = _positive_int(item.get("viewCount"))
    likes = _positive_int(item.get("likeCount"))
    dislikes = _positive_int(item.get("dislikeCount"))
    published = item.get("published")
    published_ts: int | None = None
    if isinstance(published, (int, float)) and published > 0:
        published_ts = int(published)

    return {
        "youtube_url": YT_VIDEO_URL.format(video_id=vid),
        "video_id": vid,
        "title": title,
        "channel": str(item.get("author")).strip() if item.get("author") else None,
        "channel_url": _absolute_youtube_url(item.get("authorUrl")),
        "duration_seconds": dur,
        "duration_display": _format_duration(dur),
        "views": views,
        "views_display": _format_int(views),
        "likes": likes,
        "dislikes": dislikes,
        "rating": float(item["rating"]) if isinstance(item.get("rating"), (int, float)) else None,
        "upload_display": str(item.get("publishedText")).strip() if item.get("publishedText") else None,
        "upload_date_iso": None,
        "published_timestamp": published_ts,
        "channel_subscribers": None,
        "channel_subscribers_display": str(item.get("subCountText")).strip() if item.get("subCountText") else None,
        "category": None,
        "genre": str(item.get("genre")).strip() if item.get("genre") else None,
        "tags": None,
        "verified": bool(item.get("authorVerified")) if item.get("authorVerified") is not None else None,
        "is_short": bool(item.get("isShort")) if item.get("isShort") is not None else None,
        "live_now": bool(item.get("liveNow")) if item.get("liveNow") is not None else None,
        "thumbnail": _invidious_best_thumbnail(item),
        "description": str(item.get("description")).strip() if item.get("description") else None,
        "allow_ratings": bool(item.get("allowRatings")) if item.get("allowRatings") is not None else None,
        "is_family_friendly": bool(item.get("isFamilyFriendly")) if item.get("isFamilyFriendly") is not None else None,
        "paid": bool(item.get("paid")) if item.get("paid") is not None else None,
        "premium": bool(item.get("premium")) if item.get("premium") is not None else None,
    }


def _merge_invidious_video_payload(payload: dict[str, Any], video: dict[str, Any]) -> None:
    likes = _positive_int(payload.get("likeCount"))
    dislikes = _positive_int(payload.get("dislikeCount"))
    views = _positive_int(payload.get("viewCount"))
    dur = _positive_int(payload.get("lengthSeconds"))
    if likes is not None:
        video["likes"] = likes
    if dislikes is not None:
        video["dislikes"] = dislikes
    if views is not None:
        video["views"] = views
        video["views_display"] = _format_int(views)
    if dur is not None:
        video["duration_seconds"] = dur
        video["duration_display"] = _format_duration(dur)
    if isinstance(payload.get("subCountText"), str) and payload.get("subCountText"):
        video["channel_subscribers_display"] = str(payload["subCountText"]).strip()
    subc = _positive_int(payload.get("subCount"))
    if subc is not None:
        video["channel_subscribers"] = subc
        if not video.get("channel_subscribers_display"):
            video["channel_subscribers_display"] = _format_int(subc)
    if isinstance(payload.get("genre"), str) and payload.get("genre"):
        video["genre"] = str(payload["genre"]).strip()
    kw = payload.get("keywords")
    if isinstance(kw, list) and kw:
        video["tags"] = [str(x) for x in kw if isinstance(x, str)]
    if isinstance(payload.get("description"), str) and payload.get("description").strip():
        video["description"] = str(payload["description"]).strip()
    if isinstance(payload.get("rating"), (int, float)):
        video["rating"] = float(payload["rating"])
    for key_src, key_dst in (
        ("allowRatings", "allow_ratings"),
        ("isFamilyFriendly", "is_family_friendly"),
        ("paid", "paid"),
        ("premium", "premium"),
        ("liveNow", "live_now"),
        ("authorVerified", "verified"),
    ):
        if payload.get(key_src) is not None:
            video[key_dst] = payload.get(key_src)


def _enrich_invidious_video(session: requests.Session, base: str, video: dict[str, Any], timeout: float) -> None:
    vid = video.get("video_id")
    if not isinstance(vid, str):
        return
    url = f"{base.rstrip('/')}/api/v1/videos/{vid}"
    try:
        r = session.get(url, timeout=timeout)
    except requests.RequestException:
        return
    if r.status_code != 200 or not _looks_like_json_object(r.text):
        return
    try:
        payload = r.json()
    except ValueError:
        return
    if not isinstance(payload, dict):
        return
    _merge_invidious_video_payload(payload, video)


def _piped_items_to_videos(items: list[dict[str, Any]], limit: int, duration_min: int | None = None, duration_max: int | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items:
        if len(out) >= limit:
            break
        if not isinstance(item, dict):
            continue
        row = _video_from_piped_item(item)
        if row:
            dur = row.get("duration_seconds")
            # Filter live streams (dur = 0 or None) if duration filters exist
            if dur is None or dur == 0:
                if duration_min or duration_max:
                    continue
            else:
                if duration_min and dur < duration_min:
                    continue
                if duration_max and dur > duration_max:
                    continue
            out.append(row)
    return out


def _invidious_items_to_videos(items: list[dict[str, Any]], limit: int, duration_min: int | None = None, duration_max: int | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items:
        if len(out) >= limit:
            break
        if not isinstance(item, dict):
            continue
        row = _video_from_invidious_item(item)
        if row:
            dur = row.get("duration_seconds")
            if dur is None or dur == 0:
                if duration_min or duration_max:
                    continue
            else:
                if duration_min and dur < duration_min:
                    continue
                if duration_max and dur > duration_max:
                    continue
            out.append(row)
    return out


def _optional_invidious_instances_from_registry(session: requests.Session, timeout: float) -> list[str]:
    """Merge in instances that advertise API support (often empty or Cloudflare-blocked)."""
    try:
        r = session.get("https://api.invidious.io/instances.json", timeout=timeout)
        if not r.ok or not _looks_like_json_array(r.text):
            return []
        data = r.json()
        uris: list[str] = []
        for row in data:
            if not isinstance(row, (list, tuple)) or len(row) < 2:
                continue
            info = row[1]
            if not isinstance(info, dict):
                continue
            if not info.get("api"):
                continue
            uri = info.get("uri")
            if isinstance(uri, str) and uri.startswith("http"):
                uris.append(uri.rstrip("/"))
        return uris
    except (requests.RequestException, ValueError, TypeError):
        return []


def search_youtube_links(
    query: str,
    *,
    max_results: int = 10,
    timeout: float = 25.0,
    enrich: bool = True,
    duration_min: int | None = None,
    duration_max: int | None = None,
    session: requests.Session | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """
    Return (list of video detail dicts, label_of_working_backend).

    Tries each Piped API base, then each Invidious base (plus optional registry entries).

    When ``enrich`` is True, Piped results call ``/streams/{id}`` per video for likes/dislikes
    and fuller metadata; Invidious results call ``/api/v1/videos/{id}`` similarly.
    """
    if not query.strip():
        return [], ""

    own_session = session is None
    sess = session or requests.Session()
    sess.headers.setdefault(
        "User-Agent",
        "Mozilla/5.0 (compatible; YT-Search/0.1; +https://github.com/)",
    )

    invidious_bases = list(INVIDIOUS_BASES)
    for extra in _optional_invidious_instances_from_registry(sess, min(timeout, 15.0)):
        if extra not in invidious_bases:
            invidious_bases.append(extra)

    # --- Piped ---
    for base in PIPED_API_BASES:
        base = base.rstrip("/")
        url = f"{base}/search"
        params = {"q": query, "filter": "videos"}
        try:
            r = sess.get(url, params=params, timeout=timeout)
        except requests.RequestException:
            continue
        if r.status_code != 200 or not _looks_like_json_object(r.text):
            continue
        try:
            payload = r.json()
        except ValueError:
            continue
        items = payload.get("items")
        if not isinstance(items, list):
            continue
        results = _piped_items_to_videos(items, max_results, duration_min, duration_max)
        if results:
            if enrich:
                per = min(20.0, max(5.0, timeout))
                for v in results:
                    _enrich_piped_video(sess, base, v, per)
            if own_session:
                sess.close()
            return results, f"piped:{base}"

    # --- Invidious ---
    for base in invidious_bases:
        base = base.rstrip("/")
        url = f"{base}/api/v1/search"
        params: dict[str, str] = {"q": query, "type": "video"}
        try:
            r = sess.get(url, params=params, timeout=timeout)
        except requests.RequestException:
            continue
        if r.status_code != 200 or not _looks_like_json_array(r.text):
            continue
        try:
            payload = r.json()
        except ValueError:
            continue
        if not isinstance(payload, list):
            continue
        results = _invidious_items_to_videos(payload, max_results, duration_min, duration_max)
        if results:
            if enrich:
                per = min(20.0, max(5.0, timeout))
                for v in results:
                    _enrich_invidious_video(sess, base, v, per)
            if own_session:
                sess.close()
            return results, f"invidious:{base}"

    if own_session:
        sess.close()
    return [], ""


def _configure_stdio_utf8() -> None:
    """Avoid UnicodeEncodeError on Windows consoles when titles contain emoji."""
    for stream in (sys.stdout, sys.stderr):
        reconf = getattr(stream, "reconfigure", None)
        if callable(reconf):
            try:
                reconf(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


def main(argv: list[str] | None = None) -> int:
    _configure_stdio_utf8()
    parser = argparse.ArgumentParser(description="Search YouTube links via Piped/Invidious (public instances).")
    parser.add_argument("query", nargs="*", help="Search words (if empty, you will be prompted)")
    parser.add_argument("-n", "--max-results", type=int, default=10, help="Max videos to print (default: 10)")
    parser.add_argument("--timeout", type=float, default=25.0, help="Per-request timeout in seconds")
    parser.add_argument(
        "--no-enrich",
        action="store_true",
        help="Skip extra per-video API calls (likes/dislikes, full description, etc.)",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON array of full video records")
    args = parser.parse_args(argv)

    query = " ".join(args.query).strip()
    if not query:
        query = input("Search query: ").strip()
    if not query:
        print("Empty query.", file=sys.stderr)
        return 1

    results, via = search_youtube_links(
        query,
        max_results=args.max_results,
        timeout=args.timeout,
        enrich=not args.no_enrich,
    )
    if not results:
        print(
            "No results: every Piped/Invidious instance failed or returned no videos. "
            "Edit PIPED_API_BASES / INVIDIOUS_BASES in main.py or try again later.",
            file=sys.stderr,
        )
        return 2

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(f"Using {via}\n")
        # output loop omitted for brevity in main script as Flask will handle it
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
