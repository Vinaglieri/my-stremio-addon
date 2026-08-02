import os
import requests

API_KEY = os.environ.get("TMDB_API_KEY", "")
API = "https://api.themoviedb.org/3"

def _get(path, params=None):
    if not API_KEY:
        return None
    qparams = {"api_key": API_KEY}
    if params:
        qparams.update(params)
    r = requests.get(f"{API}{path}", params=qparams, timeout=15)
    if r.status_code == 200:
        return r.json()
    return None

def tmdb_id(imdb):
    data = _get(f"/find/{imdb}", {"external_source": "imdb_id"})
    if not data:
        return None
    for bucket in ("movie_results", "tv_results"):
        if data.get(bucket):
            return data[bucket][0].get("id")
    return None

def imdb_id(tmdb_id, media_type):
    data = _get(f"/{media_type}/{tmdb_id}/external_ids")
    return data.get("imdb_id") if data else None

def related(tmdb_id, media_type, limit=10):
    data = _get(f"/{media_type}/{tmdb_id}/similar", {"language": "en-US"})
    if not data:
        return []
    return [
        {
            "tmdb_id": item["id"],
            "title": item.get("title") or item.get("name", ""),
            "year": (item.get("release_date") or item.get("first_air_date") or "")[:4],
            "poster_path": item.get("poster_path"),
            "genre_ids": item.get("genre_ids", []),
            "overview": item.get("overview", ""),
        }
        for item in data.get("results", [])[:limit]
    ]
