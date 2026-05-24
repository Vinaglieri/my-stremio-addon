from flask import Flask, jsonify, abort
app = Flask(__name__)

MANIFEST = {
    "id": "vinaglieri.addon",
    "version": "1.0.0",
    "name": "vinaglieri addon",
    "description": "Personal Stremio add-on",
    "types": ["movie", "series"],
    "resources": [
        "catalog",
        {"name": "meta", "types": ["series"], "idPrefixes": ["hpy"]},
        {"name": "stream", "types": ["movie", "series"], "idPrefixes": ["tt", "hpy"]}
    ],
    "catalogs": [
        {"type": "movie", "id": "vinaglieri movies"},
        {"type": "series", "id": "vinaglieri series"}
    ]
}

@app.get("/manifest.json")
def manifest():
    return jsonify(MANIFEST)

@app.get("/")
def root():
    return "ok"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
