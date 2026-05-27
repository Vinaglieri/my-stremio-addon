import trakt_client as trakt
import logging
import upstash_client as cache
import json

log = logging.getLogger(__name__)

COUCHMONEY_KEYWORDS = ["couchmoney", "recommended for", "since you watched", "because you"]
TRAKT_TO_STREMIO = {"movie": "movie", "show": "series"}
RELATED_CACHE_TTL = 21600  # 6 hours

def _poster(item):
    imgs = item.get("images", {})
    for key in ("poster", "thumb"):
        vals = imgs.get(key, [])
        if isinstance(vals, list) and vals:
            url = vals[0]
            if isinstance(url, str):
                return url if url.startswith("http") else f"https://{url}"
    poster_path = item.get("poster_path")
    if poster_path:
        return f"https://image.tmdb.org/t/p/w342/{poster_path}"
    return None


def _find_couchmoney_list():
    lists = trakt.get_user_lists()
    if not lists:
        return None
    for lst in lists:
        name = lst.get("name", "").lower()
        if any(kw in name for kw in COUCHMONEY_KEYWORDS):
            return lst
    return None


def _couchmoney_recs(media_type, limit=20):
    lst = _find_couchmoney_list()
    if not lst:
        return None
    list_id = lst.get("ids", {}).get("trakt")
    if not list_id:
        return None
    items = trakt._api(f"/users/me/lists/{list_id}/items/{media_type}s?limit={limit}&extended=images")
    if not items:
        return None
    results = []
    for item in items:
        m = item.get(media_type, {})
        ids = m.get("ids", {})
        imdb = ids.get("imdb", "")
        if not imdb:
            continue
        results.append({
            "id": imdb,
            "type": TRAKT_TO_STREMIO.get(media_type, media_type),
            "name": m.get("title", ""),
            "year": m.get("year"),
            "poster": _poster(m),
            "posterShape": "regular",
            "genres": m.get("genres", []),
            "overview": m.get("overview", ""),
        })
    return results


def _scored_related_movies():
    """Score all watched movies' related lists.

    Returns {imdb_id: {score, title, year, poster, genres, overview}} dict,
    cached in Upstash for 6 hours.
    """
    cached = cache.get("scored_related")
    if cached:
        try:
            return json.loads(cached)
        except Exception:
            pass

    watched = trakt.get_watched_movies()
    if not watched:
        return {}

    watched_imdbs = set()
    for item in watched:
        imdb = item.get("movie", {}).get("ids", {}).get("imdb")
        if imdb:
            watched_imdbs.add(imdb)

    scores = {}
    details = {}

    for item in watched:
        imdb = item.get("movie", {}).get("ids", {}).get("imdb")
        if not imdb:
            continue
        related = trakt.get_related_movies(imdb, 10)
        if not related:
            continue
        for rel in related:
            rid = rel.get("ids", {}).get("imdb")
            if not rid or rid in watched_imdbs:
                continue
            scores[rid] = scores.get(rid, 0) + 1
            if rid not in details:
                details[rid] = {
                    "title": rel.get("title", ""),
                    "year": rel.get("year"),
                    "poster": _poster(rel),
                    "genres": rel.get("genres", []),
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
            "genres": d.get("genres", []),
            "overview": d.get("overview", ""),
        }

    cache.set("scored_related", json.dumps(result), ex=RELATED_CACHE_TTL)
    return result


def recommended_movies(limit=50):
    scored = _scored_related_movies()
    if scored:
        log.info("Using related-movie scoring (%d candidates)", len(scored))
        sorted_ids = sorted(scored.items(), key=lambda x: (-x[1]["score"], x[0]))[:limit]
        return [
            {
                "id": rid,
                "type": "movie",
                "name": d["title"],
                "year": d["year"],
                "poster": d["poster"],
                "posterShape": "regular" if d.get("poster") else None,
                "genres": d["genres"],
                "overview": d["overview"],
            }
            for rid, d in sorted_ids
        ]

    couch = _couchmoney_recs("movie", limit)
    if couch:
        log.info("Using Couchmoney movie list (%d items)", len(couch))
        return couch

    log.info("Falling back to Trakt API recommendations")
    recs = trakt.get_recommendations_movies(min(limit, 20))
    if recs:
        return _to_catalog(recs, "movie")
    return []


