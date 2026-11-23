#!/usr/bin/env python3
"""Daily private-playlist-safe discovery from a pre-vetted public artist pool.

The private 2,515-track CSV is NOT uploaded to this public repository.
The public pool contains ONLY artists absent from that CSV snapshot.
For each day select one guitar-rock and one exploratory artist, look up their
current catalogue through the free iTunes Search API, and use only official
streaming previews with links to the corresponding Apple catalogue page.

No paid APIs, persistent tokens, or web page scraping are used.
"""
import datetime as dt
import hashlib
import json
import pathlib
import re
import unicodedata

ROOT = pathlib.Path(__file__).resolve().parents[1]
POOL = ROOT / "data" / "discovery_artists.json"
BASE_DATE = dt.date(2026, 11, 23)


def normalize(value):
    value = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return "".join(ch for ch in value if ch.isalnum())


def catalog_for_artist(artist, fetch_json):
    """Retrieve verified original artist recordings, streamed by Apple."""
    try:
        response = fetch_json("https://itunes.apple.com/search", {
            "term": artist, "media": "music", "entity": "song",
            "country": "JP", "limit": 200
        })
    except Exception as exc:
        print("MUSIC DISCOVERY search failed:", artist, type(exc).__name__, flush=True)
        return []
    tracks = []
    seen = set()
    for entry in response.get("results", []):
        if not isinstance(entry, dict):
            continue
        # Avoid accidental covers and compilations by a different artist.
        if normalize(entry.get("artistName")) != normalize(artist):
            continue
        preview = entry.get("previewUrl")
        store = entry.get("trackViewUrl")
        title = entry.get("trackName")
        track_id = entry.get("trackId")
        if (not isinstance(title, str) or not title.strip() or
            not isinstance(preview, str) or not preview.startswith("https://") or
            not isinstance(store, str) or not store.startswith("https://")):
            continue
        if normalize(title) in seen:
            continue
        seen.add(normalize(title))
        tracks.append({
            "artist": entry.get("artistName", artist),
            "title": title,
            "preview_url": preview,
            "store_url": store,
            "url": store,
            "apple_track_id": track_id,
        })
    # Preserve Apple search relevance while preferring unambiguous track names.
    return tracks


def daily_recommendations(today, fetch_json, pool=None):
    """Automatically give two different artists/genres each day.

    Position within each group rotates daily; catalogue track index advances
    on every subsequent cycle, so the same song is not intentionally repeated.
    Fail closed: a recommendation requires a confirmed Apple preview.
    """
    day = dt.date.fromisoformat(today)
    day_number = max(0, (day - BASE_DATE).days)
    if pool is None:
        pool = json.loads(POOL.read_text(encoding="utf-8"))["artists"]
    groups = {
        "rock": [a for a in pool if a["group"] == "rock"],
        "explore": [a for a in pool if a["group"] == "explore"],
    }
    for category, members in groups.items():
        # A fixed permutation keeps the schedule stable between workflows.
        members.sort(key=lambda a: hashlib.sha256(
            ("v1|" + category + "|" + a["name"]).encode("utf-8")
        ).hexdigest())
    results = []
    selected_artists = set()
    # First slot: familiar guitar energy. Second: adventurous adjacent sound.
    for group in ("rock", "explore"):
        artists = groups[group]
        if not artists:
            continue
        for attempt in range(min(9, len(artists))):
            absolute = day_number + attempt
            index = absolute % len(artists)
            cycle = absolute // len(artists)
            item = artists[index]
            artist_key = normalize(item["name"])
            if artist_key in selected_artists:
                continue
            catalog = catalog_for_artist(item["name"], fetch_json)
            if not catalog:
                continue
            # Revisit the artist only after a full rotation. Choose a new
            # distinct track each time unless its catalogue has been exhausted.
            track = catalog[cycle % len(catalog)]
            track["reason"] = item["reason"]
            track["discovery_group"] = group
            results.append(track)
            selected_artists.add(artist_key)
            break
    # On regional store outages, don't fabricate or resort to link-only songs.
    print("MUSIC DISCOVERY", today,
          "chosen=", [(s["artist"], s["title"]) for s in results],
          flush=True)
    return results


if __name__ == "__main__":
    from scripts.generate import get_json
    print(json.dumps(daily_recommendations(
        dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date().isoformat(),
        get_json), ensure_ascii=False, indent=2))
