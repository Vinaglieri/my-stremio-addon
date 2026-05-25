import os
import re
import requests

JACKETT_URL = os.environ.get("JACKETT_URL", "")
JACKETT_API_KEY = os.environ.get("JACKETT_API_KEY", "")

def search_jackett(query, category="tv,movies"):
    if not JACKETT_URL or not JACKETT_API_KEY:
        return []

    params = {
        "apikey": JACKETT_API_KEY,
        "Query": query,
        "Category": category,
    }

    try:
        r = requests.get(f"{JACKETT_URL.rstrip('/')}/api/v2.0/indexers/all/results",
                         params=params, timeout=15)
        r.raise_for_status()
        data = r.json()

        results = []
        for item in data.get("Results", []):
            magnet = ""
            for link in item.get("Links", []):
                if link.startswith("magnet:"):
                    magnet = link
                    break
            if not magnet:
                for attr in item.get("Attributes", []):
                    if attr.get("Value", "").startswith("magnet:"):
                        magnet = attr["Value"]
                        break
            if not magnet:
                continue

            title = item.get("Title", "")
            size = item.get("Size", 0)
            seeders = item.get("Seeders", 0)

            results.append({
                "title": title,
                "magnet": magnet,
                "size": size,
                "seeders": seeders,
                "source": item.get("Tracker", "jackett"),
                "indexer": item.get("Tracker", "unknown"),
            })

        return results
    except Exception:
        return []

def search_public(query, category="movie"):
    results = []

    try:
        r = requests.get(
            "https://apibay.org/q.php",
            params={"q": query, "cat": category},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list):
                for item in data:
                    if not item.get("name"):
                        continue
                    title = item.get("name", "")
                    info_hash = item.get("info_hash", "")
                    if not info_hash:
                        continue
                    magnet = f"magnet:?xt=urn:btih:{info_hash}&dn={title}"
                    results.append({
                        "title": title,
                        "magnet": magnet,
                        "size": int(item.get("size", 0)),
                        "seeders": int(item.get("seeders", 0)),
                        "source": "public",
                        "indexer": "piratebay",
                    })
    except Exception:
        pass

    results.sort(key=lambda x: x["seeders"], reverse=True)
    return results[:30]

def search(query, imdb_id=None):
    results = []

    jackett_results = search_jackett(query)
    results.extend(jackett_results)

    if not results or len(results) < 5:
        public_results = search_public(query)
        existing_hashes = {r["magnet"] for r in results}
        for pr in public_results:
            if pr["magnet"] not in existing_hashes:
                results.append(pr)

    results.sort(key=lambda x: x["seeders"], reverse=True)
    return results[:50]

def parse_quality(title):
    title_lower = title.lower()
    if "2160" in title_lower or "4k" in title_lower or "uhd" in title_lower:
        return 2160
    if "1080" in title_lower or "fhd" in title_lower:
        return 1080
    if "720" in title_lower or "hd" in title_lower:
        return 720
    if "480" in title_lower:
        return 480
    return None

def is_hevc(title):
    return "hevc" in title.lower() or "x265" in title.lower() or "h265" in title.lower()
