import base64
import logging
import os
import zlib

import requests

log = logging.getLogger(__name__)

STREMIO_API = "https://api.strem.io"
CINEMETA_API = "https://v3-cinemeta.strem.io"

AUTH_KEY = os.environ.get("STREMIO_AUTH_KEY", "")


def is_configured():
    return bool(AUTH_KEY)


def stremio_request(method, params):
    body = {"authKey": AUTH_KEY, **params}
    try:
        r = requests.post(f"{STREMIO_API}/api/{method}", json=body, timeout=30)
    except requests.exceptions.RequestException:
        return None
    if r.status_code != 200:
        log.warning("Stremio API error (%s): %s", method, r.status_code)
        return None
    data = r.json()
    if data.get("error"):
        log.warning("Stremio API error (%s): %s", method, data["error"])
        return None
    return data.get("result")


def get_library_items():
    meta = stremio_request("datastoreMeta", {
        "collection": "libraryItem",
        "from": "linvo-p2p-sync",
    })
    if not meta:
        return []
    ids = [item[0] for item in meta if isinstance(item, list)]
    items = []
    for i in range(0, len(ids), 50):
        result = stremio_request("datastoreGet", {
            "collection": "libraryItem",
            "ids": ids[i:i + 50],
        })
        if result:
            items.extend(item for item in result if isinstance(item, dict))
    return items


def decode_watched_bitfield(watched_str):
    parts = watched_str.split(":")
    if len(parts) < 3:
        return set()
    b64 = parts[-1]
    bitfield_len = int(parts[-2])
    try:
        raw = base64.b64decode(b64)
        decompressed = zlib.decompress(raw)
    except Exception:
        return set()
    watched_positions = set()
    for i in range(bitfield_len):
        byte_idx = i // 8
        bit = i % 8
        if byte_idx < len(decompressed) and (decompressed[byte_idx] & (1 << bit)):
            watched_positions.add(i)
    return watched_positions


def get_cinemeta_episodes(imdb_id):
    try:
        r = requests.get(f"{CINEMETA_API}/meta/series/{imdb_id}.json", timeout=15)
    except requests.exceptions.RequestException:
        return []
    if r.status_code != 200:
        return []
    videos = r.json().get("meta", {}).get("videos", [])
    return [v for v in videos if v.get("season", 0) > 0]


def map_bitfield_to_episodes(imdb_id, watched_str, cinemeta_videos):
    if not cinemeta_videos:
        return set()
    parts = watched_str.split(":")
    if len(parts) < 3:
        return set()
    b64 = parts[-1]
    bitfield_len = int(parts[-2])
    last_video_id = ":".join(parts[:-2])

    try:
        raw = base64.b64decode(b64)
        decompressed = zlib.decompress(raw)
    except Exception:
        return set()

    watched_indices = set()
    for i in range(bitfield_len):
        byte_idx = i // 8
        bit = i % 8
        if byte_idx < len(decompressed) and (decompressed[byte_idx] & (1 << bit)):
            watched_indices.add(i)

    all_video_ids = [f"{imdb_id}:{v['season']}:{v['episode']}" for v in cinemeta_videos]
    try:
        last_idx = all_video_ids.index(last_video_id)
    except ValueError:
        last_idx = len(all_video_ids) - 1

    start_idx = max(0, last_idx - bitfield_len + 1)
    covered_ids = all_video_ids[start_idx:start_idx + bitfield_len]

    episodes = set()
    for idx in watched_indices:
        if idx < len(covered_ids):
            vid = covered_ids[idx]
            _, season, ep = vid.split(":")
            episodes.add((int(season), int(ep)))
    return episodes


def collect_watched():
    """Return (watched_movies, watched_series) from the Stremio library.

    watched_movies: [{imdb_id, name, last_watched}]
    watched_series: {imdb_id: {name, watched_bitfield, last_watched}}
    """
    items = get_library_items()
    movies = []
    series = {}
    for item in items:
        type_ = item.get("type", "movie")
        imdb_id = item.get("_id", "")
        if not imdb_id or not imdb_id.startswith("tt"):
            continue
        name = item.get("name", "?")
        state = item.get("state", {}) or {}
        if type_ == "movie":
            if state.get("timesWatched", 0) > 0 or state.get("flaggedWatched") == 1:
                movies.append({
                    "imdb_id": imdb_id,
                    "name": name,
                    "last_watched": state.get("lastWatched", ""),
                })
        elif type_ == "series":
            watched_bitfield = state.get("watched", "")
            if watched_bitfield:
                series[imdb_id] = {
                    "name": name,
                    "watched": watched_bitfield,
                    "last_watched": state.get("lastWatched", ""),
                }
    return movies, series
