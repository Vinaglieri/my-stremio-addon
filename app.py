import os
import re
import base64
import logging
from urllib.parse import urlencode
from flask import Flask, jsonify, request, redirect, Response

from rd_client import RealDebrid
from sources import search, parse_quality, is_hevc
from scoring import pick_best
import trakt_client as trakt
import upstash_client as cache
import recommender

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = Flask(__name__)

rd = RealDebrid()

try:
    if rd.check_credentials():
        log.info("Real-Debrid authenticated")
except Exception:
    log.warning("Real-Debrid not configured")

BASE_URL = os.environ.get("BASE_URL", "https://my-stremio-addon-981079721173.us-central1.run.app")

# ----------------------------------------------------------------
# Manifest
# ----------------------------------------------------------------
@app.get("/")
def root():
    trakt_ok = trakt.is_authed()
    rd_ok = rd.check_credentials() is not None
    status = "✅" if trakt_ok and rd_ok else "⚠️"
    return f"""<html><body style="font-family:sans-serif;padding:2rem">
<h1>{status} Vinaglieri Personal</h1>
<p>Trakt: {'✅ Connected' if trakt_ok else '❌ Not connected'} 
   <a href='/trakt/auth'>{'Reconnect' if trakt_ok else 'Connect'}</a></p>
<p>Real-Debrid: {'✅ Configured' if rd_ok else '❌ Not configured'}</p>
<hr>
<p>Manifest URL: <code>{BASE_URL}/manifest.json</code></p>
<p>Add this URL in Stremio → Add-ons → Install from URL</p>
</body></html>"""

@app.get("/manifest.json")
def manifest():
    trakt_ok = trakt.is_authed()
    catalogs = []
    if trakt_ok:
        catalogs = [
            {"type": "movie", "id": "vinaglieri-recommended", "name": "Recommended for You"},
            {"type": "series", "id": "vinaglieri-recommended-shows", "name": "Recommended Series"},
        ]
    return jsonify({
        "id": "vinaglieri.personal",
        "version": "1.1.0",
        "name": "Vinaglieri Personal",
        "description": "Auto-pick streams + Trakt sync + recommendations",
        "resources": ["catalog", "stream", "meta"],
        "types": ["movie", "series"],
        "catalogs": catalogs,
        "behaviorHints": {
            "configurable": True,
            "configurationRequired": not trakt_ok,
        },
    })

# ----------------------------------------------------------------
# Trakt OAuth
# ----------------------------------------------------------------
@app.get("/trakt/auth")
def trakt_auth():
    return redirect(trakt.auth_url())

@app.get("/trakt/callback")
def trakt_callback():
    code = request.args.get("code")
    if not code:
        return "No code received", 400
    result = trakt.exchange_code(code)
    if result:
        return "<html><body><h1>✅ Trakt connected!</h1><p>Close this tab and refresh Stremio.</p><script>setTimeout(()=>window.close(),2000)</script></body></html>"
    return "Auth failed", 400

# ----------------------------------------------------------------
# Catalogs (recommendations)
# ----------------------------------------------------------------
@app.get("/catalog/<stype>/<catalog_id>.json")
def catalog(stype, catalog_id):
    if catalog_id == "vinaglieri-recommended":
        items = recommender.recommended_movies(20)
    elif catalog_id == "vinaglieri-recommended-shows":
        items = recommender.recommended_shows(20)
    else:
        items = []
    return jsonify({"metas": items})

# ----------------------------------------------------------------
# Meta (rating links on detail page)
# ----------------------------------------------------------------
@app.get("/meta/<stype>/<id>.json")
def meta(stype, id):
    imdb_id = re.match(r'(tt\d+)', id)
    imdb_id = imdb_id.group(1) if imdb_id else id
    links = []
    if trakt.is_authed():
        links.append({
            "name": "⭐ Rate",
            "category": "Ratings",
            "url": f"{BASE_URL}/rate/{stype}/{imdb_id}",
        })
    return jsonify({"meta": {"id": imdb_id, "type": stype, "links": links}})

# ----------------------------------------------------------------
# Rating page
# ----------------------------------------------------------------
RATING_PAGE = """<html><body style="font-family:sans-serif;padding:2rem;text-align:center">
<h2>⭐ Rate {title}</h2>
<div style="font-size:2rem;margin:2rem 0">
{stars}
</div>
<p id="msg"></p>
<script>
async function rate(n){{
  let r=await fetch('/rate/{stype}/{imdb_id}/submit?rating='+n);
  let d=await r.text();
  document.getElementById('msg').innerHTML='✅ Rated '+n+'/10';
  setTimeout(()=>window.close(),1500);
}}
</script>
</body></html>"""

@app.get("/rate/<stype>/<imdb_id>")
def rate_page(stype, imdb_id):
    title = imdb_id
    try:
        import requests as http
        r = http.get(f"https://v3-cinemeta.strem.io/meta/{stype}/{imdb_id}.json", timeout=5)
        if r.status_code == 200:
            title = r.json().get("meta", {}).get("name", imdb_id)
    except Exception:
        pass

    stars = "".join(f'<a href="#" onclick="rate({i});return false;" style="text-decoration:none;color:gold;">{"★" if i <= 5 else "☆"}</a> '
                   for i in range(1, 11))

    return RATING_PAGE.format(stars=stars, title=title, stype=stype, imdb_id=imdb_id)

