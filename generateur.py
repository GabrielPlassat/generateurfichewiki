"""Moteur générique : modèle YAML + documents + infos du wiki  ->  fiche en wikitexte."""
import difflib
import json
import unicodedata
from pathlib import Path

import yaml

from geo import geocoder
from ia import appeler_ia, lire_json

DOSSIER_MODELES = Path(__file__).parent / "modeles"
MAX_CARACTERES_DOCS = 60_000      # au-delà, on tronque (limite de contexte de l'IA)
MAX_NOMS_LISTE_COMPLETE = 300     # au-delà, on ne donne à l'IA que les noms probables


# ---------------------------------------------------------------- utilitaires
def normaliser(s):
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return " ".join("".join(c if c.isalnum() else " " for c in s).split())


def charger_modeles():
    modeles = {}
    for f in sorted(DOSSIER_MODELES.glob("*.yaml")):
        conf = yaml.safe_load(f.read_text(encoding="utf-8"))
        modeles[conf["nom_affiche"]] = conf
    return modeles


def noms_probables(noms_wiki, texte_docs):
    """Pour les grandes listes : garde les noms dont les mots apparaissent dans les documents."""
    if len(noms_wiki) <= MAX_NOMS_LISTE_COMPLETE:
        return noms_wiki
    texte = " " + normaliser(texte_docs) + " "
    garde = []
    for nom in noms_wiki:
        n = normaliser(nom)
        if not n:
            continue
        if f" {n} " in texte:
            garde.append(nom)
            continue
        mots = [m for m in n.split() if len(m) >= 4]
        if mots and all(f" {m} " in texte for m in mots):
            garde.append(nom)
    return garde


def rapprocher(valeur, noms_wiki):
    """Remplace chaque nom par son orthographe exacte du wiki.
    Renvoie (valeur corrigée, liste de remarques)."""
    if not valeur or not noms_wiki:
        return valeur, []
    index = {normaliser(n): n for n in noms_wiki}
    sortie, remarques = [], []
    for brut in [v.strip() for v in valeur.split(",") if v.strip()]:
        n = normaliser(brut)
        if n in index:
            sortie.append(index[n])
            continue
        proche = difflib.get_close_matches(n, list(index), n=1, cutoff=0.85)
        if proche:
            sortie.append(index[proche[0]])
            remarques.append(f"« {brut} » remplacé par « {index[proche[0]]} » (nom du wiki)")
        else:
            sortie.append(brut)
            remarques.append(f"« {brut} » n'existe pas encore sur le wiki (page à créer ?)")
    return ", ".join(dict.fromkeys(sortie)), remarques