def _scored_related_shows():
    """Score all watched shows' related lists, cached."""
    cached = cache.get("scored_related_shows")
    if cached:
        try:
            return json.loads(cached)
        except Exception:
            pass

    watched = trakt.get_watched_shows()
    if not watched:
        return {}

    watched_imdbs = set()
    for item in watched:
        imdb = item.get("show", {}).get("ids", {}).get("imdb")
        if imdb:
            watched_imdbs.add(imdb)

    scores = {}
    details = {}

    for item in watched:
        imdb = item.get("show", {}).get("ids", {}).get("imdb")
        if not imdb:
            continue
        related = trakt.get_related_shows(imdb, 10)
        if not related:
            continue
        for rel in related:
            rid = rel.get("ids", {}).get("imdb")
            if not rid or rid in watched_imdbs:
                continue
            scores[rid] = scores.get(rid, 0) + 1
            if rid not in details:
                details[rid] = {
                    "title": rel.get("title", ""),
                    "year": rel.get("year"),
                    "poster": _poster(rel),
                    "genres": rel.get("genres", []),
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
            "genres": d.get("genres", []),
            "overview": d.get("overview", ""),
        }

    cache.set("scored_related_shows", json.dumps(result), ex=RELATED_CACHE_TTL)
    return result


def recommended_shows(limit=50):
    scored = _scored_related_shows()
    if scored:
        log.info("Using related-show scoring (%d candidates)", len(scored))
        sorted_ids = sorted(scored.items(), key=lambda x: (-x[1]["score"], x[0]))[:limit]
        return [
            {
                "id": rid,
                "type": "series",
                "name": d["title"],
                "year": d["year"],
                "poster": d["poster"],
                "posterShape": "regular" if d.get("poster") else None,
                "genres": d["genres"],
                "overview": d["overview"],
            }
            for rid, d in sorted_ids
        ]

    couch = _couchmoney_recs("show", limit)
    if couch:
        log.info("Using Couchmoney show list (%d items)", len(couch))
        return couch

    log.info("Falling back to Trakt API recommendations")
    recs = trakt.get_recommendations_shows(min(limit, 20))
    if recs:
        return _to_catalog(recs, "show")
    return []


def _to_catalog(items, media_type):
    results = []
    for item in items:
        m = item if media_type == "movie" else item.get("show", item)
        ids = m.get("ids", {})
        imdb = ids.get("imdb", "")
        if not imdb:
            continue
        results.append({
            "id": imdb,
            "type": TRAKT_TO_STREMIO.get(media_type, media_type),
            "name": m.get("title", ""),
            "year": m.get("year"),
            "poster": _poster(m),
            "posterShape": "regular",
            "genres": m.get("genres", []),
            "overview": m.get("overview", ""),
        })
    return results


def since_watched(movie_id):
    import re as _re
    movie_id_clean = _re.match(r'(tt\d+)', movie_id)
    movie_id = movie_id_clean.group(1) if movie_id_clean else movie_id
    related = trakt.get_related_movies(movie_id, 20)
    if related:
        results = []
        for item in related:
            ids = item.get("ids", {})
            imdb = ids.get("imdb", "")
            if not imdb:
                continue
            results.append({
                "id": imdb,
                "type": "movie",
                "name": item.get("title", ""),
                "year": item.get("year"),
                "poster": _poster(item),
                "posterShape": "regular",
                "genres": item.get("genres", []),
                "overview": item.get("overview", ""),
            })
        return results[:10]
    couch = _couchmoney_recs("movie", 20)
    if couch:
        return [c for c in couch if c["id"] != movie_id][:10]
    return []
