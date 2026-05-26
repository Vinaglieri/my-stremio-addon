import trakt_client as trakt
import logging

log = logging.getLogger(__name__)

COUCHMONEY_KEYWORDS = ["couchmoney", "recommended for", "since you watched", "because you"]

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
            "type": media_type,
            "name": m.get("title", ""),
            "year": m.get("year"),
            "poster": _poster(m),
            "posterShape": "regular",
            "genres": m.get("genres", []),
            "overview": m.get("overview", ""),
        })
    return results


def recommended_movies(limit=20):
    couch = _couchmoney_recs("movie", limit)
    if couch:
        log.info("Using Couchmoney movie list (%d items)", len(couch))
        return couch
    log.info("Couchmoney not found, using Trakt API")
    recs = trakt.get_recommendations_movies(limit)
    if recs:
        return _to_catalog(recs, "movie")
    return []


def recommended_shows(limit=20):
    couch = _couchmoney_recs("show", limit)
    if couch:
        log.info("Using Couchmoney show list (%d items)", len(couch))
        return couch
    log.info("Couchmoney not found, using Trakt API")
    recs = trakt.get_recommendations_shows(limit)
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
            "type": media_type,
            "name": m.get("title", ""),
            "year": m.get("year"),
            "poster": _poster(m),
            "posterShape": "regular",
            "genres": m.get("genres", []),
            "overview": m.get("overview", ""),
        })
    return results


def since_watched(movie_id):
    couch = _couchmoney_recs("movie", 20)
    if couch:
        return [c for c in couch if c["id"] != movie_id][:10]
    genre_stats = trakt.get_genre_stats()
    top_genres = list(genre_stats.keys())[:3]
    recs = trakt.get_recommendations_movies(20)
    if not recs:
        return []
    results = []
    for item in recs:
        ids = item.get("ids", {})
        imdb = ids.get("imdb", "")
        if not imdb or imdb == movie_id:
            continue
        item_genres = set(item.get("genres", []))
        overlap = item_genres & set(top_genres)
        if overlap or not results:
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
