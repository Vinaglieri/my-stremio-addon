import os
import re
import logging
from flask import Flask, jsonify, request, redirect
import trakt_client as trakt
import recommender

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = Flask(__name__)

BASE = os.environ.get("BASE_URL", "https://my-stremio-addon-981079721173.us-central1.run.app")

@app.after_request
def add_cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "*"
    return resp

@app.get("/")
def root():
    tk = trakt.is_authed()
    manifest = f"{BASE}/manifest.json"
    return f"""<html><body style="font-family:sans-serif;padding:2rem">
<h1>{'✅' if tk else '⚠️'} Vinaglieri Personal</h1>
<p>Trakt: {'✅' if tk else '❌'} <a href='/trakt/auth'>{'Reconnect' if tk else 'Connect'}</a></p>
<hr>
<p><a href="{manifest}">📦 Manifest</a></p>
<p><a href="https://app.strem.io/shell-v4.4?addon={manifest}">📦 Install via Web</a></p>
<p><code>{manifest}</code></p></body></html>"""

@app.get("/manifest.json")
def manifest():
    tk = trakt.is_authed()
    catalogs = [
        {"type": "movie", "id": "vinaglieri-recommended", "name": "Recommended for You"},
        {"type": "series", "id": "vinaglieri-recommended-shows", "name": "Recommended Series"},
    ] if tk else []
    return jsonify({
        "id": "vinaglieri.personal",
        "version": "1.1.0",
        "name": "Vinaglieri Personal",
        "description": "Trakt recommendations + rating + scrobble",
        "resources": ["catalog", "meta"],
        "types": ["movie", "series"],
        "catalogs": catalogs,
    })

@app.get("/trakt/auth")
def trakt_auth():
    return redirect(trakt.auth_url())

@app.get("/trakt/callback")
def trakt_callback():
    code = request.args.get("code")
    if not code:
        return "No code", 400
    ok = trakt.exchange_code(code)
    return f"<html><body><h1>{'✅' if ok else '❌'} Trakt {'connected' if ok else 'failed'}</h1><script>setTimeout(window.close,2000)</script></body></html>"

@app.get("/catalog/<stype>/<cid>.json")
def catalog(stype, cid):
    if cid == "vinaglieri-recommended":
        items = recommender.recommended_movies(20)
    elif cid == "vinaglieri-recommended-shows":
        items = recommender.recommended_shows(20)
    else:
        items = []
    return jsonify({"metas": items})

@app.get("/meta/<stype>/<id>.json")
def meta(stype, id):
    m = re.match(r'(tt\d+)', id)
    i = m.group(1) if m else id
    links = []
    if trakt.is_authed():
        links.append({"name": "⭐ Rate", "category": "Ratings", "url": f"{BASE}/rate/{stype}/{i}"})
    return jsonify({"meta": {"id": i, "type": stype, "links": links}})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