@app.get("/rate/<stype>/<imdb_id>/submit")
def rate_submit(stype, imdb_id):
    rating = request.args.get("rating", type=int)
    if not rating or rating < 1 or rating > 10:
        return "Rating must be 1-10", 400
    episode = None
    if stype == "series":
        parts = imdb_id.split(":")
        if len(parts) == 3:
            imdb_id = parts[0]
            episode = (int(parts[1]), int(parts[2]))
    result = trakt.rate(imdb_id, rating, episode)
    if result:
        return f"✅ Rated {rating}/10"
    return "Failed to sync rating", 500

# ----------------------------------------------------------------
# Stream (auto-pick best RD)
# ----------------------------------------------------------------
@app.get("/stream/<stype>/<id>.json")
def stream(stype, id):
    imdb_id = re.match(r'(tt\d+)', id)
    if not imdb_id:
        return jsonify({"streams": []})
    imdb_id = imdb_id.group(1)

    season, episode = None, None
    if stype == "series":
        parts = id.split(":")
        if len(parts) == 3:
            episode = (int(parts[1]), int(parts[2]))

    query = imdb_id
    try:
        import requests as http
        r = http.get(f"https://v3-cinemeta.strem.io/meta/{stype}/{imdb_id}.json", timeout=5)
        if r.status_code == 200:
            meta = r.json().get("meta", {})
            name = meta.get("name", "")
            year = meta.get("year", "")
            if episode:
                query = f"{name} S{episode[0]:02d}E{episode[1]:02d} {year}".strip()
            else:
                query = f"{name} {year}".strip()
    except Exception:
        pass

    candidates = search(query, imdb_id)
    if not candidates:
        return jsonify({"streams": []})

    try:
        rd_availability = rd.check_cached_batch([s["magnet"] for s in candidates])
    except Exception:
        rd_availability = {}

    scored = pick_best(candidates, rd_availability)
    if not scored:
        return jsonify({"streams": []})

    download_url = None
    best = None
    for score, s, c in scored:
        if c:
            try:
                url = rd.resolve_stream(s["magnet"], timeout_sec=12)
                if url:
                    download_url = url
                    best = s
                    break
            except Exception:
                continue

    if not download_url:
        for score, s, c in scored:
            if not c:
                try:
                    url = rd.resolve_stream(s["magnet"], timeout_sec=20)
                    if url:
                        download_url = url
                        best = s
                        break
                except Exception:
                    continue

    if not download_url or not best:
        return jsonify({"streams": []})

    rd_enc = base64.urlsafe_b64encode(download_url.encode()).decode().rstrip("=")
    proxy_url = f"{BASE_URL}/proxy/{imdb_id}/{rd_enc}"

    q = parse_quality(best["title"])
    ql = f"{q}p" if q else "??p"
    cl = " HDR" if is_hevc(best["title"]) else ""
    gb = best.get("size", 0) / (1024**3)
    sl = f"{gb:.1f}GB" if gb > 0 else ""
    ix = best.get("indexer", "?").upper()
    name = f"⭐ {ql}{cl} | {ix} | {sl}" if sl else f"⭐ {ql}{cl} | {ix}"

    return jsonify({
        "streams": [{
            "name": name,
            "description": best["title"][:100],
            "url": proxy_url,
            "behaviorHints": {"notWebReady": True},
        }]
    })

# ----------------------------------------------------------------
# Play proxy (scrobble + redirect to RD)
# ----------------------------------------------------------------
@app.get("/debug/posters")
def debug_posters():
    recs = trakt.get_recommendations_movies(3)
    if not recs:
        return {"error": "no recs", "token": cache.get("trakt_access_token")[:10] if cache.get("trakt_access_token") else None}
    items = []
    for r in recs:
        items.append({
            "title": r.get("title"),
            "has_images": "images" in r,
            "poster_type": type(r.get("images", {}).get("poster", None)).__name__ if r.get("images", {}).get("poster", None) else "missing",
            "poster_first": str(r.get("images", {}).get("poster", [None])[0])[:80] if isinstance(r.get("images", {}).get("poster", []), list) and r.get("images", {}).get("poster", []) else None,
        })
    return {"items": items}

@app.get("/proxy/<imdb_id>/<rd_enc>")
def proxy(imdb_id, rd_enc):
    try:
        padding = 4 - len(rd_enc) % 4
        if padding != 4:
            rd_enc += "=" * padding
        rd_url = base64.urlsafe_b64decode(rd_enc).decode()
    except Exception:
        return "Invalid URL", 400

    if trakt.is_authed():
        try:
            trakt.scrobble(imdb_id)
        except Exception:
            pass

    return redirect(rd_url, 302)

# ----------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
