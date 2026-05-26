import os
import requests

URL = os.environ.get("UPSTASH_REDIS_REST_URL", "")
TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")

def _exec(*args):
    if not URL or not TOKEN:
        return None
    try:
        r = requests.post(
            URL,
            json=args,
            headers={"Authorization": f"Bearer {TOKEN}"},
            timeout=5,
        )
        return r.json()
    except Exception:
        return None

def get(key):
    r = _exec("GET", key)
    if r and r.get("result"):
        return r["result"]
    return None

def set(key, value, ttl=None):
    if ttl:
        _exec("SET", key, value, "EX", ttl)
    else:
        _exec("SET", key, value)