# ---------------------------------------------------------------- prompt
def construire_prompts(conf, texte_docs, infos_wiki):
    champs_ia = [c for c in conf["champs"] if c["source"] in ("ia", "geo")]
    noms_conf = {c["nom"] for c in conf["champs"]}
    autres = [p for p in infos_wiki.get("parametres", []) if p not in noms_conf] \
        if conf.get("completer_autres_champs_du_wiki") else []

    systeme = (
        conf["consigne_generale"].strip() + "\n\n"
        "Tu réponds UNIQUEMENT avec un objet JSON valide, sans texte autour.\n"
        "Tu écris en français. Si une information est absente des documents, "
        "laisse le champ vide (\"\") plutôt que d'inventer."
    )

    blocs = []
    if infos_wiki.get("source_modele"):
        blocs.append("### Code source du modèle sur le wiki (pour comprendre les champs)\n"
                     + infos_wiki["source_modele"][:6000])
    if infos_wiki.get("source_formulaire"):
        blocs.append("### Formulaire de saisie du wiki (aides des champs)\n"
                     + infos_wiki["source_formulaire"][:6000])

    categories_vues = set()
    for c in conf["champs"]:
        cat = c.get("liste_wiki")
        if cat and cat not in categories_vues and infos_wiki.get("listes", {}).get(cat):
            categories_vues.add(cat)
            champs_cat = ", ".join(x["nom"] for x in conf["champs"] if x.get("liste_wiki") == cat)
            noms = noms_probables(infos_wiki["listes"][cat], texte_docs)
            blocs.append(f"### Noms existants dans la catégorie « {cat} » du wiki "
                         f"(pour : {champs_cat})\n" + "\n".join(noms))

    description_champs = {"titre_page": "Titre de la page wiki : le nom du projet, court et explicite."}
    for c in champs_ia:
        if c["source"] == "geo":
            if c.get("lieu_depuis"):      # le lieu est déjà demandé via un autre champ
                continue
            description_champs["lieu"] = "Lieu principal du projet (commune, département)."
        else:
            description_champs[c["nom"]] = " ".join(c["consigne"].split())
    for p in autres:
        description_champs[p] = "Champ du modèle wiki : à remplir seulement si l'information est clairement dans les documents."
    description_champs["remarques"] = "Ce qui manque ou est incertain, pour la relecture humaine (1 à 3 phrases)."

    utilisateur = (
        "\n\n".join(blocs)
        + "\n\n### Documents fournis\n" + texte_docs[:MAX_CARACTERES_DOCS]
        + "\n\n### Ta tâche\nRemplis ce JSON (clés exactement identiques) :\n"
        + json.dumps(description_champs, ensure_ascii=False, indent=2)
    )
    return systeme, utilisateur, autres


# ---------------------------------------------------------------- génération
def generer_fiche(conf, texte_docs, infos_wiki, valeurs_defaut, fournisseur, cle, modele_ia):
    systeme, utilisateur, autres = construire_prompts(conf, texte_docs, infos_wiki)
    reponse = appeler_ia(systeme, utilisateur, fournisseur, cle, modele_ia)
    donnees = lire_json(reponse)
    return assembler(conf, donnees, infos_wiki, valeurs_defaut, autres)


def assembler(conf, donnees, infos_wiki, valeurs_defaut, autres):
    """Fusionne réponse de l'IA + valeurs par défaut + géocodage -> wikitexte."""
    remarques = []
    lignes = [f"{{{{{conf['modele_wiki']}"]
    for c in conf["champs"]:
        nom = c["nom"]
        if c["source"] == "vide":
            val = ""
        elif c["source"] == "defaut":
            val = valeurs_defaut.get(nom, c.get("valeur", ""))
        elif c["source"] == "geo":
            lieu = str(donnees.get(c.get("lieu_depuis", "lieu"), "") or "").strip()
            res = geocoder(lieu) if lieu else None
            if res:
                lat, lon, label = res
                val = c.get("format", "{lat}, {lon}").format(lat=lat, lon=lon)
                remarques.append(f"Lieu « {lieu} » localisé : {label} ({lat}, {lon})")
            else:
                val = ""
                remarques.append(f"Lieu non trouvé ({lieu or 'aucun lieu dans le document'}) : coordonnées à saisir à la main")
        else:
            val = str(donnees.get(nom, "") or "").strip()
            cat = c.get("liste_wiki")
            if cat:
                val, rq = rapprocher(val, infos_wiki.get("listes", {}).get(cat, []))
                remarques += rq
        if val.startswith(("*", "#", "=", "{|")):   # liste ou titre : doit commencer en début de ligne
            val = "\n" + val
        if val and c.get("entoure_par"):
            val = c["entoure_par"][0] + val + c["entoure_par"][1]
        lignes.append(f"|{nom}={val}")
    for p in autres:
        val = str(donnees.get(p, "") or "").strip()
        if val:
            lignes.append(f"|{p}={val}")
    lignes.append("}}")

    return {
        "titre": str(donnees.get("titre_page", "")).strip(),
        "wikitexte": "\n".join(lignes),
        "remarques_ia": str(donnees.get("remarques", "")).strip(),
        "remarques": remarques,
    }
