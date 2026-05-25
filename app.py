import os
import re
import logging
import requests as http
from flask import Flask, jsonify

from rd_client import RealDebrid
from sources import search, parse_quality, is_hevc
from scoring import pick_best

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = Flask(__name__)

rd = RealDebrid()

try:
    rd_user = rd.check_credentials()
    if rd_user:
        log.info("Real-Debrid authenticated as %s", rd_user)
    else:
        log.warning("Real-Debrid not configured or invalid token")
except Exception:
    log.warning("Real-Debrid not configured")


@app.get("/")
def root():
    return "ok"


@app.get("/manifest.json")
def manifest():
    return jsonify({
        "id": "vinaglieri.addon",
        "version": "1.0.1",
        "name": "vinaglieri addon",
        "description": "Auto-picks the best Real-Debrid stream",
        "resources": ["stream"],
        "types": ["movie", "series"],
        "catalogs": [],
        "behaviorHints": {
            "configurable": False,
            "configurationRequired": False
        }
    })


def parse_imdb_id(raw_id):
    match = re.match(r'(tt\d+)', raw_id)
    return match.group(1) if match else None


def parse_episode(raw_id):
    match = re.match(r'tt\d+:(\d+):(\d+)', raw_id)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None, None


def build_search_query(imdb_id, season, episode):
    url = f"https://v3-cinemeta.strem.io/meta/{'series' if season else 'movie'}/{imdb_id}.json"
    try:
        r = http.get(url, timeout=10)
        if r.status_code == 200:
            meta = r.json().get("meta", {})
            name = meta.get("name", "")
            year = meta.get("year", "")
            if season:
                return f"{name} S{season:02d}E{episode:02d} {year}".strip()
            return f"{name} {year}".strip()
    except Exception:
        pass
    return imdb_id


@app.get("/stream/<stype>/<id>.json")
def stream(stype, id):
    log.info("Stream request: %s / %s", stype, id)

    imdb_id = parse_imdb_id(id)
    if not imdb_id:
        return jsonify({"streams": []})

    season, episode = parse_episode(id) if stype == "series" else (None, None)

    query = build_search_query(imdb_id, season, episode)
    log.info("Search query: %s", query)

    candidates = search(query, imdb_id)
    if not candidates:
        log.warning("No candidates found for %s", query)
        return jsonify({"streams": []})

    log.info("Found %d candidates, checking RD availability...", len(candidates))

    try:
        rd_availability = rd.check_cached_batch([s["magnet"] for s in candidates])
    except Exception:
        rd_availability = {}

    scored = pick_best(candidates, rd_availability)

    best_score, best_stream, _ = scored[0]
    log.info("Best stream: %s (score: %d)", best_stream["title"], best_score)

    download_url = None
    for score, s, cached in scored[:10]:
        try:
            url = rd.resolve_stream(s["magnet"], timeout_sec=45)
            if url:
                log.info("Resolved: %s (score: %d)", s["title"], score)
                download_url = url
                best_stream = s
                break
        except Exception as e:
            log.warning("Failed to resolve %s: %s", s["title"][:40], e)
            continue

    if not download_url:
        return jsonify({"streams": []})

    quality = parse_quality(best_stream["title"])
    quality_label = f"{quality}p" if quality else "??p"
    codec_label = " HDR" if is_hevc(best_stream["title"]) else ""
    size_gb = best_stream.get("size", 0) / (1024**3)
    size_label = f"{size_gb:.1f}GB" if size_gb > 0 else ""
    indexer = best_stream.get("indexer", "?").upper()
    title_short = best_stream["title"][:80]

    name = f"⭐ {quality_label}{codec_label} | {indexer} | {size_label}" if size_label else f"⭐ {quality_label}{codec_label} | {indexer}"

    return jsonify({
        "streams": [{
            "name": name,
            "description": title_short,
            "url": download_url,
            "behaviorHints": {
                "notWebReady": True,
                "bingeGroup": f"vinaglieri-{imdb_id}",
            }
        }]
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
