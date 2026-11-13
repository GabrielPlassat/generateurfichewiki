"""Coordonnées géographiques d'un lieu français, avec les services publics :
  1. geo.api.gouv.fr (recherche de commune par son nom, le plus fiable pour "Commune, Département")
  2. data.geopf.fr (géocodeur IGN, adresses et lieux-dits)
  3. api-adresse.data.gouv.fr (ancien service, en secours)
"""
import re
import unicodedata

import requests

ENTETES = {"User-Agent": "GenerateurFichesXD/1.0"}


def _norm(s):
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn").replace("-", " ").strip()


def _decouper(lieu):
    """'Saint-Flour, Cantal' -> ('Saint-Flour', 'Cantal') ; 'Brest (29)' -> ('Brest', '29')."""
    lieu = re.split(r"[;/]| et | à ", lieu)[0].strip()          # un seul lieu
    m = re.match(r"^(.*?)\s*\((\w+)\)\s*$", lieu)
    if m:
        return m.group(1).strip(), m.group(2)
    morceaux = [m.strip() for m in lieu.split(",") if m.strip()]
    return (morceaux[0] if morceaux else lieu), (morceaux[1] if len(morceaux) > 1 else "")


def _par_commune(commune, precision):
    r = requests.get("https://geo.api.gouv.fr/communes", headers=ENTETES, timeout=15, params={
        "nom": commune, "fields": "nom,centre,departement,codeDepartement",
        "boost": "population", "limit": 10})
    r.raise_for_status()
    resultats = [c for c in r.json() if c.get("centre")]
    if precision:
        p = _norm(precision)
        filtres = [c for c in resultats if p in (_norm(c.get("departement", {}).get("nom", "")),
                                                 c.get("codeDepartement", "").lower())]
        resultats = filtres or resultats
    exacts = [c for c in resultats if _norm(c["nom"]) == _norm(commune)]
    c = (exacts or [None])[0]          # jamais une commune « ressemblante » : sinon point faux
    if not c:
        return None
    lon, lat = c["centre"]["coordinates"]
    return lat, lon, f"{c['nom']} ({c.get('codeDepartement', '')})"


def _par_adresse(url, lieu):
    r = requests.get(url, headers=ENTETES, timeout=15, params={"q": lieu, "limit": 1})
    r.raise_for_status()
    feats = r.json().get("features", [])
    if not feats:
        return None
    lon, lat = feats[0]["geometry"]["coordinates"]
    return lat, lon, feats[0]["properties"].get("label", lieu)


def geocoder(lieu):
    """Renvoie (latitude, longitude, libellé, '') si trouvé, sinon (None, None, None, raison)."""
    if not lieu or not lieu.strip():
        return None, None, None, "aucun lieu indiqué"
    commune, precision = _decouper(lieu)
    par_commune = ("geo.api.gouv.fr", lambda: _par_commune(commune, precision))
    par_adresse = [
        ("IGN", lambda: _par_adresse("https://data.geopf.fr/geocodage/search", lieu)),
        ("api-adresse", lambda: _par_adresse("https://api-adresse.data.gouv.fr/search/", lieu)),
    ]
    # une vraie adresse (numéro, code postal) : on cherche d'abord l'adresse exacte
    essais = par_adresse + [par_commune] if re.search(r"\d", lieu) else [par_commune] + par_adresse
    erreurs = []
    for nom, essai in essais:
        try:
            res = essai()
            if res:
                lat, lon, label = res
                return round(lat, 5), round(lon, 5), label, ""
            erreurs.append(f"{nom} : aucun résultat")
        except Exception as e:
            erreurs.append(f"{nom} : {type(e).__name__} {str(e)[:60]}")
    return None, None, None, " ; ".join(erreurs)
