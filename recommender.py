import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import simkl_client as simkl
import tmdb_client as tmdb
import upstash_client as cache

log = logging.getLogger(__name__)

CACHE_TTL = 86400
CACHE_KEY_MOVIES = "recommender:catalog:movie"
CACHE_KEY_SHOWS = "recommender:catalog:series"


def _get_cached(key):
    raw = cache.get(key)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _poster(item):
    poster_path = item.get("poster_path")
    if poster_path:
        return f"https://image.tmdb.org/t/p/w342/{poster_path}"
    return None


def _weight(seed):
    r = seed.get("user_rating") or seed.get("rating")
    if r and r >= 7:
        return 3
    if r and r >= 4:
        return 2
    return 1


def _seed_imdb(item):
    if item.get("ids", {}).get("imdb"):
        return item["ids"]["imdb"]
    for key in ("movie", "show"):
        if item.get(key, {}).get("ids", {}).get("imdb"):
            return item[key]["ids"]["imdb"]
    return None


def _scored_related(tmdb_type, get_watched):
    watched = get_watched()
    if not watched:
        return {}

    watched_imdbs = set()
    tasks = []
    for item in watched:
        imdb = _seed_imdb(item)
        if imdb:
            watched_imdbs.add(imdb)
            tasks.append(item)

    scores = {}
    details = {}

    def related_for(seed):
        imdb = _seed_imdb(seed)
        if not imdb:
            return imdb, None
        tid = tmdb.tmdb_id(imdb)
        if not tid:
            return imdb, None
        return imdb, tmdb.related(tid, tmdb_type, 10)

    with ThreadPoolExecutor(max_workers=10) as executor:
        future_map = {executor.submit(related_for, seed): seed for seed in tasks}
        for future in as_completed(future_map):
            seed = future_map[future]
            try:
                _, related = future.result()
            except Exception:
                continue
            if not related:
                continue
            weight = _weight(seed)
            for rel in related:
                rid = tmdb.imdb_id(rel.get("tmdb_id"), tmdb_type)
                if not rid or rid in watched_imdbs:
                    continue
                scores[rid] = scores.get(rid, 0) + weight
                if rid not in details:
                    details[rid] = {
                        "title": rel.get("title", ""),
                        "year": rel.get("year"),
                        "poster": _poster(rel),
                        "overview": rel.get("overview", ""),
                    }

    result = {}
    for rid, score in scores.items():
        d = details.get(rid, {})
        result[rid] = {
            "score": score,
            "title": d.get("title", ""),
            "year": d.get("year"),
            "poster": d.get("poster", ""),
            "overview": d.get("overview", ""),
        }
    return result


def _to_catalog(scored, media_type, limit):
    sorted_ids = sorted(scored.items(), key=lambda x: (-x[1]["score"], x[0]))[:limit]
    return [
        {
            "id": rid,
            "type": media_type,
            "name": d["title"],
            "year": d["year"],
            "poster": d["poster"],
            "posterShape": "regular" if d.get("poster") else None,
            "overview": d["overview"],
        }
        for rid, d in sorted_ids
    ]


def recommended_movies(limit=50):
    cached = _get_cached(CACHE_KEY_MOVIES)
    if cached is not None:
        log.info("Using cached movie catalog (%d items)", len(cached))
        return cached[:limit]
    scored = _scored_related("movie", simkl.get_watched_movies)
    if scored:
        log.info("Using TMDB related-movie scoring (%d candidates)", len(scored))
        items = _to_catalog(scored, "movie", limit)
        cache.set(CACHE_KEY_MOVIES, json.dumps(items), CACHE_TTL)
        return items
    return []


def recommended_shows(limit=50):
    cached = _get_cached(CACHE_KEY_SHOWS)
    if cached is not None:
        log.info("Using cached show catalog (%d items)", len(cached))
        return cached[:limit]
    scored = _scored_related("tv", simkl.get_watched_shows)
    if scored:
        log.info("Using TMDB related-show scoring (%d candidates)", len(scored))
        items = _to_catalog(scored, "series", limit)
        cache.set(CACHE_KEY_SHOWS, json.dumps(items), CACHE_TTL)
        return items
    return []
