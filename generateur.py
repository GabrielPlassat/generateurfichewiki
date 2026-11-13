"""Moteur générique : modèle YAML + document source  ->  fiche wiki en wikitexte."""
import difflib
import json
import re
import unicodedata
from pathlib import Path

from datetime import date

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
    return dict(sorted(modeles.items(), key=lambda kv: kv[1].get("ordre", 99)))


def listes_du_champ(c):
    """[(liste, correspondance), ...] : un champ peut chercher dans plusieurs listes, dans l'ordre."""
    listes = c.get("liste_wiki") or []
    listes = [listes] if isinstance(listes, str) else listes
    corr = c.get("correspondance", "proche")
    corr = [corr] * len(listes) if isinstance(corr, str) else corr
    return list(zip(listes, corr))


def categories_utilisees(conf):
    return list(dict.fromkeys(l for c in conf["champs"] for l, _ in listes_du_champ(c)))


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
    texte_colle = texte.replace(" ", "")
    garde = []
    for nom in noms_wiki:
        n = normaliser(nom)
        mots = [m for m in n.split() if len(m) >= 3] or n.split()
        if n and (f" {n} " in texte or (mots and all(f" {m} " in texte for m in mots))
                  or (len(n.replace(" ", "")) >= 8 and n.replace(" ", "") in texte_colle)):
            garde.append(nom)
    return garde


def score_proximite(a, b):
    """Proximité entre deux noms normalisés, de 0 à 1."""
    if a == b:
        return 1.0
    ma, mb = a.split(), b.split()
    if sorted(ma) == sorted(mb):                        # mêmes mots, ordre différent
        return 0.98
    if a.replace(" ", "") == b.replace(" ", ""):        # « bertrandbarbedette » = « bertrand barbedette »
        return 0.97
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


SEUILS = {"proche": 0.6, "stricte": 0.9, "valeur": 0.75}


def filtrer_sources(valeur, sources, message_rejet):
    """sources = [(noms autorisés, correspondance), ...], essayées dans l'ordre.
    Chaque élément de valeur est remplacé par le plus proche ; renvoie (valeur, remarques)."""
    if not valeur:
        return "", []
    sources = [(noms, corr) for noms, corr in sources if noms]
    if not sources:
        return valeur, [f"Liste du wiki indisponible : « {valeur} » non vérifié"]
    gardes, remarques = [], []
    for brut in [v.strip() for v in valeur.split(",") if v.strip()]:
        nom = score = None
        for noms, corr in sources:
            nom, score = nom_le_plus_proche(brut, noms, SEUILS.get(corr, 0.6))
            if nom:
                break
        if nom is None:
            remarques.append(f"« {brut} » écarté : {message_rejet}")
            continue
        gardes.append(nom)
        if normaliser(nom) != normaliser(brut):          # pas de remarque si seuls majuscules/accents changent
            fiabilite = "" if score >= 0.85 else " — à vérifier"
            remarques.append(f"« {brut} » → « {nom} »{fiabilite}")
    return ", ".join(dict.fromkeys(gardes)), remarques


def filtrer_noms(valeur, noms_wiki, correspondance="proche"):
    return filtrer_sources(valeur, [(noms_wiki, correspondance)] if noms_wiki else [],
                           "aucun nom proche sur le wiki")


def normaliser_date(valeur):
    """Toute date lisible -> 2026-06-04T09:00:00.000Z. Renvoie (date, remarque)."""
    v = valeur.strip()
    if not v:
        return "", ""
    motifs = [
        r"(?P<a>\d{4})-(?P<m>\d{1,2})-(?P<j>\d{1,2})(?:[T ](?P<h>\d{1,2})[:h](?P<mi>\d{2})?(?::(?P<s>\d{2}))?)?",
        r"(?P<j>\d{1,2})/(?P<m>\d{1,2})/(?P<a>\d{4})(?:\s*(?:à\s*)?(?P<h>\d{1,2})[:h](?P<mi>\d{2})?)?",
    ]
    for motif in motifs:
        m = re.search(motif, v)
        if m:
            d = {k: int(x) if x else 0 for k, x in m.groupdict(default="0").items()}
            iso = f"{d['a']:04d}-{d['m']:02d}-{d['j']:02d}T{d['h']:02d}:{d['mi']:02d}:{d.get('s', 0):02d}.000Z"
            rq = "" if m.group("h") else f"heure absente pour « {v} » : 00:00 par défaut, à corriger"
            return iso, rq
    return "", f"date « {v} » illisible : à saisir au format 2026-06-04T09:00:00.000Z"


