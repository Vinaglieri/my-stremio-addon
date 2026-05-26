import os
import requests
from urllib.parse import urlencode
import upstash_client as cache

CLIENT_ID = os.environ.get("TRAKT_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("TRAKT_CLIENT_SECRET", "")
REDIRECT_URI = os.environ.get("TRAKT_REDIRECT_URI", "")
API = "https://api.trakt.tv"
OAUTH = "https://trakt.tv"

HEADERS = {
    "Content-Type": "application/json",
    "trakt-api-version": "2",
    "trakt-api-key": CLIENT_ID,
}

def auth_url():
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
    }
    return f"{OAUTH}/oauth/authorize?{urlencode(params)}"

def exchange_code(code):
    r = requests.post(f"{OAUTH}/oauth/token", json={
        "code": code,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
    }, timeout=10)
    if r.status_code == 200:
        data = r.json()
        cache.set("trakt_access_token", data["access_token"])
        cache.set("trakt_refresh_token", data["refresh_token"])
        cache.set("trakt_created_at", str(data.get("created_at", "")))
        return data
    return None

def refresh_token():
    refresh = cache.get("trakt_refresh_token")
    if not refresh:
        return False
    r = requests.post(f"{OAUTH}/oauth/token", json={
        "refresh_token": refresh,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "refresh_token",
    }, timeout=10)
    if r.status_code == 200:
        data = r.json()
        cache.set("trakt_access_token", data["access_token"])
        cache.set("trakt_refresh_token", data["refresh_token"])
        return True
    return False

def _api(path, params=None):
    token = cache.get("trakt_access_token")
    if not token:
        return None
    headers = {**HEADERS, "Authorization": f"Bearer {token}"}
    r = requests.get(f"{API}{path}", headers=headers, params=params, timeout=15)
    if r.status_code == 401:
        if refresh_token():
            token = cache.get("trakt_access_token")
            headers["Authorization"] = f"Bearer {token}"
            r = requests.get(f"{API}{path}", headers=headers, params=params, timeout=15)
    if r.status_code == 200:
        return r.json()
    return None

def _api_post(path, data=None):
    token = cache.get("trakt_access_token")
    if not token:
        return None
    headers = {**HEADERS, "Authorization": f"Bearer {token}"}
    r = requests.post(f"{API}{path}", headers=headers, json=data or {}, timeout=15)
    if r.status_code == 401:
        if refresh_token():
            token = cache.get("trakt_access_token")
            headers["Authorization"] = f"Bearer {token}"
            r = requests.post(f"{API}{path}", headers=headers, json=data or {}, timeout=15)
    if r.status_code in (200, 201):
        return r.json()
    return None

def is_authed():
    return bool(cache.get("trakt_access_token"))

def get_watched_movies():
    return _api("/sync/watched/movies")

def get_watched_shows():
    return _api("/sync/watched/shows")

def get_ratings():
    return _api("/sync/ratings")

def get_recommendations_movies(limit=20):
    return _api(f"/recommendations/movies?limit={limit}&extended=images")

def get_recommendations_shows(limit=20):
    return _api(f"/recommendations/shows?limit={limit}&extended=images")

def get_user_lists():
    return _api("/users/me/lists")

def get_list_items(list_id, limit=20):
    return _api(f"/users/me/lists/{list_id}/items/{'movies' if list_id else 'movies'}?limit={limit}")

def get_user_settings():
    return _api("/users/settings")

def get_list_slug(list_id, items):
    slug = None
    for item in items:
        if item.get("ids", {}).get("slug"):
            slug = item["ids"]["slug"]
            break
    return slug

def get_user_settings():
    return _api("/users/settings")

def get_genre_stats():
    ratings = get_ratings()
    if not ratings:
        return {}
    genres = {}
    for r_item in ratings:
        if r_item.get("type") == "movie":
            movie = r_item.get("movie", {})
            item_genres = movie.get("genres", [])
            rating = r_item.get("rating", 0)
            for g in item_genres:
                genres[g] = genres.get(g, 0) + rating
    return dict(sorted(genres.items(), key=lambda x: x[1], reverse=True))

def scrobble(imdb_id, episode=None, action="start"):
    data = {
        "movie": {"ids": {"imdb": imdb_id}},
        "action": action,
        "progress": 0,
    }
    if episode:
        s, e = episode
        data = {
            "show": {"ids": {"imdb": imdb_id}},
            "episode": {"season": s, "number": e},
            "action": action,
            "progress": 0,
        }
    return _api_post("/scrobble", data)

def rate(imdb_id, rating, episode=None):
    data = {"movies": [{"ids": {"imdb": imdb_id}, "rating": rating}]}
    if episode:
        s, e = episode
        data = {"shows": [{"show": {"ids": {"imdb": imdb_id}}, "episode": {"season": s, "number": e}, "rating": rating}]}
    return _api_post("/sync/ratings", data)
