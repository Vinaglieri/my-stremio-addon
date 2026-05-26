import trakt_client as trakt
import logging

log = logging.getLogger(__name__)

COUCHMONEY_KEYWORDS = ["couchmoney", "recommended for", "since you watched", "because you"]

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
    items = trakt._api(f"/users/me/lists/{list_id}/items/{media_type}s?limit={limit}")
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
            "type": "movie",
            "name": item.get("title", ""),
            "year": item.get("year"),
            "poster": _poster(item, "movie"),
            "posterShape": "regular",
            "genres": item.get("genres", []),
            "overview": item.get("overview", ""),
        })
    return results[:10]
