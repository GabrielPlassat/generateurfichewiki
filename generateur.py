"""Moteur générique : modèle YAML + document source  ->  fiche wiki en wikitexte."""
import difflib
import json
import unicodedata
from pathlib import Path

import yaml

from geo import geocoder
from ia import appeler_ia, lire_json

DOSSIER_MODELES = Path(__file__).parent / "modeles"
MAX_CARACTERES_DOCS = 60_000      # au-delà, on tronque (limite de contexte de l'IA)
MAX_NOMS_LISTE_COMPLETE = 400     # au-delà, on ne donne à l'IA que les noms probables
CARACTERES_INTERDITS_TITRE = "'’‘`#<>[]|{}"


# ---------------------------------------------------------------- utilitaires
def charger_modeles():
    modeles = {}
    for f in sorted(DOSSIER_MODELES.glob("*.yaml")):
        conf = yaml.safe_load(f.read_text(encoding="utf-8"))
        modeles[conf["nom_affiche"]] = conf
    return modeles


def categories_utilisees(conf):
    return list(dict.fromkeys(c["liste_wiki"] for c in conf["champs"] if c.get("liste_wiki")))


def probleme_titre(titre):
    """Renvoie un message d'erreur si le titre n'est pas valable, sinon ''."""
    if not titre.strip():
        return "Indique le titre de la page wiki."
    interdits = sorted({c for c in titre if c in CARACTERES_INTERDITS_TITRE})
    if interdits:
        return ("Le titre ne doit pas contenir : " + " ".join(interdits)
                + " (pas d'apostrophe : écris par exemple « Projet de la commune » plutôt que « Projet d'… »).")
    return ""


def normaliser(s):
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return " ".join("".join(c if c.isalnum() else " " for c in s).split())


def noms_probables(noms_wiki, texte_docs):
    """Pour les grandes listes : garde les noms dont les mots apparaissent dans le document."""
    if len(noms_wiki) <= MAX_NOMS_LISTE_COMPLETE:
        return noms_wiki
    texte = " " + normaliser(texte_docs) + " "
    garde = []
    for nom in noms_wiki:
        n = normaliser(nom)
        mots = [m for m in n.split() if len(m) >= 3] or n.split()
        if n and (f" {n} " in texte or (mots and all(f" {m} " in texte for m in mots))):
            garde.append(nom)
    return garde


def filtrer_noms(valeur, noms_wiki):
    """Ne garde que les noms qui existent dans la liste du wiki, avec leur orthographe exacte.
    Renvoie (valeur filtrée, remarques)."""
    if not valeur:
        return "", []
    if not noms_wiki:
        return valeur, [f"Liste du wiki indisponible : « {valeur} » non vérifié"]
    index = {normaliser(n): n for n in noms_wiki}
    gardes, remarques = [], []
    for brut in [v.strip() for v in valeur.split(",") if v.strip()]:
        n = normaliser(brut)
        if n in index:
            gardes.append(index[n])
            continue
        proche = difflib.get_close_matches(n, list(index), n=1, cutoff=0.85)
        if proche:
            gardes.append(index[proche[0]])
            remarques.append(f"« {brut} » → « {index[proche[0]]} »")
        else:
            remarques.append(f"« {brut} » écarté : absent du wiki (créer sa page, puis l'ajouter à la main)")
    return ", ".join(dict.fromkeys(gardes)), remarques


def squelette(conf):
    """Le modèle vide, tel qu'il apparaît sur le wiki : {{Project |champ= ... }}."""
    return "\n".join([f"{{{{{conf['modele_wiki']}"] + [f"|{c['nom']}=" for c in conf["champs"]] + ["}}"])


