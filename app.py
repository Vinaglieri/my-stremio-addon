import os
import re
import base64
import logging
from flask import Flask, jsonify, request, redirect
from rd_client import RealDebrid
from sources import search, parse_quality, is_hevc
from scoring import pick_best
import trakt_client as trakt
import recommender

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = Flask(__name__)

rd = RealDebrid()
try:
    if rd.check_credentials():
        log.info("RD authenticated")
except Exception:
    log.warning("RD not configured")

BASE = os.environ.get("BASE_URL", "https://my-stremio-addon-981079721173.us-central1.run.app")

@app.after_request
def add_cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "*"
    return resp

@app.get("/")
def root():
    tk = trakt.is_authed()
    rk = rd.check_credentials() is not None
    ok = "✅" if tk and rk else "⚠️"
    manifest = f"{BASE}/manifest.json"
    return f"""<html><body style="font-family:sans-serif;padding:2rem">
<h1>{ok} Vinaglieri Personal</h1>
<p>Trakt: {'✅' if tk else '❌'} <a href='/trakt/auth'>{'Reconnect' if tk else 'Connect'}</a></p>
<p>RD: {'✅' if rk else '❌'}</p>
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
        "description": "Auto-pick streams + Trakt recommendations + rate",
        "resources": ["catalog", "stream", "meta"],
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

@app.get("/stream/<stype>/<id>.json")
def stream(stype, id):
    im = re.match(r'(tt\d+)', id)
    if not im:
        return jsonify({"streams": []})
    i = im.group(1)
    q = i
    try:
        import requests as http
        r = http.get(f"https://v3-cinemeta.strem.io/meta/{stype}/{i}.json", timeout=5)
        if r.status_code == 200:
            m = r.json().get("meta", {})
            n = m.get("name", "")
            y = m.get("year", "")
            parts = id.split(":")
            if len(parts) == 3:
                q = f"{n} S{int(parts[1]):02d}E{int(parts[2]):02d} {y}".strip()
            else:
                q = f"{n} {y}".strip()
    except Exception:
        pass
    c = search(q, i)
    if not c:
        return jsonify({"streams": []})
    try:
        rd_avail = rd.check_cached_batch([s["magnet"] for s in c])
    except Exception:
        rd_avail = {}
    scored = pick_best(c, rd_avail)
    if not scored:
        return jsonify({"streams": []})
    url, best = None, None
    for _, s, cached in scored:
        try:
            u = rd.resolve_stream(s["magnet"], timeout_sec=12 if cached else 20)
            if u:
                url, best = u, s
                break
        except Exception:
            continue
    if not url or not best:
        return jsonify({"streams": []})
    enc = base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")
    ql = f"{parse_quality(best['title']) or '??'}p"
    cl = " HDR" if is_hevc(best["title"]) else ""
    gb = best.get("size", 0) / (1073741824)
    sl = f" {gb:.1f}GB" if gb > 0 else ""
    ix = best.get("indexer", "?").upper()
    return jsonify({"streams": [{
        "name": f"⭐ {ql}{cl} | {ix}{sl}",
        "description": best["title"][:100],
        "url": f"{BASE}/proxy/{i}/{enc}",
        "behaviorHints": {"notWebReady": True},
    }]})

@app.get("/proxy/<i>/<enc>")
def proxy(i, enc):
    try:
        p = 4 - len(enc) % 4
        u = base64.urlsafe_b64decode(enc + ("=" * p if p != 4 else "")).decode()
    except Exception:
        return "Bad URL", 400
    if trakt.is_authed():
        try:
            trakt.scrobble(i)
        except Exception:
            pass
    return redirect(u, 302)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
