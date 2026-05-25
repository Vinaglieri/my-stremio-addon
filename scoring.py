import re
from sources import parse_quality, is_hevc

def score_stream(stream, cached_status):
    score = 0

    title = stream.get("title", "")
    seeders = stream.get("seeders", 0)
    size = stream.get("size", 0)

    # Big bonus for RD cached content
    if cached_status:
        score += 100
        try:
            for variant in cached_status.values():
                for quality, files in variant.items():
                    if files:
                        score += 20
                        break
        except Exception:
            pass

    size_gb = size / (1024**3)

    # Penalty for files that are too large (>50GB) or too small (<100MB for movies)
    if size_gb > 50:
        score -= 50
    elif size_gb > 20:
        score -= 20
    elif size_gb < 0.1:
        score -= 30
    elif size_gb < 0.5:
        score -= 10

    # Seeders bonus
    if seeders > 100:
        score += 15
    elif seeders > 50:
        score += 10
    elif seeders > 10:
        score += 5

    # Quality bonuses
    quality = parse_quality(title)
    if quality == 2160:
        score += 30
    elif quality == 1080:
        score += 20
    elif quality == 720:
        score += 10

    # Codec bonus
    if is_hevc(title):
        score += 5

    # Source reliability bonus
    source = stream.get("indexer", "")
    reliable_sources = ["torrentio", "comet", "rarbg", "tpb", "1337x"]
    if any(src in source.lower() for src in reliable_sources):
        score += 10

    # Penalty for CAM/TS/SCR releases
    if re.search(r'\b(cam|ts|telesync|hdcam|hdts|scr|screener|r5|dvdscr)\b',
                 title, re.IGNORECASE):
        score -= 200

    # Bonus for proper groups
    if re.search(r'\b(bluray|blu-ray|webdl|webrip|hdr|dolby)\b',
                 title, re.IGNORECASE):
        score += 15

    # Language bonus (prefer English/multi)
    if re.search(r'\b(ita|eng|multi|sub)\b', title, re.IGNORECASE):
        score += 5

    return score


def pick_best(streams, rd_availability):
    scored = []
    for s in streams:
        import re
        match = re.search(r'btih:([a-fA-F0-9]{40})', s["magnet"], re.IGNORECASE)
        hash_lower = match.group(1).lower() if match else ""
        cached = rd_availability.get(hash_lower, {}) if hash_lower else {}
        score = score_stream(s, cached)
        scored.append((score, s, cached))

    scored.sort(key=lambda x: x[0], reverse=True)

    return scored
