"""Moteur générique : modèle YAML + document source  ->  fiche wiki en wikitexte."""
import json
from pathlib import Path

import yaml

from geo import geocoder
from ia import appeler_ia, lire_json

DOSSIER_MODELES = Path(__file__).parent / "modeles"
MAX_CARACTERES_DOCS = 60_000      # au-delà, on tronque (limite de contexte de l'IA)


def charger_modeles():
    modeles = {}
    for f in sorted(DOSSIER_MODELES.glob("*.yaml")):
        conf = yaml.safe_load(f.read_text(encoding="utf-8"))
        modeles[conf["nom_affiche"]] = conf
    return modeles


def squelette(conf):
    """Le modèle vide, tel qu'il apparaît sur le wiki : {{Project |champ= ... }}."""
    return "\n".join([f"{{{{{conf['modele_wiki']}"] + [f"|{c['nom']}=" for c in conf["champs"]] + ["}}"])


# ---------------------------------------------------------------- demande à l'IA
def construire_prompts(conf, texte_docs):
    systeme = (
        conf["consigne_generale"].strip() + "\n\n"
        "Tu réponds UNIQUEMENT avec un objet JSON valide, sans texte autour.\n"
        "Tu écris en français. Si une information est absente du document, "
        "laisse le champ vide (\"\") plutôt que d'inventer."
    )
    a_remplir = {"titre_page": "Titre de la page wiki : le nom du projet, court et explicite."}
    for c in conf["champs"]:
        if c["source"] == "ia":
            a_remplir[c["nom"]] = " ".join(c["consigne"].split())
    a_remplir["remarques"] = "Ce qui manque ou est incertain, pour la relecture humaine (1 à 3 phrases)."

    utilisateur = (
        f"### Modèle de fiche « {conf['nom_affiche']} » du wiki (pour information)\n"
        + squelette(conf)
        + "\n\n### Document source\n" + texte_docs[:MAX_CARACTERES_DOCS]
        + "\n\n### Ta tâche\nRemplis ce JSON (clés exactement identiques) :\n"
        + json.dumps(a_remplir, ensure_ascii=False, indent=2)
    )
    return systeme, utilisateur


# ---------------------------------------------------------------- génération
def generer_fiche(conf, texte_docs, valeurs_defaut, fournisseur, cle, modele_ia):
    systeme, utilisateur = construire_prompts(conf, texte_docs)
    reponse = appeler_ia(systeme, utilisateur, fournisseur, cle, modele_ia)
    return assembler(conf, lire_json(reponse), valeurs_defaut)


def assembler(conf, donnees, valeurs_defaut):
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

        # texte de l'IA commençant par une liste ou un titre : doit commencer en début de ligne
        if source == "ia" and val.startswith(("*", "#", "=", "{|")):
            val = "\n" + val
        if val and c.get("entoure_par"):
            val = c["entoure_par"][0] + val + c["entoure_par"][1]
        lignes.append(f"|{nom}={val}")
    lignes.append("}}")

    return {
        "titre": str(donnees.get("titre_page", "")).strip(),
        "wikitexte": "\n".join(lignes),
        "remarques_ia": str(donnees.get("remarques", "")).strip(),
        "remarques": remarques,
    }
