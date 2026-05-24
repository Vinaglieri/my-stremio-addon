from flask import Flask, jsonify
app = Flask(__name__)

@app.get("/")
def root():
    return "ok"

@app.get("/manifest.json")
def manifest():
    return jsonify({
        "id": "vinaglieri.addon",
        "version": "1.0.0",
        "name": "vinaglieri addon",
        "description": "Personal Stremio add-on",
        "resources": ["stream"],
        "types": ["movie", "series"],
        "catalogs": []
    })

@app.get("/stream/<type>/<id>.json")
def stream(type, id):
    return jsonify({
        "streams": [
            {
                "name": "Test stream",
                "url": "https://example.com"
            }
        ]
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
