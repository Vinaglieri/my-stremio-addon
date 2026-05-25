import re
import requests

def search_dmm(imdb_id):
    """Search Debrid Media Manager for RD-cached content by IMDb ID."""
    try:
        r = requests.get(
            f"https://api.debridmediamanager.com/v1/search",
            params={"imdb_id": imdb_id},
            timeout=15,
        )
        if r.status_code != 200:
            return []

        data = r.json()
        results = []
        for item in data if isinstance(data, list) else data.get("results", []):
            title = item.get("title", "")
            magnets = item.get("magnets", [])
            for m in magnets:
                magnet = m.get("magnet", "") or m.get("link", "")
                if not magnet:
                    continue
                hash_match = re.search(r'btih:([a-fA-F0-9]{40})', magnet)
                results.append({
                    "title": title or item.get("filename", ""),
                    "magnet": magnet,
                    "size": int(m.get("size", 0) or item.get("size", 0)),
                    "seeders": 999,
                    "source": "dmm",
                    "indexer": "dmm",
                })
        return results
    except Exception:
        return []


def search_piratebay(query):
    results = []
    try:
        r = requests.get(
            "https://apibay.org/q.php",
            params={"q": query, "cat": "0"},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list):
                for item in data:
                    title = item.get("name", "")
                    info_hash = item.get("info_hash", "")
                    if not title or not info_hash:
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
    return results


def search_1337x(query):
    results = []
    try:
        r = requests.get(
            f"https://1337x.to/search/{query}/1/",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        if r.status_code != 200:
            return results

        html = r.text
        for match in re.finditer(
            r'<tr>.*?href="(/torrent/.*?)".*?>(.*?)</a>.*?'
            r'<td class="coll-2">(.*?)</td>.*?'
            r'<td class="coll-3">(.*?)</td>.*?'
            r'<td class="coll-4">(.*?)</td>',
            html, re.DOTALL
        ):
            href = match.group(1)
            name = match.group(2).strip()
            seeders_str = match.group(4).strip()

            try:
                detail = requests.get(
                    f"https://1337x.to{href}",
                    headers={"User-Agent": "Mozilla/5.0"},
                    timeout=10,
                )
                if detail.status_code == 200:
                    magnet_match = re.search(
                        r'href="(magnet:\?xt=urn:btih:[^"]+)"', detail.text
                    )
                    if magnet_match:
                        magnet = magnet_match.group(1)
                        results.append({
                            "title": name,
                            "magnet": magnet,
                            "size": 0,
                            "seeders": int(seeders_str) if seeders_str.isdigit() else 0,
                            "source": "public",
                            "indexer": "1337x",
                        })
            except Exception:
                continue
    except Exception:
        pass
    return results


def search(query, imdb_id=None):
    results = []

    if imdb_id:
        dmm_results = search_dmm(imdb_id)
        results.extend(dmm_results)
        if dmm_results:
            return results[:30]

    pb_results = search_piratebay(query)
    existing = {r["magnet"] for r in results}
    for pr in pb_results:
        if pr["magnet"] not in existing:
            results.append(pr)
            existing.add(pr["magnet"])

    if len(results) < 10:
        x1337_results = search_1337x(query)
        for xr in x1337_results:
            if xr["magnet"] not in existing:
                results.append(xr)
                existing.add(xr["magnet"])

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
