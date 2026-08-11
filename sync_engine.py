import json
import logging
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import recommender
import simkl_client as simkl
import stremio_client as stremio
import upstash_client as cache

log = logging.getLogger(__name__)

SYNC_INTERVAL = 600  # throttle: at most one sync per 10 min
LOCK_KEY = "sync:lock"
LAST_RUN_KEY = "sync:last_run"
STATE_KEY = "sync:synced"
ACTIVITIES_KEY = "sync:activities_ts"

MAX_HISTORY_WORKERS = 10


def sync_on_open():
    """Run a Stremio->Simkl sync + rebuild synchronously if due.

    Called from the manifest route (Stremio opening the addon). Runs inline in
    the request — no background thread, so it always completes on Cloud Run.
    Throttled to once per SYNC_INTERVAL via Redis lock.
    """
    if not stremio.is_configured() or not simkl.is_authed():
        return

    last_run = cache.get(LAST_RUN_KEY)
    if last_run:
        try:
            elapsed = time.time() - float(last_run)
        except (TypeError, ValueError):
            elapsed = float("inf")
        if elapsed < SYNC_INTERVAL:
            return

    if not _acquire_lock():
        return
    t0 = time.time()
    try:
        _do_sync()
    except Exception:
        log.exception("sync failed")
    finally:
        cache.set(LAST_RUN_KEY, str(time.time()))
        _exec_redis("DEL", LOCK_KEY)
        log.info("sync_on_open finished in %.1fs", time.time() - t0)


def _acquire_lock():
    try:
        r = _exec_redis("SET", LOCK_KEY, "1", "EX", str(SYNC_INTERVAL), "NX")
        return r == "OK"
    except Exception:
        return False


def _exec_redis(*args):
    import requests as http
    from upstash_client import TOKEN, URL
    if not URL or not TOKEN:
        return None
    r = http.post(
        URL,
        json=args,
        headers={"Authorization": f"Bearer {TOKEN}"},
        timeout=5,
    )
    data = r.json()
    return data.get("result")


def _do_sync():
    activities = simkl.activities()
    if activities == "unauthorized":
        log.error("Simkl token invalid (401)")
        return
    if not isinstance(activities, dict):
        log.warning("activities check failed: %r", activities)

    old_ts = _load_activities_ts()

    synced = _load_state()

    movies, series = stremio.collect_watched()
    if movies or series:
        _sync_history(movies, series, synced)

    new_ts = _activities_ts(simkl.activities())
    changed = new_ts != old_ts
    cache.set(ACTIVITIES_KEY, json.dumps(new_ts))

    if changed:
        log.info("Simkl data changed, rebuilding catalogs")
        movies_items, shows_items = recommender.rebuild()
        if movies_items or shows_items:
            recommender.push_plan_to_watch()
    else:
        log.info("No Simkl activity change, skipping rebuild")


def _activities_ts(activities):
    if not isinstance(activities, dict):
        return {}
    out = {}
    for group in ("movies", "tv_shows"):
        sub = activities.get(group)
        if isinstance(sub, dict):
            out[group] = sub.get("completed")
    return out


def _load_activities_ts():
    raw = cache.get(ACTIVITIES_KEY)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {}


def _load_state():
    raw = cache.get(STATE_KEY)
    if not raw:
        return {"movie_ids": [], "episode_keys": []}
    try:
        state = json.loads(raw)
    except (TypeError, ValueError):
        return {"movie_ids": [], "episode_keys": []}
    return {
        "movie_ids": list(state.get("movie_ids", [])),
        "episode_keys": list(state.get("episode_keys", [])),
    }


def _save_state(state):
    cache.set(STATE_KEY, json.dumps(state))


def _sync_history(movies, series, state):
    synced_ids = set(state["movie_ids"])
    synced_ep_keys = set(state["episode_keys"])

    movie_payload = []
    for movie in movies:
        if movie["imdb_id"] in synced_ids:
            continue
        entry = {"ids": {"imdb": movie["imdb_id"]}}
        if movie.get("last_watched"):
            entry["watched_at"] = movie["last_watched"]
        movie_payload.append(entry)

    if movie_payload:
        result = simkl.sync_history({"movies": movie_payload})
        if result == "unauthorized":
            log.error("Simkl token invalid (401) during movie sync")
            return
        if result:
            log.info("Synced %d movies to Simkl", len(movie_payload))
            for entry in movie_payload:
                synced_ids.add(entry["ids"]["imdb"])
            _save_state({"movie_ids": sorted(synced_ids), "episode_keys": sorted(synced_ep_keys)})
        else:
            log.warning("Simkl movie sync failed: %r", result)

    if not series:
        return

    # Fetch Cinemeta episode lists for all series in parallel (this was the
    # slow sequential phase that stalled the old background thread).
    def fetch_videos(imdb_id):
        return imdb_id, stremio.get_cinemeta_episodes(imdb_id)

    fetched = {}
    with ThreadPoolExecutor(max_workers=MAX_HISTORY_WORKERS) as executor:
        future_map = {
            executor.submit(fetch_videos, imdb_id): imdb_id
            for imdb_id in series
        }
        for future in as_completed(future_map):
            try:
                imdb_id, videos = future.result()
                fetched[imdb_id] = videos
            except Exception:
                continue

    for imdb_id, s in series.items():
        cinemeta_videos = fetched.get(imdb_id)
        if not cinemeta_videos:
            continue
        episodes = stremio.map_bitfield_to_episodes(imdb_id, s["watched"], cinemeta_videos)
        if not episodes:
            continue
        new_eps = [
            (season, ep) for season, ep in episodes
            if f"{imdb_id}:{season}:{ep}" not in synced_ep_keys
        ]
        if not new_eps:
            continue

        seasons_map = defaultdict(list)
        for season, ep in new_eps:
            seasons_map[season].append(ep)

        payload = {
            "shows": [{
                "ids": {"imdb": imdb_id},
                "seasons": [
                    {"number": s, "episodes": [{"number": e} for e in sorted(eps)]}
                    for s, eps in sorted(seasons_map.items())
                ],
            }]
        }
        result = simkl.sync_history(payload)
        if result == "unauthorized":
            log.error("Simkl token invalid (401) during series sync")
            return
        if result:
            count = sum(len(eps) for eps in seasons_map.values())
            log.info("Synced %d episodes: %s", count, s["name"])
            for season, ep in new_eps:
                synced_ep_keys.add(f"{imdb_id}:{season}:{ep}")
            _save_state({"movie_ids": sorted(synced_ids), "episode_keys": sorted(synced_ep_keys)})
        else:
            log.warning("Simkl episode sync failed for %s: %r", imdb_id, result)
