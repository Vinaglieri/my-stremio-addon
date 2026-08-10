import os
import time
import requests
import upstash_client as cache

CLIENT_ID = os.environ.get("SIMKL_CLIENT_ID", "")
API = "https://api.simkl.com"

HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "VinaglieriPersonal/1.1.0 (personal stremio addon)",
}

def request_pin():
    r = requests.get(
        f"{API}/oauth/pin",
        params={"client_id": CLIENT_ID},
        headers={"User-Agent": HEADERS["User-Agent"]},
        timeout=15,
    )
    if r.status_code != 200:
        return None
    return r.json()

def poll_pin(user_code):
    r = requests.get(
        f"{API}/oauth/pin/{user_code}",
        params={"client_id": CLIENT_ID},
        headers={"User-Agent": HEADERS["User-Agent"]},
        timeout=15,
    )
    if r.status_code != 200:
        return None
    return r.json()

def store_token(access_token):
    cache.set("simkl_access_token", access_token)
    cache.set("simkl_created_at", str(int(time.time())))

def _api(path, params=None):
    token = cache.get("simkl_access_token")
    if not token:
        return None
    headers = {**HEADERS, "Authorization": f"Bearer {token}"}
    qparams = {"client_id": CLIENT_ID}
    if params:
        qparams.update(params)
    r = requests.get(f"{API}{path}", headers=headers, params=qparams, timeout=15)
    if r.status_code == 200:
        return r.json()
    return None

def is_authed():
    return bool(cache.get("simkl_access_token"))

def get_watched_movies():
    data = _api("/sync/all-items/movies/completed", params={"extended": "full"})
    if not data:
        return None
    return data.get("movies", [])

def get_watched_shows():
    data = _api("/sync/all-items/shows/completed", params={"extended": "full"})
    if not data:
        return None
    return data.get("shows", [])

def get_ratings():
    return _api("/sync/ratings", params={"extended": "full"})

def detail(media_type, simkl_id):
    path = f"/movies/{simkl_id}" if media_type == "movie" else f"/tv/{simkl_id}"
    try:
        r = requests.get(
            f"{API}{path}",
            params={"client_id": CLIENT_ID},
            headers={"User-Agent": HEADERS["User-Agent"]},
            timeout=15,
        )
    except requests.exceptions.RequestException:
        return None
    if r.status_code != 200:
        return None
    data = r.json()
    return data if isinstance(data, dict) else None