# ---------------------------------------------------------------- demande à l'IA
def construire_prompts(conf, titre, texte_docs, listes):
    systeme = (
        conf["consigne_generale"].strip() + "\n\n"
        "Tu réponds UNIQUEMENT avec un objet JSON valide, sans texte autour.\n"
        "Tu écris en français. Si une information est absente du document, "
        "laisse le champ vide (\"\") plutôt que d'inventer.\n"
        "Pour les champs liés à une liste du wiki, tu n'utilises QUE des noms copiés "
        "à l'identique depuis cette liste (même orthographe, mêmes majuscules, mêmes accents)."
    )
    blocs = [f"### Modèle de fiche « {conf['nom_affiche']} » du wiki (pour information)\n" + squelette(conf),
             f"### Titre de la page (choisi par l'utilisateur)\n{titre}"]
    for cat in categories_utilisees(conf):
        noms = noms_probables(listes.get(cat, []), texte_docs)
        champs = ", ".join(c["nom"] for c in conf["champs"] if c.get("liste_wiki") == cat)
        if noms:
            blocs.append(f"### Liste « {cat} » du wiki — seuls noms autorisés pour : {champs}\n" + "\n".join(noms))

    a_remplir = {}
    for c in conf["champs"]:
        if c["source"] == "ia":
            a_remplir[c["nom"]] = " ".join(c["consigne"].split())
    a_remplir["remarques"] = "Ce qui manque ou est incertain, pour la relecture humaine (1 à 3 phrases)."

    utilisateur = (
        "\n\n".join(blocs)
        + "\n\n### Document source\n" + texte_docs[:MAX_CARACTERES_DOCS]
        + "\n\n### Ta tâche\nRemplis ce JSON (clés exactement identiques) :\n"
        + json.dumps(a_remplir, ensure_ascii=False, indent=2)
    )
    return systeme, utilisateur


# ---------------------------------------------------------------- génération
def generer_fiche(conf, titre, texte_docs, listes, valeurs_defaut, fournisseur, cle, modele_ia):
    systeme, utilisateur = construire_prompts(conf, titre, texte_docs, listes)
    reponse = appeler_ia(systeme, utilisateur, fournisseur, cle, modele_ia)
    return assembler(conf, titre, lire_json(reponse), listes, valeurs_defaut)


def assembler(conf, titre, donnees, listes, valeurs_defaut):
    """Fusionne réponse de l'IA + valeurs par défaut + coordonnées -> wikitexte."""
    remarques = []
    lignes = [f"{{{{{conf['modele_wiki']}"]
    for c in conf["champs"]:
        nom, source = c["nom"], c["source"]
        if source == "vide":
            val = ""
        elif source == "defaut":
            val = valeurs_defaut.get(nom, c.get("valeur", ""))
        elif source == "geo":
            lieu = str(donnees.get(c.get("lieu_depuis", "location"), "") or "").strip()
            res = geocoder(lieu) if lieu else None
            if res:
                lat, lon, label = res
                val = c.get("format", "{lat}, {lon}").format(lat=lat, lon=lon)
                remarques.append(f"Lieu « {lieu} » localisé : {label} ({lat}, {lon})")
            else:
                val = ""
                remarques.append(f"Coordonnées non trouvées ({lieu or 'aucun lieu dans le document'}) : à saisir à la main")
        else:
            val = str(donnees.get(nom, "") or "").strip()
            if c.get("liste_wiki"):
                val, rq = filtrer_noms(val, listes.get(c["liste_wiki"], []))
                remarques += [f"{nom} : {r}" for r in rq]

        # texte de l'IA commençant par une liste ou un titre : doit commencer en début de ligne
        if source == "ia" and val.startswith(("*", "#", "=", "{|")):
            val = "\n" + val
        if val and c.get("entoure_par"):
            val = c["entoure_par"][0] + val + c["entoure_par"][1]
        lignes.append(f"|{nom}={val}")
    lignes.append("}}")

    return {
        "titre": titre,
        "wikitexte": "\n".join(lignes),
        "remarques_ia": str(donnees.get("remarques", "")).strip(),
        "remarques": remarques,
    }
