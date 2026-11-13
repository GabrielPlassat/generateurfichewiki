"""Lecture du wiki MediaWiki (wikixd.fabmob.io) : modèles, formulaires, catégories."""
import re
import requests

WIKI_API = "https://wikixd.fabmob.io/api.php"
WIKI_BASE = "https://wikixd.fabmob.io"
HEADERS = {"User-Agent": "GenerateurFichesXD/1.0 (POC ADEME eXtreme Defi)"}


def _get(params, api=WIKI_API):
    params = {**params, "format": "json", "formatversion": "2"}
    r = requests.get(api, params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def lire_page(titre, api=WIKI_API):
    """Renvoie le wikitexte brut d'une page, ou '' si elle n'existe pas."""
    data = _get({"action": "query", "prop": "revisions", "titles": titre,
                 "rvprop": "content", "rvslots": "main"}, api)
    pages = data.get("query", {}).get("pages", [])
    if not pages or pages[0].get("missing"):
        return ""
    rev = pages[0]["revisions"][0]
    return rev.get("slots", {}).get("main", {}).get("content", rev.get("content", ""))


def membres_categorie(categorie, api=WIKI_API):
    """Liste des titres de pages d'une catégorie (gère la pagination)."""
    titres, cont = [], {}
    while True:
        data = _get({"action": "query", "list": "categorymembers",
                     "cmtitle": f"Catégorie:{categorie}", "cmlimit": "500",
                     "cmnamespace": "0", **cont}, api)
        titres += [m["title"] for m in data.get("query", {}).get("categorymembers", [])]
        if "continue" not in data:
            return sorted(set(titres))
        cont = {"cmcontinue": data["continue"]["cmcontinue"]}


def parametres_du_modele(wikitexte):
    """Extrait les noms de paramètres {{{nom|...}}} utilisés dans un modèle."""
    noms = re.findall(r"\{\{\{\s*([^|{}]+?)\s*[|}]", wikitexte)
    vus, res = set(), []
    for n in noms:
        if n not in vus and not n.isdigit():
            vus.add(n)
            res.append(n)
    return res


def page_existe(titre, api=WIKI_API):
    data = _get({"action": "query", "titles": titre}, api)
    pages = data.get("query", {}).get("pages", [])
    return bool(pages) and not pages[0].get("missing")


def lien_creation(titre):
    """Lien qui ouvre l'éditeur du wiki sur une nouvelle page."""
    from urllib.parse import quote
    return f"{WIKI_BASE}/index.php?title={quote(titre.replace(' ', '_'))}&action=edit"
