import os
import time
import requests

BASE_URL = "https://api.real-debrid.com/rest/1.0"

class RealDebrid:
    def __init__(self, api_token=None):
        self.api_token = api_token or os.environ.get("RD_API_KEY", "")
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {self.api_token}"})

    def _get(self, path, params=None):
        r = self.session.get(f"{BASE_URL}{path}", params=params)
        r.raise_for_status()
        return r.json()

    def _post(self, path, data=None):
        r = self.session.post(f"{BASE_URL}{path}", data=data)
        r.raise_for_status()
        return r.json()

    def _delete(self, path):
        r = self.session.delete(f"{BASE_URL}{path}")
        r.raise_for_status()
        return r.json()

    def check_credentials(self):
        try:
            user = self._get("/user")
            return user.get("username")
        except Exception:
            return None

    def add_magnet(self, magnet):
        return self._post("/torrents/addMagnet", {"magnet": magnet})

    def torrent_info(self, torrent_id):
        return self._get(f"/torrents/info/{torrent_id}")

    def select_all_files(self, torrent_id):
        return self._post(f"/torrents/selectFiles/{torrent_id}", {"files": "all"})

    def torrents_list(self, limit=100):
        return self._get("/torrents", {"limit": limit})

    def delete_torrent(self, torrent_id):
        return self._delete(f"/torrents/delete/{torrent_id}")

    def unrestrict_link(self, link):
        return self._post("/unrestrict/link", {"link": link})

    def check_cached_batch(self, magnets):
        hashes = []
        for m in magnets:
            import re
            match = re.search(r'btih:([a-fA-F0-9]{40})', m, re.IGNORECASE)
            if match:
                hashes.append(match.group(1).lower())

        if not hashes:
            return {}

        result = {}
        chunk_size = 100
        for i in range(0, len(hashes), chunk_size):
            chunk = hashes[i:i+chunk_size]
            try:
                r = requests.post(
                    f"{BASE_URL}/torrents/instantAvailability/{','.join(chunk)}",
                    headers={"Authorization": f"Bearer {self.api_token}"}
                )
                if r.status_code == 200:
                    data = r.json()
                    for h, info in data.items():
                        result[h] = info
            except Exception:
                pass

        return result

    def get_availability(self, magnet):
        result = self.check_cached_batch([magnet])
        import re
        match = re.search(r'btih:([a-fA-F0-9]{40})', magnet, re.IGNORECASE)
        if match:
            h = match.group(1).lower()
            return result.get(h, {})
        return {}

    def resolve_stream(self, magnet, timeout_sec=60):
        add = self.add_magnet(magnet)
        tid = add.get("id")
        if not tid:
            return None

        waited = 0
        while waited < timeout_sec:
            try:
                info = self.torrent_info(tid)
                status = info.get("status")

                if status in ("magnet_error", "error", "virus"):
                    break

                if status == "waiting_files_selection":
                    self.select_all_files(tid)

                if status == "downloaded":
                    links = info.get("links", [])
                    if links:
                        unrestricted = self.unrestrict_link(links[0])
                        return unrestricted.get("download")
                    break
            except Exception:
                pass

            time.sleep(2)
            waited += 2

        try:
            self.delete_torrent(tid)
        except Exception:
            pass
        return None
