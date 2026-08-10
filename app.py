import os
import re
import logging
from flask import Flask, jsonify, request
import simkl_client as simkl
import recommender
import sync_engine

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
    tk = simkl.is_authed()
    manifest = f"{BASE}/manifest.json"
    return f"""<html><body style="font-family:sans-serif;padding:2rem">
<h1>{'✅' if tk else '⚠️'} Vinaglieri Personal</h1>
<p>Simkl: {'✅' if tk else '❌'} <a href='/simkl/auth'>{'Reconnect' if tk else 'Connect'}</a></p>
<hr>
<p><a href="{manifest}">📦 Manifest</a></p>
<p><a href="https://app.strem.io/shell-v4.4?addon={manifest}">📦 Install via Web</a></p>
<p><code>{manifest}</code></p></body></html>"""

@app.get("/manifest.json")
def manifest():
    tk = simkl.is_authed()
    catalogs = [
        {"type": "movie", "id": "vinaglieri-recommended", "name": "Recommended for You"},
        {"type": "series", "id": "vinaglieri-recommended-shows", "name": "Recommended Series"},
    ] if tk else []
    return jsonify({
        "id": "vinaglieri.personal",
        "version": "1.1.0",
        "name": "Vinaglieri Personal",
        "description": "Personal Simkl recommendations",
        "resources": [
            {"name": "catalog", "types": ["movie", "series"], "idPrefixes": ["tt"]},
            {"name": "meta", "types": ["movie", "series"], "idPrefixes": ["tt"]},
            {"name": "stream", "types": ["movie", "series"], "idPrefixes": ["tt"]},
        ],
        "types": ["movie", "series"],
        "catalogs": catalogs,
    })

@app.get("/simkl/auth")
def simkl_auth():
    pin = simkl.request_pin()
    if not pin or pin.get("result") != "OK" or not pin.get("user_code"):
        return "<html><body><h1>❌ Failed to request PIN</h1></body></html>", 500
    uc = pin["user_code"]
    ver = pin.get("verification_uri") or "https://simkl.com/pin"
    return f"""<html><body style="font-family:sans-serif;padding:2rem">
<h1>🔑 Connect Simkl</h1>
<p>1. Open <a href="{ver}" target="_blank">{ver}</a></p>
<p>2. Enter code: <b style="font-size:1.5em">{uc}</b></p>
<p>3. This page updates automatically once connected.</p>
<script>
setInterval(() => {{
  fetch('/simkl/callback?user_code={uc}').then(r => r.json()).then(d => {{
    if (d.ok) location.href = '/';
  }});
}}, 3000);
</script></body></html>"""

@app.get("/simkl/callback")
def simkl_callback():
    uc = request.args.get("user_code")
    if not uc:
        return jsonify({"ok": False})
    d = simkl.poll_pin(uc)
    if d and d.get("result") == "OK" and d.get("access_token"):
        simkl.store_token(d["access_token"])
        return jsonify({"ok": True})
    return jsonify({"ok": False})

@app.get("/catalog/<stype>/<cid>.json")
def catalog(stype, cid):
    sync_engine.maybe_sync()
    if cid == "vinaglieri-recommended":
        items = recommender.recommended_movies(50)
    elif cid == "vinaglieri-recommended-shows":
        items = recommender.recommended_shows(50)
    else:
        items = []
    return jsonify({"metas": items})

@app.get("/meta/<stype>/<id>.json")
def meta(stype, id):
    m = re.match(r'(tt\d+)', id)
    i = m.group(1) if m else id
    meta = {"id": i, "type": stype, "name": "", "poster": ""}
    try:
        import requests as http
        r = http.get(f"https://v3-cinemeta.strem.io/meta/{stype}/{i}.json", timeout=5)
        if r.status_code == 200:
            d = r.json()
            if isinstance(d.get("meta"), dict):
                meta = d["meta"]
    except Exception:
        pass
    return jsonify({"meta": meta})

@app.get("/stream/<stype>/<id>.json")
def stream(stype, id):
    m = re.match(r'(tt\d+)', id)
    i = m.group(1) if m else id
    return jsonify({"streams": []})



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
