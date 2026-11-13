"""Moteur générique : modèle YAML + document source  ->  fiche wiki en wikitexte."""
import difflib
import json
import re
import unicodedata
from pathlib import Path

import yaml

from geo import geocoder
from ia import appeler_ia, lire_json, nettoyer_texte

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


def score_proximite(a, b):
    """Proximité entre deux noms normalisés, de 0 à 1."""
    if a == b:
        return 1.0
    ma, mb = a.split(), b.split()
    if sorted(ma) == sorted(mb):                        # mêmes mots, ordre différent
        return 0.98
    court, long_ = sorted((a, b), key=len)
    if f" {court} " in f" {long_} ":                    # « cargolab » dans « vehicule cargolab »
        return 0.8 + 0.2 * len(court) / len(long_)
    communs = set(ma) & set(mb)
    mots = 2 * len(communs) / (len(ma) + len(mb))
    return max(difflib.SequenceMatcher(None, a, b).ratio(), 0.9 * mots)


def nom_le_plus_proche(brut, noms_wiki, seuil):
    """Renvoie (nom du wiki, score) le plus proche, ou (None, meilleur score)."""
    n = normaliser(brut)
    meilleur, score_max = None, 0.0
    for nom in noms_wiki:
        s = score_proximite(n, normaliser(nom))
        if s > score_max:
            meilleur, score_max = nom, s
    return (meilleur, score_max) if score_max >= seuil else (None, score_max)


SEUILS = {"proche": 0.6, "stricte": 0.9}


def filtrer_noms(valeur, noms_wiki, correspondance="proche"):
    """Remplace chaque nom par le nom le plus proche de la liste du wiki.
    Renvoie (valeur corrigée, remarques)."""
    if not valeur:
        return "", []
    if not noms_wiki:
        return valeur, [f"Liste du wiki indisponible : « {valeur} » non vérifié"]
    gardes, remarques = [], []
    for brut in [v.strip() for v in valeur.split(",") if v.strip()]:
        nom, score = nom_le_plus_proche(brut, noms_wiki, SEUILS.get(correspondance, 0.6))
        if nom is None:
            remarques.append(f"« {brut} » écarté : aucun nom proche sur le wiki (créer sa page ?)")
            continue
        gardes.append(nom)
        if nom != brut:
            fiabilite = "" if score >= 0.85 else " — à vérifier"
            remarques.append(f"« {brut} » → « {nom} »{fiabilite}")
    return ", ".join(dict.fromkeys(gardes)), remarques


def squelette(conf):
    """Le modèle vide, tel qu'il apparaît sur le wiki : {{Project |champ= ... }}."""
    return "\n".join([f"{{{{{conf['modele_wiki']}"] + [f"|{c['nom']}=" for c in conf["champs"]] + ["}}"])


# ---------------------------------------------------------------- demande à l'IA
def _blocs_contexte(conf, titre, texte_docs, listes, avec_listes=True):
    blocs = [f"### Modèle de fiche « {conf['nom_affiche']} » du wiki (pour information)\n" + squelette(conf),
             f"### Titre de la page (choisi par l'utilisateur)\n{titre}"]
    if avec_listes:
        for cat in categories_utilisees(conf):
            noms = noms_probables(listes.get(cat, []), texte_docs)
            champs = ", ".join(c["nom"] for c in conf["champs"] if c.get("liste_wiki") == cat)
            if noms:
                blocs.append(f"### Liste « {cat} » du wiki — choisir le nom le plus proche pour : {champs}\n"
                             + "\n".join(noms))
    blocs.append("### Document source\n" + texte_docs[:MAX_CARACTERES_DOCS])
    return "\n\n".join(blocs)


