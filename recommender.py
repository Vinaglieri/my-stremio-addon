import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import simkl_client as simkl
import upstash_client as cache

log = logging.getLogger(__name__)

CACHE_TTL = 86400
CACHE_KEY_MOVIES = "recommender:catalog:movie"
CACHE_KEY_SHOWS = "recommender:catalog:series"

POOL_SIZE = 200  # deep candidate pool for plan-to-watch; catalog display still uses limit

SIMKL_IMG = "https://wsrv.nl/?url=https://simkl.in"


def _get_cached(key):
    raw = cache.get(key)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _simkl_poster(path):
    if path:
        return f"{SIMKL_IMG}/posters/{path}_m.webp&q=90"
    return None


def _seed_simkl_id(item):
    if item.get("ids", {}).get("simkl"):
        return item["ids"]["simkl"]
    for key in ("movie", "show"):
        if item.get(key, {}).get("ids", {}).get("simkl"):
            return item[key]["ids"]["simkl"]
    return None


def _recommendation_counts(get_watched, media_type):
    watched = get_watched()
    if not watched:
        return {}

    watched_simkl = set()
    tasks = []
    for item in watched:
        sid = _seed_simkl_id(item)
        if sid:
            watched_simkl.add(sid)
            tasks.append(sid)

    counts = {}

    def recs_for(sid):
        d = simkl.detail(media_type, sid)
        if not d:
            return None
        return d.get("users_recommendations", [])

    with ThreadPoolExecutor(max_workers=10) as executor:
        future_map = {executor.submit(recs_for, sid): sid for sid in tasks}
        for future in as_completed(future_map):
            try:
                recs = future.result()
            except Exception:
                continue
            if not recs:
                continue
            for r in recs:
                rid = r.get("ids", {}).get("simkl")
                if not rid or rid in watched_simkl:
                    continue
                counts[rid] = counts.get(rid, 0) + 1

    return counts


def _to_catalog(counts, media_type, limit):
    if not counts:
        return []

    top_ids = sorted(counts.items(), key=lambda x: (-x[1], x[0]))[:limit]
    top_sids = [sid for sid, _ in top_ids]

    details = {}

    def detail_for(sid):
        return sid, simkl.detail(media_type, sid)

    with ThreadPoolExecutor(max_workers=10) as executor:
        future_map = {executor.submit(detail_for, sid): sid for sid in top_sids}
        for future in as_completed(future_map):
            sid = future_map[future]
            try:
                _, d = future.result()
            except Exception:
                continue
            if d and d.get("ids", {}).get("imdb"):
                details[sid] = d

    items = []
    for sid, _ in top_ids:
        d = details.get(sid)
        if not d:
            continue
        items.append({
            "id": d["ids"]["imdb"],
            "type": media_type,
            "name": d.get("title", ""),
            "year": d.get("year"),
            "poster": _simkl_poster(d.get("poster")),
            "posterShape": "regular" if d.get("poster") else None,
            "overview": d.get("overview", ""),
        })
    return items


def _compute_catalog(get_watched, simkl_type, catalog_type, key, limit):
    counts = _recommendation_counts(get_watched, simkl_type)
    if not counts:
        return []
    log.info("Using Simkl users_recommendations (%d candidates)", len(counts))
    items = _to_catalog(counts, catalog_type, POOL_SIZE)
    if items:
        cache.set(key, json.dumps(items), CACHE_TTL)
    return items[:limit]


def recommended_movies(limit=50):
    cached = _get_cached(CACHE_KEY_MOVIES)
    if cached is not None:
        log.info("Using cached movie catalog (%d items)", len(cached))
        return cached[:limit]
    return _compute_catalog(simkl.get_watched_movies, "movie", "movie", CACHE_KEY_MOVIES, limit)


def recommended_shows(limit=50):
    cached = _get_cached(CACHE_KEY_SHOWS)
    if cached is not None:
        log.info("Using cached show catalog (%d items)", len(cached))
        return cached[:limit]
    return _compute_catalog(simkl.get_watched_shows, "tv", "series", CACHE_KEY_SHOWS, limit)


def rebuild():
    """Recompute both catalogs (cache-miss path), return (movies, shows)."""
    movies = _compute_catalog(simkl.get_watched_movies, "movie", "movie", CACHE_KEY_MOVIES, 50)
    shows = _compute_catalog(simkl.get_watched_shows, "tv", "series", CACHE_KEY_SHOWS, 50)
    return movies, shows


def push_plan_to_watch(target=50):
    """Fill Simkl Plan to Watch up to `target` per type (add-only).

    Scans the ranked pool (POOL_SIZE deep) and adds top untracked titles
    until each list holds `target` items. Watching/completed/hold/dropped
    statuses are never overwritten.
    """
    for key, media_type, simkl_type in (
        (CACHE_KEY_MOVIES, "movie", "movies"),
        (CACHE_KEY_SHOWS, "series", "shows"),
    ):
        items = _get_cached(key) or []
        if not items:
            continue
        existing = simkl.get_list_statuses(simkl_type)
        already = sum(
            1 for it in items
            if it.get("id") and existing.get(it["id"]) == "plantowatch"
        )
        need = max(0, target - already)
        to_add = []
        for it in items:
            if len(to_add) >= need:
                break
            sid = it.get("id")
            if sid and existing.get(sid) is None:
                to_add.append(sid)
        if not to_add:
            continue
        result = simkl.add_to_list("plantowatch", {simkl_type: to_add})
        log.info("plan-to-watch %s: +%d titles (target %d)", simkl_type, len(to_add), target)
        if result == "unauthorized":
            return False
    return True
