"""Listes des pages d'une catégorie du wiki XD (véhicules, acteurs…).

Ordre de priorité :
  1. lecture en direct sur le wiki : export Semantic MediaWiki, page-tableau
     (ex. « Tous les vélis »), API, page de la catégorie ;
  2. sinon, le fichier donnees_wiki/Categorie_<nom>.txt du dépôt GitHub
     (mis à jour avec le notebook rafraichir_listes_wiki.ipynb).
"""
import html
import re
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

import requests
from urllib.parse import unquote_plus

WIKI = "https://wikixd.fabmob.io"
DOSSIER = Path(__file__).parent / "donnees_wiki"
ENTETES = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9",
}


# Pages du wiki qui affichent un tableau de toutes les pages d'une catégorie
# (1re colonne = nom de la page). Lisibles même quand l'API est bloquée.
PAGES_TABLEAU = {
    "Vehicule": "Tous_les_vélis",
    "Acteur": "Tous_les_Acteurs",
    "Utilisateur": "Tous_les_Utilisateurs",
}
ESPACES_UTILISATEUR = ("Utilisateur:", "Utilisatrice:", "User:")


# ---------------------------------------------------------------- lecture en direct
class _PremiereColonne(HTMLParser):
    """Récupère le titre du 1er lien de la 1re cellule de chaque ligne de tableau."""

    def __init__(self):
        super().__init__()
        self.titres, self.dans_ligne, self.cellule, self.pris = [], False, 0, False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "tr":
            self.dans_ligne, self.cellule, self.pris = True, 0, False
        elif tag == "td" and self.dans_ligne:
            self.cellule += 1
        elif tag == "a" and self.dans_ligne and self.cellule == 1 and not self.pris:
            titre = a.get("title", "")
            if titre.startswith(ESPACES_UTILISATEUR):      # page d'utilisateur (même non créée)
                titre = titre.split(":", 1)[1].replace(" (page inexistante)", "").strip()
            elif ":" in titre.split(" ")[0] or "(page inexistante)" in titre:
                titre = ""                                 # autre espace de noms, ou lien rouge
            if titre:
                self.titres.append(titre)
                self.pris = True

    def handle_endtag(self, tag):
        if tag == "tr":
            self.dans_ligne = False


def _par_page_tableau(categorie):
    page = PAGES_TABLEAU.get(categorie)
    if not page:
        return []
    r = requests.get(f"{WIKI}/wiki/{page}", headers=ENTETES, timeout=30)
    r.raise_for_status()
    p = _PremiereColonne()
    p.feed(r.text)
    return p.titres


def _par_export_smw(categorie):
    """Export JSON de Semantic MediaWiki (Spécial:Ask)."""
    url = f"{WIKI}/wiki/Spécial:Ask/-5B-5BCatégorie:{categorie}-5D-5D/format%3Djson/limit%3D5000"
    r = requests.get(url, headers=ENTETES, timeout=30)
    r.raise_for_status()
    return list(r.json().get("results", {}).keys())


def _par_api(categorie):
    titres, cont = [], {}
    while True:
        r = requests.get(f"{WIKI}/api.php", headers=ENTETES, timeout=20, params={
            "action": "query", "list": "categorymembers", "cmtitle": f"Catégorie:{categorie}",
            "cmlimit": "500", "cmnamespace": "0", "format": "json", "formatversion": "2", **cont})
        r.raise_for_status()
        data = r.json()
        titres += [m["title"] for m in data["query"]["categorymembers"]]
        if "continue" not in data:
            return titres
        cont = {"cmcontinue": data["continue"]["cmcontinue"]}


def _par_page_html(categorie):
    """Lit la page Catégorie:… comme un navigateur (200 noms par page, avec « page suivante »)."""
    titres, params = [], {"title": f"Catégorie:{categorie}"}
    for _ in range(50):
        r = requests.get(f"{WIKI}/index.php", headers=ENTETES, timeout=20, params=params)
        r.raise_for_status()
        bloc = r.text.split('id="mw-pages"', 1)
        if len(bloc) < 2:
            break
        bloc = bloc[1].split('class="printfooter"', 1)[0]
        titres += [html.unescape(t) for t in re.findall(r'<li><a href="[^"]*" title="([^"]+)"', bloc)]
        suivant = re.search(r'pagefrom=([^"&#]+)[^"]*"[^>]*>page suivante', bloc)
        if not suivant:
            break
        params = {"title": f"Catégorie:{categorie}",
                  "pagefrom": unquote_plus(html.unescape(suivant.group(1)))}
    return titres


def lire_en_direct(categorie):
    for methode in (_par_export_smw, _par_page_tableau, _par_api, _par_page_html):
        try:
            titres = methode(categorie)
            if titres:
                return sorted(set(titres))
        except Exception:
            continue
    return []


# ---------------------------------------------------------------- fichiers du dépôt
def fichier(categorie):
    return DOSSIER / f"Categorie_{categorie}.txt"


def lire_fichier(categorie):
    """Renvoie (noms, date de mise à jour) ; les lignes commençant par # sont des commentaires."""
    f = fichier(categorie)
    if not f.exists():
        return [], ""
    lignes = f.read_text(encoding="utf-8").splitlines()
    maj = next((l.split(":", 1)[1].strip() for l in lignes if l.startswith("# mis à jour")), "")
    return [l.strip() for l in lignes if l.strip() and not l.startswith("#")], maj


def ecrire_fichier(categorie, noms):
    DOSSIER.mkdir(exist_ok=True)
    entete = (f"# Pages de Catégorie:{categorie} sur {WIKI}\n"
              f"# mis à jour : {date.today().isoformat()}\n"
              f"# {len(noms)} noms, un par ligne\n")
    fichier(categorie).write_text(entete + "\n".join(noms) + "\n", encoding="utf-8")


def charger_liste(categorie):
    """Renvoie (noms, provenance lisible)."""
    noms = lire_en_direct(categorie)
    if noms:
        return noms, "wiki en direct"
    noms, maj = lire_fichier(categorie)
    if noms:
        return noms, f"fichier du dépôt (mis à jour le {maj or '?'})"
    return [], "aucune liste disponible"