def prompts_champs(conf, titre, texte_docs, listes):
    """Demande n°1 : tous les champs courts, en JSON."""
    systeme = (
        conf["consigne_generale"].strip() + "\n\n"
        "Tu réponds UNIQUEMENT avec un objet JSON valide, sans texte autour.\n"
        "Tu écris en français. Si une information est absente du document, "
        "laisse le champ vide (\"\") : n'invente jamais.\n"
        "Pour les champs liés à une liste du wiki : pour chaque véhicule, acteur ou personne "
        "cité dans le document, choisis dans la liste le nom le plus proche et recopie-le à "
        "l'identique (même orthographe, mêmes majuscules, mêmes accents)."
    )
    a_remplir = {c["nom"]: " ".join(c["consigne"].split())
                 for c in conf["champs"] if c["source"] == "ia" and not c.get("redaction_separee")}
    a_remplir["remarques"] = "Ce qui manque ou est incertain, pour la relecture humaine (1 à 3 phrases)."
    utilisateur = (_blocs_contexte(conf, titre, texte_docs, listes)
                   + "\n\n### Ta tâche\nRemplis ce JSON (clés exactement identiques) :\n"
                   + json.dumps(a_remplir, ensure_ascii=False, indent=2))
    return systeme, utilisateur


def prompts_texte_long(conf, champ, titre, texte_docs):
    """Demande n°2 : un champ long (la description), en texte libre."""
    systeme = (
        conf["consigne_generale"].strip() + "\n\n"
        "Tu réponds UNIQUEMENT avec le texte demandé, en wikitexte MediaWiki, sans phrase "
        "d'introduction, sans balises ``` et sans tableau. Tu écris en français. N'invente jamais."
    )
    utilisateur = (_blocs_contexte(conf, titre, texte_docs, {}, avec_listes=False)
                   + f"\n\n### Ta tâche : rédiger le champ « {champ['nom']} »\n" + champ["consigne"].strip())
    return systeme, utilisateur


# ---------------------------------------------------------------- génération
def generer_fiche(conf, titre, texte_docs, listes, valeurs_defaut, fournisseur, cle, modele_ia):
    systeme, utilisateur = prompts_champs(conf, titre, texte_docs, listes)
    donnees = lire_json(appeler_ia(systeme, utilisateur, fournisseur, cle, modele_ia))
    for c in conf["champs"]:
        if c.get("redaction_separee"):
            systeme, utilisateur = prompts_texte_long(conf, c, titre, texte_docs)
            donnees[c["nom"]] = nettoyer_texte(appeler_ia(systeme, utilisateur, fournisseur, cle, modele_ia))
    return assembler(conf, titre, donnees, listes, valeurs_defaut)


def coordonnees(c, lieu):
    """Renvoie (valeur du champ, remarque)."""
    lat, lon, label, raison = geocoder(lieu)
    if lat is None:
        return "", f"Coordonnées non trouvées pour « {lieu or '—'} » ({raison}) : corrige le lieu ci-dessous"
    return (c.get("format", "{lat}, {lon}").format(lat=lat, lon=lon),
            f"Lieu « {lieu} » localisé : {label} ({lat}, {lon})")


def remplacer_champ(wikitexte, nom, valeur):
    """Remplace la valeur d'un champ d'une ligne (ex. coordonnées) dans la fiche."""
    return re.sub(rf"^\|{re.escape(nom)}=.*$", lambda m: f"|{nom}={valeur}", wikitexte, count=1, flags=re.M)


def assembler(conf, titre, donnees, listes, valeurs_defaut):
    """Fusionne réponses de l'IA + valeurs par défaut + coordonnées -> wikitexte."""
    remarques, lieu = [], ""
    lignes = [f"{{{{{conf['modele_wiki']}"]
    for c in conf["champs"]:
        nom, source = c["nom"], c["source"]
        if source == "vide":
            val = ""
        elif source == "defaut":
            val = valeurs_defaut.get(nom, c.get("valeur", ""))
        elif source == "geo":
            lieu = str(donnees.get(c.get("lieu_depuis", "location"), "") or "").strip()
            val, rq = coordonnees(c, lieu)
            remarques.append(rq)
        else:
            val = str(donnees.get(nom, "") or "").strip()
            val = val.replace("|", "{{!}}")     # un « | » couperait le champ dans le modèle
            if c.get("liste_wiki"):
                val, rq = filtrer_noms(val, listes.get(c["liste_wiki"], []),
                                       c.get("correspondance", "proche"))
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
        "lieu": lieu,
        "remarques_ia": str(donnees.get("remarques", "")).strip(),
        "remarques": remarques,
    }
