"""Géocodage d'un lieu français avec le service public (IGN / Base Adresse Nationale)."""
import requests

SERVICES = [
    "https://data.geopf.fr/geocodage/search",   # nouveau service IGN
    "https://api-adresse.data.gouv.fr/search/",  # ancien service BAN (secours)
]


def geocoder(lieu):
    """Renvoie (latitude, longitude, libellé trouvé) ou None."""
    if not lieu:
        return None
    for url in SERVICES:
        try:
            r = requests.get(url, params={"q": lieu, "limit": 1}, timeout=15)
            r.raise_for_status()
            feats = r.json().get("features", [])
            if feats:
                lon, lat = feats[0]["geometry"]["coordinates"]
                return round(lat, 5), round(lon, 5), feats[0]["properties"].get("label", lieu)
        except Exception:
            continue
    return None