def sans_markdown(texte):
    """Retire le gras markdown (**texte**) que l'IA ajoute parfois. Les « ** » en début de
    ligne sont conservés : ce sont des sous-listes du wikitexte."""
    texte = re.sub(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", r"\1", texte, flags=re.S)
    return re.sub(r"(?<!^)(?<!\n)\*\*", "", texte)


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
            champs = ", ".join(c["nom"] for c in conf["champs"]
                               if cat in [l for l, _ in listes_du_champ(c)])
            if noms:
                blocs.append(f"### Liste « {cat} » du wiki — choisir le nom le plus proche pour : {champs}\n"
                             + "\n".join(noms))
    blocs.append("### Document source\n" + texte_docs[:MAX_CARACTERES_DOCS])
    return "\n\n".join(blocs)


CLE_LIEU_GEO = "lieu_pour_coordonnees"   # clé interne : lieu à géocoder (pas écrit dans la fiche)


def _date_du_jour():
    return (f"Date du jour : {date.today().isoformat()}. Si une date du document n'indique pas "
            "l'année, déduis-la du document (année de la manifestation) ; à défaut, prends la "
            "prochaine occurrence de cette date à partir d'aujourd'hui.")


def prompts_champs(conf, titre, texte_docs, listes):
    """Demande n°1 : tous les champs courts, en JSON."""
    systeme = (
        conf["consigne_generale"].strip() + "\n" + _date_du_jour() + "\n\n"
        "Tu réponds UNIQUEMENT avec un objet JSON valide, sans texte autour.\n"
        "Tu écris en français. Si une information est absente du document, "
        "laisse le champ vide (\"\") : n'invente jamais.\n"
        "Pour les champs liés à une liste du wiki : pour chaque véhicule, acteur ou personne "
        "cité dans le document, choisis dans la liste le nom le plus proche et recopie-le à "
        "l'identique (même orthographe, mêmes majuscules, mêmes accents). Si tu ne le trouves "
        "pas dans la liste, écris-le tel qu'il apparaît dans le document : l'application vérifiera."
    )
    a_remplir = {}
    for c in conf["champs"]:
        if c["source"] == "ia" and not c.get("redaction_separee"):
            consigne = " ".join(c["consigne"].split())
            if c.get("valeurs_autorisees"):
                consigne += " Valeurs autorisées : " + ", ".join(c["valeurs_autorisees"]) + "."
            a_remplir[c["nom"]] = consigne
        elif c["source"] == "geo" and c.get("consigne"):
            a_remplir[CLE_LIEU_GEO] = " ".join(c["consigne"].split())
    a_remplir["remarques"] = "Ce qui manque ou est incertain, pour la relecture humaine (1 à 3 phrases)."
    utilisateur = (_blocs_contexte(conf, titre, texte_docs, listes)
                   + "\n\n### Ta tâche\nRemplis ce JSON (clés exactement identiques) :\n"
                   + json.dumps(a_remplir, ensure_ascii=False, indent=2))
    return systeme, utilisateur


def prompts_texte_long(conf, champ, titre, texte_docs):
    """Demande n°2 : un champ long (la description), en texte libre."""
    systeme = (
        conf["consigne_generale"].strip() + "\n" + _date_du_jour() + "\n\n"
        "Tu réponds UNIQUEMENT avec le texte demandé, en wikitexte MediaWiki, sans phrase "
        "d'introduction, sans balises ``` et sans tableau. N'utilise jamais la syntaxe markdown "
        "(pas de **gras**, pas de # titres) : uniquement le wikitexte. Tu écris en français. N'invente jamais."
    )
    utilisateur = (_blocs_contexte(conf, titre, texte_docs, {}, avec_listes=False)
                   + f"\n\n### Ta tâche : rédiger le champ « {champ['nom']} »\n" + champ["consigne"].strip())
    return systeme, utilisateur


AUCUN_PASSAGE = "AUCUN_PASSAGE"


def prompts_filtre(conf, texte_docs):
    """Demande n°0 (optionnelle) : ne garder que le passage de la source qui concerne le sujet."""
    systeme = (
        "Tu extrais des passages de textes. Tu recopies MOT POUR MOT, sans reformuler, sans "
        "résumer et sans rien ajouter. Tu réponds uniquement avec le texte extrait."
    )
    utilisateur = (
        "### Source\n" + texte_docs[:MAX_CARACTERES_DOCS] + "\n\n### Ta tâche\n"
        f"Cette source peut présenter plusieurs {conf.get('objets_source', 'éléments')}. "
        f"Repère celui (ou ceux) qui concerne : {' '.join(conf['filtre_sujet'].split())}\n\n"
        "1. Recopie mot pour mot tout le passage qui le décrit : titre, dates, horaires, lieu, "
        "description, intervenants, informations pratiques.\n"
        "2. Puis, sous la ligne « Contexte général : », recopie mot pour mot les seules "
        "informations générales de la source qui s'appliquent aussi à ce passage (nom et année "
        "de la manifestation, lieu, adresse, organisateur général, horaires d'ouverture). "
        "N'inclus RIEN des autres éléments de la source (autres évènements, autres intervenants).\n"
        f"Si aucun passage ne concerne ce sujet, réponds uniquement : {AUCUN_PASSAGE}"
    )
    return systeme, utilisateur


# ---------------------------------------------------------------- génération
def generer_fiche(conf, titre, texte_docs, listes, valeurs_defaut, fournisseur, cle, modele_ia, liens=()):
    extrait, remarque_filtre = None, ""
    if conf.get("filtre_sujet"):
        systeme, utilisateur = prompts_filtre(conf, texte_docs)
        extrait = nettoyer_texte(appeler_ia(systeme, utilisateur, fournisseur, cle, modele_ia))
        if AUCUN_PASSAGE in extrait or len(extrait) < 50:
            remarque_filtre = ("Aucun passage sur le sujet trouvé dans la source : "
                               "la fiche est rédigée à partir de toute la source.")
            extrait = None
        else:
            texte_docs = extrait
    systeme, utilisateur = prompts_champs(conf, titre, texte_docs, listes)
    donnees = lire_json(appeler_ia(systeme, utilisateur, fournisseur, cle, modele_ia))
    for c in conf["champs"]:
        if c.get("redaction_separee"):
            systeme, utilisateur = prompts_texte_long(conf, c, titre, texte_docs)
            donnees[c["nom"]] = nettoyer_texte(appeler_ia(systeme, utilisateur, fournisseur, cle, modele_ia))
    res = assembler(conf, titre, donnees, listes, valeurs_defaut, liens)
    res["extrait"] = extrait
    if remarque_filtre:
        res["remarques"].insert(0, remarque_filtre)
    return res


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


def assembler(conf, titre, donnees, listes, valeurs_defaut, liens=()):
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
            # on essaie l'adresse précise demandée à l'IA, puis le champ lieu de la fiche
            candidats = [str(donnees.get(k) or "").strip()
                         for k in (CLE_LIEU_GEO, c.get("lieu_depuis", "location"))]
            candidats = [x for x in dict.fromkeys(candidats) if x] or [""]
            for lieu in candidats:
                val, rq = coordonnees(c, lieu)
                if val:
                    break
            remarques.append(rq)
        else:
            val = str(donnees.get(nom, "") or "").strip()
            val = sans_markdown(val)
            val = val.replace("|", "{{!}}")     # un « | » couperait le champ dans le modèle
            if c.get("liste_wiki"):
                sources = [(listes.get(l, []), corr) for l, corr in listes_du_champ(c)]
                val, rq = filtrer_sources(val, sources, "aucun nom proche sur le wiki")
                remarques += [f"{nom} : {r}" for r in rq]
            if c.get("valeurs_autorisees"):
                val, rq = filtrer_sources(val, [(c["valeurs_autorisees"], "valeur")],
                                          "valeur non autorisée")
                remarques += [f"{nom} : {r}" for r in rq]
            if c.get("format") == "date_iso":
                val, rq = normaliser_date(val)
                if rq:
                    remarques.append(f"{nom} : {rq}")

        if c.get("ajouter_liens_source") and liens:
            val = (val + "\n\n" if val else "") + "\n".join(f"Source : {u}" for u in liens)

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
